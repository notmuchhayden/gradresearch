"""Fixed A2-S source-only scalar and smooth spatial depth diagnostic."""
from __future__ import annotations

import numpy as np

HUBER_DELTA = 0.05
LAMBDA_S = 0.01
LAMBDA_R = 0.0001


def tile_masks(pixel_indices, valid, height=288, width=512, fold=0, guard=2):
    idx = np.asarray(pixel_indices, dtype=np.int64)
    valid = np.asarray(valid, dtype=bool)
    if idx.shape != valid.shape or fold not in (0, 1):
        raise ValueError("invalid pixel/mask/fold")
    u, v = idx % width, idx // width
    xe = np.floor(np.arange(9) * width / 8).astype(int)
    ye = np.floor(np.arange(9) * height / 8).astype(int)
    parity = np.empty(len(idx), dtype=np.int8)
    inside = np.zeros(len(idx), bool)
    for r in range(8):
        for c in range(8):
            m = (u >= xe[c] + guard) & (u < xe[c+1] - guard) & (v >= ye[r] + guard) & (v < ye[r+1] - guard)
            parity[m] = (r + c) % 2
            inside |= m
    fit = valid & inside & (parity == fold)
    ev = valid & inside & (parity != fold)
    if np.any(fit & ev):
        raise AssertionError("fit/evaluation overlap")
    return fit, ev


def bilinear_basis(u, v, height=288, width=512):
    u = np.asarray(u, dtype=np.float64); v = np.asarray(v, dtype=np.float64)
    xs = np.linspace(0, width - 1, 4); ys = np.linspace(0, height - 1, 4)
    ix = np.clip(np.searchsorted(xs, u, side="right") - 1, 0, 2)
    iy = np.clip(np.searchsorted(ys, v, side="right") - 1, 0, 2)
    tx = (u - xs[ix]) / (xs[ix+1] - xs[ix]); ty = (v - ys[iy]) / (ys[iy+1] - ys[iy])
    B = np.zeros((len(u), 16), dtype=np.float64)
    for dy in range(2):
        for dx in range(2):
            w = (tx if dx else 1-tx) * (ty if dy else 1-ty)
            B[np.arange(len(u)), (iy+dy)*4 + ix+dx] += w
    return B


def field_laplacian():
    L = np.zeros((24, 16), dtype=np.float64); k = 0
    for r in range(4):
        for c in range(4):
            a = r*4+c
            if c < 3: L[k, a:a+2] = (-1, 1); k += 1
            if r < 3: L[k, a], L[k, a+4] = -1, 1; k += 1
    assert k == 24
    return L


def fit_scalar(r):
    r = np.asarray(r, dtype=np.float64)
    if not len(r) or not np.isfinite(r).all(): raise ValueError("invalid residuals")
    return float(np.median(r))


def fit_huber_scalar(r, max_iter=200, tol=1e-7):
    r = np.asarray(r, dtype=np.float64); a = fit_scalar(r)
    for i in range(1, max_iter+1):
        e = a-r; w = np.minimum(1., HUBER_DELTA/np.maximum(np.abs(e), 1e-12))
        new = float(np.sum(w*r)/np.sum(w))
        if abs(new-a) <= tol: return dict(alpha=new, iterations=i, converged=True)
        a = new
    return dict(alpha=a, iterations=max_iter, converged=False)


def fit_field(B, r, alpha_h, max_iter=200, tol=1e-7):
    B=np.asarray(B,dtype=np.float64); r=np.asarray(r,dtype=np.float64); L=field_laplacian()
    if B.shape != (len(r),16) or not np.isfinite(B).all() or not np.isfinite(r).all(): raise ValueError("invalid design")
    theta=np.full(16,float(alpha_h)); N=len(r); objective=None
    for i in range(1,max_iter+1):
        w=np.minimum(1.,HUBER_DELTA/np.maximum(np.abs(B@theta-r),1e-12))
        A=B.T@(w[:,None]*B)/N + LAMBDA_S*(L.T@L)/24 + LAMBDA_R*np.eye(16)/16
        b=B.T@(w*r)/N + LAMBDA_R*float(alpha_h)*np.ones(16)/16
        new=np.linalg.solve(A,b)
        if np.max(np.abs(new-theta))<=tol:
            theta=new; objective=loss_field(B,r,theta,alpha_h); return dict(theta=theta,iterations=i,converged=True,objective=objective,condition=float(np.linalg.cond(A)))
        theta=new
    return dict(theta=theta,iterations=max_iter,converged=False,objective=loss_field(B,r,theta,alpha_h),condition=float(np.linalg.cond(A)))


def huber(x, delta=HUBER_DELTA):
    a=np.abs(x); return np.where(a<=delta,0.5*x*x,delta*(a-0.5*delta))


def loss_field(B,r,theta,alpha_h):
    L=field_laplacian()
    return float(np.mean(huber(B@theta-r)) + LAMBDA_S/(2*24)*np.sum((L@theta)**2) + LAMBDA_R/(2*16)*np.sum((theta-alpha_h)**2))


def support_gate(fit_n, eval_n, region_counts, rank, eigen_ratio, min_n=2048):
    reasons=[]
    if fit_n < min_n: reasons.append("fit_pixels_below_2048")
    if eval_n < min_n: reasons.append("eval_pixels_below_2048")
    if min(region_counts, default=0) < 64: reasons.append("field_region_below_64")
    if rank < 16 or eigen_ratio < 1e-8: reasons.append("bilinear_design_ill_conditioned")
    return not reasons, reasons


def decide(E0, Ek, Ef, source_kf_fraction, source_candidate_fraction, target_support_pass,
           cov_k, cov_f, cov_0, correct_k, correct_f, correct_0):
    eligible=source_kf_fraction>=.8 and source_candidate_fraction>=.8 and target_support_pass and E0>0
    gain=E0-Ef
    if not eligible: return dict(label="INSUFFICIENT_SUPPORT",ratio=None)
    if gain<=0 or gain/E0<.1: return dict(label="FIELD_GAIN_NOT_ESTABLISHED",ratio=None)
    ratio=(E0-Ek)/gain
    if cov_k < cov_0-1e-6 or cov_f < cov_0-1e-6 or correct_k < correct_0-.01 or correct_f < correct_0-.01:
        return dict(label="COVERAGE_TRADEOFF",ratio=ratio)
    return dict(label="SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD" if ratio>=.9 else "RESIDUAL_FIELD_OPPORTUNITY",ratio=float(ratio))
