"""Extract E2 evidence without GT, final poses or candidate-label access."""
import builtins
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
sys.path[:0] = [str(ROOT / "src"), str(UPSTREAM / "splatt3r_core")]
from e0b_audit import sim3_matrix
from e2_signals import (CROSS_METHODS, METHODS, causal_pair, cross_pair, fit_camera,
                        image_rgb, median_views, original_active, prepare_observation)
from utils.geometry import build_covariance


def digest(path):
    path = Path(path)
    return dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")


@contextmanager
def forbid_gt_reads():
    original = builtins.open
    original_io = io.open
    def checked(file, *args, **kwargs):
        try:
            path = Path(file).resolve()
            name = path.name
            if ("data/E1" in str(path) or "results/E1_error_taxonomy" in str(path) or
                    name in {"traj.txt", "groundtruth.txt", "cam_params.json", "office0_frames.txt"} or
                    (name.startswith("depth") and path.suffix == ".png")):
                raise RuntimeError(f"GT/final-trajectory read forbidden during E2 feature extraction: {path}")
        except TypeError:
            pass
        return original(file, *args, **kwargs)
    builtins.open = checked
    io.open = checked
    try:
        yield
    finally:
        builtins.open = original
        io.open = original_io


def extract():
    started = time.monotonic()
    torch.set_num_threads(2)
    spec_path = ROOT / "configs/e2_discriminability.json"
    spec = json.loads(spec_path.read_text())
    run, out = ROOT / spec["baseline_run"], ROOT / spec["output"]
    out.mkdir(parents=True, exist_ok=True)
    if (out / "specification.json").exists():
        assert json.loads((out / "specification.json").read_text()) == spec, "Use a fresh output for changed config"
    save_json(out / "specification.json", spec)
    events_path = run / "audit/events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    decisions = [e for e in events if e["kind"] == "snapshot" and e["stage"] == "decision"]
    final_event = [e for e in events if e["kind"] == "snapshot" and e["stage"] == "final"][-1]
    raw_events = {e["event_id"]: e for e in events if e["kind"] == "raw_pair"}
    # The final local dump supplies immutable images/head outputs only. Its
    # T_WC fields are deliberately discarded; all score poses come from snapshots.
    dump_path = run / "map/office0_kfgauss.pt"
    dump = torch.load(dump_path, map_location="cpu", weights_only=True)
    kfs = [{k: frame[k] for k in ("kf_idx", "frame_id", "img", "img_shape", "means", "scales",
            "rotations", "sh", "opacities", "conf")} for frame in dump["keyframes"]]
    snapshots = []
    inputs = [spec_path, events_path, dump_path, run / "run_manifest.json"]
    assert not any(e["kind"] == "keyframe_pop" for e in events), "KF slot reuse needs explicit replay support"
    for event in decisions + [final_event]:
        path = run / "audit" / event["file"]
        snap = torch.load(path, map_location="cpu", weights_only=True)
        assert snap["pose_revision"] == event["pose_revision"]
        snapshots.append((event, snap))
        inputs.append(path)
    metadata = snapshots[-1][1]["metadata"]
    assert len(kfs) == len(metadata) == len(decisions) == 5
    raw, observations, covariance, active, cameras, rows = [], [], [], [], [], []
    for i, (kf, meta) in enumerate(zip(kfs, metadata)):
        path = run / "exports/raw_pairs" / f"{meta['candidate_event']}.pt"
        record = torch.load(path, map_location="cpu", weights_only=True)
        assert record["source_image_ids"] == meta["candidate_sources"]
        assert torch.equal(record["outputs"][0]["means"].reshape(-1, 3), kf["means"])
        assert torch.equal(record["outputs"][0]["means"], record["outputs"][0]["pts3d"])
        raw.append(record)
        obs = prepare_observation(record["outputs"][0], image_rgb(kf), spec)
        observations.append(obs)
        q = kf["rotations"] / kf["rotations"].norm(dim=-1, keepdim=True).clamp_min(1e-6)
        covariance.append(build_covariance(kf["scales"], q).numpy().astype(np.float64))
        active.append(original_active(kf))
        K, eligible, detail = fit_camera(obs["points"], obs["confidence"], obs["hw"], spec)
        cameras.append(dict(anchor_kf=i, K=K.tolist(), **detail))
        rows.append(dict(anchor_kf=i, input_frame=meta["frame_id"], original_frame=2 * meta["frame_id"],
                         event_id=meta["candidate_event"], source_images=meta["candidate_sources"],
                         raw_sequence=raw_events[meta["candidate_event"]]["sequence"]))
        inputs.append(path)
    n = len(kfs[0]["means"])
    features = {mode + "__" + method: np.full((5, n), np.nan, np.float32)
                for mode in spec["score_availability_modes"] for method in METHODS}
    arrays = dict(active=np.concatenate(active), anchor_kf=np.repeat(np.arange(5, dtype=np.uint8), n),
                  pixel_index=np.tile(np.arange(n, dtype=np.int32), 5))
    history_input = {method: np.full((5, n), -1, np.int16) for method in CROSS_METHODS}
    creation_poses = np.empty((5, 4, 4))
    pair_audit, snapshot_audit = [], []
    for event, snap in snapshots:
        final = event["stage"] == "final"
        mode = "final_revision_hindsight" if final else "at_creation"
        count = len(snap["metadata"])
        poses = [sim3_matrix(p.numpy()) for p in snap["poses"]]
        for i in range(count):
            views = {name: [] for name in CROSS_METHODS if not name.endswith("2view")}
            meta_i = snap["metadata"][i]
            assert meta_i["candidate_event"] == metadata[i]["candidate_event"]
            assert meta_i["candidate_sources"] == raw[i]["source_image_ids"]
            assert raw_events[meta_i["candidate_event"]]["sequence"] < event["sequence"]
            means = kfs[i]["means"].numpy().astype(float)
            for j in range(count):
                if j == i:
                    continue
                meta_j = snap["metadata"][j]
                assert meta_j["candidate_event"] == metadata[j]["candidate_event"]
                assert meta_j["candidate_sources"] == raw[j]["source_image_ids"]
                eligible = causal_pair(meta_i["candidate_sources"], meta_j["candidate_sources"],
                                       event["sequence"], raw_events[meta_j["candidate_event"]]["sequence"])
                row = dict(decision_sequence=event["sequence"], decision_input=snap["input_frame"],
                           stage=event["stage"], pose_revision=snap["pose_revision"], candidate_kf=i,
                           evidence_kf=j, source_disjoint=eligible,
                           shared_images=sorted(set(meta_i["candidate_sources"]) & set(meta_j["candidate_sources"])))
                if eligible:
                    scores, stats = cross_pair(means, covariance[i], observations[i], observations[j], poses[i], poses[j], spec)
                    for method, values in scores.items():
                        views[method].append(values)
                    row.update(stats)
                pair_audit.append(row)
            combined, support = {}, {}
            for method, values in views.items():
                combined[method], support[method] = median_views(values, n)
            combined["P1_plane_front_2view"] = combined["P1_plane_front_1view"].copy()
            plane_count = support["P1_plane_front_1view"]
            combined["P1_plane_front_2view"][plane_count < 2] = np.nan
            for method, values in combined.items():
                if final:
                    features[mode + "__" + method][i] = values
                else:
                    if i == count - 1:
                        features["at_creation__" + method][i] = values
                    pending = history_input[method][i] < 0
                    first = pending & np.isfinite(values)
                    features["causal_deferred_first_eligible__" + method][i, first] = values[first]
                    history_input[method][i, first] = snap["input_frame"]
            snapshot_audit.append(dict(stage=event["stage"], input=snap["input_frame"], candidate_kf=i,
                pose_revision=snap["pose_revision"], raw_ray_depth_eligible=int(np.isfinite(combined["B6_depth_front"]).sum()),
                plane_1plus=int((plane_count >= 1).sum()), plane_2plus=int((plane_count >= 2).sum())))
            if not final and i == count - 1:
                creation_poses[i] = poses[i]
                rows[i].update(decision_sequence=event["sequence"], pose_revision=snap["pose_revision"],
                               decision_file=event["file"])
                raw_points = raw[i]["outputs"][0]["pts3d"].numpy().reshape(-1, 3)
                self_residual = np.linalg.norm(means - raw_points, axis=1) / np.maximum(np.linalg.norm(raw_points, axis=1), 1e-12)
                for prefix in spec["score_availability_modes"]:
                    features[prefix + "__B2_confidence"][i] = -kfs[i]["conf"].numpy()
                    features[prefix + "__B2_opacity"][i] = -kfs[i]["opacities"].numpy()
                    features[prefix + "__B5_self_residual"][i] = self_residual
        print(f"Scored snapshot {event['stage']} input={snap['input_frame']} revision={snap['pose_revision']}", flush=True)
    for key, value in features.items():
        arrays[key] = value.reshape(-1)
    for method, times in history_input.items():
        arrays["first_eligible_input__" + method] = times.reshape(-1)
    arrays["creation_poses"] = creation_poses
    np.savez_compressed(out / "features.npz", **arrays)
    save_json(out / "score_metadata.json", dict(candidates=5 * n, active=int(arrays["active"].sum()),
        lineage=rows, predicted_cameras=cameras, snapshots=snapshot_audit, cpu_wall_seconds=time.monotonic() - started,
        gt_reads="forbidden", final_dump_pose_fields_used=False, evidence_scope="raw KF self branches only"))
    (out / "pair_audit.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pair_audit))
    code = [ROOT / p for p in ("src/e2_signals.py", "scripts/score_e2.py", "scripts/render_e2_premaps.py",
            "src/e2_metrics.py", "scripts/analyze_e2.py", "scripts/plot_e2.py", "scripts/run_e2.sh",
            "tests/test_e2.py", "src/e0b_audit.py", "src/e1_taxonomy.py")]
    for p in code:
        saved = out / "code" / p.relative_to(ROOT)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, saved)
    manifest = dict(specification=digest(spec_path), inputs=[digest(p) for p in inputs], code=[digest(p) for p in code],
                    feature_sha256=digest(out / "features.npz")["sha256"],
                    gt_reads="forbidden", label_reads=False, score_pose="each recorded snapshot revision only",
                    numpy=np.__version__, torch=torch.__version__)
    save_json(out / "score_manifest.json", manifest)
    print(f"GT-free scores saved to {out}", flush=True)


if __name__ == "__main__":
    with forbid_gt_reads():
        extract()
