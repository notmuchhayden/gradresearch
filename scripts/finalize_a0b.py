#!/usr/bin/env python3
"""Shared-mask A0b results; uncertainty gates are kept independent of outcomes."""
from pathlib import Path
import csv
import json
import shutil
import sys
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from prepare_a0b import load_context,stats,SPEC
from prepare_e2b_run import digest,save_json
from a0_metrics import factorial


def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    spec,out,run,frames,mapping,lookup,poses=load_context();dest=out/'analysis';dest.mkdir(exist_ok=False)
    evaluation=out/'evaluation';pre=json.loads((out/'preflight/manifest.json').read_text())
    complete=json.loads((evaluation/'completion.json').read_text())
    for row in complete['metrics']:assert digest(ROOT/row['path'])==row
    oracle=json.loads((out/'oracles/manifest.json').read_text());assert oracle['spec']==digest(SPEC)
    variants={v['id']:v for v in oracle['variants']}
    results={key:json.loads((evaluation/key/'metrics.json').read_text()) for key in variants}
    for row in results.values():
        for k in ['depth_cache','covered_cache']:assert digest(ROOT/row[k]['path'])==row[k]
    def key(scope,arm,model='HKairport_released',C=1,gauge='position'):
        return next(k for k,v in variants.items() if (v['scope'],v['arm'],v['model'],v['C_multiplier'],v['gauge'])==(scope,arm,model,C,gauge))
    names=['A00','A10','A01','A11'];grids=pre['evaluation_grid_ids'];diag=spec['diagnostic_view_ids']
    references={}
    for model in spec['camera_models']:
        for grid in grids:
            with np.load(out/'preflight/references'/f'{model}_target_{grid:03d}.npz') as f:
                references[model,grid]=(f['depth'],f['valid'])
    def group(name,keys,grid_ids):
        arrays={k:(np.load(evaluation/k/'depth.npy',mmap_mode='r'),np.load(evaluation/k/'covered.npy',mmap_mode='r')) for k in keys}
        idx={k:{g:i for i,g in enumerate(results[k]['frame_ids'])} for k in keys}
        rows=[];pooled={k:[] for k in keys};by_bin={};mask_files=[]
        for grid in grid_ids:
            valid=np.logical_and.reduce([references[variants[k]['model'],grid][1] for k in keys])
            common=valid.copy()
            for k in keys:common &= arrays[k][1][idx[k][grid]] & np.isfinite(arrays[k][0][idx[k][grid]])
            row=dict(grid_index=grid,reference_intersection_pixels=int(valid.sum()),common_pixels=int(common.sum()),
                common_fraction_of_reference=float(common.sum()/valid.sum()) if valid.any() else None,mae_m={},absrel={},median_m={},p95_m={})
            for k in keys:
                gt=references[variants[k]['model'],grid][0];pred=arrays[k][0][idx[k][grid]];error=np.abs(pred[common]-gt[common])
                row['mae_m'][k]=float(error.mean()) if len(error) else None
                row['absrel'][k]=float((error/gt[common]).mean()) if len(error) else None
                row['median_m'][k]=float(np.median(error)) if len(error) else None
                row['p95_m'][k]=float(np.percentile(error,95)) if len(error) else None
                pooled[k].append(error)
                for lo,hi in zip(spec['evaluation']['depth_bins_m'][:-1],spec['evaluation']['depth_bins_m'][1:]):
                    take=common&(gt>=lo)&(gt<hi)
                    if take.any():by_bin.setdefault(f'{lo}-{hi}',{}).setdefault(k,[]).append(float(np.abs(pred[take]-gt[take]).mean()))
            rows.append(row)
            if name in ['strict_common4','full_map_common4']:
                p=dest/f'{name}_grid{grid:03d}_mask.npy';np.save(p,common);mask_files.append(digest(p))
        summary={}
        for k in keys:
            summary[k]={m:float(np.mean([r[m][k] for r in rows if r[m][k] is not None])) if any(r[m][k] is not None for r in rows) else None for m in ['mae_m','absrel','median_m','p95_m']}
            summary[k]['pooled_pixel_errors_m']=stats(np.concatenate(pooled[k]))
        result=dict(name=name,frame_count=len(grid_ids),frames_with_common_pixels=sum(r['common_pixels']>0 for r in rows),
            common_pixels_per_frame=stats([r['common_pixels'] for r in rows]),
            mean_common_fraction_of_reference=float(np.mean([r['common_fraction_of_reference'] for r in rows])),
            summary=summary,per_frame=rows,depth_bin_mae_m={b:{k:float(np.mean(v)) for k,v in a.items()} for b,a in by_bin.items()},
            common_mask_files=mask_files)
        save_json(dest/(name+'.json'),result)
        return result
    groups={scope:group(scope+'_common4',[key(scope,a) for a in names],grids) for scope in ['strict','full_map']}
    aux=group('strict_aux_common6',[key('strict',a) for a in names+['Z10','Z11']],grids)
    cs=group('C_sensitivity_common12',[key('strict',a,C=c) for c in [1,.8,1.25] for a in names],diag)
    cams=group('camera_sensitivity_common16',[key('strict',a,model=m) for m in spec['camera_models'] for a in names],diag)
    gauges=group('gauge_sensitivity_common8',[key('strict',a,gauge=g) for g in ['position','orientation'] for a in names],diag)
    per_camera={m:group('camera_'+m+'_common4',[key('strict',a,model=m) for a in names],diag) for m in spec['camera_models']}
    table=[];effects=[]
    for scope,g in groups.items():
        errors={a:g['summary'][key(scope,a)]['mae_m'] for a in names}
        if all(v is not None for v in errors.values()):effects.append(dict(scope=scope,**factorial(errors)))
        for arm in names:
            k=key(scope,arm);s=results[k]['summary'];row=dict(scope=scope,arm=arm,candidate_count=variants[k]['count'],
                common_MAE_m=g['summary'][k]['mae_m'],common_AbsRel=g['summary'][k]['absrel'],
                mean_frame_median_m=g['summary'][k]['median_m'],mean_frame_p95_m=g['summary'][k]['p95_m'],
                coverage=s['coverage'],correct_depth_coverage=s['correct_coverage'],PSNR_dB=s['psnr_db'],SSIM=s['ssim'])
            table.append(row)
    sensitivity=[]
    for c in [1,.8,1.25]:
        errors={a:cs['summary'][key('strict',a,C=c)]['mae_m'] for a in names}
        sensitivity.append(dict(factor='C',setting=str(c),errors=errors,effects=factorial(errors) if all(v is not None for v in errors.values()) else None))
    for m in spec['camera_models']:
        errors={a:cams['summary'][key('strict',a,model=m)]['mae_m'] for a in names}
        sensitivity.append(dict(factor='camera',setting=m,errors=errors,effects=factorial(errors) if all(v is not None for v in errors.values()) else None))
    for g in ['position','orientation']:
        errors={a:gauges['summary'][key('strict',a,gauge=g)]['mae_m'] for a in names}
        sensitivity.append(dict(factor='gauge',setting=g,errors=errors,effects=factorial(errors) if all(v is not None for v in errors.values()) else None))
    # Track loss is reported on the original interval; no problematic view is dropped.
    strata=[]
    for label,lo,hi in [('before_tracking_gap',100,182),('tracking_gap',182,197),('after_tracking_gap',197,300)]:
        take=[r for r in groups['strict']['per_frame'] if lo<=r['grid_index']<hi]
        strata.append(dict(stratum=label,grid_interval=[lo,hi],views=len(take),mean_common_pixels=float(np.mean([r['common_pixels'] for r in take])),
            errors={a:float(np.mean([r['mae_m'][key('strict',a)] for r in take if r['mae_m'][key('strict',a)] is not None])) if any(r['mae_m'][key('strict',a)] is not None for r in take) else None for a in names}))
    # Sparse measured cloud NN is explicitly only a center proxy.
    ref=np.load(evaluation/'heldout_lidar_center_reference.npz')['xyz'];tree=cKDTree(ref)
    proxy=[]
    for arm in names:
        k=key('strict',arm);xyz=np.load(out/'oracles'/(k+'_center_proxy.npy'));d=tree.query(xyz,workers=2)[0]
        proxy.append(dict(arm=arm,candidate_center_count=len(xyz),reference_points=len(ref),center_to_sparse_reference_m=stats(d),
            definition='sampled Gaussian centers to sparse heldout LiDAR points; not rendered surface Chamfer or full scene completeness'))
    candidate=json.loads((out/'oracles/candidate_manifest.json').read_text())
    replaced_all=sum(r['common_candidates'] for r in candidate)
    decision=dict(execution='COMPLETE_CONDITIONAL',research='REVISE_CALIBRATION_AND_A1',
        strict_GT_causal_attribution=False,depth_only_GO=False,reason='Published sequence extrinsic is nonorthogonal; RGB preprocessing and physical-vs-Terra camera equivalence unconfirmed. Local/placement contrasts conditional on gauge and sparse source support.',
        prior_E4e_tracking_gate='FAIL unchanged',strict_valid_views=groups['strict']['frames_with_common_pixels'],
        target_views=len(grids),strict_candidates=oracle['strict_candidate_count'],native_active=oracle['native_active'],
        strict_fraction_of_native=oracle['strict_candidate_count']/oracle['native_active'],
        full_map_replaced_candidates=replaced_all,full_map_local_replacement_fraction=replaced_all/oracle['native_active'])
    result=dict(table=table,effects=effects,sensitivity=sensitivity,tracking_strata=strata,center_proxy=proxy,decision=decision,
        strict_common_mask=dict(frames=groups['strict']['frames_with_common_pixels'],counts=groups['strict']['common_pixels_per_frame'],
            mean_fraction_of_reference=groups['strict']['mean_common_fraction_of_reference']),
        Z_controls={a:aux['summary'][key('strict',a)]['mae_m'] for a in names+['Z10','Z11']},
        source_local_residuals=candidate,preflight_gates=pre['gates'],
        alignment=json.loads((out/'preflight/alignment.json').read_text()),
        gauge_control=json.loads((out/'oracles/gauge_sensitivity.json').read_text()))
    save_json(dest/'results.json',result);save_json(dest/'decision.json',decision)
    write_csv(dest/'A0b_four_arms.csv',table);write_csv(dest/'A0b_effects.csv',effects)
    save_json(ROOT/'configs/a0b_results_summary.json',dict(experiment='A0b',scene='HKairport01',**decision,table=table,effects=effects,
        report='docs/experiments/A0b_HKairport01_factorial_results.md',output=spec['output']))
    sources=[Path(__file__),SPEC,ROOT/'configs/a0b_amendment_A1.json',ROOT/'scripts/prepare_a0b.py',ROOT/'scripts/build_a0b_oracles.py',
        ROOT/'scripts/evaluate_a0b_oracles.py',ROOT/'src/a0b_geometry.py',ROOT/'tests/test_a0b_geometry.py']
    for p in sources:
        q=out/'final_code'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(dest/'source_manifest.json',[digest(p) for p in sources])
    print(json.dumps(dict(table=table,effects=effects,sensitivity=sensitivity,decision=decision),indent=2),flush=True)


if __name__=='__main__':main()
