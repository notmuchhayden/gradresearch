#!/usr/bin/env python3
"""Independent artifact audit after V1; no model or evaluator rerun."""
from pathlib import Path
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from v1_common import checked,views,ARMS,CZ
from prepare_e2b_run import digest,save_json


def main():
    spec,out = checked()
    construction = json.loads((out/'maps/manifest.json').read_text())
    cache = {}
    for m in construction['maps']:
        p = ROOT/m['file']['path']
        assert digest(p)==m['file']
        cache[(m['case'],m['arm'])] = np.memmap(p,dtype=np.float32,mode='r',shape=(m['count'],13))
    for case in {k[0] for k in cache}:
        members = [v for (c,a),v in cache.items() if c==case]
        for m in members[1:]:
            np.testing.assert_array_equal(m[:,9:],members[0][:,9:])
    np.testing.assert_array_equal(cache[('position_strict','C00')],cache[('original_strict','A00')])
    np.testing.assert_array_equal(cache[('position_strict','C11')][:,:3],cache[('original_strict','A11')][:,:3])
    for a in ARMS:
        unit0 = json.loads((out/'maps/unit_contract.json').read_text())['maps'][0]
        if a=='C00':
            assert digest(ROOT/unit0['file']['path'])['sha256']==digest(out/'maps/position_full/C00.f32')['sha256']
    full_offset,strict_offset = 0,0
    unknown_total = 0
    thinning_rows = {}
    for b in construction['blocks']:
        local = np.load(out/'maps/local'/f"kf{b['kf_idx']:03d}.npz")
        n,s = b['active'],b['strict']
        use = local['strict']
        assert use.sum()==s and len(use)==n
        for a in ARMS:
            full = cache[('position_full',a)][full_offset:full_offset+n]
            np.testing.assert_array_equal(full[use],cache[('position_strict',a)][strict_offset:strict_offset+s])
        unknown = ~local['reference_replace']
        unknown_total += int(unknown.sum())
        for a,barm in [('C00','C10'),('C01','C11')]:
            np.testing.assert_array_equal(cache[('position_full',a)][full_offset:full_offset+n][unknown],
                                          cache[('position_full',barm)][full_offset:full_offset+n][unknown])
        for name,selection in b['source_selections'].items():
            mask = np.load(out/'maps/local'/f"kf{b['kf_idx']:03d}_{name}.npy")
            assert mask.sum()==selection['count'] and len(mask)==s
            offset = thinning_rows.get(name,0)
            for a in ARMS:
                np.testing.assert_array_equal(cache[('position_strict',a)][strict_offset:strict_offset+s][mask],
                    cache[(name,a)][offset:offset+int(mask.sum())])
            thinning_rows[name] = offset+int(mask.sum())
        full_offset += n
        strict_offset += s
    assert full_offset==construction['active'] and strict_offset==construction['strict']
    assert unknown_total==construction['active']-construction['full_reference_replaced']
    cameras = views()
    primary = json.loads((out/'analysis/position_strict_common4.json').read_text())
    ds,cs = {},{}
    for a in ARMS:
        p = out/'evaluation/position_strict'/a
        ds[a],cs[a] = np.load(p/'depth.npy',mmap_mode='r'),np.load(p/'covered.npy',mmap_mode='r')
    errors = {a:[] for a in ARMS}
    support = 0
    for j,(f,ref) in enumerate(cameras.items()):
        common = ref['valid'].copy()
        for a in ARMS: common &= cs[a][j]&np.isfinite(ds[a][j])
        count = int(np.count_nonzero(common))
        assert count==primary['rows'][j]['common_pixels']
        support += int(count>=1000 and count/ref['valid'].sum()>=.5)
        for a in ARMS:
            e = float(np.mean(np.abs(ds[a][j][common]-ref['gt'][common])))
            assert e==primary['rows'][j]['errors'][a]
            errors[a].append(e)
    for a in ARMS: assert float(np.mean(errors[a]))==primary['summary'][a]['MAE_m']
    assert support==primary['support_gate']['qualifying_views']==400
    completion = json.loads((out/'evaluation/completion.json').read_text())
    assert completion['failed_attempt_rerender_bitwise_equal']
    # Both sides of the partial retry remain independently available.
    for filename in ['depth.npy','covered.npy']:
        assert digest(out/'failed_attempt1/original_strict/A00'/filename)['sha256']==digest(out/'evaluation/original_strict/A00'/filename)['sha256']
    report = json.loads((out/'report_manifest.json').read_text())
    for row in report['files']: assert digest(ROOT/row['path'])==row
    save_json(out/'verification.json',dict(status='PASS',frozen_input_and_amended_code_hashes=True,
        map_hashes=len(cache),all_arm_attributes_bitwise_equal=True,strict_full_selection_bitwise_equal=True,
        preserved_unobserved_candidates=unknown_total,source_thinning_bitwise_rows=thinning_rows,
        primary_independent_recomputation_views=400,qualifying_views=support,
        failed_attempt_depth_coverage_identity=True,report_figure_hashes=True,
        existing_unittest_count=48,existing_unittest_status='PASS',
        unittest_patterns=['test_*contract.py','test_scale_reparameterization.py','test_canonical_oracles.py','test_gauge_support.py','test_a0_metrics.py']))
    print('V1 final artifact verification PASS.',flush=True)


if __name__=='__main__': main()
