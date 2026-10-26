"""Invertible local/placement scale allocation; no geometry correction or GT fit."""
from dataclasses import dataclass

import numpy as np

from pointmap_contract import sim3_parts


@dataclass(frozen=True)
class CanonicalGeometry:
    points: np.ndarray
    covariance: np.ndarray
    rigid_placement: np.ndarray
    absorbed_scale: float


def _arrays(points, covariance):
    points = np.asarray(points, dtype=np.float64)
    covariance = np.asarray(covariance, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Expected N x 3 local points")
    if covariance.shape != (len(points), 3, 3):
        raise ValueError("Expected one 3 x 3 covariance per point")
    if not np.isfinite(points).all() or not np.isfinite(covariance).all():
        raise ValueError("Nonfinite local geometry")
    return points, covariance


def absorb_scale(points, covariance, placement):
    """Move positive uniform placement scale into local means AND covariance.

    Translation remains the camera origin in the same world frame. This is
    a representation change: world centers/covariances must remain unchanged.
    """
    points, covariance = _arrays(points, covariance)
    scale, rotation, translation = sim3_parts(placement)
    rigid = np.eye(4, dtype=np.float64)
    rigid[:3, :3] = rotation
    rigid[:3, 3] = translation
    return CanonicalGeometry(points * scale, covariance * scale**2, rigid, scale)


def restore_scale(canonical):
    """Inverse of absorb_scale, retaining the original positive scale."""
    scale = canonical.absorbed_scale
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Expected positive finite absorbed scale")
    points, covariance = _arrays(canonical.points, canonical.covariance)
    rigid_scale, _, _ = sim3_parts(canonical.rigid_placement)
    if not np.isclose(rigid_scale, 1., atol=1e-10, rtol=0):
        raise ValueError("Canonical placement must be rigid")
    placement = canonical.rigid_placement.copy()
    placement[:3, :3] *= scale
    return points / scale, covariance / scale**2, placement


def reallocate_scale(points, covariance, placement, factor):
    """Apply x'=q*x, Sigma'=q^2*Sigma, linear placement'=linear/q.

    The factor is supplied, never estimated from depths or target poses.
    """
    points, covariance = _arrays(points, covariance)
    sim3_parts(placement)
    if not np.isscalar(factor) or not np.isfinite(factor) or factor <= 0:
        raise ValueError("Reallocation factor must be one positive finite scalar")
    changed = np.array(placement, dtype=np.float64, copy=True)
    changed[:3, :3] /= factor
    return points * factor, covariance * factor**2, changed


def absorb_standard_deviations(standard_deviations, scale):
    standard_deviations = np.asarray(standard_deviations, dtype=np.float64)
    if standard_deviations.ndim != 2 or standard_deviations.shape[1] != 3:
        raise ValueError("Expected N x 3 standard deviations")
    if not np.isfinite(standard_deviations).all() or np.any(standard_deviations <= 0):
        raise ValueError("Standard deviations must be finite and positive")
    if not np.isscalar(scale) or not np.isfinite(scale) or scale <= 0:
        raise ValueError("Expected positive finite scale")
    return standard_deviations * scale
