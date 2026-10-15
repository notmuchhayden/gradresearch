"""Check real candidate lineage, Sim(3) placement and serialized-map fidelity."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
RUN = ROOT / "results/E0_baseline_reproduction"
sys.path[:0] = [str(UPSTREAM), str(UPSTREAM / "scripts")]

import lietorch
import numpy as np
import torch
from eval_map_quality import render_map
from splatt3r_slam.splatt3r_utils import _sim3_to_4x4, bake_gaussians_world
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply


@torch.no_grad()
def main():
    # Verify coordinate algebra without TF32's reduced mantissa precision.
    torch.backends.cuda.matmul.allow_tf32 = False
    angle = 0.7
    transform = lietorch.Sim3(torch.tensor([[1., 2., 3., 0., 0., np.sin(angle / 2), np.cos(angle / 2), 2.]], device="cuda", dtype=torch.float32))
    local = {"means": torch.tensor([[0.1, -0.2, 2.]], device="cuda"),
             "scales": torch.tensor([[0.1, 0.2, 0.3]], device="cuda"),
             "rotations": torch.tensor([[0., 0., np.sin(0.15), np.cos(0.15)]], device="cuda", dtype=torch.float32),
             "sh": torch.zeros(1, 3, 1, device="cuda"),
             "opacities": torch.ones(1, 1, device="cuda") * 0.9,
             "conf": torch.ones(1, 1, device="cuda") * 10}
    world, tri, _, _ = bake_gaussians_world(local, torch.zeros(3, 1, 1, device="cuda"), 1, 1, transform,
        depth_max_percentile=1.0, max_scale=1.0, min_confidence=0, min_opacity=0, inflate_scales_for_stride=False)
    matrix = _sim3_to_4x4(transform)[0]
    expected_mean = transform.act(local["means"])
    gaussian_rotation = torch.tensor([[np.cos(0.3), -np.sin(0.3), 0.],
                                     [np.sin(0.3), np.cos(0.3), 0.], [0., 0., 1.]], device="cuda", dtype=torch.float32)
    local_covariance = gaussian_rotation @ torch.diag(local["scales"][0] ** 2) @ gaussian_rotation.T
    expected_cov = matrix[:3, :3] @ local_covariance @ matrix[:3, :3].T
    row, col = torch.triu_indices(3, 3, device="cuda")
    torch.testing.assert_close(world, expected_mean)
    torch.testing.assert_close(tri[0], expected_cov[row, col])
    recovered = transform.inv().act(world)
    torch.testing.assert_close(recovered, local["means"])
    inverse = torch.linalg.inv(matrix[:3, :3])
    torch.testing.assert_close(inverse @ expected_cov @ inverse.T, local_covariance)
    print("Sim(3) mean/covariance, scale squared and inverse checks: PASS", flush=True)

    # Reconstruct the real map using the same numeric mode as upstream main.py.
    torch.backends.cuda.matmul.allow_tf32 = True

    dump = torch.load(RUN / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
    sources = [json.loads(p.read_text()) for p in (RUN / "exports/candidate_sources").glob("*.json")]
    baked = []
    raw_count = 0
    lineage = []
    for kf in dump["keyframes"]:
        records = [r for r in sources if r["frame_id"] == kf["frame_id"] and r["anchor_kf"] == kf["kf_idx"]]
        matches = []
        for record in records:
            raw = torch.load(RUN / "exports/raw_pairs" / f"{record['prediction_event_id']}.pt", map_location="cpu", weights_only=True)
            if torch.equal(raw["outputs"][0]["means"].reshape(-1, 3), kf["means"]):
                matches.append((record, raw))
        assert matches, f"No exact raw candidate provenance for KF {kf['kf_idx']}"
        record, raw = matches[-1]
        assert all(0 <= i < 60 for i in raw["source_image_ids"])
        assert raw["anchor_frame_id"] == kf["frame_id"]
        assert kf["fused_pointmap"].shape == kf["means"].shape
        raw_count += kf["means"].shape[0]
        lineage.append({"anchor_kf": kf["kf_idx"], "frame_id": kf["frame_id"],
                        "prediction_event_id": record["prediction_event_id"], "source_image_ids": raw["source_image_ids"],
                        "original_source_frame_ids": [2 * i for i in raw["source_image_ids"]],
                        "candidates": kf["means"].shape[0], "fused_ancestry_status": "unknown"})
        kwargs = {k: kf[k].to("cuda") for k in ("means", "scales", "rotations", "sh", "opacities", "conf")}
        result = bake_gaussians_world(kwargs, kf["img"].to("cuda"), *kf["img_shape"],
            lietorch.Sim3(kf["T_WC"].to("cuda")), spatial_stride=1, depth_max_percentile=0.98,
            max_scale=1., min_confidence=1.5, inflate_scales_for_stride=False)
        if result is not None:
            baked.append(result)
    means, covariance_tri, rgb, opacity = [torch.cat([b[i] for b in baked]) for i in range(4)]
    covariance = torch.zeros(means.shape[0], 3, 3, device="cuda")
    covariance[:, row, col] = covariance_tri
    covariance[:, col, row] = covariance_tri
    live = {"means": means, "covariances": covariance, "rgb": rgb, "opacity": opacity}
    persisted = decode_gaussians_from_ply(RUN / "map/office0_gaussians.ply", device="cuda")
    assert means.shape[0] == persisted["n"]
    torch.testing.assert_close(persisted["means"], means, atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(persisted["covariances"], covariance, atol=1e-5, rtol=1e-4)
    # Any fixed pinhole camera gives the same before/after serialization check.
    h, w = dump["keyframes"][0]["img_shape"]
    K = np.array([[0.5 * w, 0, 0.5 * w], [0, 0.5 * w, 0.5 * h], [0, 0, 1.]])
    T = _sim3_to_4x4(lietorch.Sim3(dump["keyframes"][0]["T_WC"].to("cuda")))[0].cpu().numpy()
    s = np.linalg.det(T[:3, :3]) ** (1 / 3)
    T[:3, :3] /= s
    before = render_map(live, T, K, (h, w), "cuda")
    after = render_map(persisted, T, K, (h, w), "cuda")
    error = (before - after).abs()
    assert error.mean().item() < 1e-4
    report = {"sim3_checks": "PASS", "lineage_checks": "PASS", "keyframes": dump["n"],
              "final_kf_candidate_count": raw_count, "active_gaussian_count": persisted["n"],
              "all_raw_pair_events": len(list((RUN / "exports/raw_pairs").glob("*.pt"))),
              "serialization_render_mean_abs_error": error.mean().item(),
              "serialization_render_max_abs_error": error.max().item(),
              "fused_ancestry_status": "unknown", "pose_revision": "final_snapshot_unversioned", "lineage": lineage}
    (RUN / "export_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "lineage"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
