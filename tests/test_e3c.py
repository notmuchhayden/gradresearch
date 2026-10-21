"""Counterexamples for common-view matching and shared support semantics."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from e3c_matched import matched_scores,geometry_pair
from e2_signals import cross_pair,prepare_observation


class MatchedTests(unittest.TestCase):
    def test_missing_plane_view_cannot_supply_second_depth_vote(self):
        r,count,_,_=matched_scores([[.9],[.8]],[[.7],[np.nan]],1)
        self.assertEqual(count[0],1)
        self.assertTrue(np.isnan(r['D_shared'][0]))
        self.assertTrue(np.isnan(r['P_shared'][0]))
        self.assertTrue(np.isfinite(r['D_native'][0]))

    def test_plane_support_veto_is_identical_for_both_scores(self):
        r,_,_,_=matched_scores([[.9],[.8],[.7]],[[.9],[.8],[0.]],1)
        self.assertTrue(np.isnan(r['D_shared'][0]));self.assertTrue(np.isnan(r['P_shared'][0]))

    def test_union_veto_checks_depth_support_for_both(self):
        r,_,_,_=matched_scores([[.9],[.8],[0.]],[[.7],[.6],[.5]],1)
        self.assertAlmostEqual(r['D_shared'][0],.8,places=6)
        self.assertTrue(np.isnan(r['D_union'][0]));self.assertTrue(np.isnan(r['P_union'][0]))

    def test_median_ablation_changes_only_aggregation(self):
        r,_,_,_=matched_scores([[.1],[.2],[.3],[.9]],[[.1],[.2],[.3],[.9]],1)
        self.assertAlmostEqual(r['D_maskmedian'][0],.25,places=6)
        self.assertAlmostEqual(r['D_shared'][0],.3,places=6)

    def test_disjoint_finite_views_cannot_be_matched_after_aggregation(self):
        r,_,_,_=matched_scores([[.9],[.8],[np.nan],[np.nan]],[[np.nan],[np.nan],[.9],[.8]],1)
        self.assertTrue(np.isnan(r['P_shared'][0]));self.assertTrue(np.isnan(r['D_shared'][0]))

    def test_empty_and_mismatched_views(self):
        r,c,_,_=matched_scores([],[],3)
        self.assertTrue(all(np.isnan(v).all() for v in r.values()));self.assertEqual(c.sum(),0)
        with self.assertRaises(ValueError):matched_scores([[1]],[],1)

    def test_geometry_prefix_matches_original_without_rgb(self):
        import torch
        spec=json.loads((ROOT/'configs/e2_discriminability.json').read_text())
        y,x=np.mgrid[-.4:.4:21j,-.4:.4:21j]
        pts=np.stack([x,y,np.ones_like(x)*2],-1).astype(np.float32)
        obs=prepare_observation(dict(pts3d=torch.from_numpy(pts),conf=torch.ones(21,21)*3),np.zeros((21,21,3)),spec)
        means=pts.reshape(-1,3).astype(float);cov=np.tile(np.eye(3)*1e-6,(len(means),1,1))
        a=np.eye(4);b=a.copy();b[0,3]=.1
        with patch('e2_signals.photometric_warp',side_effect=lambda c,e,r,ids,s:(np.zeros(len(ids)),np.zeros(len(ids)))):
            old,_=cross_pair(means,cov,obs,obs,a,b,spec)
        d,p,_=geometry_pair(means,cov,obs,obs,a,b,spec)
        from e0b_audit import transform
        from e2_signals import match_rays
        ids,_,_,_=match_rays(transform(means,np.linalg.inv(b)@a),obs,spec['ray_angle_max_degrees'])
        np.testing.assert_array_equal(d,old['B6_depth_front'])
        np.testing.assert_array_equal(p,old['P1_plane_front_1view']*obs['spacing'][ids]/obs['radius'][ids])


if __name__=='__main__':unittest.main()
