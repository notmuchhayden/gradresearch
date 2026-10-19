"""Fault injection into captured E0b snapshots; the original artifacts stay intact."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from e0b_audit import Audit

RUN = Path(__file__).resolve().parents[1] / "results/E0b_ancestry_causality/short"


@unittest.skipUnless((RUN / "wall_seconds.txt").exists(), "Requires a completed E0b short capture")
class CapturedRunFaultInjection(unittest.TestCase):
    def reject_snapshot(self, mutate):
        audit = Audit(RUN)
        original = audit.snapshot
        def damaged(event):
            snapshot = original(event)
            mutate(snapshot)
            return snapshot
        with patch.object(audit, "snapshot", side_effect=damaged):
            with self.assertRaises(AssertionError):
                audit.validate()

    def test_future_creation_sequence_is_rejected(self):
        self.reject_snapshot(lambda s: s["metadata"][0].update(created_sequence=10**12))

    def test_wrong_pose_value_at_same_revision_is_rejected(self):
        def mutate(s):
            s["poses"][0, 0, 0] += 1
        self.reject_snapshot(mutate)

    def test_missing_fused_source_is_rejected(self):
        self.reject_snapshot(lambda s: s["metadata"][0]["fused"].update(images=[]))


if __name__ == "__main__":
    unittest.main()
