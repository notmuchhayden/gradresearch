#!/usr/bin/env python3
"""Report both historical all-valid and interior denominators from frozen caches.

Reporting supplement only: no rerender, fit, candidate/mask replacement, or GO.
Primary common-mask metrics remain those registered before V1 outcomes.
"""
from pathlib import Path
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from v1_common import checked,views,ARMS,CZ
from prepare_e2b_run import digest,save_json


def main():
    _,out = checked()
    cameras = views()
    results = {}
    for arm in ARMS+CZ:
        p = out/'evaluation/position_strict'/arm
        m = json.loads((p/'metrics.json').read_text())
        for field in ['depth_cache','coverage_cache']: assert digest(ROOT/m[field]['path'])==m[field]
        d,c = np.load(p/'depth.npy',mmap_mode='r'),np.load(p/'covered.npy',mmap_mode='r')
        rows = []
        for j,f in enumerate(m['frame_ids']):
            a = cameras[f]
            err = np.abs(d[j]-a['gt'])
            correct = c[j]&(err<=np.maximum(.05,.02*a['gt']))
            row = dict(frame=f)
            for label,mask in [('interior',a['valid']),('all_valid',a['all_valid'])]:
                good = mask&c[j]
                row[label] = dict(reference_pixels=int(mask.sum()),covered_pixels=int(good.sum()),
                    coverage=float(good.sum()/mask.sum()) if mask.any() else None,
                    correct_coverage=float((mask&correct).sum()/mask.sum()) if mask.any() else None,
                    own_covered_MAE_m=float(err[good].mean()) if good.any() else None)
            # Independent replay of the stored primary own-covered statistics.
            for label,key in [('coverage','coverage'),('correct_coverage','correct_coverage'),('own_covered_MAE_m','mae_m')]:
                assert row['interior'][label]==m['frames'][j][key]
            rows.append(row)
        summary = {label:{key:float(np.mean([r[label][key] for r in rows]))
                          for key in ['coverage','correct_coverage','own_covered_MAE_m']}
                   for label in ['interior','all_valid']}
        results[arm] = dict(rows=rows,summary=summary,source_metrics=digest(p/'metrics.json'))
    save_json(out/'analysis/reference_denominator_audit.json',dict(status='PASS',
        role='Reporting supplement; primary interior/common metrics unchanged; historical A1-C all-GT coverage also disclosed',
        arms=results,thresholds=dict(abs_m=.05,relative=.02),new_render=False,decision_changed=False))
    print('V1 denominator and cached-metric replay audit PASS.',flush=True)


if __name__=='__main__': main()
