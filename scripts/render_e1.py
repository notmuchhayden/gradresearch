"""Render frozen baseline/GT-anchor diagnostic on odd, evaluation-only views."""
import argparse
import json
import os
import shutil
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src"), str(UPSTREAM), str(UPSTREAM / "scripts")]
from analyze_e1 import digest, load_view, percentile, write_json
from e1_taxonomy import transform
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer


@torch.no_grad()
def render_values(g, pose, K, hw, values):
    # Match upstream scale-invariant numeric conditioning, but honor cx/cy.
    h, w = hw
    ext = torch.tensor(pose, dtype=torch.float32, device="cuda")
    ext[:3, 3] *= 10
    view = torch.linalg.inv(ext).T.contiguous()
    near, far = 1., 10000.
    projection = torch.zeros((4, 4), dtype=torch.float32, device="cuda")
    projection[0, 0], projection[1, 1] = 2 * K[0, 0] / w, 2 * K[1, 1] / h
    # Rasterizer ndc2Pix(v,S) = ((v+1)*S-1)/2.
    projection[0, 2], projection[1, 2] = (2 * K[0, 2] + 1) / w - 1, (2 * K[1, 2] + 1) / h - 1
    projection[2, 2], projection[2, 3] = far / (far - near), -far * near / (far - near)
    projection[3, 2] = 1
    settings = GaussianRasterizationSettings(image_height=h, image_width=w,
        tanfovx=w / (2 * K[0, 0]), tanfovy=h / (2 * K[1, 1]),
        bg=torch.zeros(3, device="cuda"), scale_modifier=1., viewmatrix=view,
        projmatrix=view @ projection.T, sh_degree=0, campos=ext[:3, 3], prefiltered=False, debug=True)
    row, col = torch.triu_indices(3, 3, device="cuda")
    image, _ = GaussianRasterizer(settings)(means3D=g["means"] * 10,
        means2D=torch.zeros_like(g["means"]), shs=None, colors_precomp=values.contiguous(),
        opacities=g["opacity"][:, None], cov3D_precomp=(g["covariances"] * 100)[:, row, col])
    return image.reshape(3, h, w)


def smoke():
    K = np.array([[50., 0, 31.5], [0, 50, 31.5], [0, 0, 1.]])
    g = dict(means=torch.tensor([[0., 0, 1.], [0., 0, 2.]], device="cuda"),
             covariances=torch.eye(3, device="cuda")[None].repeat(2, 1, 1) * 0.01 ** 2,
             opacity=torch.full((2,), 0.5, device="cuda"))
    values = torch.tensor([[1., 1, 0], [2., 0, 1]], device="cuda")
    image = render_values(g, np.eye(4), K, (64, 64), values)
    depth = image[0] / (image[1] + image[2]).clamp_min(1e-9)
    assert 1 < depth[32, 32] < 2
    assert 0 < image[2, 32, 32] < image[1, 32, 32] < 1
    # A principal-point shift must move the same density by exactly that many pixels.
    shifted_K = K.copy()
    shifted_K[0, 2] += 5
    shifted = render_values(g, np.eye(4), shifted_K, (64, 64), values)
    torch.testing.assert_close(shifted[:, :, 5:], image[:, :, :-5], atol=1e-5, rtol=1e-5)
    print("CUDA synthetic front/back compositing and class attribution: PASS", flush=True)


