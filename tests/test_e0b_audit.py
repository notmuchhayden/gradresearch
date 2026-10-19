"""Scientific guardrails for source eligibility and geometry availability."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from e0b_audit import disjoint, ray_support, sim3_matrix, transform
from e0b_export import merge_lineage


class AuditGuardrails(unittest.TestCase):
    def test_fusion_can_destroy_source_disjointness(self):
        old = merge_lineage(None, dict(images=[0], pairs=[[0, 0]], event_id="a"), first=True)
        self.assertTrue(disjoint([41, 82], old["images"], old["status"]))
        fused = merge_lineage(old, dict(images=[0, 41], pairs=[[41, 0]], event_id="b"))
        self.assertFalse(disjoint([41, 82], fused["images"], fused["status"]))
        self.assertEqual(fused["events"], ["a", "b"])

    def test_unknown_or_missing_ancestry_never_qualifies(self):
        self.assertFalse(disjoint([1], [2], "unknown"))
        self.assertFalse(disjoint([1], []))
        fused = merge_lineage({"images": [0], "status": "unknown"},
                              dict(images=[2], pairs=[[2, 2]], event_id="c"))
        self.assertEqual(fused["status"], "unknown")

    def test_sim3_inverse_with_rotation_translation_and_scale(self):
        pose = sim3_matrix([1, -2, 3, 0, 0, np.sin(.3), np.cos(.3), 2.5])
        points = np.array([[.3, .4, 2.], [1, 2, 5.]])
        np.testing.assert_allclose(transform(transform(points, pose), np.linalg.inv(pose)), points, atol=1e-12)

    def test_ray_support_requires_real_baseline_and_rejects_behind_camera(self):
        spec = dict(confidence_min=1.5, ray_support_max_angle_degrees=1., parallax_min_degrees=1.)
        candidate = np.array([[0., 0., 3.], [0., 0., -3.]])
        confidence = np.ones((2, 1)) * 2
        identity = np.eye(4)
        supported, ray, _, _ = ray_support(candidate, confidence, identity,
                                           np.array([[0., 0., 3.]]), np.array([[2.]]), identity, spec)
        self.assertEqual(ray.tolist(), [True, False])
        self.assertFalse(supported.any())
        translated = np.eye(4)
        translated[0, 3] = .3
        supported, _, _, _ = ray_support(candidate, confidence, identity,
                                          np.array([[-.3, 0., 3.]]), np.array([[2.]]), translated, spec)
        self.assertEqual(supported.tolist(), [True, False])


if __name__ == "__main__":
    unittest.main()
