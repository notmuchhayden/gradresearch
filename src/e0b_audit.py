"""CPU audit of raw/fused lineage, decision-time poses, and ray support.

Source disjointness is image-level only. Ray support is a feasibility proxy,
not occlusion testing, ground truth, or candidate correctness classification.
"""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
import torch


def sim3_matrix(data):
    t = np.asarray(data, dtype=np.float64).reshape(8)
    matrix = np.eye(4)
    matrix[:3, :3] = t[7] * Rotation.from_quat(t[3:7]).as_matrix()
    matrix[:3, 3] = t[:3]
    return matrix


def transform(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def disjoint(candidate_sources, evidence_sources, status="traced"):
    return (status == "traced" and bool(candidate_sources) and bool(evidence_sources)
            and not set(candidate_sources).intersection(evidence_sources))


def percentile_summary(values):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return dict(count=0, median=None, p05=None, p95=None, max=None)
    return dict(count=len(values), median=float(np.median(values)),
                p05=float(np.percentile(values, 5)), p95=float(np.percentile(values, 95)),
                max=float(np.max(values)))


def ray_support(candidate_local, candidate_conf, candidate_pose, evidence_points,
                evidence_conf, evidence_pose, spec, tree=None):
    valid_e = np.isfinite(evidence_points).all(1) & (evidence_conf.reshape(-1) >= spec["confidence_min"])
    radii = np.linalg.norm(evidence_points, axis=1)
    valid_e &= radii > 1e-8
    if tree is None and valid_e.any():
        tree = cKDTree(evidence_points[valid_e] / radii[valid_e, None])
    world = transform(candidate_local, candidate_pose)
    in_evidence = transform(world, np.linalg.inv(evidence_pose))
    radius = np.linalg.norm(in_evidence, axis=1)
    valid = (np.isfinite(world).all(1) & np.isfinite(radius) & (radius > 1e-8)
             & (candidate_conf.reshape(-1) >= spec["confidence_min"]))
    ray_angle = np.full(len(world), np.inf)
    if tree is not None and valid.any():
        distance = tree.query(in_evidence[valid] / radius[valid, None], workers=1)[0]
        ray_angle[valid] = np.degrees(2 * np.arcsin(np.clip(distance / 2, 0, 1)))
    ray_ok = valid & (ray_angle <= spec["ray_support_max_angle_degrees"])
    a, b = world - candidate_pose[:3, 3], world - evidence_pose[:3, 3]
    cosine = (a * b).sum(1) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12)
    parallax = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    supported = ray_ok & (parallax >= spec["parallax_min_degrees"])
    return supported, ray_ok, parallax, tree


