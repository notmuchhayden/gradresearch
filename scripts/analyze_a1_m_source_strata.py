#!/usr/bin/env python3
"""Descriptive source coverage supplement; never change G/M maps or decisions."""
from pathlib import Path
import csv
import json
import sys
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src')]
from a1_gm_common import context, cases
from a1_c_common import reference_poses
from gauge_support import sampling_mask
from prepare_e2b_run import save_json, digest


def main():
    spec, out, _, unit = context('M')
    rows = []
    inputs = []
    bins = dict(office2=[0, 2, 4, 8, np.inf], HKairport01=[0, 30, 60, 120, np.inf])
    thresholds = {}
    prior_registration = ROOT / spec['A1_U'] / 'registration.json'
    prior_inputs = json.loads(prior_registration.read_text())['inputs']
    for scene, uc in unit['scenes'].items():
        um = json.loads((ROOT / spec['A1_U'] / 'construction' / scene / 'manifest.json').read_text())
        path = ROOT / uc['baseline'] / uc['dump']
        recorded = digest(path)
        assert recorded in prior_inputs, 'Supplement must reuse the previously frozen A1-U dump'
        inputs.append(recorded)
        dump = torch.load(path, map_location='cpu', weights_only=True)
        keyframes = {k['kf_idx']: k for k in dump['keyframes']}
        _, mapping = reference_poses(scene)
        blocks = []
        for k in um['keyframes']:
            local = np.load(ROOT / k['local_file']['path'])
            reg = np.load(ROOT / uc['oracle_root'] / uc['registry_template'].format(index=k['kf_idx']))
            native = reg['native_mask']
            pixels = local['active_pixel_indices']
            conf = keyframes[k['kf_idx']]['conf'].numpy().reshape(-1)[native]
            frame = 2 * k['frame_id'] if scene == 'office2' else mapping[k['frame_id']]['grid_index']
            if scene == 'office2':
                common = wide = reg['common_mask'][native]
            else:
                common = reg['reference_intersection'][native]
                ref = np.load(ROOT / 'results/A0b_pointmap_pose_factorial/HKairport01/preflight/references' / f'HKairport_released_source_{frame:03d}.npz')
                wide = ref['valid'].ravel()[native]
            blocks.append(dict(kf=np.full(len(pixels), k['kf_idx']), frame=frame,
                               pixels=pixels, confidence=conf, distance=np.linalg.norm(local['y'], axis=1),
                               common=common, wide=wide))
        values = {key: np.concatenate([b[key] for b in blocks]) for key in ['kf', 'confidence', 'distance', 'common', 'wide']}
        q = np.quantile(values['confidence'], [1/3, 2/3])
        thresholds[scene] = q.tolist()
        confbin = np.searchsorted(q, values['confidence'], side='right')
        distancebin = np.searchsorted(bins[scene][1:-1], values['distance'], side='right')
        for name, case in cases('M').items():
            if case['scene'] != scene:
                continue
            valid = values['common'] if 'common' in case['base'] or scene == 'office2' else values['wide']
            if case['kind'] == 'full_mixed':
                selected = np.ones(len(valid), bool)
            else:
                selected = np.concatenate([np.full(len(b['pixels']), b['frame'] >= (200 if scene == 'office2' else 100)) for b in blocks]) & valid
            if case['kind'] == 'source_only':
                selected &= np.concatenate([sampling_mask((288,512), b['frame'], case['pattern'], case['density'], spec['sparsification']['seed']).ravel()[b['pixels']] for b in blocks])
            manifest = json.loads((out / 'maps' / name / 'manifest.json').read_text())
            assert selected.sum() == manifest['count']
            replaced = selected & valid
            assert replaced.sum() == manifest.get('reference_replaced_count', manifest['count'])
            groups = [('all', 'all', np.ones(len(valid), bool))]
            groups += [('source_KF', str(k), values['kf'] == k) for k in np.unique(values['kf'])]
            groups += [('predicted_local_range_m', f'[{lo},{hi})', distancebin == i) for i, (lo, hi) in enumerate(zip(bins[scene][:-1], bins[scene][1:]))]
            groups += [('native_confidence_tertile', str(i+1), confbin == i) for i in range(3)]
            for axis, label, mask in groups:
                n = int((selected & mask).sum())
                nr = int((replaced & mask).sum())
                rows.append(dict(case=name, scene=scene, axis=axis, stratum=label,
                                 native_population=int(mask.sum()), selected=n, local_reference_available=nr,
                                 local_reference_unavailable=n-nr, reference_fraction=nr/n if n else None))
        del dump, keyframes
    folder = out / 'analysis'
    save_json(folder / 'source_strata.json', dict(
        status='DESCRIPTIVE_POSTHOC_SUPPLEMENT',
        interpretation='Source coverage counts only, not rendered-error attribution. Distance uses effective predicted local Euclidean range including reference-unavailable candidates. Confidence tertiles use all native candidates per scene; ties are kept together. No changes to maps, masks, thresholds, primary metrics or decisions.',
        distance_bins={k: [str(x) for x in v] for k,v in bins.items()}, confidence_tertile_thresholds=thresholds,
        inputs=inputs, prior_input_registration=digest(prior_registration), rows=rows))
    with (folder / 'source_strata.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print('Source KF/range/confidence coverage supplement PASS:', len(rows), 'rows')


if __name__ == '__main__':
    main()
