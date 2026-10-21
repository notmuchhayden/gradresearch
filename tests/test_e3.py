"""Behavioral/synthetic checks: unknown, causality, queue harm and rendering."""
import builtins
import io
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'scripts')]
from e3_admission import Admission,KEEP,REJECT,DEFER,BYPASS,EXCLUDED,decision_metrics
from e3_cpu_renderer import render


def history(plane,counts,photo=None):
    plane = np.array(plane,np.float32).reshape(1,-1)
    return dict(P1_second_front_relative=plane,support_count=np.array(counts).reshape(1,-1),
        B7_rgb_ncc_region=plane if photo is None else np.array(photo,np.float32).reshape(1,-1),
        B6_depth_front=plane,B2_confidence=plane)


def policy(name,n=2,ttl=2):
    t = {m:0.5 for m in ['P1_second_front_relative','B7_rgb_ncc_region','B6_depth_front',
                         'B2_confidence','B8_dog_redundancy']}
    return Admission(name,np.ones(n,bool),np.zeros(n,int),np.zeros(n,int),t,ttl)


class AdmissionTests(unittest.TestCase):
    def test_unknown_never_rejected_or_certified(self):
        p = policy('P2')
        p.advance(0,0,1,history([np.nan,np.nan],[0,1]))
        np.testing.assert_array_equal(p.state,[DEFER,DEFER])
        self.assertFalse(p.ever_eligible.any())

    def test_repeat_count_is_current_snapshot_not_time_union(self):
        p = policy('P2_unbounded')
        for i in range(3):
            p.advance(i,i*10,i,history([np.nan,np.nan],[1,1]))
        np.testing.assert_array_equal(p.state,[DEFER,DEFER])

    def test_timeout_preserves_unknown_without_force_rejection(self):
        p = policy('P2')
        for i in range(3):
            p.advance(i,i*10,i,history([np.nan,np.nan],[0,0]))
        np.testing.assert_array_equal(p.state,[BYPASS,BYPASS])
        np.testing.assert_array_equal(p.first_admit,[20,20])
        self.assertTrue(p.timed_out.all())

    def test_support_veto_can_release_queue(self):
        p = policy('P2')
        p.advance(0,0,1,history([np.nan,0.1],[2,2]))
        np.testing.assert_array_equal(p.state,[KEEP,KEEP])
        self.assertFalse(p.ever_eligible[0])

    def test_rejected_absorbing_and_kept_reviewable(self):
        p = policy('P2')
        p.advance(0,0,1,history([1.,0.1],[2,2]))
        p.advance(1,10,2,history([0.1,1.],[2,2]))
        p.advance(2,20,3,history([0.1,0.1],[2,2]))
        np.testing.assert_array_equal(p.state,[REJECT,REJECT])
        np.testing.assert_array_equal(p.first_reject,[0,10])
        np.testing.assert_array_equal(p.rejected_revision,[1,2])

    def test_missing_rgb_does_not_confirm_conflict(self):
        p = policy('P3')
        p.advance(0,0,1,history([1.,1.],[2,2],[np.nan,0.1]))
        np.testing.assert_array_equal(p.state,[DEFER,KEEP])
        p.advance(1,10,2,history([1.,1.],[2,2],[1.,0.1]))
        np.testing.assert_array_equal(p.state,[REJECT,KEEP])

    def test_birth_only_does_not_use_future_evidence(self):
        p = policy('P1')
        p.advance(0,0,1,history([np.nan,np.nan],[0,0]))
        p.advance(1,10,2,history([1.,1.],[2,2]))
        np.testing.assert_array_equal(p.state,[BYPASS,BYPASS])
        self.assertFalse(p.ever_eligible.any())

    def test_future_and_original_excluded_never_enter_map(self):
        p = policy('P2')
        p.active[1] = False
        p.state[1] = EXCLUDED
        p.anchors[0] = 1
        mask = p.advance(0,0,1,history([1.,1.],[2,2]))
        self.assertFalse(mask.any())
        self.assertFalse((p.state==REJECT).any())

    def test_deferred_normal_is_lost_coverage_not_retained_map(self):
        m = decision_metrics(np.array([DEFER,KEEP]),np.array([1,3]),np.ones(2,bool),np.ones(2,bool))
        self.assertEqual(m['normal_not_rejected'],1.)
        self.assertEqual(m['normal_active_retention'],0.)
        self.assertEqual(m['normal_deferred'],1)

    def test_feature_reads_block_gt_and_final_map(self):
        from run_e3 import feature_guard
        with feature_guard():
            for p in ['data/E2b/Replica/room0/traj.txt','x/evaluation/room0/labels.npz','final.ply']:
                with self.assertRaises(RuntimeError):
                    Path(p).read_bytes()


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.K = np.array([[50.,0,31.],[0,50.,31.],[0,0,1.]])
        self.mu = np.array([[0.,0,1.],[0.,0,2.]],np.float32)
        self.cov = np.tile(np.eye(3,dtype=np.float32)[None]*0.01**2,(2,1,1))
        self.opacity = np.full(2,0.5,np.float32)

    def test_analytic_center_and_front_back(self):
        out = render(self.mu,self.cov,self.opacity,np.array([[1.,1.,0],[2.,0,1]],np.float32),
                     np.eye(4),self.K,(64,64))
        np.testing.assert_allclose(out[31,31],[1.,0.5,0.25],atol=1e-6)
        self.assertAlmostEqual(out[31,31,0]/out[31,31,1:].sum(),4/3,places=5)

    def test_principal_point_shift_and_empty_map(self):
        values = np.ones((2,3),np.float32)
        a = render(self.mu,self.cov,self.opacity,values,np.eye(4),self.K,(64,64))
        k = self.K.copy();k[0,2]+=5
        b = render(self.mu,self.cov,self.opacity,values,np.eye(4),k,(64,64))
        np.testing.assert_allclose(a[:,:-5],b[:,5:],atol=1e-6)
        empty = render(self.mu[:0],self.cov[:0],self.opacity[:0],values[:0],np.eye(4),self.K,(64,64))
        self.assertEqual(float(empty.sum()),0.)

    def test_uniform_world_scale_preserves_image(self):
        values = np.ones((2,3),np.float32)
        a = render(self.mu,self.cov,self.opacity,values,np.eye(4),self.K,(64,64))
        b = render(self.mu*3,self.cov*9,self.opacity,values,np.eye(4),self.K,(64,64))
        np.testing.assert_allclose(a,b,atol=1e-6)


if __name__=='__main__':
    unittest.main()
