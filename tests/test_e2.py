"""E2 safety semantics, warped RGB, causal provenance and tie-aware metrics."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from e2_signals import (causal_pair, cross_pair, dog, fit_camera, median_views, prepare_observation)
from e2_metrics import calibrate_normal_threshold, operating_point, pr_metrics
from score_e2 import forbid_gt_reads


class E2Tests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "configs/e2_discriminability.json").read_text())
        self.h, self.w, self.f = 32, 40, 35.
        y, x = np.indices((self.h, self.w))
        self.points = np.stack([(x - 19.5) * 2 / self.f, (y - 15.5) * 2 / self.f, np.ones_like(x) * 2], axis=-1).astype(float)
        self.image = np.stack([x / 40, y / 32, (x % 4) / 4], -1).astype(np.float32)
        self.raw = dict(pts3d=torch.from_numpy(self.points[None]), conf=torch.ones(1, self.h, self.w) * 5)

    def test_source_overlap_and_future_are_not_independent_evidence(self):
        self.assertFalse(causal_pair([2, 3], [1, 2], 9, 8))
        self.assertTrue(causal_pair([2, 3], [0, 1], 9, 8))
        self.assertFalse(causal_pair([2, 3], [], 9, 8))
        with self.assertRaises(ValueError):
            causal_pair([2, 3], [0, 1], 9, 10)

    def test_predicted_camera_fit_uses_rays(self):
        K, eligible, stats = fit_camera(self.points.reshape(-1, 3), np.full(self.h * self.w, 5.), (self.h, self.w), self.spec)
        np.testing.assert_allclose(K, [[35, 0, 19.5], [0, 35, 15.5], [0, 0, 1]], atol=1e-10)
        self.assertTrue(eligible.all())

    def test_no_parallax_or_occlusion_cannot_be_front_evidence(self):
        observation = prepare_observation(self.raw, self.image, self.spec)
        means = self.points.reshape(-1, 3)
        covariance = np.tile(np.eye(3) * 1e-6, (len(means), 1, 1))
        scores, _ = cross_pair(means, covariance, observation, observation, np.eye(4), np.eye(4), self.spec)
        self.assertFalse(np.isfinite(scores["B6_depth_front"]).any())
        candidate_pose = np.eye(4); candidate_pose[0, 3] = 0.15
        behind = means.copy(); behind[:, 2] += 1
        scores, stats = cross_pair(behind, covariance, observation, observation, candidate_pose, np.eye(4), self.spec)
        self.assertFalse(np.isfinite(scores["B6_depth_front"]).any())
        self.assertGreater(stats["occluded"], 0)

    def test_front_plane_has_positive_evidence_and_rgb_warp_is_finite(self):
        observation = prepare_observation(self.raw, self.image, self.spec)
        means = self.points.reshape(-1, 3).copy(); means[:, 2] -= 0.2
        covariance = np.tile(np.eye(3) * 1e-6, (len(means), 1, 1))
        candidate_pose = np.eye(4); candidate_pose[0, 3] = 0.1
        scores, stats = cross_pair(means, covariance, observation, observation, candidate_pose, np.eye(4), self.spec)
        self.assertTrue(np.nanmax(scores["B6_depth_front"]) > 0)
        self.assertTrue(np.nanmax(scores["P1_plane_front_1view"]) > 0)
        self.assertGreater(stats["rgb_l1_eligible"], 0)
        self.assertTrue(np.isfinite(scores["B7_rgb_ncc_region"]).any())

    def test_missing_scores_and_two_view_counts_stay_unknown(self):
        score, count = median_views([], 3)
        self.assertTrue(np.isnan(score).all())
        a = np.array([np.nan, 0.2, 0.3]); b = np.array([0.5, np.nan, 0.7])
        score, count = median_views([a, b], 3)
        np.testing.assert_allclose(score, [0.5, 0.2, 0.5])
        np.testing.assert_array_equal(count, [1, 1, 2])

    def test_constant_tied_score_ap_equals_prevalence(self):
        m, _ = pr_metrics([1, 0, 1, 0], [0, 0, 0, 0])
        self.assertEqual(m["average_precision"], 0.5)
        m, _ = pr_metrics([1, 0, 1, 0], [4, 3, 2, 1])
        self.assertAlmostEqual(m["average_precision"], (1 + 2 / 3) / 2)

    def test_strict_threshold_ties_keep_normals_and_unknowns(self):
        score = np.array([0., 0, 0, 1, np.nan])
        bad = np.array([False, False, False, True, True])
        normal = ~bad
        threshold = calibrate_normal_threshold(score, normal, 0.99)
        self.assertEqual(threshold, 0)
        result = operating_point(score, bad, normal, threshold)
        self.assertEqual(result["global_normal_retention"], 1)
        self.assertEqual(result["global_bad_recall"], 0.5)
        self.assertEqual(result["precision"], 1)
        self.assertIsNone(calibrate_normal_threshold(score, np.zeros(5, bool), 0.99))

    def test_gt_and_final_trajectory_reads_fail_closed(self):
        with forbid_gt_reads():
            for path in (ROOT / "data/E1/Replica/cam_params.json", ROOT / "data/Replica/office0/traj.txt",
                         ROOT / "results/E1_error_taxonomy/candidate_labels.npz"):
                with self.assertRaises(RuntimeError):
                    path.read_bytes()

    def test_dog_constant_image_has_no_structure(self):
        np.testing.assert_allclose(dog(np.ones((32, 40, 3)), [0.5, 1.5]), 0, atol=1e-7)


if __name__ == "__main__":
    unittest.main()
