"""CPU forward renderer, explicitly a numerical adaptation, not CUDA timing.

Uses the checked-in upstream forward equations (pinhole EWA, 0.3 pixel
low-pass covariance, 16x16 tiles, alpha cutoff and early termination).
The caller supplies frozen means/covariances and arbitrary per-splat values.
"""
import ctypes
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np


@lru_cache(maxsize=1)
def backend():
    root = Path(__file__).resolve().parents[1]
    source = root / 'src/e3_splat_cpu.cpp'
    import hashlib
    key = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = root / 'results/E3_admission_decision/build' / f'splat_{key}.so'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        subprocess.run(['g++', '-O3', '-std=c++17', '-shared', '-fPIC', '-fopenmp',
                        str(source), '-o', str(target)], check=True)
    lib = ctypes.CDLL(str(target))
    array = np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS')
    ints = np.ctypeslib.ndpointer(dtype=np.int32, flags='C_CONTIGUOUS')
    lib.splat_cpu.argtypes = [ctypes.c_int]*4 + [array]*3 + [ints] + [array]*3
    lib.splat_cpu.restype = None
    return lib


def project(means, covariances, pose, K, hw):
    """Project world Gaussians using rigid camera pose, same near plane as E1."""
    h, w = hw
    R = np.asarray(pose[:3, :3], np.float32)
    p = (means - np.asarray(pose[:3, 3], np.float32)) @ R
    cov = R.T @ covariances @ R
    z = p[:, 2]
    safe_z = np.maximum(z, 1e-8)
    ratio = p[:, :2] / safe_z[:, None]
    limit = 1.3*np.array([w/(2*K[0,0]), h/(2*K[1,1])])
    clamped = np.clip(ratio, -limit, limit)
    J = np.zeros((len(p), 2, 3), np.float32)
    J[:, 0, 0] = K[0,0]/safe_z
    J[:, 1, 1] = K[1,1]/safe_z
    J[:, 0, 2] = -K[0,0]*clamped[:,0]/safe_z
    J[:, 1, 2] = -K[1,1]*clamped[:,1]/safe_z
    c = J @ cov @ J.transpose(0,2,1)
    a, b, d = c[:,0,0]+0.3, c[:,0,1], c[:,1,1]+0.3
    determinant = a*d-b*b
    inverse = np.divide(1., determinant, out=np.zeros_like(a), where=determinant>0)
    conic = np.stack([d*inverse, -b*inverse, a*inverse], -1)
    mid = (a+d)*0.5
    eigen_max = mid+np.sqrt(np.maximum(0.1, mid*mid-determinant))
    radius = np.ceil(3*np.sqrt(np.maximum(0,eigen_max)))
    radius[(z<=0.02) | (determinant<=0) | ~np.isfinite(radius)] = 0
    xy = ratio * np.array([K[0,0],K[1,1]], np.float32) + np.array([K[0,2],K[1,2]],np.float32)
    # Near-plane check is z > .2 in the upstream 10x conditioned coordinates.
    return (np.ascontiguousarray(xy,np.float32), np.ascontiguousarray(conic,np.float32),
            np.ascontiguousarray(z,np.float32), np.ascontiguousarray(radius,np.int32))


def render(means, covariance, opacity, values, pose, K, hw):
    values = np.ascontiguousarray(values,np.float32)
    out = np.zeros((*hw, values.shape[1]),np.float32)
    if len(means):
        xy, conic, z, radius = project(means,covariance,pose,K,hw)
        backend().splat_cpu(len(means),*hw,values.shape[1],xy,conic,z,radius,
                            np.ascontiguousarray(opacity,np.float32),values,out)
    return out
