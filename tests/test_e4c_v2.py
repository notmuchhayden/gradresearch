"""Mechanism checks, not synthetic efficacy claims."""
from pathlib import Path
import sys
import unittest
import warnings
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from e4c_surface_v2 import partition, fit_patches, hull_contains, states, diverse_pair, second_diverse, view_geometry


class SurfaceTest(unittest.TestCase):
    def test_partition_removes_cross_pool_image_overlap(self):
        lineage = [dict(source_images=([0] if i == 0 else [i-1, i])) for i in range(8)]
        self.assertEqual(partition(lineage), ([0, 5, 6, 7], [2, 3]))

    def test_unknown_ancestry_fails_closed(self):
        with self.assertRaises(ValueError): partition([dict(source_images=[])])

    def test_hull_has_finite_extent_and_boundary(self):
        xy = np.array([[[-1,-1],[1,-1],[1,1],[-1,1]]], float)
        for q, expected in [([0,0],True),([2,0],False),([1,1],True)]:
            self.assertEqual(bool(hull_contains(xy,np.array([q]))[0]),expected)

    def test_zero_forward_score_is_not_support(self):
        geometry = dict(ids=np.arange(2), eligible=np.ones(2,bool), signed=np.array([-10.,0.]),
                        sigma=np.zeros(2), depth=np.zeros(2))
        fit=dict(spacing=np.ones(2)*.01,scale=np.zeros(2),mean=np.ones((2,3)))
        support,plane,_=states(geometry,fit)
        np.testing.assert_array_equal(plane,[0,0]);np.testing.assert_array_equal(support,[False,True])

    def test_center_excluded_fit_ignores_moved_center(self):
        yy,xx=np.mgrid[:11,:11];p=np.stack([xx*.01,yy*.01,np.ones_like(xx)],axis=-1).astype(float)
        obs=dict(points=p.reshape(-1,3),confidence=np.ones(121)*3,hw=(11,11),edge=np.zeros(121,bool))
        a=fit_patches(obs);obs['points'][60,2]=1.2;b=fit_patches(obs)
        np.testing.assert_allclose(a['mean'][60],b['mean'][60]);np.testing.assert_allclose(a['normal'][60],b['normal'][60])
        self.assertTrue(b['reliable'][60])

    def test_repeated_kf_is_not_repeated_evidence(self):
        m=[np.array([True])]*2;d=[np.array([[0.,0.,1.]]),np.array([[.1,0,.995]])]
        with self.assertRaises(ValueError):diverse_pair(m,d,[1,1])

    def test_diversity_and_strict_threshold_tie(self):
        d=[np.array([[0.,0.,1.]]),np.array([[np.sin(.1),0,np.cos(.1)]])]
        result=second_diverse([np.array([2.]),np.array([3.])],d,[0,1])
        self.assertEqual(float(result[0]),2.);self.assertFalse(bool((result>2)[0]))
        self.assertTrue(bool(diverse_pair([np.array([True])]*2,d,[0,1])[0]))

    def test_degenerate_patch_abstains(self):
        obs=dict(points=np.ones((121,3)),confidence=np.ones(121)*3,hw=(11,11),edge=np.zeros(121,bool))
        self.assertFalse(fit_patches(obs)['reliable'].any())

    def test_audit_center_exclusion_and_occlusion(self):
        yy,xx=np.mgrid[:11,:11];p=np.stack([xx*.01,yy*.01,np.ones_like(xx)],axis=-1).astype(float).reshape(-1,3)
        obs=dict(points=p,confidence=np.ones(121)*3,hw=(11,11),edge=np.zeros(121,bool),radius=np.linalg.norm(p,axis=1))
        fit=fit_patches(obs,radius=3,audit=True)
        self.assertTrue(fit['reliable'][60])
        means=p.copy();means[60,2]=1.5
        g=view_geometry(means,np.zeros((121,3,3)),obs,obs,fit,np.eye(4),np.eye(4),local=True)
        self.assertFalse(g['eligible'][60])
        self.assertFalse(states(g,fit,audit=True)[0][60])

    def test_covariance_scale_and_coordinate_invariance(self):
        yy,xx=np.mgrid[:11,:11];p=np.stack([xx*.01,yy*.01,np.ones_like(xx)],axis=-1).astype(float).reshape(-1,3)
        obs=dict(points=p,confidence=np.ones(121)*3,hw=(11,11),edge=np.zeros(121,bool),radius=np.linalg.norm(p,axis=1))
        fit=fit_patches(obs);cov=np.tile(np.eye(3)*1e-6,(121,1,1))
        g=view_geometry(p,cov,obs,obs,fit,np.eye(4),np.eye(4),local=True)
        pose=np.eye(4);pose[:3,:3]*=2;pose[:3,3]=[3,4,5]
        transformed=view_geometry(p,cov,obs,obs,fit,pose,pose,local=True)
        np.testing.assert_array_equal(g['eligible'],transformed['eligible'])
        np.testing.assert_allclose(g['sigma'],transformed['sigma'])

    def test_front_conflict_uses_ray_hit_not_perpendicular_footprint(self):
        from scipy.spatial import cKDTree
        yy,xx=np.mgrid[:11,:11];p=np.stack([xx*.01,yy*.01,np.ones_like(xx)],axis=-1).astype(float).reshape(-1,3)
        rays=p/np.linalg.norm(p,axis=1,keepdims=True)
        obs=dict(points=p,confidence=np.ones(121)*3,hw=(11,11),edge=np.zeros(121,bool),
                 radius=np.linalg.norm(p,axis=1),tree=cKDTree(rays),tree_indices=np.arange(121))
        fit=fit_patches(obs);pose=np.eye(4);pose[0,3]=.03
        means=np.array([[.01,.04,.5]])
        g=view_geometry(means,np.zeros((1,3,3)),dict(confidence=np.array([3.])),obs,fit,pose,np.eye(4))
        support,score,_=states(g,fit)
        self.assertTrue(g['eligible'][0]);self.assertTrue(g['front'][0])
        self.assertFalse(g['support_hull'][0]);self.assertFalse(support[0]);self.assertGreater(score[0],1)


if __name__=='__main__':unittest.main()
