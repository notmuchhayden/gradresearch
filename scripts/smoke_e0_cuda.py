"""Minimal actual GPU operations, without loading the large scene predictor."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "thirdparty/Splatt3R-SLAM/splatt3r_core"))
import torch
import numpy as np
import faiss
import lietorch
from src.pixelsplat_src.cuda_splatting import render_cuda

with torch.no_grad():
    device = "cuda"
    resource = faiss.StandardGpuResources()
    resource.setTempMemory(64 * 1024 * 1024)
    index = faiss.GpuIndexFlatL2(resource, 8)
    vectors = np.eye(8, dtype=np.float32)
    index.add(vectors)
    distances, indices = index.search(vectors, 1)
    assert np.array_equal(indices[:, 0], np.arange(8))
    print('GPU faiss add/search: PASS', flush=True)
    transform = lietorch.Sim3.Identity(1, device=device)
    points = torch.tensor([[[0., 0., 2.]]], device=device)
    torch.testing.assert_close(transform.inv().act(transform.act(points[0])), points[0])
    image = render_cuda(torch.eye(4, device=device)[None],
        torch.tensor([[[1., 0., .5], [0., 1., .5], [0., 0., 1.]]], device=device),
        torch.tensor([.1], device=device), torch.tensor([100.], device=device),
        (32, 32), torch.zeros(1, 3, device=device), points,
        (torch.eye(3, device=device) * .01)[None, None],
        torch.ones(1, 1, 3, 1, device=device) * .8,
        torch.ones(1, 1, device=device) * .9, use_sh=False)
    torch.cuda.synchronize()
    assert image.isfinite().all() and image.max() > 0
    print(json.dumps({"sim3": "PASS", "rasterizer": "PASS", "render_max": image.max().item(),
                      "faiss_gpu_count": faiss.get_num_gpus()}), flush=True)
