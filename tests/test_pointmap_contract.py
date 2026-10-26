"""Synthetic controls and corruption checks for independent oracle factors."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pointmap_contract import (backproject_z, build_arms, fit_prefix_gauge,
                               metric_placement, project, sim3_from_xyzw,
                               sim3_parts, source_points_in_anchor,
                               stratified_subset, transform_covariance,
                               transform_points, validate_arms)


def pose(t=(0, 0, 0), angles=(0, 0, 0), scale=1):
    return sim3_from_xyzw([*t, *Rotation.from_euler("xyz", angles).as_quat(), scale])


class CoordinateContractTests(unittest.TestCase):
    def arms(self, raw=None, gt=None, raw_pose=None, C=1, gauge=None):
        points = np.array([[1., 0, 2], [0, 1, 3], [0, 0, 4]])
        return build_arms(points if raw is None else raw, points if gt is None else gt,
                          np.eye(4) if raw_pose is None else raw_pose, np.eye(4),
                          np.eye(4) if gauge is None else gauge, C,
                          np.repeat(np.diag([.01, .02, .03])[None], 3, axis=0),
                          np.array(["event:self:0", "event:self:1", "event:self:2"]),
                          np.array([True, True, False]), {"opacity": np.array([.9, .8, .7])})

    def test_zdepth_plane_roundtrip_and_range_difference(self):
        K = np.array([[100., 0, 50], [0, 100, 40], [0, 0, 1]])
        pixels = np.array([[50., 40], [150, 40], [50, 140]])
        points = backproject_z(pixels, np.full(3, 2.), K)
        np.testing.assert_allclose(points, [[0, 0, 2], [2, 0, 2], [0, 2, 2]])
        np.testing.assert_allclose(project(points, K), pixels)
        self.assertAlmostEqual(np.linalg.norm(points[1]), np.sqrt(8))
        with self.assertRaises(ValueError):
            backproject_z(pixels, np.array([2., 0, np.nan]), K)

    def test_xyzw_rotation_scale_and_inverse(self):
        matrix = pose(t=(1, 2, 3), angles=(0, 0, np.pi/2), scale=2)
        np.testing.assert_allclose(transform_points([[1, 0, 2]], matrix), [[1, 4, 7]], atol=1e-12)
        np.testing.assert_allclose(transform_points(transform_points([[1, 0, 2]], matrix), np.linalg.inv(matrix)), [[1, 0, 2]], atol=1e-12)
        covariance = np.diag([1., 2, 3])[None]
        np.testing.assert_allclose(transform_covariance(covariance, matrix)[0], np.diag([8, 4, 12]), atol=1e-12)
        np.testing.assert_allclose(transform_covariance(transform_covariance(covariance, matrix), np.linalg.inv(matrix)), covariance, atol=1e-12)

    def test_reject_reflection_shear_bad_quaternion(self):
        for bad in (np.diag([-1., 1, 1, 1]), np.diag([2., 1, 1, 1])):
            with self.assertRaises(ValueError):
                sim3_parts(bad)
        with self.assertRaises(ValueError):
            sim3_from_xyzw([0, 0, 0, 0, 0, 0, 0, 1])
        with self.assertRaises(ValueError):
            metric_placement(np.eye(4), np.eye(4), -1)

    def test_prefix_excludes_future_gt_and_rejects_degeneracy(self):
        xyz = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [2, 1, 0]])
        target = transform_points(xyz, pose(t=(3, 2, 1), angles=(.2, .1, -.4), scale=2))
        ids = np.arange(0, 10, 2)
        first, used = fit_prefix_gauge(xyz, target, ids, 6)
        target[3:] += 1000
        second, _ = fit_prefix_gauge(xyz, target, ids, 6)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(used, [0, 2, 4])
        with self.assertRaises(ValueError):
            fit_prefix_gauge(np.zeros_like(xyz), target, ids, 6)
        with self.assertRaises(ValueError):
            fit_prefix_gauge(xyz, target, ids[::-1], 6)
        with self.assertRaises(ValueError):
            fit_prefix_gauge(xyz, target, ids, 100)

    def test_fixed_unit_conversion_preserves_a00_mean_and_covariance(self):
        raw_pose = pose(t=(1, -2, .5), angles=(.2, -.5, .1), scale=1.7)
        gauge = pose(t=(5, 1, 2), angles=(.3, .1, -.3), scale=2.4)
        for C in (.2, 2.4, 9.):
            arms = self.arms(raw_pose=raw_pose, C=C, gauge=gauge)
            raw = arms["A00"]["local_points_m"] / C
            np.testing.assert_allclose(arms["A00"]["world_points_m"], transform_points(raw, gauge @ raw_pose), atol=1e-12)
            raw_cov = arms["A00"]["local_covariance_m2"] / C**2
            np.testing.assert_allclose(arms["A00"]["world_covariance_m2"], transform_covariance(raw_cov, gauge @ raw_pose), atol=1e-12)
        self.assertFalse(np.allclose(self.arms(C=1)["A01"]["world_points_m"], self.arms(C=2)["A01"]["world_points_m"]))

    def test_cross_branch_relative_pose_and_no_double_gt_transform(self):
        anchor = pose(t=(1, 2, 3), angles=(.1, .2, -.5))
        source = pose(t=(-2, 1, 0), angles=(.3, -.4, .2))
        points = np.array([[.1, -.2, 2.], [.4, .1, 3.]])
        local = source_points_in_anchor(points, source, anchor)
        expected = transform_points(points, source)
        np.testing.assert_allclose(transform_points(local, anchor), expected, atol=1e-12)
        self.assertFalse(np.allclose(transform_points(transform_points(local, anchor), anchor), expected))

    def test_synthetic_depth_error_changes_only_local_factor(self):
        gt = self.arms()["A00"]["local_points_m"]
        arms = self.arms(raw=gt*1.2, gt=gt)
        for name in ("A10", "A11"):
            np.testing.assert_allclose(arms[name]["world_points_m"], gt)
        self.assertGreater(np.linalg.norm(arms["A01"]["world_points_m"]-gt), .1)

    def test_synthetic_pose_error_changes_only_placement_factor(self):
        for bad_pose in (pose(t=(1, 0, 0)), pose(angles=(0, .4, 0)), pose(scale=1.5)):
            arms = self.arms(raw_pose=bad_pose)
            target = arms["A01"]["world_points_m"]
            np.testing.assert_array_equal(target, arms["A11"]["world_points_m"])
            np.testing.assert_array_equal(arms["A00"]["world_points_m"], arms["A10"]["world_points_m"])
            self.assertGreater(np.linalg.norm(arms["A00"]["world_points_m"]-target), .1)

    def test_interaction_sign_for_known_mixed_error(self):
        gt = np.repeat([[1., 0, 2]], 3, axis=0)
        raw = gt + [1, 0, 0]
        arms = self.arms(raw=raw, gt=gt, raw_pose=pose(t=(1, 0, 0)))
        E = {k: float(np.mean(np.sum((v["world_points_m"]-gt)**2, axis=1))) for k,v in arms.items()}
        self.assertEqual(E, {"A00":4., "A10":1., "A01":1., "A11":0.})
        self.assertEqual(E["A11"]-E["A10"]-E["A01"]+E["A00"], 2.)

    def test_corruption_of_id_mask_attributes_and_covariance_is_rejected(self):
        for key in ("candidate_ids", "common_mask", "local_covariance_m2", "opacity"):
            arms = self.arms()
            if key == "candidate_ids":
                arms["A10"][key][0] = "different"
            elif key == "common_mask":
                arms["A10"][key][0] = False
            elif key == "opacity":
                arms["A10"]["attributes"][key][0] += .1
            else:
                arms["A10"][key][0, 0, 0] += .1
            with self.assertRaises(ValueError):
                validate_arms(arms)

    def test_correlated_intervention_is_rejected_even_if_world_is_recomputed(self):
        for arm_name, key in (("A10", "placement"), ("A01", "local_points_m")):
            arms = deepcopy(self.arms())
            if key == "placement":
                # Keep the pose a valid SE(3): rejection must come from the
                # intervention invariant, not a malformed rotation matrix.
                arms[arm_name][key][0, 3] += .1
            else:
                arms[arm_name][key][0, 0] += .1
            a = arms[arm_name]
            a["world_points_m"] = transform_points(a["local_points_m"], a["placement"])
            a["world_covariance_m2"] = transform_covariance(a["local_covariance_m2"], a["placement"])
            with self.assertRaises(ValueError):
                validate_arms(arms)

    def test_stratified_selection_is_deterministic_and_respects_common_mask(self):
        y,x = np.indices((16, 16)); uv=np.column_stack([x.ravel(),y.ravel()])
        common = np.arange(256)%3 != 0
        args = (uv, np.linspace(.5, 5, 256), common, (16,16), 7, (4,4), [1,2,4], 2)
        a,b = stratified_subset(*args),stratified_subset(*args)
        np.testing.assert_array_equal(a,b)
        self.assertTrue(common[a].all())
        self.assertEqual(len(a),len(np.unique(a)))


if __name__ == "__main__":
    unittest.main()
