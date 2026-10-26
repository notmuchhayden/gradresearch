from pathlib import Path
import sys
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gauge_support import orientation_prefix_gauge,change_canonical_gauge,sampling_mask
from pointmap_contract import transform_points,transform_covariance


class GaugeSupportTests(unittest.TestCase):
    def poses(self):
        a=np.repeat(np.eye(4)[None],8,axis=0);a[:,:3,3]=np.column_stack([np.arange(8),np.arange(8)**2*.1,np.zeros(8)])
        R=Rotation.from_euler('xyz',[.2,-.1,.3]).as_matrix();G=np.eye(4);G[:3,:3]=2*R;G[:3,3]=[3,4,5]
        b=a.copy();b[:,:3,:3]=R;b[:,:3,3]=transform_points(a[:,:3,3],G)
        return a,b,G

    def test_prefix_gauge_recovers_known_similarity(self):
        a,b,G=self.poses();g,m=orientation_prefix_gauge(a,b,np.arange(8),5)
        np.testing.assert_allclose(g,G,atol=1e-12);self.assertEqual(m['prefix_ids'],list(range(5)))

    def test_heldout_pose_values_cannot_change_fitted_gauge(self):
        a,b,G=self.poses();b[5:,:3,3]+=1e6;b[5:,:3,:3]=Rotation.from_euler('x',2).as_matrix()
        g,_=orientation_prefix_gauge(a,b,np.arange(8),5);np.testing.assert_allclose(g,G,atol=1e-12)

    def test_canonical_change_matches_world_similarity(self):
        _,_,G=self.poses();p=np.array([[1.,2,3.],[2,1,4.]]);cov=np.repeat(np.diag([.1,.2,.3])[None],2,axis=0);Q=np.eye(4);Q[:3,3]=[3,-4,2]
        y,s,q=change_canonical_gauge(p,cov,Q,G)
        np.testing.assert_allclose(transform_points(y,q),transform_points(transform_points(p,Q),G),atol=1e-12)
        np.testing.assert_allclose(transform_covariance(s,q),transform_covariance(transform_covariance(cov,Q),G),atol=1e-12)

    def test_masks_are_deterministic_nested_and_frame_indexed(self):
        for pat in ['uniform_hash','scan_rows']:
            low=sampling_mask((288,512),201,pat,.01);high=sampling_mask((288,512),201,pat,.1)
            np.testing.assert_array_equal(low,sampling_mask((288,512),201,pat,.01));self.assertFalse(np.any(low&~high))
            self.assertFalse(np.array_equal(low,sampling_mask((288,512),203,pat,.01)))

    def test_scan_mask_has_whole_rows_and_no_depth_input(self):
        x=sampling_mask((288,512),201,'scan_rows',.1)
        self.assertTrue(np.all(np.sum(x,axis=1)%512==0));self.assertGreater(x.sum(),0)

    def test_degenerate_prefix_and_bad_sampling_are_rejected(self):
        a,b,_=self.poses();a[:,:3,3]=0
        with self.assertRaises(ValueError):orientation_prefix_gauge(a,b,np.arange(8),5)
        for density in [0,-.1,2]:
            with self.assertRaises(ValueError):sampling_mask((10,10),0,'uniform_hash',density)


if __name__=='__main__':unittest.main()
