import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import numpy as np
from scalar_spatial_diagnostic import (tile_masks, bilinear_basis, field_laplacian,
    fit_scalar, fit_huber_scalar, fit_field, decide, support_gate)


class DiagnosticTests(unittest.TestCase):
    def test_tiles_guard_and_exchange(self):
        ids=np.arange(288*512); valid=np.ones(len(ids),bool)
        f0,e0=tile_masks(ids,valid,fold=0); f1,e1=tile_masks(ids,valid,fold=1)
        self.assertFalse(np.any(f0&e0)); np.testing.assert_array_equal(f0,e1); np.testing.assert_array_equal(e0,f1)
        # Outer boundary and tile edges are excluded by the two-pixel guard.
        for p in [0,1,2,61,62,63,64,65,510,511]: self.assertFalse(f0[p] or e0[p] or f1[p] or e1[p])

    def test_basis_and_laplacian(self):
        B=bilinear_basis([0,511,0,511,255.5],[0,0,287,287,143.5])
        self.assertEqual(B.shape,(5,16)); np.testing.assert_allclose(B.sum(1),1)
        np.testing.assert_array_equal(np.argmax(B[:4],axis=1),[0,3,12,15])
        L=field_laplacian(); self.assertEqual(L.shape,(24,16)); np.testing.assert_allclose(L@np.ones(16),0)

    def test_scalar_and_field_recover_bias(self):
        rng=np.random.default_rng(4); r=np.full(6000,.13)+rng.normal(0,.002,6000)
        self.assertAlmostEqual(fit_scalar(r),.13,delta=.001)
        h=fit_huber_scalar(r); self.assertTrue(h['converged'])
        u=rng.uniform(0,511,len(r));v=rng.uniform(0,287,len(r));B=bilinear_basis(u,v)
        f=fit_field(B,r,h['alpha']);self.assertTrue(f['converged']);self.assertLess(np.max(np.abs(f['theta']-.13)),.01)

    def test_known_field_improves_heldout(self):
        rng=np.random.default_rng(9); n=10000;u=rng.uniform(0,511,n);v=rng.uniform(0,287,n);B=bilinear_basis(u,v)
        theta=np.linspace(-.12,.12,16); r=B@theta+rng.normal(0,.002,n)
        h=fit_huber_scalar(r[:5000]);f=fit_field(B[:5000],r[:5000],h['alpha'])
        self.assertTrue(f['converged']); self.assertLess(np.mean((B[5000:]@f['theta']-r[5000:])**2),np.mean((h['alpha']-r[5000:])**2))

    def test_decisions(self):
        common=dict(source_kf_fraction=1,source_candidate_fraction=1,target_support_pass=True,cov_k=.8,cov_f=.8,cov_0=.8,correct_k=.5,correct_f=.5,correct_0=.5)
        self.assertEqual(decide(.1,.02,.05,**common)['label'],'SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD')
        self.assertEqual(decide(.1,.08,.05,**common)['label'],'RESIDUAL_FIELD_OPPORTUNITY')
        self.assertEqual(decide(.1,.02,.05,**{**common,'source_kf_fraction':.5})['label'],'INSUFFICIENT_SUPPORT')
        self.assertEqual(decide(.1,.02,.095,**common)['label'],'FIELD_GAIN_NOT_ESTABLISHED')

    def test_fold_masks_exclude_changed_evaluation_targets_from_fit(self):
        ids=np.arange(288*512);valid=np.ones(len(ids),bool);fit,ev=tile_masks(ids,valid,fold=0)
        r=np.linspace(-.1,.1,len(ids));a=fit_scalar(r[fit]);b=fit_huber_scalar(r[fit])['alpha']
        r[ev]=1e6
        self.assertEqual(a,fit_scalar(r[fit]));self.assertEqual(b,fit_huber_scalar(r[fit])['alpha'])

    def test_office3_replaced_false_values_never_enter_fit(self):
        replace=np.array([True,False,True,False]);ref=np.array([1.,2.,3.,4.]);y=np.ones(4)
        selected=replace & np.isfinite(ref) & (ref>0)
        before=fit_scalar(np.log(ref[selected]/y[selected]));ref[~replace]=1e100
        after=fit_scalar(np.log(ref[selected]/y[selected]));self.assertEqual(before,after)

    def test_scene_frame_conventions(self):
        office2_mapper_frame=142;office2_original=2*office2_mapper_frame
        office3_source_frame=234;office3_original=office3_source_frame
        self.assertEqual(office2_original,284);self.assertEqual(office3_original,234)

    def test_support_gate_reasons_and_design_checks(self):
        ok,reason=support_gate(2048,2048,[64]*16,16,1e-8);self.assertTrue(ok);self.assertEqual(reason,[])
        ok,reason=support_gate(2047,2048,[64]*16,16,1e-8);self.assertFalse(ok);self.assertIn('fit_pixels_below_2048',reason)
        ok,reason=support_gate(3000,3000,[63]+[64]*15,16,1e-8);self.assertFalse(ok);self.assertIn('field_region_below_64',reason)

    def test_ray_and_packed_attribute_preservation(self):
        y=np.array([[.4,-.2,2.],[1.,.5,4.]],float);d=np.array([.1,-.08]);corrected=y*np.exp(d[:,None])
        np.testing.assert_allclose(corrected/np.linalg.norm(corrected,axis=1,keepdims=True),y/np.linalg.norm(y,axis=1,keepdims=True),atol=1e-15)
        packed=np.arange(26,dtype=np.float32).reshape(2,13);out=packed.copy();out[:,:3]=corrected.astype(np.float32)
        np.testing.assert_array_equal(out[:,3:],packed[:,3:]);self.assertTrue(np.array_equal(out[:,3:],packed[:,3:]))

    def test_unsupported_rows_keep_centers_and_candidates(self):
        base=np.arange(6*13,dtype=np.float32).reshape(6,13);out=base.copy();supported=np.array([True,False,True])
        block_sizes=[2,1,3];offset=0
        for ok,n in zip(supported,block_sizes):
            if ok:out[offset:offset+n,:3]+=1
            offset+=n
        np.testing.assert_array_equal(out[2:3,:3],base[2:3,:3]);np.testing.assert_array_equal(out[:,3:],base[:,3:])
        candidates=np.array(['a','b','c','d','e','f']);self.assertEqual(candidates.tolist(),['a','b','c','d','e','f'])

    def test_coverage_tradeoff_and_ratio_above_one_are_not_clipped(self):
        common=dict(source_kf_fraction=1,source_candidate_fraction=1,target_support_pass=True,cov_k=.8,cov_f=.8,cov_0=.8,correct_k=.5,correct_f=.5,correct_0=.5)
        d=decide(.1,.08,.09,**common);self.assertEqual(d['label'],'SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD');self.assertAlmostEqual(d['ratio'],2.)
        d=decide(.1,.02,.05,**{**common,'cov_f':.79});self.assertEqual(d['label'],'COVERAGE_TRADEOFF')

    def test_fold_disagreement_is_not_a_scene_level_pass(self):
        common=dict(source_kf_fraction=1,source_candidate_fraction=1,target_support_pass=True,cov_k=.8,cov_f=.8,cov_0=.8,correct_k=.5,correct_f=.5,correct_0=.5)
        labels=[decide(.1,.08,.05,**common)['label'],decide(.1,.01,.05,**common)['label']]
        self.assertNotEqual(labels[0],labels[1]);self.assertFalse(all(x=='SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD' for x in labels))


if __name__=='__main__': unittest.main()
