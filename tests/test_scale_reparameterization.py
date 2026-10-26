"""Controls that distinguish representation changes from silent map edits."""
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pointmap_contract import sim3_from_xyzw, transform_points, transform_covariance
from scale_reparameterization import absorb_scale, restore_scale, reallocate_scale, absorb_standard_deviations


class ScaleReparameterizationTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.points = rng.normal(size=(20, 3))
        matrix = rng.normal(size=(20, 3, 3))
        self.covariance = matrix @ matrix.transpose(0, 2, 1)
        self.pose = sim3_from_xyzw([3., -5., 7., *Rotation.from_euler('xyz', [.3, -.2, .5]).as_quat(), .47])

    def test_world_points_and_covariance_preserved(self):
        c = absorb_scale(self.points, self.covariance, self.pose)
        np.testing.assert_allclose(transform_points(c.points, c.rigid_placement), transform_points(self.points, self.pose), atol=1e-12)
        np.testing.assert_allclose(transform_covariance(c.covariance, c.rigid_placement), transform_covariance(self.covariance, self.pose), atol=1e-12)
        np.testing.assert_array_equal(c.rigid_placement[:3, 3], self.pose[:3, 3])
        self.assertAlmostEqual(np.linalg.det(c.rigid_placement[:3, :3]), 1.)

    def test_restore_roundtrip(self):
        points, covariance, pose = restore_scale(absorb_scale(self.points, self.covariance, self.pose))
        for a, b in [(points, self.points), (covariance, self.covariance), (pose, self.pose)]:
            np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-12)

    def test_reallocation_including_translation_is_invariant(self):
        canonical = absorb_scale(self.points, self.covariance, self.pose)
        for q in [.5, .8, 1.25, 2.]:
            points, cov, pose = reallocate_scale(self.points, self.covariance, self.pose, q)
            c = absorb_scale(points, cov, pose)
            np.testing.assert_allclose(c.points, canonical.points, atol=1e-12)
            np.testing.assert_allclose(c.covariance, canonical.covariance, atol=1e-12)
            np.testing.assert_allclose(c.rigid_placement, canonical.rigid_placement, atol=1e-12)
            np.testing.assert_array_equal(pose[:3, 3], self.pose[:3, 3])

    def test_mean_only_absorption_is_rejected(self):
        c = absorb_scale(self.points, self.covariance, self.pose)
        bad = transform_covariance(self.covariance, c.rigid_placement)
        correct = transform_covariance(self.covariance, self.pose)
        self.assertFalse(np.allclose(bad, correct, rtol=1e-9, atol=1e-12))

    def test_naive_scale_removal_is_not_a_reparameterization(self):
        c = absorb_scale(self.points, self.covariance, self.pose)
        self.assertFalse(np.allclose(transform_points(self.points, c.rigid_placement), transform_points(self.points, self.pose)))

    def test_standard_deviation_requires_linear_not_squared_factor(self):
        std = np.array([[.1, .2, .3]])
        changed = absorb_standard_deviations(std, .47)
        np.testing.assert_allclose(changed**2, std**2 * .47**2)
        self.assertFalse(np.allclose(changed, std * .47**2))

    def test_unit_scale_and_empty_input(self):
        c = absorb_scale(np.empty((0, 3)), np.empty((0, 3, 3)), np.eye(4))
        self.assertEqual(c.points.shape, (0, 3))
        np.testing.assert_array_equal(c.rigid_placement, np.eye(4))

    def test_rejects_nonpositive_or_nonfinite_reallocation(self):
        for q in [0., -1., np.nan, np.inf]:
            with self.assertRaises(ValueError):
                reallocate_scale(self.points, self.covariance, self.pose, q)

    def test_rejects_nonfinite_or_mismatched_geometry(self):
        with self.assertRaises(ValueError):
            absorb_scale(self.points, self.covariance[:-1], self.pose)
        bad = self.points.copy(); bad[0, 0] = np.nan
        with self.assertRaises(ValueError):
            absorb_scale(bad, self.covariance, self.pose)

    def test_rejects_reflection_and_anisotropic_placement(self):
        for value in [-1., 2.]:
            bad = np.eye(4); bad[0, 0] = value
            with self.assertRaises(ValueError):
                absorb_scale(self.points, self.covariance, bad)


if __name__ == '__main__':
    unittest.main()
