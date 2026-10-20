"""Check safety of repeated contradictions and cumulative threshold transfer."""
from pathlib import Path
import json
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from e2b_transfer import repeat_score, temporal_max, operation, progress_checks
from e2_metrics import calibrate_normal_threshold
from score_e2b import forbid_e2b_gt_reads


class E2bTests(unittest.TestCase):
    def test_other_scene_gt_and_evaluation_labels_are_blocked(self):
        with forbid_e2b_gt_reads():
            for p in (ROOT/'data/E2b/Replica/room0/traj.txt',
                      ROOT/'data/E2b/Replica/room0/results/depth000002.png',
                      ROOT/'results/E2b_repeated_observations_threshold_transfer/evaluation/room0/labels.npz',
                      ROOT/'results/E2b_repeated_observations_threshold_transfer/baselines/room0/map/room0_frames.txt'):
                with self.assertRaises(RuntimeError):
                    p.read_bytes()

    def test_one_extreme_conflict_does_not_substitute_two_conflicts(self):
        s, count, _ = repeat_score([np.array([100., 3.]), np.array([1., 4.])], 2)
        np.testing.assert_array_equal(count, [2, 2])
        np.testing.assert_array_equal(s > 2, [False, True])

    def test_normal_surface_support_vetoes_conflicting_front_votes(self):
        views = [np.array([8., 8.]), np.array([7., 7.]), np.array([0., np.nan])]
        score, count, support = repeat_score(views, 2)
        self.assertTrue(np.isnan(score[0]))
        self.assertEqual(score[1], 7.)
        np.testing.assert_array_equal(support, [True, False])
        self.assertEqual(repeat_score(views, 2, veto=False)[0][0], 7.)

    def test_views_from_different_snapshots_cannot_be_added(self):
        a = repeat_score([np.array([8.]), np.array([np.nan])], 1)[0]
        b = repeat_score([np.array([np.nan]), np.array([8.])], 1)[0]
        self.assertTrue(np.isnan(temporal_max(a, b)).all())

    def test_calibration_controls_cumulative_not_per_snapshot_rejection(self):
        current = []
        for i in range(5):
            x = np.zeros(1000)
            x[i*5:(i+1)*5] = 1.
            current.append(x)
        peak = np.max(current, axis=0)
        threshold = calibrate_normal_threshold(peak, np.ones(1000, bool), 0.99)
        self.assertEqual(threshold, 1.)
        self.assertEqual(int((peak > threshold).sum()), 0)
        self.assertEqual(int((peak > 0).sum()), 25)

    def test_missing_evidence_is_not_a_safe_operating_point(self):
        labels = np.array([1, 3, 0])
        op = operation(np.full(3, np.nan), labels, None, np.zeros(3, bool))
        self.assertEqual(op['global_normal_retention'], 1.)
        self.assertEqual(op['global_bad_recall'], 0.)
        self.assertIsNone(op['eligible_normal_retention'])
        self.assertIsNone(op['precision'])
        rule=json.loads((ROOT/'configs/e2b_observation_transfer.json').read_text())['progress']
        checks=progress_checks(0.,op,rule)
        self.assertFalse(all(checks.values()))
        self.assertFalse(checks['calibrated'])
        self.assertFalse(checks['global_bad_recall'])

    def test_observability_denominator_includes_vetoed_normals(self):
        labels = np.array([1, 1, 3, 3, 0])
        op = operation(np.array([np.nan, 4., 5., np.nan, 6.]), labels, 3., np.ones(5, bool))
        self.assertEqual(op['eligible_normal_retention'], 0.5)
        self.assertEqual(op['eligible_bad_recall'], 0.5)
        self.assertEqual(op['unknown_gt_rejected'], 1)
        self.assertEqual(op['precision'], 0.5)


if __name__ == '__main__':
    unittest.main()
