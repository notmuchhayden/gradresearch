#!/usr/bin/env python3
"""Freeze existing assets and replay the office0 baseline without altering E0.

Run with the project Python. --gpu also executes CUDA smoke tests, a fresh
RGB-only E0-sized baseline, and both saved-map and fresh-map evaluation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
E0 = ROOT / "results/E0_baseline_reproduction"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(path):
    path = Path(path)
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha}


def command(args, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return {"command": [str(a) for a in args], "returncode": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def checked_manifest(rows, path_key):
    results = []
    for row in rows:
        path = ROOT / row[path_key]
        actual = digest(path) if path.is_file() else {"path": row[path_key], "missing": True}
        actual["expected_sha256"] = row["sha256"]
        actual["matches"] = actual.get("sha256") == row["sha256"] and (
            "bytes" not in row or actual.get("bytes") == row["bytes"])
        results.append(actual)
    return results


def inventory(out):
    frozen = out / "frozen"
    frozen.mkdir()
    repo = {"head": command(["git", "rev-parse", "HEAD"]),
            "status": command(["git", "status", "--short"]),
            "upstream_head": command(["git", "rev-parse", "HEAD"], UPSTREAM),
            "upstream_status": command(["git", "status", "--short"], UPSTREAM)}
    (frozen / "research.diff").write_text(command(["git", "diff", "--binary"])["stdout"] + "\n")
    (frozen / "upstream.diff").write_text(command(["git", "diff", "--binary"], UPSTREAM)["stdout"] + "\n")
    paths = sorted({p for folder in ("configs", "scripts", "src", "tests")
                    for p in (ROOT / folder).rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts})
    paths += [ROOT / "README.md", ROOT / "docs/pointmap_pose_error_decomposition_research_plan_v1.md",
              ROOT / "docs/experiments/surface_guided_gaussian_mapping_experiment_summary.md"]
    paths += sorted((ROOT / "docs/experiments").glob("E*.md"))
    upstream_paths = command(["git", "ls-files", "-z"], UPSTREAM)["stdout"].split("\0")
    paths += [UPSTREAM / p for p in upstream_paths if p and (UPSTREAM / p).is_file()
              and (p.endswith((".py", ".yaml", ".yml", ".cu", ".cpp", ".h")))]
    code_rows = []
    for path in sorted(set(paths)):
        code_rows.append(digest(path))
        target = frozen / "source" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    save(out / "source_manifest.json", {"repositories": repo, "files": code_rows})

    old_environment = json.loads((ROOT / "configs/e0_environment_resolved.json").read_text())
    versions = {d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata["Name"]}
    normalize = lambda name: name.lower().replace("_", "-")
    current = {normalize(n): v for n, v in versions.items()}
    changes = [{"package": row["name"], "recorded": row["version"], "current": current.get(normalize(row["name"]))}
               for row in old_environment["distributions"]
               if current.get(normalize(row["name"])) != row["version"]]
    import torch
    env = {"recorded_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
           "python": sys.version, "executable": sys.executable,
           "torch": torch.__version__, "torch_cuda": torch.version.cuda,
           "cuda_available": torch.cuda.is_available(), "distributions": versions,
           "changes_since_e0": changes,
           "gpu": command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader"]),
           "project_nvcc": command([str(ROOT / ".venv/lib/python3.11/site-packages/nvidia/cu13/bin/nvcc"), "--version"]),
           "pip_check": command([sys.executable, "-m", "pip", "check"])}
    if env["cuda_available"]:
        env["device"] = torch.cuda.get_device_name(0)
        env["device_capability"] = list(torch.cuda.get_device_capability(0))
    save(out / "environment.json", env)
    weights = checked_manifest(json.loads((ROOT / "configs/e0_weights_manifest.json").read_text()), "file")
    data = checked_manifest(json.loads((ROOT / "configs/e0_replica_download_manifest.json").read_text())["files"], "path")
    historical_code = checked_manifest(json.loads((ROOT / "configs/e0_code_manifest.json").read_text())["files"], "file")
    save(out / "asset_hashes.json", {"weights": weights, "e0_data": data, "historical_e0_code": historical_code})

    # Freeze E0's entire raw export plus its persisted map and original metrics.
    baseline_paths = sorted((E0 / "exports").rglob("*.pt")) + sorted((E0 / "exports").rglob("*.json"))
    baseline_paths += sorted((E0 / "map").glob("*"))
    baseline_paths += [E0 / "export_checks.json", E0 / "evaluation/metrics.json"]
    baseline_rows = [digest(p) for p in baseline_paths if p.is_file()]
    save(out / "baseline_manifest.json", {"baseline": str(E0.relative_to(ROOT)), "files": baseline_rows})

    history = []
    for path in sorted((ROOT / "configs").glob("*results_summary.json")):
        value = json.loads(path.read_text())
        history.append({**digest(path), "recorded_status": value.get("status", value.get("decision")),
                        "scope": "historical result, not rerun by N0"})
    e4 = json.loads((ROOT / "configs/e4_validation.json").read_text())
    e4_metrics = checked_manifest([row["metrics"] for row in e4["scenes"]], "path")
    drive = ROOT / "results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync"
    extra = [ROOT / "results/E4e_uav_dataset_pilot/development/HKairport01/baseline/run_manifest.json",
             drive / "baseline_A2b/run_manifest.json", drive / "evaluation_tracklet_masked_v3/metrics.json",
             drive / "evaluation_pose_oracle/metrics.json", drive / "evaluation_pose_oracle/evaluation_manifest.json"]
    extra_rows = [digest(p) if p.is_file() else {"path": str(p.relative_to(ROOT)), "missing": True} for p in extra]
    scenes = sorted({p.parent.name for p in (ROOT / "data").rglob("traj.txt") if "Replica" in p.parts})
    save(out / "historical_assets.json", {"summaries": history, "e4_metrics_rehashed": e4_metrics,
         "e4e_e4f_records": extra_rows, "existing_replica_scenes": scenes,
         "scope": "Selected records checked; large E0b-E4f raw datasets and UAV archives are not exhaustively rehashed."})
    assert all(row["matches"] for row in weights), "Weight hash mismatch"
    assert all(row["matches"] for row in data), "E0 RGB/depth/calibration/trajectory hash mismatch"
    assert all(row["matches"] for row in e4_metrics), "E4 recorded metric hash mismatch"
    assert not any(row.get("missing") for row in extra_rows), "Missing historical run/evaluation record"
    assert env["pip_check"]["returncode"] == 0, "pip check failed"
    return {"weights_verified": len(weights), "data_files_verified": len(data),
            "baseline_files_frozen": len(baseline_rows), "source_files_frozen": len(code_rows),
            "e0_code_hash_differences": [r["path"] for r in historical_code if not r["matches"]],
            "package_version_changes": changes, "e4_metric_files_verified": len(e4_metrics)}


def cpu_checks(out):
    import cv2
    import numpy as np
    import torch
    from scipy.spatial.transform import Rotation
    dump = torch.load(E0 / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
    lineage = [json.loads(p.read_text()) for p in (E0 / "exports/candidate_sources").glob("*.json")]
    rows = []
    for kf in dump["keyframes"]:
        record = next(r for r in lineage if r["anchor_kf"] == kf["kf_idx"] and r["frame_id"] == kf["frame_id"])
        raw = torch.load(E0 / "exports/raw_pairs" / (record["prediction_event_id"] + ".pt"), map_location="cpu", weights_only=True)
        predicted = raw["outputs"][0]
        assert torch.equal(predicted["means"], predicted["pts3d"])
        assert torch.equal(kf["means"], predicted["means"].reshape(-1, 3))
        h, w = kf["img_shape"]
        assert len(kf["means"]) == h * w
        for name in ("means", "scales", "rotations", "sh", "opacities", "conf", "T_WC"):
            assert torch.isfinite(kf[name]).all(), name
        assert (kf["scales"] > 0).all()
        assert raw["anchor_frame_id"] == kf["frame_id"]
        assert record["gaussian_coordinate_frame"] == "anchor_camera"
        assert "row-major-pixel-index" in record["candidate_id_format"]
        rows.append({"kf_idx": kf["kf_idx"], "frame_id": kf["frame_id"], "original_frame_id": 2 * kf["frame_id"],
                     "candidate_count": len(kf["means"]), "image_hw": [h, w],
                     "source_image_ids": raw["source_image_ids"], "prediction_event_id": raw["event_id"],
                     "raw_pointmap_mean_exact": True, "candidate_pixel_mapping": "row-major index -> (index % width, index // width)",
                     "pose_revision": kf["pose_revision"], "fused_ancestry_status": kf["fused_ancestry_status"]})
    poses = np.loadtxt(E0 / "map/office0_frames.txt")
    assert poses.shape == (60, 8) and np.isfinite(poses).all()
    np.testing.assert_array_equal(poses[:, 0], np.arange(0, 120, 2))
    np.testing.assert_allclose(np.linalg.norm(poses[:, 4:8], axis=1), 1, atol=2e-6)
    dataset = ROOT / "data/Replica/office0"
    traj = np.loadtxt(dataset / "traj.txt").reshape(-1, 4, 4)
    groundtruth = np.loadtxt(dataset / "groundtruth.txt")
    assert len(groundtruth) == 120
    np.testing.assert_array_equal(groundtruth[:, 0], np.arange(120))
    np.testing.assert_allclose(groundtruth[:, 1:4], traj[:120, :3, 3], atol=1e-6)
    np.testing.assert_allclose(Rotation.from_quat(groundtruth[:, 4:8]).as_matrix(), traj[:120, :3, :3], atol=3e-6)
    camera = json.loads((dataset.parent / "cam_params.json").read_text())["camera"]
    depth_rows = []
    for frame in (0, 1, 82, 119):
        rgb = cv2.imread(str(dataset / "results" / f"frame{frame:06d}.jpg"))
        depth = cv2.imread(str(dataset / "results" / f"depth{frame:06d}.png"), cv2.IMREAD_UNCHANGED)
        assert rgb.shape[:2] == depth.shape == (camera["h"], camera["w"])
        assert depth.dtype == np.uint16
        valid = depth > 0
        metric = depth[valid] / camera["scale"]
        depth_rows.append({"frame": frame, "shape": list(depth.shape), "valid_fraction": float(valid.mean()),
                           "depth_median_m": float(np.median(metric)), "depth_scale": camera["scale"]})
    saved = json.loads((E0 / "evaluation/metrics.json").read_text())
    for split, summary in saved["summaries"].items():
        selected = [r for r in saved["frames"] if r["split"] == split]
        assert len(selected) == summary["n_frames"]
        assert all(r["original_frame_id"] % 2 == 1 for r in selected)
        for key, value in summary.items():
            if key != "n_frames":
                np.testing.assert_allclose(np.mean([r[key] for r in selected]), value, atol=1e-12)
    result = {"status": "PASS", "keyframes": rows, "tracked_poses": len(poses),
              "raw_events": len(list((E0 / "exports/raw_pairs").glob("*.pt"))),
              "gt_trajectory_matches_traj": True, "sampled_rgb_depth": depth_rows,
              "saved_summary_recomputed": True,
              "limits": ["E0 pose revisions and fused ancestry are unversioned/unknown.",
                         "No N1 intervention independence or metric-gauge validation claimed.",
                         "E0 full-trajectory alignment is replayed only for regression, not adopted as the A0 calibration rule."]}
    save(out / "cpu_checks.json", result)
    return {"keyframes": len(rows), "raw_candidates": sum(r["candidate_count"] for r in rows),
            "tracked_poses": len(poses), "raw_events": result["raw_events"]}


def gpu_checks(out):
    import numpy as np
    import torch
    assert torch.cuda.is_available(), "CUDA unavailable in this execution context"
    env = os.environ.copy()
    env.update(CONDA_PREFIX=str(ROOT / ".venv"), CUDA_VISIBLE_DEVICES="0", PYTHONHASHSEED="0",
               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2",
               PYTHONPATH=str(ROOT / "src"), E0_SEED="0", E0_DISABLE_GT="1",
               E0_FAISS_TEMP_MB="64", E0_LOW_VRAM="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               TORCH_HOME=str(E0 / "setup/torch-cache"), HF_HOME=str(E0 / "setup/huggingface"),
               XDG_CACHE_HOME=str(out / "cache"), MPLCONFIGDIR=str(out / "matplotlib"))
    commands = []

    def execute(args, log, cwd=ROOT):
        started = time.monotonic()
        with (out / log).open("w") as stream:
            result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        row = {"command": [str(a) for a in args], "cwd": str(cwd), "log": log,
               "returncode": result.returncode, "wall_seconds": time.monotonic() - started}
        commands.append(row)
        save(out / "gpu_commands.json", commands)
        print(f"{log}: exit {result.returncode}, {row['wall_seconds']:.1f}s", flush=True)
        assert result.returncode == 0, f"See {out / log}"

    execute([sys.executable, ROOT / "scripts/smoke_e0_cuda.py"], "cuda_smoke.log")
    # Import the unchanged E0 implementation, overriding only the output root.
    runner = out / "replay_e0.py"
    runner.write_text("""import importlib.util, sys
