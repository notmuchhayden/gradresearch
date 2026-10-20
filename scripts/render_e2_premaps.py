"""GT-free B8: render original-map prefixes at recorded creation revisions."""
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src"), str(UPSTREAM)]
import lietorch
from splatt3r_slam.splatt3r_utils import bake_gaussians_world
from render_e1 import render_values
from score_e2 import digest, forbid_gt_reads, save_json
from e0b_audit import sim3_matrix
from e2_signals import dog, image_rgb, sample_bilinear


@torch.no_grad()
def main():
    started = time.monotonic()
    torch.set_num_threads(2)
    spec = json.loads((ROOT / "configs/e2_discriminability.json").read_text())
    run, out = ROOT / spec["baseline_run"], ROOT / spec["output"]
    score_manifest = json.loads((out / "score_manifest.json").read_text())
    assert digest(ROOT / "configs/e2_discriminability.json") == score_manifest["specification"]
    for entry in score_manifest["code"]:
        assert digest(ROOT / entry["path"])["sha256"] == entry["sha256"], entry["path"]
    meta = json.loads((out / "score_metadata.json").read_text())
    dump = torch.load(run / "map/office0_kfgauss.pt", weights_only=True, map_location="cpu")
    features = np.load(out / "features.npz")
    scores, rows = [], []
    image_dir = out / "premaps"
    image_dir.mkdir(exist_ok=True)
    for i, frame in enumerate(dump["keyframes"]):
        path = run / "audit" / meta["lineage"][i]["decision_file"]
        snapshot = torch.load(path, weights_only=True, map_location="cpu")
        assert len(snapshot["metadata"]) == i + 1
        assert snapshot["pose_revision"] == meta["lineage"][i]["pose_revision"]
        camera = meta["predicted_cameras"][i]
        K = np.array(camera["K"])
        h, w = frame["img_shape"]
        image = image_rgb(frame)
        pose = sim3_matrix(snapshot["poses"][i].numpy())
        np.testing.assert_array_equal(pose, features["creation_poses"][i])
        camera_pose = pose.copy()
        camera_pose[:3, :3] /= np.cbrt(np.linalg.det(camera_pose[:3, :3]))
        baked = []
        torch.backends.cuda.matmul.allow_tf32 = True
        for j in range(i):
            old = dump["keyframes"][j]
            local = {key: old[key].to("cuda") for key in ("means", "scales", "rotations", "sh", "opacities", "conf")}
            baked.append(bake_gaussians_world(local, old["img"].to("cuda"), h, w,
                lietorch.Sim3(snapshot["poses"][j].to("cuda")), spatial_stride=1, depth_max_percentile=0.98,
                max_scale=1., min_confidence=1.5, min_opacity=0.3, inflate_scales_for_stride=False))
        # Rendering is evaluated in full FP32; map baking matches baseline TF32.
        torch.backends.cuda.matmul.allow_tf32 = False
        if baked:
            means, tri, rgb, opacity = [torch.cat([x[k] for x in baked]) for k in range(4)]
            covariance = torch.zeros((len(means), 3, 3), device="cuda")
            row, col = torch.triu_indices(3, 3, device="cuda")
            covariance[:, row, col] = tri
            covariance[:, col, row] = tri
            rendered = render_values(dict(means=means, covariances=covariance, opacity=opacity),
                                     camera_pose, K, (h, w), rgb).cpu().numpy().transpose(1, 2, 0)
            active_n = len(means)
        else:
            rendered = np.zeros((h, w, 3), np.float32)
            active_n = 0
        p = frame["means"].numpy()
        z = p[:, 2]
        x = K[0, 0] * p[:, 0] / np.maximum(z, 1e-12) + K[0, 2]
        y = K[1, 1] * p[:, 1] / np.maximum(z, 1e-12) + K[1, 2]
        # Regrid the rendered pinhole view onto the current predicted ray grid.
        warped = cv2.remap(rendered, x.reshape(h, w).astype(np.float32), y.reshape(h, w).astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        source_dog, occupancy = dog(image, spec["dog_sigmas_pixels"]), dog(warped, spec["dog_sigmas_pixels"])
        yy, xx = np.indices((h, w))
        pinhole_ray = np.stack([(xx - K[0, 2]) / K[0, 0], (yy - K[1, 2]) / K[1, 1], np.ones((h, w))], -1).reshape(-1, 3)
        pinhole_ray /= np.linalg.norm(pinhole_ray, axis=1, keepdims=True)
        ray = p / np.maximum(np.linalg.norm(p, axis=1, keepdims=True), 1e-12)
        angle = np.degrees(np.arccos(np.clip((ray * pinhole_ray).sum(1), -1, 1)))
        good = ((z > 0) & (frame["conf"].numpy() >= spec["confidence_min"]) &
                (angle <= spec["camera_fit_angular_error_max_degrees"]) &
                (x >= 0) & (x <= w - 1) & (y >= 0) & (y <= h - 1))
        # DoG has a spatial footprint; protect warp/image boundary pixels.
        margin = int(np.ceil(3 * max(spec["dog_sigmas_pixels"])))
        interior = (xx >= margin) & (xx < w - margin) & (yy >= margin) & (yy < h - margin)
        good &= interior.reshape(-1)
        score = (occupancy - source_dog).reshape(-1)
        score[~good] = np.nan
        scores.append(score)
        np.savez_compressed(image_dir / f"kf{i:04d}.npz", source=image, render_pinhole=rendered,
                            render_predicted_rays=warped, input_dog=source_dog, occupancy_dog=occupancy,
                            eligible=good.reshape(h, w), score=score.reshape(h, w), K=K)
        rows.append(dict(anchor_kf=i, pose_revision=snapshot["pose_revision"],
                         included_kfs=list(range(i)), excluded_current_and_future_kfs=list(range(i, 5)),
                         active_gaussians=active_n, eligible=int(good.sum()), predicted_camera=camera,
                         snapshot_sha256=digest(path)["sha256"]))
        print(json.dumps(rows[-1]), flush=True)
        torch.cuda.empty_cache()
    np.savez_compressed(out / "b8_features.npz", B8_dog_redundancy=np.concatenate(scores))
    manifest = dict(status="PASS", gt_reads="forbidden", final_map_used=False, current_candidate_map_used=False,
                    score_manifest_sha256=digest(out / "score_manifest.json")["sha256"],
                    features_sha256=digest(out / "b8_features.npz")["sha256"],
                    code=[digest(Path(__file__)), digest(ROOT / "scripts/render_e1.py"),
                          digest(UPSTREAM / "splatt3r_slam/splatt3r_utils.py")],
                    maps=rows, gpu=torch.cuda.get_device_name(), wall_seconds=time.monotonic() - started)
    save_json(out / "b8_manifest.json", manifest)


if __name__ == "__main__":
    with forbid_gt_reads():
        main()
