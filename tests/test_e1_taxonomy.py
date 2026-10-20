"""Synthetic geometry cases that guard E1's label semantics."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from e1_taxonomy import (backproject, camera_geometry, classify, depth_masks,
                         fit_sim3, mark_redundancy, projected_opacity_area, transform)


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.spec = dict(depth_valid_range_m=[0.1, 10], depth_edge_abs_m=0.05,
                         depth_edge_relative=0.02, depth_edge_dilation_pixels=2,
                         depth_tolerance_abs_m=0.05, depth_tolerance_relative=0.02,
                         ellipsoid_sigma=3, repeated_front_min_views=2,
                         repeated_front_min_parallax_degrees=1,
                         duplicate_distance_m=0.02, duplicate_normal_max_angle_degrees=20)
        self.K = np.array([[50., 0, 31.5], [0, 50., 31.5], [0, 0, 1]])

    def views(self):
        depth = np.full((64, 64), 2.)
        valid, edge = depth_masks(depth, self.spec)
        views = []
        for x in (0, 0.2):
            pose = np.eye(4)
            pose[0, 3] = x
            views.append(dict(depth=depth.copy(), valid=valid.copy(), edge=edge.copy(), pose=pose))
        return views

    def test_front_surface_occlusion_and_extent(self):
        means = np.array([[0., 0., 1.], [0., 0., 2.], [0., 0., 3.], [0., 0., 1.]])
        cov = np.tile(np.eye(3) * 0.001 ** 2, (4, 1, 1))
        cov[-1, 2, 2] = 0.5 ** 2
        result = classify(means, cov, self.views(), self.K, self.spec)
        # A large splat reaching the wall cannot be certified as fully in free space.
        np.testing.assert_array_equal(result["labels"], [3, 1, 0, 0])
        self.assertTrue(result["center_front"][-1])
        self.assertFalse(result["ellipsoid_front"][-1])

    def test_repeated_same_pose_is_not_angular_evidence(self):
        views = self.views()
        views[1]["pose"] = views[0]["pose"].copy()
        result = classify(np.array([[0., 0, 1.]]), np.eye(3)[None] * 1e-6, views, self.K, self.spec)
        self.assertEqual(result["labels"][0], 0)

    def test_missing_depth_and_edges_cannot_reject(self):
        views = self.views()
        for v in views:
            v["depth"][:, 25:40] = 0
            v["valid"], v["edge"] = depth_masks(v["depth"], self.spec)
        result = classify(np.array([[0., 0, 1.]]), np.eye(3)[None] * 1e-6, views, self.K, self.spec)
        self.assertEqual(result["labels"][0], 0)
        depth = np.ones((64, 64))
        depth[:, 32:] = 3
        _, edge = depth_masks(depth, self.spec)
        self.assertTrue(edge[:, 30:34].all())

    def test_cross_view_disagreement_is_ambiguous(self):
        views = self.views()
        views[0]["depth"][:] = 1
        result = classify(np.array([[0., 0, 1.]]), np.eye(3)[None] * 1e-6, views, self.K, self.spec)
        self.assertEqual(result["labels"][0], 0)
        self.assertEqual(result["center_support_views"][0], 1)
        self.assertEqual(result["center_front_views"][0], 1)

    def test_thin_depth_structure_is_protected_by_boundary_mask(self):
        views = self.views()
        for view in views:
            center = int(np.rint(31.5 - 50 * view["pose"][0, 3]))
            view["depth"][:, center - 1:center + 1] = 1.
            view["valid"], view["edge"] = depth_masks(view["depth"], self.spec)
        result = classify(np.array([[0., 0, 1.]]), np.eye(3)[None] * 1e-6, views, self.K, self.spec)
        self.assertEqual(result["labels"][0], 0)
        self.assertEqual(result["reliable_gt_views"][0], 0)

    def test_redundancy_protects_normals_and_active_universe(self):
        means = np.array([[0., 0., 2.], [0.01, 0, 2], [0.005, 0, 2]])
        normals = np.array([[0., 0, 1], [0., 0, 1], [1., 0, 0]])
        labels = mark_redundancy(np.ones(3, np.uint8), means, normals, np.array([0, 1, 2]),
                                 np.ones(3, bool), self.spec)
        np.testing.assert_array_equal(labels, [1, 2, 1])
        labels = mark_redundancy(np.ones(3, np.uint8), means, normals, np.array([0, 1, 2]),
                                 np.array([False, True, True]), self.spec)
        np.testing.assert_array_equal(labels, [1, 1, 1])

    def test_sim3_and_squared_covariance_scale(self):
        source = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        known = np.eye(4)
        known[:3, :3] = [[0, -2, 0], [2, 0, 0], [0, 0, 2]]
        known[:3, 3] = [1, 2, 3]
        fitted = fit_sim3(source, transform(source, known))
        np.testing.assert_allclose(fitted, known, atol=1e-12)
        covariance = np.diag([1., 2, 3])
        np.testing.assert_allclose(fitted[:3, :3] @ covariance @ fitted[:3, :3].T,
                                   np.diag([8, 4, 12]), atol=1e-12)
        with self.assertRaises(ValueError):
            fit_sim3(source * 0, source)

    def test_crop_pinhole_round_trip_and_footprint(self):
        cam = dict(w=1200, h=680, fx=600., fy=600., cx=599.5, cy=339.5)
        K, hw, crop = camera_geometry(cam)
        self.assertEqual(hw, (290, 512))
        self.assertEqual(crop, (1, 0, 288, 512))
        depth = np.full((288, 512), 2.)
        points = backproject(depth, K)
        self.assertAlmostEqual(points[20, 30, 0] * K[0, 0] / 2 + K[0, 2], 30)
        area = projected_opacity_area(np.array([[0., 0, 2.]]), np.eye(3)[None] * 0.01 ** 2, np.eye(3), self.K)
        self.assertAlmostEqual(area[0], 2 * np.pi * (0.3 + (50 * 0.01 / 2) ** 2))


if __name__ == "__main__":
    unittest.main()
