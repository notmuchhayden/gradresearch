import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from rgb_mask_diagnostic import (GRID, sample, warp, diagnose, profile, choose,
                                 context_support, classify_effect)
import a2_o_m_common as common


def tiny_pair(centers=(30, 80), ycenter=100, baseline=1.):
    rng = np.random.default_rng(19)
    K = np.array([[100., 0, 127.5], [0, 100., 127.5], [0, 0, 1.]])
    du = np.tile(np.arange(-1, 2), 3)
    dv = np.repeat(np.arange(-1, 2), 3)
    xy = np.array([np.stack([c+du, ycenter+dv], -1) for c in centers])
    y = np.stack([(xy[..., 0]-127.5)/100*4, (xy[..., 1]-127.5)/100*4,
                  np.full(xy.shape[:2], 4.)], -1)
    qe = np.eye(4)
    qe[0, 3] = baseline
    p = dict(points=y, rgb=rng.random(y.shape), xy=xy,
             centers=xy[:, 4, 1]*512+xy[:, 4, 0],
             primary_parallax=np.ones(len(y), bool), ray_grid_match=np.ones(len(y), bool))
    return dict(patches=p, source_Q=np.eye(4), evidence_Q=qe, K=K,
                evidence_rgb=rng.random((256, 256, 3)),
                evidence_z=np.full((256, 256), 4.), evidence_valid=np.ones((256, 256), bool))


class RGBMaskDiagnosticTests(unittest.TestCase):
    def test_strict_top_boundary_legacy_discrepancy(self):
        _, inside, old, _ = sample(np.ones((8, 8, 3)), np.array([[[2., -1.]]]))
        self.assertFalse(inside.item())
        self.assertTrue(old.item())

    def test_bad_candidate_does_not_change_candidate_denominators(self):
        p = tiny_pair()
        d = diagnose(p)
        self.assertTrue(d['R1']['eligible'][0])
        self.assertFalse(d['R1']['mask'][0])
        self.assertTrue(d['R1']['mask'][1])
        scores = profile(p, d['R1']['mask'])
        self.assertEqual(len(scores['loss']), 41)
        # A caller cannot evaluate the invalid baseline-only denominator.
        with self.assertRaises(ValueError):
            profile(p, d['R1']['eligible'])

    def test_r1_does_not_gate_by_predicted_depth_agreement(self):
        p = tiny_pair(centers=(80, 100), baseline=.4)
        d = diagnose(p)
        self.assertEqual(d['L2']['retained'], 0)
        self.assertEqual(d['R1']['retained'], 2)

    def test_pure_rotation_raw_profile_is_scale_invariant(self):
        p = tiny_pair(centers=(80, 100), baseline=0)
        p['evidence_Q'][:3, :3] = np.array([[1., 0, 0], [0, np.cos(.01), -np.sin(.01)],
                                           [0, np.sin(.01), np.cos(.01)]])
        scores = profile(p, diagnose(p)['R1']['mask'])
        self.assertLess(float(np.ptp(scores['loss'])), 1e-8)

    def test_zero_and_tie_use_selected_loss(self):
        self.assertEqual(len(GRID), 41)
        self.assertEqual(choose(np.ones(41))['a'], 0.)
        loss = np.ones(41)
        loss[19], loss[21] = 0., 5e-9
        chosen = choose(loss)
        self.assertEqual(chosen['a'], -.01)
        self.assertEqual(chosen['loss'], loss[19])
        with self.assertRaises(ValueError):
            choose([float('nan')]*41)

    def test_photo_only_gain_cannot_be_geometry_success(self):
        self.assertEqual(classify_effect(.02, .1, .2), 'PHOTO_GEOMETRY_MISMATCH')
        self.assertEqual(classify_effect(.02, .1, .05, supported=False), 'INSUFFICIENT_SUPPORT')
        self.assertEqual(classify_effect(0., .1, .05), 'NO_RESOLVED_PHOTO_GAIN')

    def test_unsupported_kf_remains_in_scene_denominator(self):
        records = [dict(source_kf=k, pool='rgb_fit', support=True) for k in (1, 2) for _ in range(2)]
        s = context_support(records, {1: 10, 2: 10, 3: 100})
        self.assertFalse(s['passed'])
        self.assertEqual(s['denominator'], 3)
        self.assertAlmostEqual(s['candidate_fraction'], 1/6)

    def test_reference_and_holdout_mutation_do_not_change_fit(self):
        p = tiny_pair(centers=(80, 100), baseline=.4)
        def fit_only(bundle):
            fit = bundle['fit']
            d = diagnose(fit)
            return d['R1']['mask_sha256'], choose(profile(fit, d['R1']['mask'])['loss'])
        b = dict(fit=p, audit=copy.deepcopy(p), target=np.zeros(5), reference=np.zeros(5))
        before = fit_only(b)
        b['audit']['evidence_rgb'][:] = 0
        b['target'][:] = 100
        b['reference'][:] = 100
        b['fit']['ref_z'] = np.ones(5)*100
        b['fit']['strict'] = np.zeros(5, bool)
        self.assertEqual(before, fit_only(b))

    def test_real_native_adapter_never_accesses_reference_arrays(self):
        cls = np.lib.npyio.NpzFile if hasattr(np.lib.npyio, 'NpzFile') else np.lib._npyio_impl.NpzFile
        original = cls.__getitem__
        reads = []
        allowed = {'y', 'rigid_Q', 'active_pixel_indices', 'native_mask', 'active_candidate_ids'}
        def guarded(obj, key):
            reads.append(key)
            if key not in allowed:
                raise AssertionError('forbidden reference NPZ access: '+str(key))
            return original(obj, key)
        with patch.object(cls, '__getitem__', guarded):
            rows = common.native_rows('office2')
        self.assertEqual(len(rows), 11)
        self.assertTrue(reads)
        self.assertTrue(set(reads) <= allowed)

    def test_checkerboard_patch_does_not_cross_guard(self):
        h, w = 288, 512
        v, u = np.indices((h, w))
        y = np.stack([(u-255.5)/100*4, (v-143.5)/100*4, np.full((h, w), 4.)], -1)
        rgb = np.random.default_rng(0).random((h, w, 3))
        seen = []
        for fold in (0, 1):
            p = common.legacy().native_patch_samples(y.reshape(-1, 3), np.arange(h*w), rgb, fold=fold, stride=2)
            xy = p['xy']
            self.assertTrue(np.all(xy[..., 0]//64 == xy[:, 4:5, 0]//64))
            self.assertTrue(np.all(xy[..., 1]//36 == xy[:, 4:5, 1]//36))
            self.assertTrue(np.all(((xy[:, 4, 0]//64+xy[:, 4, 1]//36) % 2) == fold))
            seen.append(set(p['centers'].tolist()))
        self.assertFalse(seen[0] & seen[1])

    def test_map_correction_keeps_camera_translation_fixed(self):
        y = np.array([[1., 2., 4.]])
        q = np.eye(4)
        q[:3, 3] = [10., 20., 30.]
        a = .1
        corrected = np.exp(a)*y @ q[:3, :3].T+q[:3, 3]
        wrong = (y @ q[:3, :3].T+q[:3, 3])*np.exp(a)
        self.assertGreater(np.max(np.abs(corrected-wrong)), 1.)
        np.testing.assert_allclose((corrected-q[:3, 3])/y, np.exp(a))


if __name__ == '__main__':
    unittest.main()
