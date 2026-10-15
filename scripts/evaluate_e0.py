"""E0 pilot evaluator: explicit unseen RGB frames and rendered GT-depth metrics.

Uses the upstream renderer and a single evaluation-only Sim(3) alignment.
This is a feasibility check, not an admission-policy comparison or TSDF metric.
"""
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
RUN = ROOT / "results/E0_baseline_reproduction"
sys.path[:0] = [str(UPSTREAM), str(UPSTREAM / "scripts")]
os.environ.pop("E0_DISABLE_GT", None)

import cv2
import lpips
import numpy as np
import torch
from skimage.metrics import structural_similarity
from eval_map_quality import load_tum_traj, associate, umeyama_sim3, render_map
from eval_map_geometry import render_depth, resize_depth_like_rgb
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
from splatt3r_slam.config import load_config
from splatt3r_slam.dataloader import load_dataset
from splatt3r_slam.splatt3r_utils import resize_img
from splatt3r_slam.image import normalize_exposure, reset_exposure_reference


@torch.no_grad()
def main():
    os.chdir(UPSTREAM)
    load_config(str(ROOT / "configs/e0_replica_office0.yaml"))
    dataset = load_dataset(str(ROOT / "data/Replica/office0"))
    gt_ts, gt_pose = load_tum_traj(dataset.dataset_path / "groundtruth.txt")
    timestamps, estimates = load_tum_traj(RUN / "map/office0_frames.txt")
    pairs = associate(timestamps, gt_ts)
    if len(pairs) < 3:
        raise RuntimeError("At least 3 matched tracked-frame poses required for evaluation alignment")
    source = np.array([estimates[i, :3, 3] for i, _ in pairs])
    target = np.array([gt_pose[j, :3, 3] for _, j in pairs])
    if np.var(source, axis=0).sum() < 1e-10:
        raise RuntimeError("Degenerate trajectory; scale cannot be estimated")
    scale, rotation, translation = umeyama_sim3(source, target)
    if not np.isfinite(scale) or scale <= 0:
        raise RuntimeError("Invalid alignment scale")
    g = decode_gaussians_from_ply(RUN / "map/office0_gaussians.ply", device="cuda")
    # Load persisted state a second time to verify deterministic re-rendering.
    g_reload = decode_gaussians_from_ply(RUN / "map/office0_gaussians.ply", device="cuda")
    reset_exposure_reference()
    normalize_exposure(dataset.get_image(0))
    perceptual = lpips.LPIPS(net="alex", verbose=False).eval().to("cuda")
    rows = []
    reload_error = None
    frames = list(range(1, 40, 2)) + list(range(41, 120, 2))
    assert all(i % 2 == 1 for i in frames)  # Mapper received only even frames.
    camera = json.loads((ROOT / "data/Replica/cam_params.json").read_text())["camera"]
    # Tracking is uncalibrated, so the loader intentionally returns no K.
    # Evaluate against the raw pinhole camera, transformed by the exact RGB crop.
    _, (scale_w, scale_h, crop_w, crop_h) = resize_img(
        dataset.get_image(0), dataset.img_size, return_transformation=True)
    K_frame = np.array([[camera['fx'] / scale_w, 0., camera['cx'] / scale_w - crop_w],
                        [0., camera['fy'] / scale_h, camera['cy'] / scale_h - crop_h],
                        [0., 0., 1.]])
    for index in frames:
        rgb = normalize_exposure(dataset.get_image(index))
        image = resize_img(rgb, dataset.img_size)["img"] * 0.5 + 0.5
        h, w = image.shape[-2:]
        c2w = np.eye(4)
        c2w[:3, :3] = rotation.T @ gt_pose[index, :3, :3]
        c2w[:3, 3] = rotation.T @ (gt_pose[index, :3, 3] - translation) / scale
        pred = render_map(g, c2w, K_frame, (h, w), "cuda").reshape(1, 3, h, w).clamp(0, 1)
        if reload_error is None:
            second = render_map(g_reload, c2w, K_frame, (h, w), "cuda").reshape_as(pred).clamp(0, 1)
            reload_error = (second - pred).abs().max().item()
            assert reload_error <= 1e-6, reload_error
            del second, g_reload
        depth, covered = render_depth(g, c2w, K_frame, (h, w), "cuda")
        depth = depth.cpu().numpy() * scale
        covered = covered.cpu().numpy()
        raw = cv2.imread(str(dataset.dataset_path / "results" / f"depth{index:06d}.png"), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise FileNotFoundError(f"depth{index:06d}.png")
        gt = resize_depth_like_rgb(raw.astype(np.float32) / camera["scale"], dataset.img_size)
        assert gt.shape == (h, w)
        valid = np.isfinite(gt) & (gt > 0)
        mask = valid & covered & np.isfinite(depth) & (depth > 0)
        predicted = pred[0].cpu().numpy().transpose(1, 2, 0)
        target_image = image[0].cpu().numpy().transpose(1, 2, 0)
        mse = float(np.mean((predicted - target_image) ** 2))
        row = {"original_frame_id": index, "split": "validation" if index < 40 else "held_out_test",
               "psnr_db": -10 * math.log10(max(mse, 1e-12)),
               "lpips_alex": float(perceptual(pred, image.to("cuda"), normalize=True).mean()),
               "ssim": float(structural_similarity(predicted, target_image, channel_axis=2, data_range=1)),
               "gt_valid_pixels": int(valid.sum()), "rendered_valid_pixels": int(mask.sum()),
               "gt_depth_coverage": float(mask.sum() / max(1, valid.sum())),
               "gt_rendered_depth_l1_m": float(np.abs(depth[mask] - gt[mask]).mean()) if mask.any() else None,
               "gt_rendered_depth_absrel": float((np.abs(depth[mask] - gt[mask]) / gt[mask]).mean()) if mask.any() else None}
        rows.append(row)
        if index in (1, 41, 81):
            folder = RUN / "evaluation/render"
            folder.mkdir(parents=True, exist_ok=True)
            for label, im in (("target", target_image), ("render", predicted)):
                cv2.imwrite(str(folder / f"frame{index:06d}_{label}.png"), cv2.cvtColor((im * 255).round().astype(np.uint8), cv2.COLOR_RGB2BGR))
        print(json.dumps(row), flush=True)
    summaries = {}
    for split in ("validation", "held_out_test"):
        selected = [r for r in rows if r["split"] == split]
        summaries[split] = {"n_frames": len(selected)}
        for key in ("psnr_db", "ssim", "lpips_alex", "gt_depth_coverage", "gt_rendered_depth_l1_m", "gt_rendered_depth_absrel"):
            values = [r[key] for r in selected if r[key] is not None]
            summaries[split][key] = float(np.mean(values)) if values else None
    result = {"stage": "E0 feasibility pilot", "gaussian_active_count": g["n"],
              "evaluation_intrinsics": K_frame.tolist(), "rgb_hw": [h, w],
              "alignment": {"source": "all tracked mapping-input frame poses, resolved at final anchor revisions", "scale": scale, "rotation": rotation.tolist(), "translation": translation.tolist(), "matched_poses": len(pairs),
                            "ate_rmse_m": float(np.sqrt(np.mean(np.sum((scale * source @ rotation.T + translation - target) ** 2, axis=1))))},
              "reload_render_max_abs_error": reload_error,
              "depth_definition": "alpha-weighted expected rendered depth, covered if compositing weight > 1e-3",
              "aggregation": "unweighted mean of per-frame scores; accuracy on rendered valid GT pixels, coverage on all valid GT pixels",
              "tsdf_mesh_metrics": None, "summaries": summaries, "frames": rows}
    (RUN / "evaluation").mkdir(parents=True, exist_ok=True)
    (RUN / "evaluation/metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summaries, indent=2), flush=True)


if __name__ == "__main__":
    main()
