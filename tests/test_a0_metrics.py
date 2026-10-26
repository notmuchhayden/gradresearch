from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from a0_metrics import common_covered_metrics,depth_state,factorial


class A0MetricsTests(unittest.TestCase):
    def test_hiding_wrong_surface_cannot_improve_correct_coverage(self):
        gt=np.array([[1.,2.]])
        valid=np.ones_like(gt,dtype=bool)
        _,_,_,full=depth_state(np.array([[1.,1.]]),np.ones_like(gt),gt,valid)
        _,_,_,deleted=depth_state(np.array([[1.,0.]]),np.array([[1.,0.]]),gt,valid)
        self.assertEqual(deleted['mae_m'],0)
        self.assertEqual(full['correct_coverage'],deleted['correct_coverage'])
        self.assertLess(deleted['coverage'],full['coverage'])

    def test_shared_mask_uses_exact_same_gt_pixels_for_every_arm(self):
        gt=np.ones((2,2));valid=np.ones((2,2),bool)
        p={'a':gt.copy(),'b':gt+1};c={'a':valid.copy(),'b':valid.copy()};c['b'][0,0]=False
        mask,m=common_covered_metrics(p,c,gt,valid)
        self.assertEqual(mask.sum(),3)
        self.assertEqual(m['a']['common_pixels'],m['b']['common_pixels'])
        self.assertEqual(m['a']['mae_m'],0);self.assertEqual(m['b']['mae_m'],1)

    def test_weighted_depth_and_invalid_gt_are_not_range(self):
        gt=np.array([[2.,0.]],np.float32);valid=gt>0
        pred,_,_,m=depth_state(np.array([[1.,100.]],np.float32),np.array([[.5,1.]],np.float32),gt,valid)
        self.assertEqual(pred[0,0],2);self.assertEqual(m['gt_pixels'],1);self.assertEqual(m['mae_m'],0)

    def test_empty_shared_support_is_reported_missing(self):
        gt=np.ones((1,1));valid=np.ones((1,1),bool)
        _,m=common_covered_metrics({'a':gt},{'a':np.zeros((1,1),bool)},gt,valid)
        self.assertEqual(m['a']['common_pixels'],0);self.assertIsNone(m['a']['mae_m'])

    def test_known_interaction_sign_and_nonadditivity(self):
        e=factorial({'A00':4.,'A10':1.,'A01':1.,'A11':0.})
        self.assertEqual(e['delta_local'],3);self.assertEqual(e['delta_placement'],3)
        self.assertEqual(e['interaction'],2);self.assertEqual(e['joint_improvement'],4)

    def test_negative_oracle_gain_is_retained(self):
        e=factorial({'A00':1.,'A10':2.,'A01':.5,'A11':1.5})
        self.assertEqual(e['delta_local'],-1);self.assertEqual(e['delta_placement'],.5)
        self.assertEqual(e['interaction'],0)


if __name__=='__main__':unittest.main()
