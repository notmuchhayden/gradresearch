"""Record installed versions and trusted weight origins after each setup stage."""
from importlib import metadata
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return {"command": args, "exit_code": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def main():
    import torch
    upstream = ROOT / "thirdparty/Splatt3R-SLAM"
    environment = {
        "recorded_date": "2026-10-15", "timezone": "Asia/Seoul",
        "python": sys.version, "executable": sys.executable,
        "os": platform.freedesktop_os_release(), "kernel": platform.release(),
        "upstream_commit": run(["git", "rev-parse", "HEAD"], upstream)["stdout"],
        "upstream_patch": "docs/patches/e0_upstream.patch",
        "gpu": run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader"]),
        "nvcc": run(["/usr/local/cuda/bin/nvcc", "--version"]),
        "project_nvcc": run([str(ROOT / '.venv/lib/python3.11/site-packages/nvidia/cu13/bin/nvcc'), '--version']),
        "compiler_by_component": {"faiss": "system CUDA 13.4, sm_120", "lietorch_rasterizer_slam_backend_rope": "project CUDA 13.2, sm_120 (verify build logs)"},
        "torch_cuda_available": torch.cuda.is_available(),
        "torch_cuda_version": torch.version.cuda,
        "torch_compiled_architectures": torch.cuda.get_arch_list(),
        "distributions": sorted(({"name": d.metadata["Name"], "version": d.version} for d in metadata.distributions()), key=lambda d: d["name"].lower()),
        "pip_check": run([sys.executable, "-m", "pip", "check"]),
    }
    if torch.cuda.is_available():
        x = torch.randn(128, 128, device="cuda")
        y = x @ x.T
        torch.cuda.synchronize()
        environment["cuda_matmul_finite"] = bool(y.isfinite().all())
        environment["gpu_capability"] = list(torch.cuda.get_device_capability())
    (ROOT / "configs/e0_environment_resolved.json").write_text(json.dumps(environment, indent=2) + "\n")
    freeze = run([sys.executable, "-m", "pip", "freeze"])
    (ROOT / "configs/e0_pip_freeze.txt").write_text(freeze["stdout"] + "\n")
    explicit = ROOT / "results/E0_baseline_reproduction/setup/conda-explicit.txt"
    (ROOT / "configs/e0_conda_linux64.explicit.txt").write_text(explicit.read_text())
    patch = subprocess.check_output(["git", "diff", "--binary"], cwd=upstream)
    (ROOT / "docs/patches/e0_upstream.patch").write_bytes(patch)
    weights = []
    for filename, url in (
        ("epoch=19-step=1200.ckpt", "https://huggingface.co/brandonsmart/splatt3r_v1.0/resolve/main/epoch%3D19-step%3D1200.ckpt"),
        ("MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth", "https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"),
        ("MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl", "https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl"),
    ):
        path = ROOT / "checkpoints/e0" / filename
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        weights.append({"file": str(path.relative_to(ROOT)), "url": url, "bytes": path.stat().st_size, "sha256": digest})
    alex = ROOT / 'results/E0_baseline_reproduction/setup/torch-cache/hub/checkpoints/alexnet-owt-7be5be79.pth'
    if alex.exists():
        with alex.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        weights.append({'file': str(alex.relative_to(ROOT)), 'url': 'https://download.pytorch.org/models/alexnet-owt-7be5be79.pth',
                        'bytes': alex.stat().st_size, 'sha256': digest, 'role': 'upstream model loss module and evaluation LPIPS backbone'})
    (ROOT / "configs/e0_weights_manifest.json").write_text(json.dumps(weights, indent=2) + "\n")
    # Identify the uncommitted research code as well as the pinned upstream tree.
    paths = sorted(set(ROOT.glob('scripts/*.py')) | set(ROOT.glob('scripts/*.sh')) | set(ROOT.glob('src/*.py')))
    paths += [ROOT / p for p in ('configs/e0_environment.yml', 'configs/e0_replica_office0.yaml',
                                'configs/e0_replica_split.json', 'docs/patches/e0_upstream.patch')]
    code = {'research_parent_commit': run(['git', 'rev-parse', 'HEAD'])['stdout'],
            'state': 'uncommitted source snapshot; file hashes identify the executed implementation',
            'files': [{'file': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    (ROOT / 'configs/e0_code_manifest.json').write_text(json.dumps(code, indent=2) + '\n')
    result = ROOT / 'results/E0_baseline_reproduction'
    if (result / 'wall_seconds.txt').exists():
        import numpy as np
        rows = list(csv.DictReader((result / 'timing.csv').open()))
        memory = list(csv.DictReader((result / 'device_memory.csv').open()))
        dump = torch.load(result / 'map/office0_kfgauss.pt', map_location='cpu', weights_only=True)
        h, w = dump['keyframes'][0]['img_shape']
        stats = {'timed_tracking_frames': len(rows), 'wall_seconds': int((result / 'wall_seconds.txt').read_text()),
                 'device_memory_peak_sampled_mib': max(int(row[' memory.used [MiB]'].strip().split()[0]) for row in memory),
                 'memory_sampling_seconds': 1, 'memory_scope': 'whole GPU device; sampled, not process allocator peak',
                 'gaussian_ply_bytes': (result / 'map/office0_gaussians.ply').stat().st_size,
                 'kfgauss_dump_bytes': (result / 'map/office0_kfgauss.pt').stat().st_size,
                 'resident_map_buffer_slots': 16 * h * w,
                 'resident_count_scope': 'preallocated map slots; transient predictions are not counted'}
        for key in ('track_ms', 'backend_wait_ms', 'iter_ms'):
            values = np.array([float(row[key]) for row in rows])
            stats[key] = {'mean': float(values.mean()), 'median': float(np.median(values)), 'p95': float(np.percentile(values, 95))}
        (result / 'run_stats.json').write_text(json.dumps(stats, indent=2) + '\n')
    print(json.dumps({"cuda_available": environment["torch_cuda_available"], "pip_check": environment["pip_check"], "weights": len(weights)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
