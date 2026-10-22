"""Synthetic counterexamples for E4b's diagnostic, not performance claims."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
import numpy as np
import torch
from e1_taxonomy import backproject
from e2_signals import prepare_observation
from e3b_provisional import ProvisionalAdmission,REJECT
from e4b_audit import (cohort_codes,funnel,aggregate_oracles,prepare_gt,reference_quality,
    gt_front,oracle_pair,change_metrics)
import json


class E4bTest(unittest.TestCase):
    def scene(self,z=1.5):
        h=w=15;K=np.array([[20.,0,7],[0,20.,7],[0,0,1.]])
        depth=np.full((h,w),2.,np.float64)
        points=backproject(np.full((h,w),z),K)
        base=json.loads((ROOT/'configs/e2_discriminability.json').read_text())
        label=json.loads((ROOT/'configs/e1_taxonomy.json').read_text())
        raw=dict(pts3d=torch.tensor(points),conf=torch.full((h,w),3.))
        obs=prepare_observation(raw,np.zeros((h,w,3)),base)
        gt=prepare_gt(obs,depth,K,label,base)
        return obs,gt,base

    def test_four_cohorts_are_exhaustive(self):
        np.testing.assert_array_equal(cohort_codes(np.array([0,1,1,0],bool),np.array([0,0,1,1],bool)),[0,1,2,3])

    def test_coherent_wrong_plane_is_not_absolute_accuracy(self):
        obs,gt,base=self.scene();q=reference_quality(obs,gt,1.,base);k=7*15+7
        self.assertTrue(obs['patch_reliable'][k]);self.assertTrue(q['gt_reliable'][k])
        self.assertTrue(q['wrong_5_10'][k]);self.assertTrue(q['coherent_front'][k]);self.assertTrue(q['all_points_wrong'][k])
        self.assertAlmostEqual(q['plane_offset_m'][k],.5,places=5)
        self.assertAlmostEqual(q['plane_angle_degrees'][k],0,places=5)

    def test_accurate_plane_passes_gt_quality(self):
        obs,gt,base=self.scene(2.);q=reference_quality(obs,gt,1.,base);k=112
        self.assertFalse(q['wrong_5_10'][k]);self.assertFalse(q['coherent_front'][k])

    def test_one_fixed_global_scale_not_local_fitting(self):
        obs,gt,base=self.scene(1.);q=reference_quality(obs,gt,2.,base)
        self.assertAlmostEqual(q['plane_offset_m'][112],0,places=5)
        self.assertFalse(q['wrong_5_10'][112])

    def test_missing_gt_is_not_a_correct_reference(self):
        obs,gt,base=self.scene();gt['depth'][:]=0
        label=json.loads((ROOT/'configs/e1_taxonomy.json').read_text())
        g=prepare_gt(obs,gt['depth'],gt['K'],label,base)
        self.assertFalse(g['reliable'].any());self.assertTrue((g['status']==0).all())

    def test_covariance_extent_blocks_gt_front(self):
        _,gt,_=self.scene();p=np.array([[0,0,1.5],[0,0,1.5]])
        cov=np.array([np.eye(3)*.0001,np.eye(3)*.04]);ids=np.array([112,112])
        front,match=gt_front(p,cov,gt,1.,ids)
        np.testing.assert_array_equal(front,[True,False]);self.assertTrue(match.all())

    def test_patch_correspondence_is_required(self):
        _,gt,_=self.scene();p=np.array([[.3,0,1.5]])
        front,match=gt_front(p,np.zeros((1,3,3)),gt,1.,np.array([112]))
        self.assertFalse(match[0]);self.assertFalse(front[0])

    def test_fixed_veto_and_recomputed_veto_are_separate(self):
        d=[np.array([.4]),np.array([.5])];p=[np.array([0.]),np.array([.5])]
        g=[np.array([.4]),np.array([.5])]
        factual,fixed,recomputed=aggregate_oracles(d,p,g,1)
        self.assertTrue(np.isnan(factual[0]));self.assertTrue(np.isnan(fixed[0]))
        self.assertAlmostEqual(recomputed[0],.4,places=6)

    def test_oracle_does_not_create_missing_pairs(self):
        d=[np.array([.4]),np.array([.5])];p=[np.array([np.nan]),np.array([.5])]
        g=[np.array([100.]),np.array([.9])]
        self.assertTrue(all(np.isnan(v[0]) for v in aggregate_oracles(d,p,g,1)))

    def test_gt_plane_changes_residual_but_preserves_nan_pairs(self):
        obs,gt,_=self.scene();p=np.array([[0,0,1.5],[0,0,1.5]])
        cov=np.zeros((2,3,3));ids=np.array([112,112]);d=np.array([.2,np.nan]);pl=np.array([0.,np.nan])
        changed,use=oracle_pair(p,cov,d,pl,ids,obs,gt,1.)
        self.assertAlmostEqual(changed[0],1/3,places=6);self.assertTrue(use[0]);self.assertTrue(np.isnan(changed[1]))

    def test_funnel_keeps_order_when_veto_and_low_count_overlap(self):
        c=funnel(np.array([1,1,1,1]),np.array([0,1,2,2]),np.array([1,1,1,0],bool),
            np.array([np.nan,np.nan,np.nan,.8]),.5,2)
        np.testing.assert_array_equal(c,[2,3,4,6])
        self.assertEqual(funnel(np.array([0]),np.array([0]),np.array([0],bool),np.array([np.nan]),.5,0)[0],0)

    def test_normal_harm_and_bad_loss_are_reported(self):
        f=np.array([0,1,0,1],bool);g=~f;y=np.array([3,3,1,0]);a=np.ones(4,bool)
        r=change_metrics(f,g,y,a,np.array([1,0,0,0],bool))
        self.assertEqual(r['bad_newly_rejected'],1);self.assertEqual(r['bad_no_longer_rejected'],1)
        self.assertEqual(r['normal_newly_rejected'],1);self.assertEqual(r['unknown_no_longer_rejected'],1)

    def test_temporal_reject_is_absorbing_and_ties_kept(self):
        p=ProvisionalAdmission(dict(kind='review'),np.ones(2,bool),np.zeros(2,int),.5)
        p.advance(0,0,1,np.array([.5,.6]));p.advance(1,1,2,np.array([0.,np.nan]))
        self.assertNotEqual(p.state[0],REJECT);self.assertEqual(p.state[1],REJECT);self.assertEqual(p.first_reject[1],0)


if __name__=='__main__':unittest.main()