def frame_metrics(pred, weight, bad_weight, view, spec):
    gt = view["depth"]
    valid, edge = view["valid"], view["edge"]
    covered = np.isfinite(pred) & (pred > 0) & (weight > spec["render_coverage_weight_min"])
    tol = np.maximum(spec["depth_tolerance_abs_m"], spec["depth_tolerance_relative"] * gt)
    error = np.abs(pred - gt)
    correct = covered & (error <= tol)
    result = dict(original_frame_id=view["frame"], gt_valid_pixels=int(valid.sum()),
                  covered_gt_pixels=int((covered & valid).sum()),
                  gt_depth_coverage=float(np.mean(covered[valid])),
                  missing_coverage_fraction=float(np.mean(~covered[valid])),
                  depth_correct_coverage=float(np.mean(correct[valid])),
                  depth_l1_m=float(np.mean(error[covered & valid])),
                  depth_absrel=float(np.mean((error / np.maximum(gt, 1e-9))[covered & valid])),
                  mean_composited_front_class_weight=float(np.mean(bad_weight[valid])),
                  front_class_fraction_of_render_weight=float(np.sum(bad_weight[valid]) / max(np.sum(weight[valid]), 1e-9)))
    for name, mask in (("interior", valid & ~edge), ("depth_boundary", valid & edge)):
        result[name] = dict(gt_pixels=int(mask.sum()), coverage=float(np.mean(covered[mask])) if mask.any() else None,
                            depth_correct_coverage=float(np.mean(correct[mask])) if mask.any() else None,
                            rendered_too_front_fraction=float(np.mean((covered & (pred < gt - tol))[mask])) if mask.any() else None)
    result["sensitivity_depth_correct_coverage"] = {
        str(t): float(np.mean((covered & (error <= np.maximum(t, spec["depth_tolerance_relative"] * gt)))[valid]))
        for t in spec["sensitivity_absolute_tolerances_m"]}
    return result


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    started = time.monotonic()
    smoke()
    if args.smoke_only:
        return
    spec = json.loads((ROOT / "configs/e1_taxonomy.json").read_text())
    run, dataset, out = [ROOT / spec[k] for k in ("baseline_run", "evaluation_dataset", "output")]
    taxonomy = json.loads((out / "taxonomy_summary.json").read_text())
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["specification_sha256"] == digest(ROOT / "configs/e1_taxonomy.json")["sha256"]
    for entry in manifest["code"]:
        assert digest(ROOT / entry["path"])["sha256"] == entry["sha256"], entry["path"]
    camera = json.loads((dataset / "cam_params.json").read_text())["camera"]
    poses = np.loadtxt(dataset / "office0/traj.txt").reshape(-1, 4, 4)
    K, hw = np.array(taxonomy["intrinsics"]), taxonomy["rgb_hw"]
    alignment = np.array(taxonomy["alignment"]["matrix"])
    labels = np.load(out / "candidate_labels.npz")
    diagnostic = np.load(out / "diagnostic_active_geometry.npz")
    original = decode_gaussians_from_ply(run / "map/office0_gaussians.ply", device="cpu")
    A = torch.tensor(alignment[:3, :3], dtype=torch.float32)
    estimated_mean = torch.tensor(transform(original["means"].numpy(), alignment), dtype=torch.float32)
    estimated_cov = A @ original["covariances"] @ A.T
    render_dir = out / "render"
    render_dir.mkdir(exist_ok=True)
    results = dict(device=torch.cuda.get_device_name(), frames={}, summaries={}, smoke="PASS",
                   definition="full-map expected z and transmittance-weighted class opacity; class labels use even GT views only; no policy update")
    active = labels["active"]
    for arm in ("estimated_pose", "gt_anchor_pose_diagnostic"):
        mu, cov = ((estimated_mean, estimated_cov) if arm == "estimated_pose" else
                   (torch.from_numpy(diagnostic["means"]), torch.from_numpy(diagnostic["covariance"])))
        g = dict(means=mu.to("cuda"), covariances=cov.to("cuda"), opacity=original["opacity"].to("cuda"))
        codes = torch.from_numpy(labels[arm + "_labels_active"][active].astype(np.int64)).to("cuda")
        rows = []
        residual_max = 0.
        for frame in range(1, 360, 2):
            view = load_view(dataset, frame, camera, poses, spec)
            pose = view["pose"]
            z = (g["means"] - torch.tensor(pose[:3, 3], dtype=torch.float32, device="cuda")) @ torch.tensor(pose[:3, 2], dtype=torch.float32, device="cuda")
            first = render_values(g, pose, K, hw, torch.stack([z, torch.ones_like(z), (codes == 3).float()], dim=1))
            other = render_values(g, pose, K, hw, torch.stack([(codes == 0).float(), (codes == 1).float(), (codes == 2).float()], dim=1))
            residual = float((other.sum(0) + first[2] - first[1]).abs().max())
            assert residual < 2e-5, residual
            residual_max = max(residual_max, residual)
            pred = (first[0] / first[1].clamp_min(1e-9)).cpu().numpy()
            weight, bad_weight = first[1].cpu().numpy(), first[2].cpu().numpy()
            row = frame_metrics(pred, weight, bad_weight, view, spec)
            row["split"] = "validation" if frame < 40 else "held_out_test" if frame < 120 else "extension_held_out_diagnostic"
            rows.append(row)
            if frame in (1, 41, 81, 149, 223, 299):
                np.savez_compressed(render_dir / f"{arm}_frame{frame:06d}.npz", gt_depth=view["depth"],
                                    rendered_depth=pred, weight=weight, front_class_weight=bad_weight,
                                    edge=view["edge"], valid=view["valid"])
            if frame % 40 == 1:
                print(json.dumps(dict(arm=arm, frame=frame, l1_m=row["depth_l1_m"], coverage=row["gt_depth_coverage"])), flush=True)
        results["frames"][arm] = rows
        results["summaries"][arm] = {}
        for split in ("validation", "held_out_test", "extension_held_out_diagnostic", "all"):
            selected = [r for r in rows if r["split"] == split or split == "all"]
            summary = dict(n_frames=len(selected),
                aggregation="unweighted per-frame means; single scene; covered-only L1 accompanies all-GT coverage",
                class_weight_partition_max_abs_error=residual_max)
            for key in ("gt_depth_coverage", "missing_coverage_fraction", "depth_correct_coverage", "depth_l1_m", "depth_absrel",
                        "mean_composited_front_class_weight", "front_class_fraction_of_render_weight"):
                summary[key] = float(np.mean([r[key] for r in selected]))
            for region in ("interior", "depth_boundary"):
                summary[region] = {key: float(np.mean([r[region][key] for r in selected if r[region][key] is not None]))
                                   for key in ("coverage", "depth_correct_coverage", "rendered_too_front_fraction")}
            summary["sensitivity_depth_correct_coverage"] = {
                str(t): float(np.mean([r["sensitivity_depth_correct_coverage"][str(t)] for r in selected]))
                for t in spec["sensitivity_absolute_tolerances_m"]}
            results["summaries"][arm][split] = summary
        del g, codes
        torch.cuda.empty_cache()
    results["wall_seconds"] = time.monotonic() - started
    write_json(out / "render_metrics.json", results)
    write_json(ROOT / "configs/e1_render_results_summary.json", {k: v for k, v in results.items() if k != "frames"})
    write_json(out / "render_manifest.json", dict(code=digest(Path(__file__)),
                taxonomy_sha256=digest(out / "taxonomy_summary.json")["sha256"],
                labels_sha256=digest(out / "candidate_labels.npz")["sha256"],
                cuda=torch.version.cuda, torch=torch.__version__, gpu=torch.cuda.get_device_name(),
                peak_torch_allocated_bytes=torch.cuda.max_memory_allocated(),
                peak_torch_reserved_bytes=torch.cuda.max_memory_reserved(),
                environment={k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}))
    shutil.copy2(out / "render_manifest.json", ROOT / "configs/e1_render_manifest.json")
    print(json.dumps(results["summaries"], indent=2), flush=True)


if __name__ == "__main__":
    main()
