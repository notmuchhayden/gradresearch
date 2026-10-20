"""Verify frozen E0b PLY candidate order in its original GPU numeric mode."""
import json
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "thirdparty/Splatt3R-SLAM"), str(ROOT / "scripts")]
import lietorch
import torch
from splatt3r_slam.splatt3r_utils import bake_gaussians_world
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply


@torch.no_grad()
def main():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.set_num_threads(2)
    spec = json.loads((ROOT / "configs/e1_taxonomy.json").read_text())
    run, out = ROOT / spec["baseline_run"], ROOT / spec["output"]
    out.mkdir(parents=True, exist_ok=True)
    dump = torch.load(run / "map/office0_kfgauss.pt", weights_only=True, map_location="cpu")
    baked = []
    for kf in dump["keyframes"]:
        local = {k: kf[k].to("cuda") for k in ("means", "scales", "rotations", "sh", "opacities", "conf")}
        baked.append(bake_gaussians_world(local, kf["img"].to("cuda"), *kf["img_shape"],
                     lietorch.Sim3(kf["T_WC"].to("cuda")), spatial_stride=1,
                     depth_max_percentile=0.98, max_scale=1., min_confidence=1.5,
                     min_opacity=0.3, inflate_scales_for_stride=False))
    means, tri, _, opacity = [torch.cat([b[i] for b in baked]) for i in range(4)]
    row, col = torch.triu_indices(3, 3, device="cuda")
    covariance = torch.zeros((len(means), 3, 3), device="cuda")
    covariance[:, row, col] = tri
    covariance[:, col, row] = tri
    g = decode_gaussians_from_ply(run / "map/office0_gaussians.ply", device="cuda")
    assert len(means) == g["n"] == 705772
    torch.testing.assert_close(g["means"], means, atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(g["covariances"], covariance, atol=1e-5, rtol=1e-4)
    torch.testing.assert_close(g["opacity"], opacity, atol=1e-6, rtol=1e-5)
    result = dict(status="PASS", active=len(means), numeric_mode="original upstream TF32 enabled",
                  means_max_abs_error=float((g["means"] - means).abs().max()),
                  covariance_max_abs_error=float((g["covariances"] - covariance).abs().max()),
                  gpu=torch.cuda.get_device_name(),
                  ply_sha256=hashlib.sha256((run / "map/office0_gaussians.ply").read_bytes()).hexdigest(),
                  keyframe_dump_sha256=hashlib.sha256((run / "map/office0_kfgauss.pt").read_bytes()).hexdigest())
    (out / "baseline_gpu_integrity.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
