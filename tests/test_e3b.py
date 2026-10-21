"""Synthetic E3b tests for temporal risk, subgroup protection and provisional use."""
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from e3b_provisional import cumulative_scores,calibrate,ProvisionalAdmission,metrics,PROVISIONAL,KEEP,REJECT


class CalibrationTests(unittest.TestCase):
    def test_high_risk_common_group_overrides_global_quantile(self):
        score=np.r_[np.zeros(990),np.arange(10)+1.].astype(np.float32)
        common=np.arange(1000)>=990
        r=calibrate(score,np.ones(1000,int),np.ones(1000,bool),common,np.zeros(1000,int),.9,5)
        self.assertEqual(r['threshold'],10.)
        self.assertGreater(r['threshold'],np.quantile(score,.9,method='higher'))

    def test_anchor_group_prevents_temporal_risk_concentration(self):
        score=np.r_[np.zeros(100),np.arange(10)+1.].astype(np.float32)
        r=calibrate(score,np.ones(110,int),np.ones(110,bool),np.ones(110,bool),
            np.r_[np.zeros(100,int),np.ones(10,int)],.9,5)
        self.assertEqual(r['threshold'],10.)

    def test_missing_required_group_is_uncalibrated(self):
        r=calibrate(np.arange(20.),np.ones(20,int),np.ones(20,bool),np.zeros(20,bool),np.zeros(20,int),.99,5)
        self.assertIsNone(r['threshold']);self.assertFalse(r['calibrated'])

    def test_persistence_does_not_join_across_missing_snapshot(self):
        peak,persistent=cumulative_scores([np.array([1.,.8]),np.array([np.nan,.7]),np.array([2.,np.nan])],2)
        np.testing.assert_allclose(peak,[2.,.8])
        self.assertTrue(np.isnan(persistent[0]));self.assertAlmostEqual(persistent[1],.7,places=6)

    def test_calibration_uses_candidate_max_not_per_snapshot_quantiles(self):
        peak,_=cumulative_scores([np.array([0.,2.]),np.array([3.,0.])],2)
        np.testing.assert_array_equal(peak,[3.,2.])


class ProvisionalTests(unittest.TestCase):
    def make(self,kind='review',threshold=.5):
        return ProvisionalAdmission(dict(kind=kind),np.array([True,True,False]),np.array([0,1,0]),threshold)

    def test_unknown_renderable_and_future_absent(self):
        p=self.make();mask=p.advance(0,0,1,np.array([np.nan]))
        np.testing.assert_array_equal(mask,[True,False,False]);self.assertEqual(p.state[0],PROVISIONAL)
        p.advance(1,10,2,np.array([np.nan,np.nan]))
        m=metrics(p.arrays(),np.array([1,1,0]),p.active)
        self.assertEqual(m['normal_active_retention'],1.);self.assertEqual(m['deferred'],0)

    def test_existing_candidate_rechecked_then_rejection_absorbing(self):
        p=self.make();p.advance(0,0,1,[np.nan]);p.advance(1,10,2,[1.,np.nan]);p.advance(2,20,3,[0.,0.])
        self.assertEqual(p.state[0],REJECT);self.assertEqual(p.first_reject[0],10);self.assertEqual(p.reject_revision[0],2)

    def test_two_snapshot_persistence_and_ties(self):
        p=self.make('persistent');p.advance(0,0,1,[1.]);p.advance(1,10,2,[1.,.5]);p.advance(2,20,3,[np.nan,.5])
        self.assertEqual(p.state[0],REJECT);self.assertNotEqual(p.state[1],REJECT)

    def test_future_rows_and_skipped_snapshots_fail(self):
        p=self.make()
        with self.assertRaises(ValueError):p.advance(0,0,1,[0.,1.])
        p=self.make()
        with self.assertRaises(ValueError):p.advance(1,10,2,[0.,1.])

    def test_uncalibrated_cannot_remove_candidates(self):
        p=self.make(threshold=None);p.advance(0,0,1,[100.])
        self.assertNotEqual(p.state[0],REJECT)

    def test_no_held_out_gt_in_replay(self):
        from run_e3 import feature_guard
        with feature_guard():
            for p in ['data/E3b/Replica/room1/traj.txt','x/evaluation/room1/labels.npz']:
                with self.assertRaises(RuntimeError):Path(p).read_bytes()


if __name__=='__main__':unittest.main()
