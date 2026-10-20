"""Evaluate sealed GT-free E2 scores against E1/creation-pose GT proxies."""
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.spatial import cKDTree
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"),
               str(ROOT / "thirdparty/Splatt3R-SLAM/splatt3r_core")]
from score_e2 import digest, save_json
from e0b_audit import transform
from e1_taxonomy import classify
from e2_metrics import calibrate_normal_threshold, operating_point, pr_metrics
from e2_signals import METHODS
from analyze_e1 import load_view
from utils.geometry import build_covariance


def evaluate(score, labels, universe, threshold_by_retention):
    bad, normal = labels == 3, np.isin(labels, [1, 2])
    available = np.isfinite(score) & universe
    labeled = (bad | normal) & universe
    used = available & labeled
    metric, curve = pr_metrics(bad[used], score[used])
    metric.update(universe=int(universe.sum()), labeled_universe=int(labeled.sum()),
                  score_eligible=int(available.sum()), labeled_eligible=int(used.sum()),
                  score_coverage=float(available.sum() / max(universe.sum(), 1)),
                  labeled_coverage=float(used.sum() / max(labeled.sum(), 1)),
                  global_bad_score_coverage=float((bad & available).sum() / max((bad & universe).sum(), 1)),
                  operating_points={ret: operating_point(score, bad, normal, value, universe)
                                    for ret, value in threshold_by_retention.items()})
    return metric, curve


