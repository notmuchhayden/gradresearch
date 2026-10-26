#!/usr/bin/env python3
"""Separate G/M shared-pixel contrasts, support gates and measurement effects."""
from pathlib import Path
import csv
import json
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_gm_common import context,cases,get_views,ARMS
from prepare_e2b_run import digest,save_json
from gauge_support import sampling_mask
from canonical_oracles import support_gate
from a0_metrics import common_covered_metrics,factorial
from a1_c_common import stats


def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def effect(errors):
    if any(v is None for v in errors.values()):return None
    e=factorial(dict(zip(['A00','A10','A01','A11'],[errors[a] for a in ARMS])))
    e.update(local_given_reference_pose=errors['C01']-errors['C11'],rigid_given_reference_local=errors['C10']-errors['C11'])
    return e


def mean(values):
    good=[v for v in values if v is not None];return float(np.mean(good)) if good else None


def analyze(exp):
    spec,out,c,u=context(exp);definitions=cases(exp);dest=out/'analysis';dest.mkdir(exist_ok=True)
    evaluation=json.loads((out/'evaluation/completion.json').read_text());assert evaluation['status']=='COMPLETE'
    data={};records={};views_cache={};groups={};table=[]
    for name,case in definitions.items():
        p=out/'evaluation'/name/'manifest.json';assert digest(p)==evaluation['cases'][name]
        em=json.loads(p.read_text());data[name]={};records[name]={}
        for row in em['metrics']:
            assert digest(ROOT/row['path'])==row;m=json.loads((ROOT/row['path']).read_text());a=m['arm'];records[name][a]=m
            for field in ['depth_cache','coverage_cache']:assert digest(ROOT/m[field]['path'])==m[field]
            data[name][a]=dict(depth=np.load(ROOT/m['depth_cache']['path'],mmap_mode='r'),coverage=np.load(ROOT/m['coverage_cache']['path'],mmap_mode='r'))
    def group(label,members,case_for_reference,masked=False):
        definition=definitions[case_for_reference];views=get_views(definition['scene'],views_cache);ids=list(views);rs=[];own={key:[] for key in members};cfg=c['cases'][definition['base']]
        sample_files=[]
        for j,f in enumerate(ids):
            ref=views[f];valid=ref['valid'].copy();full_count=int(valid.sum())
            if masked:
                mask=sampling_mask(ref['hw'],f,definition['pattern'],definition['density'],spec['sparsification']['seed']);valid &= mask
                p=dest/f'{label}_targetmask_{f:04d}.npy';np.save(p,mask);sample_files.append(digest(p))
            pred={key:data[n][a]['depth'][j] for key,(n,a) in members.items()};cov={key:data[n][a]['coverage'][j] for key,(n,a) in members.items()}
            common,metrics=common_covered_metrics(pred,cov,ref['gt'],valid)
            row=dict(frame=f,common_pixels=int(common.sum()),reference_pixels=int(valid.sum()),full_reference_pixels=full_count,
                common_fraction=float(common.sum()/valid.sum()) if valid.any() else None,
                measured_fraction_of_full_reference=float(valid.sum()/full_count) if full_count else None,
                common_fraction_of_full_reference=float(common.sum()/full_count) if full_count else None,
                errors={a:v['mae_m'] for a,v in metrics.items()},absrel={a:v['absrel'] for a,v in metrics.items()})
            rs.append(row)
            for key in members:
                good=valid&cov[key];err=np.abs(pred[key]-ref['gt']);correct=cov[key]&(err<=np.maximum(cfg['absolute_tolerance_m'],.02*ref['gt']))
                own[key].append(dict(MAE_m=float(err[good].mean()) if good.any() else None,
                    coverage=float(good.sum()/valid.sum()) if valid.any() else None,
                    correct_coverage=float((valid&correct).sum()/valid.sum()) if valid.any() else None))
        gatecfg=spec['evaluation']['sparse_support' if definition['scene']=='HKairport01' or masked else 'dense_support']
        gate=support_gate(rs,gatecfg['min_pixels'],gatecfg['min_reference_fraction'],gatecfg['min_view_fraction'])
        result=dict(label=label,members=members,scene=definition['scene'],registered_views=len(ids),scorable_views=sum(v['common_pixels']>0 for v in rs),
            counts=stats([v['common_pixels'] for v in rs]),mean_fraction_of_reference=mean([v['common_fraction'] for v in rs]),
            mean_fraction_of_full_reference=mean([v['common_fraction_of_full_reference'] for v in rs]),
            mean_measured_fraction_of_full_reference=mean([v['measured_fraction_of_full_reference'] for v in rs]),
            summary={key:dict(MAE_m=mean([r['errors'][key] for r in rs]),AbsRel=mean([r['absrel'][key] for r in rs]),
                own_covered_MAE_m=mean([r['MAE_m'] for r in own[key]]),coverage=mean([r['coverage'] for r in own[key]]),
                correct_coverage=mean([r['correct_coverage'] for r in own[key]])) for key in members},rows=rs,support_gate=gate,
            target_sampling=masked,target_mask_files=sample_files)
        save_json(dest/(label+'.json'),result);groups[label]=result;return result
    case_results={}
    for name,case in definitions.items():
        members={a:(name,a) for a in ARMS};g=group(name+'_common4',members,name,masked=case['kind']=='target_only')
        errors={a:g['summary'][a]['MAE_m'] for a in ARMS};ef=effect(errors)
        mm=json.loads((out/'maps'/name/'manifest.json').read_text());native=u['scenes'][case['scene']]['expected_active']
        for a in ARMS:
            s=g['summary'][a];table.append(dict(experiment='A1-'+exp,case=name,scene=case['scene'],kind=case['kind'],gauge=case['gauge'],arm=a,candidates=mm['count'],
                local_reference_candidates=mm.get('reference_replaced_count',mm['count']),fraction_of_native=mm['count']/native,
                common_MAE_m=s['MAE_m'],common_AbsRel=s['AbsRel'],coverage=s['coverage'],correct_coverage=s['correct_coverage'],
                mean_common_pixels=g['counts']['mean'],common_fraction_of_reference=g['mean_fraction_of_reference'],
                common_fraction_of_full_reference=g['mean_fraction_of_full_reference'],measured_fraction_of_full_reference=g['mean_measured_fraction_of_full_reference'],
                support_pass=g['support_gate']['passed'],registered_views=g['registered_views'],scorable_views=g['scorable_views']))
        if case['reuse'] and case['kind']!='target_only':
            published=json.loads((ROOT/spec['A1_C']/'analysis'/case['base']/'C_common4.json').read_text())
            assert [r['common_pixels'] for r in g['rows']]==[r['common_pixels'] for r in published['rows']]
            for a in ARMS:assert errors[a]==published['summary'][a]['MAE_m']
        strata=[]
        if case['scene']=='HKairport01':
            for label,lo,hi in [('pre_gap',100,182),('gap',182,197),('post_gap',197,300)]:
                rr=[r for r in g['rows'] if lo<=r['frame']<hi];strata.append(dict(stratum=label,views=len(rr),errors={a:mean([r['errors'][a] for r in rr]) for a in ARMS}))
        case_results[name]=dict(definition=case,count=mm['count'],reference_replaced_count=mm.get('reference_replaced_count',mm['count']),
            primary=g,effects=ef,tracking_strata=strata,reference_resolved=case['scene']=='office2')
        print('Analyzed',exp,name,'support',g['support_gate']['passed'],flush=True)
    pairs=[]
    if exp=='G':pairdefs=[(base+'_position',base+'_orientation') for base in spec['cases']]
    else:pairdefs=spec['scope_pairs']+[(case['base'],name) for name,case in definitions.items() if case['kind']=='source_only']
    for left,right in pairdefs:
        members={side+'_'+a:(name,a) for side,name in [('L',left),('R',right)] for a in ARMS}
        g=group(left+'__vs__'+right+'_common8',members,left)
        errorsL={a:g['summary']['L_'+a]['MAE_m'] for a in ARMS};errorsR={a:g['summary']['R_'+a]['MAE_m'] for a in ARMS}
        eL,eR=effect(errorsL),effect(errorsR)
        flip={};material={}
        for factor,relative in [('delta_local','local_gain_relative_to_baseline'),('delta_placement','placement_gain_relative_to_baseline')]:
            flip[factor]=bool(eL and eR and np.sign(eL[factor])!=np.sign(eR[factor]))
            material[factor]=bool(flip[factor] and abs(eL[relative])>=.1 and abs(eR[relative])>=.1 and g['support_gate']['passed'])
        pairs.append(dict(left=left,right=right,group=g,errors_left=errorsL,errors_right=errorsR,effects_left=eL,effects_right=eR,
            sign_flip=flip,material_sign_flip_with_adequate_support=material))
    target_checks=[]
    if exp=='M':
        for name,case in definitions.items():
            if case['kind']!='target_only':continue
            base=case_results[case['base']]
            for a in ARMS:
                for field in ['depth_cache','coverage_cache']:assert records[name][a][field]==records[case['base']][a][field]
            target_checks.append(dict(case=name,unchanged_map_and_render_caches=True,full_reference_errors={a:base['primary']['summary'][a]['MAE_m'] for a in ARMS},
                sampled_reference_errors={a:case_results[name]['primary']['summary'][a]['MAE_m'] for a in ARMS},
                measured_fraction=case_results[name]['primary']['mean_measured_fraction_of_full_reference']))
    decision=dict(execution='COMPLETE',scientific_GO=False,material_gauge_or_support_flips=any(any(p['material_sign_flip_with_adequate_support'].values()) for p in pairs),
        any_direction_flip_with_adequate_support=any(p['group']['support_gate']['passed'] and any(p['sign_flip'].values()) for p in pairs),
        next='Freeze diagnostic replication protocol; office3 V1 pending, no method GO',HK_reference='REFERENCE_UNRESOLVED',office3_office4_predictions_run=False)
    result=dict(experiment='A1-'+exp,cases=case_results,pairs=pairs,table=table,target_identity_checks=target_checks,decision=decision,
        tests=dict(new_gauge_support=6,existing=38,total=44),evaluation_counts=evaluation)
    save_json(dest/'results.json',result);save_json(dest/'decision.json',decision);write_csv(dest/f'A1_{exp}_four_arms.csv',table)
    matrix=[]
    for name,cr in case_results.items():
        g=cr['primary'];e=cr['effects']
        matrix.append(dict(case=name,gauge=cr['definition']['gauge'],kind=cr['definition']['kind'],candidates=cr['count'],reference_replaced=cr['reference_replaced_count'],
            common_pixels_mean=g['counts']['mean'],reference_fraction=g['mean_fraction_of_reference'],full_reference_fraction=g['mean_fraction_of_full_reference'],
            support_pass=g['support_gate']['passed'],delta_local=e['delta_local'] if e else None,delta_rigid=e['delta_placement'] if e else None,interaction=e['interaction'] if e else None))
    write_csv(dest/'A1_gauge_support_matrix.csv',matrix)
    summary=dict(experiment='A1-'+exp,decision=decision,table=table,cases={name:dict(count=v['count'],reference_replaced=v['reference_replaced_count'],effects=v['effects'],
        errors={a:v['primary']['summary'][a]['MAE_m'] for a in ARMS},support_gate=v['primary']['support_gate'],mean_common_fraction=v['primary']['mean_fraction_of_reference']) for name,v in case_results.items()},
        pairs=[{k:v for k,v in p.items() if k!='group'} for p in pairs],target_checks=target_checks,new_depth_views=evaluation['new_depth_views'],reused_depth_views=evaluation['reused_depth_views'])
    save_json(ROOT/f'configs/a1_{exp.lower()}_results_summary.json',summary)
    print(json.dumps(dict(experiment='A1-'+exp,decision=decision,cases=summary['cases']),indent=2),flush=True)


if __name__=='__main__':
    for experiment in ['G','M']:analyze(experiment)
