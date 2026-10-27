#!/usr/bin/env python3
"""Registered, staged A2-O-M execution. Early stops are complete diagnoses."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
import cv2
import numpy as np

from a2_o_m_common import (OLD, OUT, U, ROOT, native_rows, init_scene, load_pairs,
                           pair_bundle, legacy, dump, write_csv, sha, digest, DATA)
from rgb_mask_diagnostic import (GRID, VARIANTS, diagnose, profile, choose,
                                 mask_sha, subset_pair, context_support)

CFG = ROOT/'configs/a2_o_m_protocol.json'
PLAN = ROOT/'docs/experiments/A2_O_M_execution_plan.md'
CODE = [CFG, PLAN, ROOT/'src/rgb_mask_diagnostic.py',
        ROOT/'scripts/a2_o_m_common.py', ROOT/'scripts/a2_o_m_controls.py',
        ROOT/'scripts/run_a2_o_m.py', ROOT/'tests/test_rgb_mask_diagnostic.py']


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def require_registration():
    reg = read(OUT/'registration.json')
    for item in reg['code']:
        if item['path'] == str(PLAN.relative_to(ROOT)):
            continue  # The original plan is immutable in registered_code; live execution notes may follow.
        if sha(ROOT/item['path']) != item['sha256']:
            raise RuntimeError(f"registered code mismatch: {item['path']}; preserve and amend before rerun")
    return reg


def preflight():
    import torch
    torch.set_num_threads(2)
    expected = read(OLD.parent/'preflight.json')['scenes']['office2']
    archived_reg = read(OLD/'registration.json')
    archive_checks = []
    for item in archived_reg['code']:
        p = OLD/'registered_code'/item['path']
        assert sha(p) == item['sha256'], p
        archive_checks.append(digest(p))
    data = init_scene('office2')
    assert len(data) == 11 and sum(len(k['y']) for k in data.values()) == 1545979
    pairs, pair_path = load_pairs('office2')
    baseline = ROOT/'results/A0_pointmap_pose_factorial/office2/baseline'
    snap_path = baseline/'audit/snapshots/input000499_final.pt'
    assert sha(snap_path) == expected['final_snapshot']['sha256']
    snap = torch.load(snap_path, map_location='cpu', weights_only=True)
    assert snap['pose_revision'] == 520
    meta = {int(m['kf_idx']): m for m in snap['metadata']}
    inputs = [digest(pair_path), digest(OLD/'office2/selected_parameters.json'),
              digest(OLD/'office2/selection_seal.json'), digest(snap_path),
              digest(U/'manifest.json'), digest(ROOT/'data/N2/Replica/cam_params.json'),
              digest(ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json')]
    prior_locals = {item['path']: item['sha256'] for item in expected['local_files']}
    provenance = {}
    for i, k in data.items():
        assert sha(k['local_path']) == prior_locals[str(k['local_path'].relative_to(ROOT))]
        m = meta[i]
        assert 2*int(m['frame_id']) == k['original_frame']
        assert m['candidate_event'] == k['candidate_event']
        assert m['fused']['status'] in ('known', 'traced')
        raw_path = baseline/'exports/raw_pairs'/f"{k['candidate_event']}.pt"
        raw = torch.load(raw_path, map_location='cpu', weights_only=True)
        assert 2*int(raw['anchor_frame_id']) == k['original_frame']
        provenance[i] = set(map(int, raw['source_image_ids']))
        del raw
        for p in (k['local_path'], k['registry_path'], raw_path,
                  ROOT/f"data/N2/Replica/office2/results/frame{k['original_frame']:06d}.jpg"):
            inputs.append(digest(p))
    for s in range(1, 11):
        good = [r for r in pairs if r['source_kf'] == s and r['status'] == 'PROVENANCE_DISJOINT']
        good.sort(key=lambda r: (r['evidence_frame'], r['evidence_kf']))
        for pos, row in enumerate(good):
            assert provenance[s].isdisjoint(provenance[row['evidence_kf']])
            assert set(json.loads(row['source_images'])) == provenance[s]
            assert set(json.loads(row['evidence_images'])) == provenance[row['evidence_kf']]
            assert row['pool'] == ('rgb_fit' if pos % 2 == 0 else 'rgb_audit')
            assert row['final_pose_revision'] == row['evidence_pose_revision'] == 520
    result = dict(status='PASS', at=now(), inputs=inputs, archived_code=archive_checks,
                  native_keyframes=11, native_candidates=1545979, post_prefix_keyframes=10,
                  native_post_prefix_candidates=sum(len(k['y']) for k in data.values() if k['original_frame'] >= 200),
                  final_pose_revision=520, pair_rows=len(pairs),
                  provenance_pairs=sum(r['status'] == 'PROVENANCE_DISJOINT' for r in pairs),
                  reference_arrays_accessed=False,
                  colocated_registry_arrays_read=['native_mask', 'active_candidate_ids'],
                  whole_file_checksums_include_uninterpreted_reference_bytes=True,
                  office3_new_data_accessed=False, office4_accessed=False, hk_accessed=False,
                  environment=dict(python=sys.version, torch=torch.__version__,
                                   cuda_available=torch.cuda.is_available(), cv2=cv2.__version__,
                                   torch_threads=2, opencv_threads=cv2.getNumThreads()))
    dump(OUT/'preflight.json', result)
    dump(OUT/'input_manifest.json', dict(inputs=inputs, legacy_code=archive_checks))
    print(json.dumps({k: v for k, v in result.items() if k not in ('inputs', 'archived_code')}, ensure_ascii=False))


def register():
    if (OUT/'registration.json').exists():
        raise RuntimeError('registration exists; no overwrite')
    pre = read(OUT/'preflight.json')
    assert pre['status'] == 'PASS'
    code = [digest(p) for p in CODE]
    for item in code:
        src = ROOT/item['path']
        dst = OUT/'registered_code'/item['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    spec = read(CFG)['controls']
    dump(OUT/'controls/specification.json', spec)
    dump(OUT/'registration.json', dict(status='REGISTERED_BEFORE_M0_AND_CONTROLS', at=now(),
                                      code=code, preflight=digest(OUT/'preflight.json'),
                                      inputs=digest(OUT/'input_manifest.json'),
                                      controls_spec=digest(OUT/'controls/specification.json'),
                                      protocol_revision='R1', scientific_revision_count=1))
    print('REGISTERED_BEFORE_M0_AND_CONTROLS')


def stored_legacy():
    old = read(OLD/'office2/selected_parameters.json')
    out = {}
    for g, folds in old['selections'].items():
        for f, kfs in folds.items():
            for k, s in kfs.items():
                for r in s.get('fit_support', {}).get('reasons', []):
                    out[g, int(f), int(k), r['evidence_kf']] = (r['eligible'], r['retained'])
    assert len(out) == 160
    return out


def percentile(x):
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    return np.quantile(x, [0, .25, .5, .75, 1]).tolist() if len(x) else []


def support_audit(scene):
    require_registration()
    if scene != 'office2':
        raise RuntimeError('M0 is office2 only; office3 must pass development gate first')
    root = OUT/scene
    root.mkdir(exist_ok=True)
    if (root/'support_summary.json').exists():
        raise RuntimeError('support-audit complete; use verify rather than overwrite')
    native = init_scene(scene)
    pairs, pair_path = load_pairs(scene)
    shutil.copy2(pair_path, root/'pair_manifest.csv')
    pairs = [r for r in pairs if r['status'] == 'PROVENANCE_DISJOINT']
    expected = stored_legacy()
    old = legacy()
    candidates, modes = old.scalar_candidates(), old.dct_modes()
    rows, waterfall, manifest, candidate_rows = [], [], [], []
    stats = []
    native_counts = {i: len(k['y']) for i, k in native.items() if k['original_frame'] >= 200}
    start = time.monotonic()
    for gauge in ('position', 'orientation'):
        for fold in (0, 1):
            for pos, row in enumerate(pairs):
                s, e, pool = row['source_kf'], row['evidence_kf'], row['pool']
                # Audit uses opposite tiles; legacy stored profiles were fit-only.
                actual_fold = fold if pool == 'rgb_fit' else 1-fold
                pair = pair_bundle(scene, row, gauge, actual_fold)
                d = diagnose(pair)
                p = pair['patches']
                centers = p['centers']
                stride4 = ((centers % 512) % 4 == 0) & ((centers//512) % 4 == 0)
                if pool == 'rgb_fit':
                    measured = (d['L4']['eligible_count'], d['L4']['retained'])
                    assert measured == expected[gauge, fold, s, e], (gauge, fold, s, e, measured)
                    # Execute the actual registered primitive, including legacy bounds.
                    original_pair = subset_pair(pair, np.flatnonzero(stride4))
                    original_pair['patches']['texture'] &= original_pair['patches']['ray_grid_match']
                    parity = old.evaluate_pair_candidates(original_pair, candidates, modes)
                    assert parity['eligible'] == measured[0]
                    assert parity.get('retained', 0) == measured[1]
                    assert np.array_equal(parity['mask'], d['L4']['mask'][stride4])
                tag = f'{gauge}_fold{fold}_k{s:02d}_e{e:02d}_{pool}'
                path = root/'masks'/f'{tag}.npz'
                path.parent.mkdir(exist_ok=True)
                flags = d['flags']
                arrays = dict(centers=centers, xy=p['xy'], grid=GRID,
                              flags=np.packbits(np.stack(list(flags.values())), axis=1),
                              flag_names=np.array(list(flags)),
                              cv_new=np.packbits(d['cv_new'], axis=1),
                              cv_old=np.packbits(d['cv_old'], axis=1))
                for variant in VARIANTS:
                    arrays['eligible_'+variant] = np.packbits(d[variant]['eligible'])
                    arrays['mask_'+variant] = np.packbits(d[variant]['mask'])
                np.savez_compressed(path, **arrays)
                manifest.append(dict(file=str(path.relative_to(OUT)), sha256=sha(path),
                                     gauge=gauge, fold=fold, source_kf=s, evidence_kf=e, pool=pool,
                                     centers=len(centers), mask_R1_sha256=d['R1']['mask_sha256']))
                for variant, (stride, agreement) in VARIANTS.items():
                    result = d[variant]
                    base = dict(gauge=gauge, fold=fold, source_kf=s, evidence_kf=e, pool=pool,
                                variant=variant, eligible=result['eligible_count'],
                                retained=result['retained'], support=result['support'],
                                retention=result['retained']/max(1, result['eligible_count']),
                                mask_sha256=result['mask_sha256'], mask_file=str(path.relative_to(OUT)))
                    rows.append(base)
                    m = ((centers % 512) % stride == 0) & ((centers//512) % stride == 0)
                    stages = [('sampled_3x3', m.copy())]
                    for key in ('source_edge', 'source_texture', 'ray', 'parallax',
                                'legacy_bounds' if agreement else 'bounds', 'evidence'):
                        m &= flags[key]
                        stages.append((key, m.copy()))
                    if agreement:
                        m &= flags['agreement']
                        stages.append(('agreement', m.copy()))
                    m &= flags['warped_texture']
                    stages.append(('eligible', m.copy()))
                    assert int(m.sum()) == base['eligible']
                    stages.append(('all_41_common', result['mask']))
                    wr = dict(base)
                    wr.update({name: int(mask.sum()) for name, mask in stages})
                    wr['unique_source_patch_pixels'] = len(np.unique(p['xy'][result['mask'], :, 1]*512+p['xy'][result['mask'], :, 0]))
                    wr['occupied_8x8_tiles'] = len(np.unique((centers[result['mask']]//512//36)*8+(centers[result['mask']] % 512//64)))
                    waterfall.append(wr)
                    for ci, a in enumerate(GRID):
                        candidate_rows.append(dict(gauge=gauge, fold=fold, source_kf=s, evidence_kf=e,
                                                   pool=pool, variant=variant, a=float(a),
                                                   candidate_retained=result['candidate_retained'][ci],
                                                   cumulative_retained=result['intersection_progress'][ci]))
                stats.append(dict(gauge=gauge, fold=fold, source_kf=s, evidence_kf=e, pool=pool,
                                  ray_error_quantiles=percentile(p['ray_error']),
                                  source_std_quantiles=percentile((p['rgb'] @ np.array([.299, .587, .114])).std(1)),
                                  parallax_bins=np.histogram(p['parallax_deg'], [0, .25, 1, 3, np.inf])[0].tolist(),
                                  signed_z_residual_quantiles=percentile(d['signed_residual']),
                                  legacy_bounds_accepted_negative_y=int((flags['legacy_bounds'] & ~flags['bounds']).sum()),
                                  camera_baseline=pair['camera_baseline'],
                                  baseline_over_median_depth=pair['camera_baseline']/float(np.median(p['points'][:, 4, 2])),
                                  **pair['raster_stats']))
                if (pos+1) % 12 == 0:
                    print(json.dumps(dict(stage='M0', gauge=gauge, fold=fold, completed=pos+1,
                                          total=len(pairs), elapsed_s=round(time.monotonic()-start, 1))), flush=True)
    write_csv(root/'support_ablations.csv', rows)
    write_csv(root/'support_waterfall.csv', waterfall)
    write_csv(root/'candidate_intersections.csv', candidate_rows)
    dump(root/'mask_manifest.json', manifest)
    dump(root/'gate_diagnostics.json', stats)
    contexts = {}
    for variant in VARIANTS:
        contexts[variant] = {}
        for gauge in ('position', 'orientation'):
            for fold in (0, 1):
                rr = [r for r in rows if r['gauge'] == gauge and r['fold'] == fold and r['variant'] == variant]
                contexts[variant][f'{gauge}_fold{fold}'] = {
                    pool: context_support(rr, native_counts, pool=pool) for pool in ('rgb_fit', 'rgb_audit')}
    summary = dict(status='PASS_LEGACY_REPRODUCTION', at=now(),
                   legacy_fit_records=160, legacy_max_eligible=171, legacy_max_retained=0,
                   contexts=contexts, elapsed_s=time.monotonic()-start,
                   reference_arrays_accessed=False, photometric_profiles_computed=False,
                   mask_manifest=digest(root/'mask_manifest.json'),
                   registration=digest(OUT/'registration.json'))
    dump(root/'support_summary.json', summary)
    dump(OUT/'legacy_result_correction_audit.json', dict(original_document=digest(ROOT/'docs/experiments/A2_O_rgb_observability_results.md'),
          original_statement='공통 mask 유지 후 pair당 최대 171개',
          corrected_statement='eligible 최대 171개; retained 최대 0개',
          evidence=digest(root/'support_ablations.csv'), original_document_modified=False))
    print(json.dumps(summary, ensure_ascii=False))


def controls():
    require_registration()
    if (OUT/'controls/results.json').exists():
        raise RuntimeError('controls already executed; preserve output before implementation amendment')
    from a2_o_m_controls import run_controls
    result = run_controls(read(OUT/'controls/specification.json'), OUT/'controls')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))


def seal_r1():
    require_registration()
    m0, m1 = read(OUT/'office2/support_summary.json'), read(OUT/'controls/results.json')
    passed = m0['status'] == 'PASS_LEGACY_REPRODUCTION' and m1['status'] == 'PASS'
    dump(OUT/'r1_seal.json', dict(status='PASS' if passed else 'STOP_CONTROL_FAILURE', at=now(),
                                 registration=digest(OUT/'registration.json'),
                                 support=digest(OUT/'office2/support_summary.json'),
                                 controls=digest(OUT/'controls/results.json')))
    print('R1_SEALED' if passed else 'STOP_CONTROL_FAILURE')


def profile_scene(scene):
    require_registration()
    assert read(OUT/'r1_seal.json')['status'] == 'PASS', 'M1 must pass'
    if scene != 'office2':
        raise RuntimeError('office3 requires a verified successful development seal')
    root = OUT/scene
    if (root/'selected_parameters.json').exists():
        raise RuntimeError('selection exists; no overwrite')
    data = init_scene(scene)
    pairs, _ = load_pairs(scene)
    pair_lookup = {(r['source_kf'], r['evidence_kf']): r for r in pairs if r['status'] == 'PROVENANCE_DISJOINT'}
    masks = read(root/'mask_manifest.json')
    supports = read(root/'support_summary.json')['contexts']['R1']
    with (root/'support_ablations.csv').open() as f:
        counts = list(csv.DictReader(f))
    supported_pairs = {(r['gauge'], int(r['fold']), int(r['source_kf']), int(r['evidence_kf']))
                       for r in counts if r['variant'] == 'R1' and r['pool'] == 'rgb_fit' and r['support'] == 'True'}
    selections, profile_rows = {}, []
    for gauge in ('position', 'orientation'):
        for fold in (0, 1):
            key = f'{gauge}_fold{fold}'
            kf_profiles, selected = {}, {}
            fit = supports[key]['rgb_fit']
            for kf in range(1, 11):
                if kf not in fit['supported_kfs']:
                    selected[str(kf)] = dict(support=False, a=0., status='INSUFFICIENT_FIT_SUPPORT')
                    continue
                pp = []
                for m in masks:
                    if (m['gauge'], m['fold'], m['source_kf'], m['evidence_kf']) not in supported_pairs or m['gauge'] != gauge or m['fold'] != fold or m['source_kf'] != kf or m['pool'] != 'rgb_fit':
                        continue
                    path = OUT/m['file']
                    assert sha(path) == m['sha256']
                    with np.load(path) as a:
                        centers = a['centers']
                        mask = np.unpackbits(a['mask_R1'])[:len(centers)].astype(bool)
                    pair = pair_bundle(scene, pair_lookup[kf, m['evidence_kf']], gauge, fold)
                    assert np.array_equal(pair['patches']['centers'], centers)
                    scores = profile(pair, mask)
                    pp.append(scores)
                    for i, a in enumerate(GRID):
                        profile_rows.append(dict(gauge=gauge, fold=fold, source_kf=kf,
                                                 evidence_kf=m['evidence_kf'], a=float(a),
                                                 **{k: float(v[i]) for k, v in scores.items()},
                                                 mask_sha256=mask_sha(mask)))
                assert len(pp) >= 2
                avg = {k: np.mean([p[k] for p in pp], axis=0) for k in pp[0]}
                kf_profiles[kf] = avg['loss']
                selected[str(kf)] = dict(support=True, Ok=choose(avg['loss']),
                                         Gk=choose(avg['geometry']), fit_pair_count=len(pp))
            og = choose(np.mean(list(kf_profiles.values()), axis=0)) if kf_profiles else None
            selections[key] = dict(fit_support=fit, kfs=selected, Og=og,
                                   apply_kfs=fit['supported_kfs'])
    if profile_rows:
        write_csv(root/'profiles.csv', profile_rows)
    passed = all(v['fit_support']['passed'] for v in selections.values())
    result = dict(status='FIT_SELECTION_COMPLETE' if passed else 'STOP_INSUFFICIENT_SUPPORT',
                  selection_records_complete=True, coefficient_selection_successful=passed,
                  scene=scene, at=now(), selection_source='RGB_fit_only', reference_arrays_accessed=False,
                  selections=selections, profile_rows=len(profile_rows))
    dump(root/'selected_parameters.json', result)
    print(json.dumps(dict(status=result['status'], profile_rows=len(profile_rows),
                          fit_contexts={k: v['fit_support'] for k, v in selections.items()})))


def freeze(scene):
    require_registration()
    p = OUT/scene/'selected_parameters.json'
    dump(OUT/scene/'selection_seal.json', dict(status='FROZEN', at=now(), selection=digest(p),
          registration=digest(OUT/'registration.json'), masks=digest(OUT/scene/'mask_manifest.json')))
    print('SELECTION_FROZEN')


def verify(scene):
    """Independent cache recomputation; no call to diagnose/profile/context_support."""
    require_registration()
    root = OUT/scene
    manifests = read(root/'mask_manifest.json')
    with (root/'support_ablations.csv').open() as f:
        rows = list(csv.DictReader(f))
    lookup = {(r['gauge'], int(r['fold']), int(r['source_kf']), int(r['evidence_kf']), r['pool'], r['variant']): r for r in rows}
    checked = 0
    for m in manifests:
        p = OUT/m['file']
        assert sha(p) == m['sha256']
        with np.load(p) as a:
            n = len(a['centers'])
            unpack = lambda arr: np.unpackbits(arr, axis=-1)[..., :n].astype(bool)
            flags = dict(zip(a['flag_names'].tolist(), unpack(a['flags'])))
            pre = flags['source_edge'] & flags['source_texture'] & flags['ray'] & flags['parallax']
            for variant, (stride, agreement) in VARIANTS.items():
                centers = a['centers']
                sm = ((centers % 512) % stride == 0) & ((centers//512) % stride == 0)
                eligible = pre & flags['legacy_bounds' if agreement else 'bounds'] & flags['evidence'] & flags['warped_texture'] & sm
                if agreement:
                    eligible &= flags['agreement']
                cv = unpack(a['cv_old' if agreement else 'cv_new'])
                expected_mask = eligible & np.logical_and.reduce(cv, axis=0)
                assert np.array_equal(unpack(a['eligible_'+variant]), eligible)
                assert np.array_equal(unpack(a['mask_'+variant]), expected_mask)
                r = lookup[m['gauge'], m['fold'], m['source_kf'], m['evidence_kf'], m['pool'], variant]
                assert int(r['eligible']) == int(eligible.sum())
                assert int(r['retained']) == int(expected_mask.sum())
                assert r['mask_sha256'] == mask_sha(expected_mask)
                expected_support = expected_mask.sum() >= 256 and expected_mask.sum() >= .5*eligible.sum()
                assert (r['support'] == 'True') == expected_support
                checked += 1
    native = init_scene(scene)
    ncounts = {i: len(k['y']) for i, k in native.items() if k['original_frame'] >= 200}
    summary = read(root/'support_summary.json')
    for variant, contexts in summary['contexts'].items():
        for key, pools in contexts.items():
            gauge, fold = key.split('_fold')
            for pool, saved in pools.items():
                supported = []
                for kf in ncounts:
                    count = sum(r['gauge'] == gauge and int(r['fold']) == int(fold) and
                                r['pool'] == pool and r['variant'] == variant and
                                int(r['source_kf']) == kf and r['support'] == 'True' for r in rows)
                    assert count == saved['pair_counts'][str(kf)]
                    if count >= 2:
                        supported.append(kf)
                fraction = sum(ncounts[k] for k in supported)/sum(ncounts.values())
                assert supported == saved['supported_kfs']
                assert fraction == saved['candidate_fraction']
                assert saved['passed'] == (len(supported)/len(ncounts) >= .8 and fraction >= .8)
    if (root/'selection_seal.json').exists():
        seal = read(root/'selection_seal.json')
        assert sha(root/'selected_parameters.json') == seal['selection']['sha256']
        selected = read(root/'selected_parameters.json')
        if selected['profile_rows']:
            with (root/'profiles.csv').open() as f:
                pp = list(csv.DictReader(f))
            for key, v in selected['selections'].items():
                gauge, fold = key.split('_fold')
                for kf, s in v['kfs'].items():
                    if not s['support']:
                        continue
                    per_a = [[float(r['loss']) for r in pp if r['gauge'] == gauge and r['fold'] == fold and r['source_kf'] == kf and float(r['a']) == a] for a in GRID]
                    loss = np.array([np.mean(vv) for vv in per_a])
                    tied = np.flatnonzero(loss <= loss.min()+1e-8)
                    idx = min(tied, key=lambda i: (abs(GRID[i]), GRID[i]))
                    assert GRID[idx] == s['Ok']['a']
    result = dict(status='PASS', checked_mask_records=checked, checked_pair_artifacts=len(manifests),
                  independent_of_measurement_functions=True, checks=['mask_bitsets', 'support_counts',
                  'context_denominators', 'coefficient_argmin_when_present', 'seal_hashes'], at=now())
    dump(root/'verification.json', result)
    print(json.dumps(result))


def report():
    require_registration()
    m0 = read(OUT/'office2/support_summary.json') if (OUT/'office2/support_summary.json').exists() else None
    m1 = read(OUT/'controls/results.json') if (OUT/'controls/results.json').exists() else None
    selection = read(OUT/'office2/selected_parameters.json') if (OUT/'office2/selected_parameters.json').exists() else None
    if m1 and m1['status'] != 'PASS':
        decision = 'STOP_CONTROL_FAILURE'
    elif selection and selection['status'] == 'STOP_INSUFFICIENT_SUPPORT':
        decision = 'STOP_INSUFFICIENT_SUPPORT'
    else:
        decision = 'IN_PROGRESS'
    complete = decision.startswith('STOP_')
    summary = dict(experiment='A2-O-M', execution_status='COMPLETE_EARLY_STOP' if complete else 'IN_PROGRESS',
                   controls_status=m1['status'] if m1 else 'NOT_RUN',
                   m0_status=m0['status'] if m0 else 'NOT_RUN',
                   fit_support_status=selection['status'] if selection else 'NOT_RUN_DUE_TO_GATE',
                   audit_status='NOT_RUN_DUE_TO_GATE', source_status='NOT_RUN_DUE_TO_GATE',
                   target_status='NOT_RUN_DUE_TO_GATE', validation_status='NOT_RUN_DUE_TO_GATE',
                   final_decision=decision, rgb_coefficient_geometry_effect_estimated=False,
                   reference_arrays_accessed=False, office3_new_evaluation=False,
                   office4_accessed=False, hk_accessed=False, at=now())
    dump(OUT/'summary.json', summary)
    files = [digest(p) for p in OUT.rglob('*') if p.is_file() and 'registered_code' not in p.parts and p.name != 'execution_manifest.json' and p.suffix != '.log']
    dump(OUT/'execution_manifest.json', dict(summary=summary, artifacts=files))
    print(json.dumps(summary, ensure_ascii=False))


def guarded_downstream(command, scene):
    require_registration()
    path = OUT/'office2/selected_parameters.json'
    if not path.exists() or read(path)['status'] != 'FIT_SELECTION_COMPLETE':
        raise RuntimeError(f'{command} refused: office2 fit gate not passed; NOT_RUN_DUE_TO_GATE')
    raise RuntimeError(f'{command}: required downstream implementation not yet available; EVALUATION_BLOCKED')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=['preflight', 'register', 'support-audit', 'controls',
                        'seal-r1', 'profile', 'freeze-selection', 'verify', 'report',
                        'evaluate-source', 'evaluate-target', 'seal-development', 'register-validation'])
    parser.add_argument('--config', type=Path, default=CFG)
    parser.add_argument('--scene', default='office2', choices=['office2', 'office3'])
    args = parser.parse_args()
    if args.config.resolve() != CFG:
        raise ValueError('only the registered R1 protocol path is supported')
    cfg = read(CFG)
    assert cfg['source']['stride'] == 2 and not cfg['visibility']['candidate_depth_agreement_is_gate']
    assert cfg['grid'] == dict(start=-.2, stop=.2, step=.01, count=41, tie_epsilon=1e-8, flat_epsilon=1e-4, photo_gain_min=1e-4)
    cv2.setNumThreads(2)
    commands = dict(preflight=preflight, register=register, controls=controls,
                    **{'support-audit': lambda: support_audit(args.scene),
                       'seal-r1': seal_r1, 'profile': lambda: profile_scene(args.scene),
                       'freeze-selection': lambda: freeze(args.scene),
                       'verify': lambda: verify(args.scene), 'report': report})
    if args.command in commands:
        commands[args.command]()
    else:
        guarded_downstream(args.command, args.scene)


if __name__ == '__main__':
    main()