def main():
    started = time.monotonic()
    torch.set_num_threads(2)
    spec = json.loads((ROOT / "configs/e2_discriminability.json").read_text())
    out, baseline, e1 = [ROOT / spec[k] for k in ("output", "baseline_run", "e1_run")]
    manifest = json.loads((out / "score_manifest.json").read_text())
    for entry in manifest["code"] + manifest["inputs"]:
        assert digest(ROOT / entry["path"])["sha256"] == entry["sha256"], entry["path"]
    assert digest(out / "features.npz")["sha256"] == manifest["feature_sha256"]
    b8_manifest = json.loads((out / "b8_manifest.json").read_text())
    assert b8_manifest["gt_reads"] == "forbidden" and not b8_manifest["final_map_used"]
    assert b8_manifest["score_manifest_sha256"] == digest(out / "score_manifest.json")["sha256"]
    assert b8_manifest["features_sha256"] == digest(out / "b8_features.npz")["sha256"]
    feature_file = np.load(out / "features.npz")
    features = {k: feature_file[k] for k in feature_file.files}
    b8 = np.load(out / "b8_features.npz")["B8_dog_redundancy"]
    for mode in spec["score_availability_modes"]:
        features[mode + "__B8_dog_redundancy"] = b8
    old = np.load(e1 / "candidate_labels.npz")
    np.testing.assert_array_equal(features["active"], old["active"])
    np.testing.assert_array_equal(features["anchor_kf"], old["anchor_kf"])
    np.testing.assert_array_equal(features["pixel_index"], old["pixel_index"])
    e1_summary = json.loads((e1 / "taxonomy_summary.json").read_text())
    e1_manifest = json.loads((e1 / "render_manifest.json").read_text())
    assert digest(e1 / "candidate_labels.npz")["sha256"] == e1_manifest["labels_sha256"]
    label_spec = e1_summary["specification"]
    dataset = ROOT / label_spec["evaluation_dataset"]
    camera = json.loads((dataset / "cam_params.json").read_text())["camera"]
    gt_poses = np.loadtxt(dataset / "office0/traj.txt").reshape(-1, 4, 4)
    views = [load_view(dataset, i, camera, gt_poses, label_spec) for i in e1_summary["taxonomy_gt_view_ids"]]
    alignment = np.array(e1_summary["alignment"]["matrix"])
    dump = torch.load(baseline / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
    means, covariance = [], []
    for i, kf in enumerate(dump["keyframes"]):
        pose = alignment @ features["creation_poses"][i]
        means.append(transform(kf["means"].numpy(), pose))
        q = kf["rotations"] / kf["rotations"].norm(dim=-1, keepdim=True).clamp_min(1e-6)
        cov = build_covariance(kf["scales"], q).numpy()
        covariance.append(pose[:3, :3] @ cov @ pose[:3, :3].T)
    current = classify(np.concatenate(means), np.concatenate(covariance), views,
                       np.array(e1_summary["intrinsics"]), label_spec)["labels"]
    labels_raw = dict(creation_pose_gt_proxy=current,
                     e1_final_estimated=old["estimated_pose_labels_raw"],
                     e1_gt_anchor=old["gt_anchor_pose_diagnostic_labels_raw"])
    labels_active = dict(creation_pose_gt_proxy=current,
                        e1_final_estimated=old["estimated_pose_labels_active"],
                        e1_gt_anchor=old["gt_anchor_pose_diagnostic_labels_active"])
    for dictionaries in (labels_raw, labels_active):
        a, b = dictionaries["e1_final_estimated"], dictionaries["e1_gt_anchor"]
        consensus = np.zeros(len(a), np.uint8)
        consensus[(a == 3) & (b == 3)] = 3
        consensus[np.isin(a, [1, 2]) & np.isin(b, [1, 2])] = 1
        dictionaries["e1_cross_pose_consensus"] = consensus
    np.savez_compressed(out / "evaluation_labels.npz", **{"raw__" + k: v for k, v in labels_raw.items()},
                        **{"active__" + k: v for k, v in labels_active.items()})
    anchors, active = features["anchor_kf"], features["active"]
    development = np.isin(anchors, spec["development_kfs"])
    temporal = np.isin(anchors, spec["temporal_evaluation_kfs"])
    # Seal calibration before calculating any temporal-partition performance.
    thresholds = {}
    primary = labels_raw["creation_pose_gt_proxy"]
    for scope, mask in (("raw", np.ones(len(primary), bool)), ("active", active)):
        thresholds[scope] = {}
        for mode in spec["score_availability_modes"]:
            thresholds[scope][mode] = {}
            for method in METHODS:
                score = features[mode + "__" + method]
                thresholds[scope][mode][method] = {
                    str(ret): calibrate_normal_threshold(score, development & mask & (primary == 1), ret)
                    for ret in spec["normal_retention_targets"]}
    save_json(out / "thresholds_development_only.json", thresholds)
    threshold_hash = digest(out / "thresholds_development_only.json")["sha256"]
    results = dict(specification=spec, calibration_sha256=threshold_hash, primary_label="creation_pose_gt_proxy",
                   label_definition="bad=3, protected normal=1/2, unknown=0 excluded; creation proxy has no redundancy subclass",
                   results={}, common_cohorts={}, duplicate_diagnostic={}, integrity=dict(
                   score_inputs_code="PASS", no_gt_feature_reads="PASS", no_final_premap="PASS", candidate_identity="PASS"))
    curves = {}
    for scope, mask, labels in (("raw", np.ones(len(primary), bool), labels_raw), ("active", active, labels_active)):
        results["results"][scope] = {}
        for label_name, label in labels.items():
            label_rows = {}
            for mode in spec["score_availability_modes"]:
                mode_rows = {}
                for partition, subset in (("development", development), ("temporal_evaluation", temporal),
                                          ("all_descriptive", np.ones(len(primary), bool))):
                    table = {}
                    for method in METHODS:
                        score = features[mode + "__" + method]
                        table[method], curve = evaluate(score, label, mask & subset, thresholds[scope][mode][method])
                        if scope == "raw" and label_name == "creation_pose_gt_proxy" and partition == "temporal_evaluation":
                            curves[mode + "__" + method + "__recall"] = curve[0]
                            curves[mode + "__" + method + "__precision"] = curve[1]
                    mode_rows[partition] = table
                label_rows[mode] = mode_rows
            results["results"][scope][label_name] = label_rows
        results["common_cohorts"][scope] = {}
        for mode in spec["score_availability_modes"]:
            groups = []
            for group in spec["common_cohorts"]:
                common = mask.copy()
                for method in group:
                    common &= np.isfinite(features[mode + "__" + method])
                table = {}
                for label_name, label in labels.items():
                    table[label_name] = {method: evaluate(features[mode + "__" + method], label, common & temporal,
                        thresholds[scope][mode][method])[0] for method in group}
                groups.append(dict(methods=group, raw_temporal_universe=int((mask & temporal).sum()),
                                   common_temporal_candidates=int((common & temporal).sum()), metrics=table))
            results["common_cohorts"][scope][mode] = groups
        # B8 primarily targets redundancy, which is a different positive label.
        label = labels["e1_final_estimated"]
        available = mask & temporal & np.isin(label, [1, 2]) & np.isfinite(b8)
        results["duplicate_diagnostic"][scope] = pr_metrics(label[available] == 2, b8[available])[0]
    age = {}
    input_frames = np.array([row["frame_id"] for row in dump["keyframes"]])
    creation_input = input_frames[anchors]
    for method in ("B6_depth_front", "B7_rgb_ncc_region", "P1_plane_front_1view", "P1_plane_front_2view"):
        first = features["first_eligible_input__" + method]
        seen = first >= 0
        delay = first[seen] - creation_input[seen]
        age[method] = dict(ever_eligible=int(seen.sum()), never_eligible_fraction=float((~seen).mean()),
                          first_input_delay_median=float(np.median(delay)) if len(delay) else None,
                          first_input_delay_p95=float(np.percentile(delay, 95)) if len(delay) else None)
    results["availability_delay"] = age
    # A predeclared descriptive progress rule; no research-wide GO from one scene.
    common = results["common_cohorts"]["raw"]["at_creation"][1]
    t = common["metrics"]["creation_pose_gt_proxy"]
    p, b6, b7 = [t[m] for m in ("P1_plane_front_1view", "B6_depth_front", "B7_rgb_ncc_region")]
    sufficient = (p["bad"] >= 100 and p["normal"] >= 100 and
                  common["common_temporal_candidates"] >= 0.01 * common["raw_temporal_universe"])
    lead = sufficient and all(x["average_precision"] is not None for x in (p, b6, b7)) and (
        p["average_precision"] >= b6["average_precision"] + 0.02 and
        p["average_precision"] >= b7["average_precision"] + 0.02)
    own = results["results"]["raw"]["creation_pose_gt_proxy"]["at_creation"]["temporal_evaluation"]["P1_plane_front_1view"]
    retention = own["operating_points"]["0.99"]["global_normal_retention"]
    lead = bool(lead and retention is not None and retention >= 0.99)
    two = np.isfinite(features["at_creation__P1_plane_front_2view"])
    results["decision"] = dict(common_temporal_cohort_sufficient=bool(sufficient),
        predeclared_descriptive_signal_lead=lead, actual_repeated_view_coverage=float(two.mean()),
        research_wide_go=False, admission_gate_validated=False,
        interpretation="pilot score comparison only; preserve unknowns; additional scenes and repeated-view evidence required")
    results["evaluation_wall_seconds"] = time.monotonic() - started
    results["label_counts_raw"] = {name: {str(code): int((value == code).sum()) for code in (0, 1, 2, 3)}
                                  for name, value in labels_raw.items()}
    np.savez_compressed(out / "pr_curves.npz", **curves)
    save_json(out / "metrics.json", results)
    save_json(ROOT / "configs/e2_results_summary.json", results)
    eval_inputs = [out / "features.npz", out / "b8_features.npz", out / "score_manifest.json", out / "b8_manifest.json",
                   e1 / "candidate_labels.npz", e1 / "taxonomy_summary.json", e1 / "render_manifest.json",
                   dataset / "cam_params.json", dataset / "office0/traj.txt",
                   *[dataset / "office0/results" / f"depth{i:06d}.png" for i in e1_summary["taxonomy_gt_view_ids"]]]
    save_json(out / "evaluation_manifest.json", dict(inputs=[digest(p) for p in eval_inputs],
        thresholds_sha256=threshold_hash, code=[digest(Path(__file__)), digest(ROOT / "src/e2_metrics.py")],
        metrics_sha256=digest(out / "metrics.json")["sha256"], gt_use="evaluation labels only; thresholds use development normal labels only"))
    save_json(ROOT / "configs/e2_code_manifest.json", dict(score=manifest, b8=b8_manifest,
               evaluation=json.loads((out / "evaluation_manifest.json").read_text())))
    print(json.dumps(results["decision"], indent=2), flush=True)
    for method, values in results["results"]["raw"]["creation_pose_gt_proxy"]["at_creation"]["temporal_evaluation"].items():
        print(json.dumps(dict(method=method, ap=values["average_precision"], coverage=values["score_coverage"],
                              bad=values["bad"], normal=values["normal"], at_99=values["operating_points"]["0.99"])), flush=True)


if __name__ == "__main__":
    main()