from pathlib import Path
root, run, stage = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location('n0_legacy', root / 'scripts' / (stage + '.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.RUN = run
module.main()
""")
    replay = out / "saved_baseline_replay"
    replay.mkdir()
    for name in ("map", "exports"):
        (replay / name).symlink_to(E0 / name, target_is_directory=True)
    for stage in ("check_e0_exports", "evaluate_e0"):
        execute([sys.executable, runner, ROOT, replay, stage], f"saved_{stage}.log")
    fresh = out / "fresh_baseline"
    fresh.mkdir()
    env["E0_EXPORT_DIR"] = str(fresh / "exports")
    env["E0B_AUDIT_DIR"] = str(fresh / "audit")
    args = [sys.executable, UPSTREAM / "main.py", "--dataset", ROOT / "data/Replica/office0",
            "--config", ROOT / "configs/e0_replica_office0.yaml",
            "--checkpoint", ROOT / "checkpoints/e0/epoch=19-step=1200.ckpt",
            "--retriever-path", ROOT / "checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth",
            "--no-viz", "--no-render-gaussians", "--keyframe-buffer", "16", "--dump-keyframe-gaussians",
            "--spatial-stride", "1", "--max-gaussians", "16777216", "--depth-max-percentile", "0.98",
            "--max-scale", "1.0", "--min-confidence", "1.5", "--refiner-conf-fade", "0",
            "--save-as", fresh / "map", "--render-dir", fresh / "render", "--frame-timing", fresh / "timing.csv"]
    save(fresh / "run_manifest.json", {"purpose": "N0 RGB-only baseline regression; no new method",
         "seed": 0, "refinement": 0, "input_original_frame_ids": list(range(0, 120, 2)),
         "gt_use": "evaluation only", "environment_overrides": {k: env[k] for k in (
             "E0_SEED", "E0_DISABLE_GT", "E0_FAISS_TEMP_MB", "E0_LOW_VRAM", "E0_EXPORT_DIR", "E0B_AUDIT_DIR",
             "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONHASHSEED", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
         "source_manifest": str((out / "source_manifest.json").relative_to(ROOT)),
         "asset_hashes": str((out / "asset_hashes.json").relative_to(ROOT)), "command": [str(a) for a in args]})
    execute(args, "fresh_baseline.log", UPSTREAM)
    for stage in ("check_e0_exports", "evaluate_e0"):
        execute([sys.executable, runner, ROOT, fresh, stage], f"fresh_{stage}.log")
    original = json.loads((E0 / "evaluation/metrics.json").read_text())
    comparison = {}
    for name, run in (("saved", replay), ("fresh", fresh)):
        actual = json.loads((run / "evaluation/metrics.json").read_text())
        checks = json.loads((run / "export_checks.json").read_text())
        differences = {split: {key: actual["summaries"][split][key] - value for key, value in summary.items()}
                       for split, summary in original["summaries"].items()}
        comparison[name] = {"active_gaussians": actual["gaussian_active_count"],
                            "export_checks": checks, "summaries": actual["summaries"],
                            "differences_from_e0": differences,
                            "alignment_scale": actual["alignment"]["scale"]}
        assert actual["gaussian_active_count"] == original["gaussian_active_count"]
        for split, summary in original["summaries"].items():
            for key, value in summary.items():
                # Recorded before replay: near-exact saved-map regression;
                # fresh SLAM may vary slightly despite a fixed random seed.
                tol = (1e-4 if key == "psnr_db" else 1e-6) if name == "saved" else (
                    0.05 if key == "psnr_db" else 0 if key == "n_frames" else 0.002)
                np.testing.assert_allclose(actual["summaries"][split][key], value, atol=tol, rtol=0)
    save(out / "reproduction.json", comparison)
    return {name: {"active_gaussians": row["active_gaussians"], "summaries": row["summaries"],
                   "differences_from_e0": row["differences_from_e0"]} for name, row in comparison.items()}


def preservation(out):
    rows = json.loads((out / "baseline_manifest.json").read_text())["files"]
    failures = [row["path"] for row in rows if digest(ROOT / row["path"]) != row]
    save(out / "preservation.json", {"status": "PASS" if not failures else "FAIL",
                                     "e0_files_rehashed": len(rows), "changed": failures})
    assert not failures, "Original E0 files changed"
    return {"e0_files_rehashed": len(rows), "unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/N0_asset_audit/2026-10-26")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / "results/N0_asset_audit"):
        parser.error("Output must be under results/N0_asset_audit")
    out.mkdir(parents=True, exist_ok=False)
    result = {"stage": "N0", "started_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
              "scope": "Existing asset freeze, office0 baseline regression, N1 prerequisites; no A0 efficacy claim",
              "gpu_requested": args.gpu, "checks": {}}
    stages = [("inventory", inventory), ("cpu", cpu_checks)]
    if args.gpu:
        stages.append(("gpu", gpu_checks))
    stages.append(("preservation", preservation))
    for name, operation in stages:
        print(f"N0 {name} started", flush=True)
        try:
            result["checks"][name] = {"status": "PASS", "details": operation(out)}
        except Exception:
            result["checks"][name] = {"status": "FAIL", "traceback": traceback.format_exc()}
            print(result["checks"][name]["traceback"], flush=True)
        save(out / "audit.json", result)
    result["status"] = "PASS" if args.gpu and all(r["status"] == "PASS" for r in result["checks"].values()) else "INCOMPLETE"
    result["finished_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    save(out / "audit.json", result)
    print(json.dumps({"status": result["status"], "output": str(out)}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