class Audit:
    def __init__(self, run):
        self.run = Path(run)
        self.manifest = json.loads((self.run / "run_manifest.json").read_text())
        self.spec = self.manifest["specification"]
        self.events = [json.loads(s) for s in (self.run / "audit/events.jsonl").read_text().splitlines()]
        self.raw_events = {e["event_id"]: e for e in self.events if e["kind"] == "raw_pair"}
        self.pair_rows = []

    @lru_cache(maxsize=8)
    def raw(self, event):
        return torch.load(self.run / "exports/raw_pairs" / f"{event}.pt", map_location="cpu", weights_only=True)

    def snapshot(self, event):
        return torch.load(self.run / "audit" / event["file"], map_location="cpu", weights_only=True)

    def validate(self):
        assert [e["sequence"] for e in self.events] == list(range(1, len(self.events) + 1))
        assert len(self.raw_events) == len(list((self.run / "exports/raw_pairs").glob("*.pt")))
        revision = 0
        states = {}
        known_kfs = set()
        replay_errors = []
        pose_batches_changed = 0
        candidate_checks = 0
        final = None
        last_frame = None
        pose_state = {}
        for e in self.events:
            kind = e["kind"]
            if kind == "raw_pair":
                # Non-keyframe maps are never reused by later tracking calls.
                if last_frame is not None and last_frame not in known_kfs:
                    states.pop(last_frame, None)
                last_frame = e["input_frame"]
                raw = self.raw(e["event_id"])
                assert raw["source_image_ids"] == e["source_image_ids"]
                assert max(e["source_image_ids"]) <= e["input_frame"]
            elif kind == "pointmap_update":
                update = e["update"]
                assert update is not None and e["filtering_mode"] == "weighted_pointmap"
                raw = self.raw(update["event_id"])
                assert update["images"] == raw["source_image_ids"]
                assert update["pairs"] == raw["source_pair_ids"]
                assert self.raw_events[update["event_id"]]["sequence"] < e["sequence"]
                branch = raw["outputs"][update["branch"]]
                X = branch["pts3d"].numpy().reshape(-1, 3).copy()
                C = branch["conf"].numpy().reshape(-1, 1).copy()
                if e["transform"] is not None:
                    X = transform(X, sim3_matrix(e["transform"])).astype(np.float32)
                frame_id = e["target_frame"]
                old = states.get(frame_id)
                if e["first"]:
                    images, pairs, events = set(), set(), set()
                else:
                    assert old is not None
                    images, pairs, events = old["images"].copy(), old["pairs"].copy(), old["events"].copy()
                    X = (old["C"] * old["X"] + C * X) / (old["C"] + C)
                    C = old["C"] + C
                images.update(raw["source_image_ids"])
                pairs.update(map(tuple, raw["source_pair_ids"]))
                events.add(update["event_id"])
                assert sorted(images) == e["fused"]["images"]
                assert sorted(events) == e["fused"]["events"]
                assert sorted(pairs) == sorted(map(tuple, e["fused"]["pairs"]))
                states[frame_id] = dict(X=X, C=C, images=images, pairs=pairs, events=events,
                                        n=1 if e["first"] else old["n"] + 1)
            elif kind in ("keyframe_write", "pose_update"):
                revision += 1
                assert e["pose_revision"] == revision
                if kind == "keyframe_write":
                    known_kfs.add(e["metadata"]["frame_id"])
                    pose_state[e["metadata"]["kf_idx"]] = e["pose"]
                else:
                    pose_batches_changed += int(not np.array_equal(e["before"], e["after"]))
                    for idx, before, after in zip(e["kf_indices"], e["before"], e["after"]):
                        np.testing.assert_array_equal(pose_state[idx], before)
                        pose_state[idx] = after
            elif kind == "snapshot":
                snap = self.snapshot(e)
                assert snap["pose_revision"] == revision == e["pose_revision"]
                for i, meta in enumerate(snap["metadata"]):
                    np.testing.assert_array_equal(snap["poses"][i].numpy(), pose_state[i])
                    assert meta["fused"]["status"] == "traced"
                    assert meta["created_sequence"] < e["sequence"]
                    assert self.raw_events[meta["candidate_event"]]["sequence"] < e["sequence"]
                    assert meta["candidate_sources"] == self.raw(meta["candidate_event"])["source_image_ids"]
                    state = states[meta["frame_id"]]
                    assert sorted(state["images"]) == meta["fused"]["images"]
                    assert sorted(state["events"]) == meta["fused"]["events"]
                    assert all(self.raw_events[x]["sequence"] < e["sequence"] for x in meta["fused"]["events"])
                    saved = snap["fused_points"][i].numpy()
                    np.testing.assert_allclose(state["X"], saved, atol=2e-4, rtol=2e-4)
                    np.testing.assert_allclose(state["C"] / state["n"], snap["fused_confidence"][i].numpy(), atol=2e-4, rtol=2e-4)
                    assert state["n"] == int(snap["pointmap_updates"][i])
                    replay_errors.append(float(np.abs(state["X"] - saved).max()))
                if e["stage"] == "final":
                    final = snap
        assert final is not None
        dump = torch.load(self.run / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
        assert dump["n"] == len(final["metadata"])
        for kf, meta in zip(dump["keyframes"], final["metadata"]):
            assert kf["frame_id"] == meta["frame_id"]
            assert torch.equal(kf["means"], self.raw(meta["candidate_event"])["outputs"][0]["means"].reshape(-1, 3))
            candidate_checks += 1
        with (self.run / "map/office0_frames.txt").open() as f:
            tracked = sum(bool(line.strip()) and not line.startswith("#") for line in f)
        assert tracked == self.spec["cases"][self.manifest["case"]]["expected_inputs"]
        checks = dict(status="PASS", journal_events=len(self.events), raw_events=len(self.raw_events),
                      snapshots=sum(e["kind"] == "snapshot" for e in self.events),
                      final_keyframes=len(final["metadata"]), candidate_exact_matches=candidate_checks,
                      tracked_frames=tracked, unknown_fused_ancestry=0,
                      fused_replay_max_abs_error=max(replay_errors), pose_revision=revision,
                      backend_pose_update_batches=sum(e["kind"] == "pose_update" for e in self.events),
                      backend_pose_batches_actually_changed=pose_batches_changed,
                      lineage_replay="PASS", numerical_pointmap_replay="PASS", no_future_leakage="PASS",
                      pose_revision_at_decision="PASS", pose_value_replay="PASS", gt_depth_or_trajectory_used=False)
        return checks

    def evaluate_snapshot(self, snap, label):
        metadata = snap["metadata"]
        n = len(metadata)
        poses = [sim3_matrix(p) for p in snap["poses"].numpy()]
        h, w = snap["image_shape"]
        stride = self.spec["geometry_sample_grid_stride"]
        sample = np.arange(h * w).reshape(h, w)[::stride, ::stride].reshape(-1)
        results = {mode: [] for mode in ("raw", "fused")}
        trees = {}
        for mode in results:
            for i, candidate in enumerate(metadata):
                raw = self.raw(candidate["candidate_event"])
                means = raw["outputs"][0]["means"].numpy().reshape(-1, 3)[sample]
                conf = raw["outputs"][0]["conf"].numpy().reshape(-1, 1)[sample]
                count = np.zeros(len(sample), dtype=np.int32)
                source_views = 0
                overlapping = 0
                unknown = 0
                parallax_all = []
                for j, evidence in enumerate(metadata):
                    if i == j:
                        continue
                    if mode == "raw":
                        sources = evidence["candidate_sources"]
                        status = "traced" if sources else "unknown"
                    else:
                        sources = evidence["fused"].get("images", [])
                        status = evidence["fused"]["status"]
                    eligible = disjoint(candidate["candidate_sources"], sources, status)
                    overlapping += int(status == "traced" and not eligible)
                    unknown += int(status != "traced")
                    row = dict(snapshot=label, decision_input=snap["input_frame"],
                               pose_revision=snap["pose_revision"], mode=mode,
                               candidate_kf=i, evidence_kf=j, source_disjoint=eligible,
                               candidate_input=candidate["frame_id"], evidence_input=evidence["frame_id"],
                               evidence_age_at_decision_inputs=snap["input_frame"] - evidence["frame_id"],
                               candidate_evidence_input_gap=abs(candidate["frame_id"] - evidence["frame_id"]),
                               evidence_latest_source_input=max(sources) if sources else None,
                               shared_images=len(set(candidate["candidate_sources"]) & set(sources)),
                               ancestry_status=status)
                    if eligible:
                        source_views += 1
                        if mode == "raw":
                            eraw = self.raw(evidence["candidate_event"])["outputs"][0]
                            points = eraw["pts3d"].numpy().reshape(-1, 3)
                            econf = eraw["conf"].numpy().reshape(-1, 1)
                        else:
                            points = snap["fused_points"][j].numpy()
                            econf = snap["fused_confidence"][j].numpy()
                        supported, ray_ok, parallax, tree = ray_support(
                            means, conf, poses[i], points, econf, poses[j], self.spec, trees.get((mode, j)))
                        trees[mode, j] = tree
                        count += supported
                        parallax_all.extend(parallax[ray_ok].tolist())
                        row.update(ray_support_fraction=float(ray_ok.mean()),
                                   ray_and_parallax_fraction=float(supported.mean()),
                                   parallax_degrees=percentile_summary(parallax[ray_ok]))
                    self.pair_rows.append(row)
                results[mode].append(dict(candidate_kf=i, frame_id=candidate["frame_id"],
                                          source_disjoint_views=source_views, source_overlap_views=overlapping,
                                          unknown_views=unknown, sample_count=len(sample),
                                          sample_supported_1plus=int((count >= 1).sum()),
                                          sample_supported_2plus=int((count >= 2).sum()),
                                          parallax_degrees=percentile_summary(parallax_all),
                                          counts=count))
        return results

    def availability(self):
        decisions = [e for e in self.events if e["kind"] == "snapshot" and e["stage"] == "decision"]
        final_event = next(e for e in reversed(self.events) if e["kind"] == "snapshot" and e["stage"] == "final")
        final = self.snapshot(final_event)
        histories = {mode: {} for mode in ("raw", "fused")}
        metadata = final["metadata"]
        # Failed relocalization slots are not silently treated as stable KF IDs.
        assert not any(e["kind"] == "keyframe_pop" for e in self.events), "Relocalization slot reuse requires explicit replay handling"
        for event in decisions:
            snap = self.snapshot(event)
            label = f"creation_kf{len(snap['metadata']) - 1}"
            scores = self.evaluate_snapshot(snap, label)
            for mode, rows in scores.items():
                for row in rows:
                    i = row["candidate_kf"]
                    if i not in histories[mode]:
                        count = row["sample_count"]
                        histories[mode][i] = dict(creation={k: v for k, v in row.items() if k != "counts"},
                                                 first_source_kf=None, first_source_input=None,
                                                 first_geometry_kf=np.full(count, -1, dtype=int),
                                                 first_geometry_input=np.full(count, -1, dtype=int),
                                                 first_geometry_wall=np.full(count, np.nan),
                                                 ever_2plus=np.zeros(count, dtype=bool))
                    hist = histories[mode][i]
                    hist["ever_2plus"] |= row["counts"] >= 2
                    if row["source_disjoint_views"] and hist["first_source_kf"] is None:
                        hist["first_source_kf"] = len(snap["metadata"]) - 1
                        hist["first_source_input"] = snap["input_frame"]
                    first = (hist["first_geometry_kf"] < 0) & (row["counts"] >= 1)
                    hist["first_geometry_kf"][first] = len(snap["metadata"]) - 1
                    hist["first_geometry_input"][first] = snap["input_frame"]
                    hist["first_geometry_wall"][first] = (
                        snap["captured_monotonic_ns"] - metadata[i]["created_monotonic_ns"]) / 1e9
        oracle = self.evaluate_snapshot(final, "hindsight_final_revision")
        summaries = {}
        candidates = []
        for mode, history in histories.items():
            total = sum(h["creation"]["sample_count"] for h in history.values())
            all_frame_delays, all_kf_delays, all_wall_delays = [], [], []
            for i, hist in history.items():
                available = hist["first_geometry_kf"] >= 0
                frame_delays = hist["first_geometry_input"][available] - metadata[i]["frame_id"]
                kf_delays = hist["first_geometry_kf"][available] - i
                assert (frame_delays >= 0).all() and (kf_delays >= 0).all()
                all_frame_delays.extend(frame_delays.tolist())
                all_kf_delays.extend(kf_delays.tolist())
                all_wall_delays.extend(hist["first_geometry_wall"][available].tolist())
                candidates.append(dict(mode=mode, candidate_kf=i, input_frame=metadata[i]["frame_id"],
                                       original_frame=2 * metadata[i]["frame_id"],
                                       source_input_frames=metadata[i]["candidate_sources"],
                                       final_fused_source_count=len(metadata[i]["fused"]["images"]),
                                       creation=hist["creation"],
                                       first_source_kf_delay=None if hist["first_source_kf"] is None else hist["first_source_kf"] - i,
                                       first_source_input_delay=None if hist["first_source_input"] is None else hist["first_source_input"] - metadata[i]["frame_id"],
                                       eventual_causal_geometry_fraction=float(available.mean()),
                                       eventual_causal_geometry_2plus_fraction=float(hist["ever_2plus"].mean()),
                                       first_geometry_input_delay=percentile_summary(frame_delays),
                                       first_geometry_kf_delay=percentile_summary(kf_delays),
                                       first_geometry_instrumented_wall_seconds=percentile_summary(hist["first_geometry_wall"][available])))
            source_at_creation = sum(h["creation"]["source_disjoint_views"] > 0 for h in history.values())
            summaries[mode] = dict(
                candidate_pools=len(history), raw_candidates=len(history) * int(np.prod(final["image_shape"])),
                sampled_candidates=total,
                source_disjoint_at_creation_pool_fraction=source_at_creation / len(history),
                source_disjoint_eventual_pool_fraction=sum(h["first_source_kf"] is not None for h in history.values()) / len(history),
                geometry_at_creation_fraction=sum(h["creation"]["sample_supported_1plus"] for h in history.values()) / total,
                geometry_at_creation_2plus_fraction=sum(h["creation"]["sample_supported_2plus"] for h in history.values()) / total,
                geometry_eventual_causal_fraction=sum(int((h["first_geometry_kf"] >= 0).sum()) for h in history.values()) / total,
                geometry_eventual_causal_2plus_fraction=sum(int(h["ever_2plus"].sum()) for h in history.values()) / total,
                geometry_final_revision_hindsight_fraction=sum(r["sample_supported_1plus"] for r in oracle[mode]) / total,
                first_geometry_input_delay=percentile_summary(all_frame_delays),
                first_geometry_deferred_only_input_delay=percentile_summary([v for v in all_frame_delays if v > 0]),
                first_geometry_original_frame_delay=percentile_summary(np.asarray(all_frame_delays) * 2),
                first_geometry_kf_delay=percentile_summary(all_kf_delays),
                first_geometry_instrumented_wall_seconds=percentile_summary(all_wall_delays))
        return summaries, candidates, final

    def run_all(self):
        torch.set_num_threads(2)
        checks = self.validate()
        print(json.dumps(checks, indent=2), flush=True)
        availability, candidates, final = self.availability()
        pose_changes = []
        final_poses = [sim3_matrix(p) for p in final["poses"].numpy()]
        for e in self.events:
            if e["kind"] != "snapshot" or e["stage"] != "decision":
                continue
            snap = self.snapshot(e)
            for i, p in enumerate(snap["poses"].numpy()):
                current = sim3_matrix(p)
                pose_changes.append(dict(decision_input=snap["input_frame"], kf=i,
                                         decision_revision=snap["pose_revision"], final_revision=final["pose_revision"],
                                         translation_difference_slam_units=float(np.linalg.norm(current[:3, 3] - final_poses[i][:3, 3])),
                                         scale_ratio_to_final=float(np.cbrt(np.linalg.det(current[:3, :3]) / np.linalg.det(final_poses[i][:3, :3]))),
                                         rotation_difference_degrees=float(np.degrees(Rotation.from_matrix(
                                             (final_poses[i][:3, :3] / np.cbrt(np.linalg.det(final_poses[i][:3, :3]))).T @
                                             (current[:3, :3] / np.cbrt(np.linalg.det(current[:3, :3])))).magnitude()))))
        memory = []
        for line in (self.run / "device_memory.csv").read_text().splitlines()[1:]:
            try:
                memory.append(float(line.split(",")[1].split()[0]))
            except (IndexError, ValueError):
                pass
        from plyfile import PlyData
        ply = PlyData.read(str(self.run / "map/office0_gaussians.ply"))
        result = dict(case=self.manifest["case"], checks=checks, availability=availability,
                      candidate_pools=candidates, pair_audit_rows=len(self.pair_rows),
                      pose_changes=pose_changes,
                      keyframe_original_frames=[2 * m["frame_id"] for m in final["metadata"]],
                      final_fused_ancestry=[dict(kf=i, source_images=m["fused"]["images"],
                                                raw_events=len(m["fused"]["events"])) for i, m in enumerate(final["metadata"])],
                      active_gaussians=len(ply["vertex"].data),
                      execution_wall_seconds=int((self.run / "wall_seconds.txt").read_text()),
                      sampled_device_memory_peak_mib=max(memory) if memory else None,
                      memory_sampling_ms=200,
                      specification=self.spec)
        creation_pairs = [r for r in self.pair_rows if r["snapshot"] != "hindsight_final_revision"
                          and r["candidate_input"] == r["decision_input"]]
        result["creation_evidence_pair_grades"] = {}
        for mode in ("raw", "fused"):
            rows = [r for r in creation_pairs if r["mode"] == mode]
            result["creation_evidence_pair_grades"][mode] = dict(
                self=len(final["metadata"]), cross_view_pairs=len(rows),
                source_disjoint=sum(r["source_disjoint"] for r in rows),
                source_overlap=sum(not r["source_disjoint"] and r["ancestry_status"] == "traced" for r in rows),
                unknown=sum(r["ancestry_status"] != "traced" for r in rows))
        naive = {(r["candidate_kf"], r["evidence_kf"]) for r in creation_pairs if r["mode"] == "raw" and r["source_disjoint"]}
        contaminated = [r for r in creation_pairs if r["mode"] == "fused"
                        and (r["candidate_kf"], r["evidence_kf"]) in naive and not r["source_disjoint"]]
        result["fused_contamination_at_creation"] = dict(
            raw_source_disjoint_pairs=len(naive), fused_overlapping_among_them=len(contaminated),
            fraction=len(contaminated) / len(naive) if naive else None,
            affected_pairs=[dict(candidate_kf=r["candidate_kf"], evidence_kf=r["evidence_kf"], shared_images=r["shared_images"]) for r in contaminated])
        result["pilot_progress_rule_pass"] = (
            checks["status"] == "PASS" and checks["final_keyframes"] >= 3
            and availability["raw"]["geometry_at_creation_fraction"] >= 0.10)
        if self.manifest["case"] == "short":
            reference = self.run.parents[1] / "E0_baseline_reproduction/map/office0_kfgauss.pt"
            if reference.exists():
                old = torch.load(reference, map_location="cpu", weights_only=True)
                new = torch.load(self.run / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
                result["e0_reference_comparison"] = dict(
                    keyframe_frames_equal=[x["frame_id"] for x in old["keyframes"]] == [x["frame_id"] for x in new["keyframes"]],
                    candidate_means_exact=all(torch.equal(x["means"], y["means"]) for x, y in zip(old["keyframes"], new["keyframes"])),
                    final_poses_exact=all(torch.equal(x["T_WC"], y["T_WC"]) for x, y in zip(old["keyframes"], new["keyframes"])),
                    fused_pointmaps_exact=all(torch.equal(x["fused_pointmap"], y["fused_pointmap"]) for x, y in zip(old["keyframes"], new["keyframes"])))
        (self.run / "audit_summary.json").write_text(json.dumps(result, indent=2) + "\n")
        with (self.run / "pair_audit.jsonl").open("w") as f:
            for row in self.pair_rows:
                f.write(json.dumps(row) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k in (
            "case", "availability", "keyframe_original_frames", "pilot_progress_rule_pass",
            "active_gaussians", "execution_wall_seconds", "sampled_device_memory_peak_mib")}, indent=2), flush=True)
        return result
