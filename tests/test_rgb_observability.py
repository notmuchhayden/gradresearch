import unittest
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rgb_observability import (scalar_grid,bilinear_basis,dct_modes,photo_patch,
    tie_argmin,apply_log_depth,huber,shared_scale_residual,support_status)


class RGBObservabilityTests(unittest.TestCase):
    def test_scalar_grid_and_ties(self):
        g=scalar_grid(); self.assertEqual(len(g),41); self.assertIn(0.,g)
        i,_,n=tie_argmin([0.,0.,1.],[-.01,.01,.2]); self.assertEqual(i,0); self.assertEqual(n,2)

    def test_basis_partition_and_modes(self):
        u=np.array([0.,127.5,511.]);v=np.array([0.,143.5,287.])
        B=bilinear_basis(u,v);np.testing.assert_allclose(B.sum(1),1.,atol=1e-12)
        V=dct_modes();self.assertEqual(V.shape,(15,16))
        np.testing.assert_allclose(V.mean(1),0,atol=1e-12)
        np.testing.assert_allclose(np.mean(V*V,axis=1),1,atol=1e-12)
        np.testing.assert_allclose(V@V.T/16,np.eye(15),atol=1e-12)

    def test_photo_identity_and_constant_patch(self):
        a=np.random.default_rng(7).random((3,3,3));self.assertAlmostEqual(photo_patch(a,a)[0],0.,places=10)
        c=np.ones((3,3,3))*.5; self.assertTrue(np.isfinite(photo_patch(c,c)[0]))

    def test_ray_preserving_depth_and_geometry_control(self):
        y=np.array([[1.,2.,3.]]); z=apply_log_depth(y,np.log(1.2))
        np.testing.assert_allclose(z/y,1.2)
        r=shared_scale_residual([2.,4.],[2.2,4.4]);np.testing.assert_allclose(r,r[0])
        self.assertTrue(np.all(huber(r)>=0))

    def test_support_never_treats_missing_as_success(self):
        self.assertFalse(support_status([0,0,3])['supported'])
        self.assertTrue(support_status([1,2])['supported'])


if __name__=='__main__': unittest.main()
