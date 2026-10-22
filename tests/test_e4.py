import sys
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from e4_budget import select_budget,pack_parameters,unpack_parameters,voxel_birth_score,image_metrics,sample_mesh,surface_metrics


class BudgetTests(unittest.TestCase):
    def test_fallback_exact_and_never_resurrects(self):
        a=np.ones(10,bool);n=a.copy();n[:2]=False
        m,d=select_budget(a,n,np.arange(10.),.5,'policy_fallback')
        self.assertEqual(m.sum(),5);self.assertFalse(m[:2].any());self.assertEqual(d['fallback_rejections'],3)

    def test_unreachable_never_resurrects(self):
        m,d=select_budget(np.ones(10,bool),np.zeros(10,bool),np.zeros(10),.9,'policy_fallback')
        self.assertIsNone(m);self.assertEqual(d['reason'],'natural_survivors_below_quota')

    def test_ranker_missing_evidence_unreachable(self):
        a=np.ones(10,bool);v=np.full(10,np.nan);v[0]=1
        self.assertIsNone(select_budget(a,a,v,.5,'rank_only')[0])

    def test_ranker_does_not_silently_prune_unknown(self):
        a=np.ones(5,bool);v=np.array([np.nan,2,1,np.nan,3.])
        m,_=select_budget(a,a,v,.6,'rank_only');np.testing.assert_array_equal(m,[1,0,1,1,0])

    def test_tied_scores_are_seeded_and_deterministic(self):
        a=np.ones(100,bool)
        m,_=select_budget(a,a,np.zeros(100),.5,'rank_only',1)
        np.testing.assert_array_equal(m,select_budget(a,a,np.zeros(100),.5,'rank_only',1)[0])
        self.assertFalse(np.array_equal(m,select_budget(a,a,np.zeros(100),.5,'rank_only',2)[0]))

    def test_random_controls_ignore_original_excluded(self):
        a=np.arange(10)%2==0;m,_=select_budget(a,a,np.zeros(10),.8,'random')
        self.assertEqual(m.sum(),4);self.assertFalse(m[~a].any())

    def test_voxel_duplicates_include_current_birth(self):
        v=voxel_birth_score([[0,0,0]],[[.1,0,0],[1.1,0,0],[1.2,0,0]],1.)
        np.testing.assert_array_equal(v,[1,0,1])

    def test_exact_serialization_bytes_and_roundtrip(self):
        m=np.ones((3,3),np.float32);c=np.tile(np.eye(3,dtype=np.float32),(3,1,1));r=m*.5;o=np.ones(3,np.float32)
        p=pack_parameters(m,c,r,o);self.assertEqual(p.nbytes,52*3)
        for a,b in zip((m,c,r,o),unpack_parameters(p)):np.testing.assert_array_equal(a,b)

    def test_invalid_natural_subset_fails(self):
        with self.assertRaises(ValueError):select_budget(np.zeros(3,bool),np.ones(3,bool),np.zeros(3),.5,'policy_fallback')


class MetricTests(unittest.TestCase):
    def test_rgb_identity_and_known_offset(self):
        a=np.ones((16,16,3),np.float32)*.5
        self.assertAlmostEqual(image_metrics(a,a)['ssim'],1.)
        self.assertAlmostEqual(image_metrics(a+.1,a)['psnr_db'],20.,places=4)

    def test_surface_distance_and_empty_are_not_perfect(self):
        a=np.array([[0,0,0],[1,0,0.]])
        self.assertAlmostEqual(surface_metrics(a,a+[0,0,.1])['chamfer_m'],.1)
        self.assertFalse(surface_metrics(a,np.empty((0,3)))['valid'])

    def test_triangle_samples_stay_on_surface(self):
        v=np.array([[0.,0,2],[1,0,2],[0,1,2]])
        p=sample_mesh(v,[[0,1,2]],1000,0)
        self.assertTrue(np.allclose(p[:,2],2));self.assertTrue((p[:,0]+p[:,1]<=1+1e-12).all())
        np.testing.assert_array_equal(p,sample_mesh(v,[[0,1,2]],1000,0))


if __name__=='__main__':unittest.main()
