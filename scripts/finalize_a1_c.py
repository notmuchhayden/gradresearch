#!/usr/bin/env python3
"""Shared-denominator A1-C contrasts, original-result replay and scope gates."""
from pathlib import Path
import csv
import json
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_c_common import context,frames,prior,prior_group_path,load_views,stats,ARMS,ALL_ARMS,OLD_ARMS
from a0_metrics import common_covered_metrics,factorial
from canonical_oracles import support_gate
from prepare_e2b_run import digest,save_json


def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def effect(values,names):
    if any(v is None for v in values.values()):return None
    result=factorial(dict(zip(OLD_ARMS,[values[a] for a in names])))
    result.update(local_effect_given_reference_pose=values[names[2]]-values[names[3]],
        pose_effect_given_reference_local=values[names[1]]-values[names[3]])
    return result


def main():
    spec,out,_=context();dest=out/'analysis';dest.mkdir(exist_ok=False)
    completion=json.loads((out/'evaluation/completion.json').read_text());assert completion['status']=='COMPLETE'
    for r in completion['metric_files']:
        assert digest(ROOT/r['path'])==r
        m=json.loads((ROOT/r['path']).read_text())
        for field in ['depth_cache','coverage_cache']:assert digest(ROOT/m[field]['path'])==m[field]
    cases={};table=[];effect_rows=[];gates=[];source_rows=[]
    for case_name,case in spec['cases'].items():
        folder=dest/case_name;folder.mkdir();vroot=out/'evaluation'/case_name
        manifest=json.loads((out/'oracles'/case_name/'manifest.json').read_text());views,_=load_views(case);ids=frames(case)
        records={v['id']:json.loads((vroot/v['id']/'metrics.json').read_text()) for v in manifest['variants']}
        data={}
        for name,r in records.items():data[name]=dict(depth=np.load(vroot/name/'depth.npy',mmap_mode='r'),coverage=np.load(vroot/name/'covered.npy',mmap_mode='r'),ids=r['frame_ids'])
        for arm in OLD_ARMS:
            p=prior(case,arm);old=json.loads((p['folder']/'metrics.json').read_text())
            data[arm]=dict(depth=np.load(p['folder']/'depth.npy',mmap_mode='r'),coverage=np.load(p['folder']/'covered.npy',mmap_mode='r'),ids=old['frame_ids'])
        def group(label,names,grid_ids):
            indices={a:{f:i for i,f in enumerate(data[a]['ids'])} for a in names};rows=[];summary={};bins={}
            for f in grid_ids:
                ref=views[f];pred={a:data[a]['depth'][indices[a][f]] for a in names};cov={a:data[a]['coverage'][indices[a][f]] for a in names}
                mask,metrics=common_covered_metrics(pred,cov,ref['gt'],ref['valid'])
                row=dict(frame=f,common_pixels=int(mask.sum()),reference_pixels=int(ref['valid'].sum()),
                    fraction_of_reference=float(mask.sum()/ref['valid'].sum()) if ref['valid'].any() else None,
                    MAE_m={a:metrics[a]['mae_m'] for a in names},AbsRel={a:metrics[a]['absrel'] for a in names},median_m={},p95_m={})
                for a in names:
                    e=np.abs(pred[a][mask]-ref['gt'][mask]);row['median_m'][a]=float(np.median(e)) if len(e) else None;row['p95_m'][a]=float(np.percentile(e,95)) if len(e) else None
                for lo,hi in zip(case['depth_bins_m'][:-1],case['depth_bins_m'][1:]):
                    take=mask&(ref['gt']>=lo)&(ref['gt']<hi)
                    if take.any():
                        b=f'{lo}-{hi}';bins.setdefault(b,{a:[] for a in names})
                        for a in names:bins[b][a].append(float(np.abs(pred[a][take]-ref['gt'][take]).mean()))
                rows.append(row)
                if label in ['C_common4','prior_A_common4']:
                    np.save(folder/f'{label}_frame{f:04d}_mask.npy',mask)
            for a in names:
                summary[a]={field:float(np.mean([r[field][a] for r in rows if r[field][a] is not None])) if any(r[field][a] is not None for r in rows) else None for field in ['MAE_m','AbsRel','median_m','p95_m']}
            cfg=spec['evaluation']['dense_support' if case['scene']=='office2' else 'sparse_support']
            gate=support_gate(rows,cfg['min_pixels'],cfg['min_reference_fraction'],cfg['min_view_fraction'])
            result=dict(group=label,registered_views=len(grid_ids),scorable_views=sum(r['common_pixels']>0 for r in rows),
                common_pixel_counts=stats([r['common_pixels'] for r in rows]),mean_fraction_of_reference=float(np.mean([r['fraction_of_reference'] for r in rows])),
                summary=summary,rows=rows,support_gate=gate,depth_bin_MAE_m={b:{a:float(np.mean(v)) if v else None for a,v in x.items()} for b,x in bins.items()})
            save_json(folder/(label+'.json'),result);return result
        canonical=group('C_common4',ARMS,ids);aux=group('C_CZ_common6',ALL_ARMS,ids);old=group('prior_A_common4',OLD_ARMS,ids);paired=group('prior_A_C_common8',OLD_ARMS+ARMS,ids)
        # Replay the original published per-view values, not only a rounded scene mean.
        published=json.loads(prior_group_path(case).read_text());pubrows=published['per_frame'];pmap={r.get('frame',r.get('grid_index')):r for r in pubrows}
        max_metric_delta=0.
        for row in old['rows']:
            pub=pmap[row['frame']];assert row['common_pixels']==pub['common_pixels']
            if case['scope']=='sequence_camera_support':expected=pub['errors']
            else:expected={a:pub['mae_m'][case['prior_ids'][a]] for a in OLD_ARMS}
            for a in OLD_ARMS:
                if expected[a] is None:assert row['MAE_m'][a] is None
                else:
                    d=abs(row['MAE_m'][a]-expected[a]);assert d<=spec['implementation_checks']['prior_cache_metric_atol_m'];max_metric_delta=max(d,max_metric_delta)
            if case['scope']=='camera_common':
                oldmask=ROOT/spec['prior_HK']/'analysis'/f'strict_common4_grid{row["frame"]:03d}_mask.npy'
                np.testing.assert_array_equal(np.load(folder/f'prior_A_common4_frame{row["frame"]:04d}_mask.npy'),np.load(oldmask))
        cerrors={a:canonical['summary'][a]['MAE_m'] for a in ARMS};ce=effect(cerrors,ARMS)
        pe_old=effect({a:paired['summary'][a]['MAE_m'] for a in OLD_ARMS},OLD_ARMS);pe_new=effect({a:paired['summary'][a]['MAE_m'] for a in ARMS},ARMS)
        assert paired['summary']['A00']['MAE_m']==paired['summary']['C00']['MAE_m']
        for a in ARMS:
            s=records[a]['summary'];surf=records[a]['surface']
            table.append(dict(case=case_name,arm=a,candidates=manifest['count'],registered_views=len(ids),scorable_views=canonical['scorable_views'],
                common_MAE_m=cerrors[a],common_AbsRel=canonical['summary'][a]['AbsRel'],coverage=s['coverage'],correct_depth_coverage=s['correct_coverage'],
                PSNR_dB=s['psnr_db'],SSIM=s['ssim'],observed_TSDF_Chamfer_m=surf['chamfer_m'] if surf else None,
                reference_status=case['reference_status']))
        if ce:effect_rows.append(dict(case=case_name,comparison='C_common4',**ce))
        if pe_old:effect_rows.append(dict(case=case_name,comparison='A_on_AC_common8',**pe_old))
        if pe_new:effect_rows.append(dict(case=case_name,comparison='C_on_AC_common8',**pe_new))
        cov=None
        if case['scene']=='office2':
            cov=group('covariance_common8',ARMS+['W_'+a for a in ARMS],case['covariance_views'])
            default_errors={a:cov['summary'][a]['MAE_m'] for a in ARMS};fixed_errors={a:cov['summary']['W_'+a]['MAE_m'] for a in ARMS}
            cov['transport_effects']=effect(default_errors,ARMS);cov['fixed_world_effects']=effect(fixed_errors,ARMS)
            cov['direction_changed']=any(np.sign(cov['transport_effects'][k])!=np.sign(cov['fixed_world_effects'][k]) for k in ['delta_local','delta_placement','joint_improvement'])
            cov['ranking_changed']=np.sign(default_errors['C10']-default_errors['C01'])!=np.sign(fixed_errors['C10']-fixed_errors['C01'])
            cov['ranking_changed']=bool(cov['ranking_changed']);save_json(folder/'covariance_common8.json',cov)
        strata=[]
        if case['scene']=='HKairport01':
            for label,lo,hi in [('pre_gap',100,182),('tracking_gap',182,197),('post_gap',197,300)]:
                rs=[r for r in canonical['rows'] if lo<=r['frame']<hi]
                strata.append(dict(stratum=label,views=len(rs),MAE_m={a:float(np.mean([r['MAE_m'][a] for r in rs if r['MAE_m'][a] is not None])) if any(r['MAE_m'][a] is not None for r in rs) else None for a in ARMS}))
        auxerrors={a:aux['summary'][a]['MAE_m'] for a in ALL_ARMS}
        gate=dict(case=case_name,**canonical['support_gate'],mean_fraction_of_reference=canonical['mean_fraction_of_reference'],
            reference_resolved=case['scene']=='office2',gauge_sensitivity_run=False,office3_V1_run=False,
            scientific_GO=False,next='A1-G/M then V1; preserve conditional UAV labels')
        gates.append(gate)
        for row in manifest['source_residuals']:source_rows.append(dict(case=case_name,**row))
        cases[case_name]=dict(primary=canonical,effects=ce,auxiliary=aux,ray_control_errors=auxerrors,prior_replay=dict(status='PASS',max_per_view_metric_difference_m=max_metric_delta),
            prior_group=old,paired_group=paired,paired_original_effects=pe_old,paired_canonical_effects=pe_new,covariance_control=cov,tracking_strata=strata,gate=gate)
    result=dict(experiment='A1-C',execution='COMPLETE',research='A1_G_M_AND_V1_REQUIRED',table=table,effects=effect_rows,cases=cases,
        gates=gates,source_residuals=source_rows,tests=dict(new_canonical_tests=6,prior_tests=32,total=38),
        limitations=['Two previously used development scenes; no independent scene replication',
            'C local intervention includes absorbed estimated KF scale; not raw model depth attribution',
            'Canonical covariance differs from original A arms; C11 centers equal old A11, covariance may differ',
            'HKairport physical calibration and Terra pose relationship remain unresolved',
            'A1-G/M and office3 V1 are not completed by this C execution'])
    save_json(dest/'results.json',result);save_json(dest/'decision.json',dict(execution=result['execution'],research=result['research'],gates=gates,correction_GO=False))
    write_csv(dest/'A1_C_four_arms.csv',table);write_csv(dest/'A1_effects.csv',effect_rows)
    summary={k:v for k,v in result.items() if k not in ['cases','source_residuals']}
    summary['scopes']={k:dict(primary_errors={a:v['primary']['summary'][a]['MAE_m'] for a in ARMS},
        common_pixel_counts=v['primary']['common_pixel_counts'],mean_common_fraction=v['primary']['mean_fraction_of_reference'],
        support_gate=v['primary']['support_gate'],ray_control_errors=v['ray_control_errors'],paired_A_effects=v['paired_original_effects'],paired_C_effects=v['paired_canonical_effects']) for k,v in cases.items()}
    save_json(ROOT/'configs/a1_c_results_summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
