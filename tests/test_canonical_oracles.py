from pathlib import Path
import sys
import unittest
from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from canonical_oracles import build_canonical_arms,validate_canonical_arms,support_gate


class CanonicalOracleTests(unittest.TestCase):
    def arms(self):
        p=np.array([[1.,0,2.],[0,1,3.]])
        q=np.eye(4);q[:3,3]=[3,4,5]
        gt=np.eye(4);gt[:3,:3]=Rotation.from_euler('z',.4).as_matrix()
        cov=np.repeat(np.diag([.01,.02,.03])[None],2,axis=0)
        return build_canonical_arms(p,p*np.array([.8,.8,1.2]),cov,q,gt,np.array(['a','b']),{'opacity':np.array([.9,.8])})

    def test_rigid_intervention_preserves_local_geometry_and_covariance(self):
        a=self.arms();np.testing.assert_array_equal(a['C00']['local'],a['C01']['local'])
        np.testing.assert_array_equal(a['C00']['local_covariance'],a['C01']['local_covariance'])
        self.assertFalse(np.array_equal(a['C00']['placement'],a['C01']['placement']))

    def test_local_intervention_preserves_placement(self):
        a=self.arms();np.testing.assert_array_equal(a['C00']['placement'],a['C10']['placement'])
        np.testing.assert_array_equal(a['C00']['world_covariance'],a['C10']['world_covariance'])

    def test_ray_control_keeps_predicted_ray_and_reference_Z(self):
        a=self.arms();p=a['C00']['local'];z=a['CZ10']['local']
        np.testing.assert_allclose(p/p[:,2:],z/z[:,2:]);np.testing.assert_array_equal(z[:,2],a['C10']['local'][:,2])

    def test_nonrigid_pose_and_negative_depth_rejected(self):
        with self.assertRaises(ValueError):
            p=np.ones((1,3));q=np.eye(4);q[:3,:3]*=2
            build_canonical_arms(p,p,np.eye(3)[None],q,np.eye(4),np.array(['a']),{})
        a=self.arms();p=a['C00']['local'].copy();p[0,2]=-1
        with self.assertRaises(ValueError):
            build_canonical_arms(p,p,a['C00']['local_covariance'],np.eye(4),np.eye(4),np.array(['a','b']),{})

    def test_detects_arm_dependent_attributes_covariance_and_pose(self):
        for field in ['attribute','covariance','pose']:
            a=self.arms()
            if field=='attribute':a['C10']['attributes']['opacity'][0]=.5
            elif field=='covariance':a['C10']['local_covariance'][0,0,0]*=2
            else:a['C10']['placement'][0,3]+=1
            with self.assertRaises((ValueError,AssertionError)):validate_canonical_arms(a)

    def test_support_gate_counts_unscorable_views_in_denominator(self):
        rows=[dict(common_pixels=2000,reference_pixels=4000)]*3+[dict(common_pixels=0,reference_pixels=4000)]*2
        self.assertFalse(support_gate(rows,1000,.2,.8)['passed'])
        self.assertEqual(support_gate(rows,1000,.2,.8)['registered_views'],5)


if __name__=='__main__':unittest.main()
