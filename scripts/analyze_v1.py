#!/usr/bin/env python3
"""Paired V1 comparisons with explicit support and separate target sampling."""
from pathlib import Path
import csv
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from v1_common import checked,views,definitions,ARMS,CZ,OLD,stats
from prepare_e2b_run import digest,save_json
from canonical_oracles import support_gate
from gauge_support import sampling_mask
from a0_metrics import common_covered_metrics,factorial


def mean(x):
    good = [v for v in x if v is not None]
    return float(np.mean(good)) if good else None


def effects(errors):
    values = list(errors.values())
    if any(v is None for v in values): return None
    e = factorial(dict(zip(OLD,values)))
    e.update(local_given_reference_pose=values[2]-values[3],rigid_given_reference_local=values[1]-values[3])
    return e


def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w = csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    spec,out = checked()
    dest = out/'analysis'
    dest.mkdir(exist_ok=False)
    completion = json.loads((out/'evaluation/completion.json').read_text())
    assert completion['status']=='COMPLETE'
    uc = json.loads((out/'unit_render/completion.json').read_text())
    assert uc['status']=='PASS'
    cameras = views()
    data,records = {},{}
    defs = definitions()
    maps = json.loads((out/'maps/manifest.json').read_text())
    count = {}
    for row in completion['metrics']:
        assert digest(ROOT/row['path'])==row
        m = json.loads((ROOT/row['path']).read_text())
        key = (m['case'],m['arm'])
        records[key] = m
        count[m['case']] = m['map']['count']
        for field in ['depth_cache','coverage_cache']: assert digest(ROOT/m[field]['path'])==m[field]
        data[key] = dict(depth=np.load(ROOT/m['depth_cache']['path'],mmap_mode='r'),
                         coverage=np.load(ROOT/m['coverage_cache']['path'],mmap_mode='r'),
                         indices={f:j for j,f in enumerate(m['frame_ids'])})
    groups = {}
    def group(label,members,ids=None,target=None):
        ids = list(cameras) if ids is None else ids
        rows,own = [],{key:[] for key in members}
        target_files = []
        for f in ids:
            ref = cameras[f]
            valid = ref['valid'].copy()
            full_count = int(valid.sum())
            if target is not None:
                mask = sampling_mask(ref['hw'],f,target['pattern'],target['density'],0)
                valid &= mask
                path = dest/f'{label}_targetmask_{f:04d}.npy'
                np.save(path,mask)
                target_files.append(digest(path))
            pred,covered = {},{}
            for key,pair in members.items():
                d = data[tuple(pair)]
                j = d['indices'][f]
                pred[key],covered[key] = d['depth'][j],d['coverage'][j]
            common,metric = common_covered_metrics(pred,covered,ref['gt'],valid)
            rows.append(dict(frame=f,common_pixels=int(common.sum()),reference_pixels=int(valid.sum()),full_reference_pixels=full_count,
                common_fraction=float(common.sum()/valid.sum()) if valid.any() else None,
                measured_fraction_of_full_reference=float(valid.sum()/full_count) if full_count else None,
                common_fraction_of_full_reference=float(common.sum()/full_count) if full_count else None,
                errors={key:value['mae_m'] for key,value in metric.items()},absrel={key:value['absrel'] for key,value in metric.items()}))
            for key in members:
                err = np.abs(pred[key]-ref['gt'])
                good = valid&covered[key]
                correct = covered[key]&(err<=np.maximum(.05,.02*ref['gt']))
                own[key].append(dict(mae_m=float(err[good].mean()) if good.any() else None,
                    coverage=float(good.sum()/valid.sum()) if valid.any() else None,
                    correct_coverage=float((valid&correct).sum()/valid.sum()) if valid.any() else None))
        gatecfg = spec['support_sparse' if target is not None else 'support_dense']
        gate = support_gate(rows,gatecfg['min_pixels'],gatecfg['min_reference_fraction'],gatecfg['min_view_fraction'])
        summary = {key:dict(MAE_m=mean([r['errors'][key] for r in rows]),AbsRel=mean([r['absrel'][key] for r in rows]),
            own_covered_MAE_m=mean([r['mae_m'] for r in own[key]]),coverage=mean([r['coverage'] for r in own[key]]),
            correct_coverage=mean([r['correct_coverage'] for r in own[key]])) for key in members}
        result = dict(label=label,members=members,registered_views=len(ids),scorable_views=sum(r['common_pixels']>0 for r in rows),
            counts=stats([r['common_pixels'] for r in rows]),mean_fraction_of_reference=mean([r['common_fraction'] for r in rows]),
            mean_fraction_of_full_reference=mean([r['common_fraction_of_full_reference'] for r in rows]),
            mean_measured_fraction_of_full_reference=mean([r['measured_fraction_of_full_reference'] for r in rows]),
            summary=summary,rows=rows,support_gate=gate,target_only=target is not None,target_mask_files=target_files)
        save_json(dest/(label+'.json'),result)
        groups[label] = result
        return result
    cases,table = {},[]
    for name,definition in defs.items():
        base = 'position_strict' if definition['kind']=='target_only' else name
        arms = OLD if definition['kind']=='original' else ARMS
        ids = spec['covariance_views'] if definition['kind']=='fixed_world' else list(cameras)
        g = group(name+'_common4',{a:(base,a) for a in arms},ids,definition if definition['kind']=='target_only' else None)
        errors = {a:g['summary'][a]['MAE_m'] for a in arms}
        cases[name] = dict(definition=definition,count=count[base],effects=effects(errors),errors=errors,
            support_gate=g['support_gate'],mean_common_fraction=g['mean_fraction_of_reference'],
            mean_common_pixels=g['counts']['mean'],summary=g['summary'],scorable_views=g['scorable_views'])
        for a in arms:
            table.append(dict(case=name,arm=a,candidates=count[base],kind=definition['kind'],gauge=definition['gauge'],
                common_MAE_m=errors[a],coverage=g['summary'][a]['coverage'],correct_coverage=g['summary'][a]['correct_coverage'],
                common_fraction=g['mean_fraction_of_reference'],full_reference_fraction=g['mean_fraction_of_full_reference'],
                measured_fraction=g['mean_measured_fraction_of_full_reference'],support_pass=g['support_gate']['passed'],
                registered_views=g['registered_views'],scorable_views=g['scorable_views']))
        print('V1 analyzed',name,'support',g['support_gate']['passed'],flush=True)
    ray = group('C_CZ_common6',{a:('position_strict',a) for a in ARMS+CZ})
    pairs = []
    pairdefs = [('position_strict','orientation_strict'),('position_strict','position_full'),('position_strict','original_strict'),('position_strict','fixed_world_strict')]
    pairdefs += [('position_strict',name) for name,d in defs.items() if d['kind']=='source_only']
    for left,right in pairdefs:
        armsR = OLD if right=='original_strict' else ARMS
        members = {'L_'+a:(left,a) for a in ARMS}
        members.update({'R_'+a:(right,a) for a in armsR})
        ids = spec['covariance_views'] if right=='fixed_world_strict' else None
        g = group(left+'__'+right+'_common8',members,ids)
        el = effects({a:g['summary']['L_'+a]['MAE_m'] for a in ARMS})
        er = effects({a:g['summary']['R_'+a]['MAE_m'] for a in armsR})
        flips = {k:bool(el and er and np.sign(el[k])!=np.sign(er[k])) for k in ['delta_local','delta_placement']}
        material = {k:bool(flips[k] and g['support_gate']['passed'] and abs(el[rel])>=.1 and abs(er[rel])>=.1)
            for k,rel in [('delta_local','local_gain_relative_to_baseline'),('delta_placement','placement_gain_relative_to_baseline')]}
        pairs.append(dict(left=left,right=right,group=g['label'],support_gate=g['support_gate'],
            errors_left={a:g['summary']['L_'+a]['MAE_m'] for a in ARMS},errors_right={a:g['summary']['R_'+a]['MAE_m'] for a in armsR},
            effects_left=el,effects_right=er,sign_flip=flips,material_sign_flip=material,mean_common_fraction=g['mean_fraction_of_reference']))
    primary = cases['position_strict']
    local_qualified = all(cases[n]['support_gate']['passed'] and cases[n]['effects']['local_gain_relative_to_baseline']>=.1 and
        cases[n]['summary']['C10']['correct_coverage']>=cases[n]['summary']['C00']['correct_coverage']-.01
        for n in ['position_strict','orientation_strict'])
    any_flip = any(p['support_gate']['passed'] and any(p['sign_flip'].values()) for p in pairs if p['right']!='original_strict')
    any_support_failure = any(not c['support_gate']['passed'] for c in cases.values())
    # Only a next diagnostic stage is eligible; Oracle gains never grant D/P GO.
    decision = dict(execution='COMPLETE',native_and_unit='PASS',primary_support=primary['support_gate']['passed'],
        local_minimum_effect_both_gauges=local_qualified,any_gauge_scope_covariance_direction_flip=any_flip,
        any_support_failure=any_support_failure,scientific_GO=False,algorithm_GO=False,
        interpretation='CONDITIONAL_LOCAL_OPPORTUNITY' if local_qualified else 'INCONCLUSIVE',
        next='A2-S diagnostic scalar/spatial cross-fit' if local_qualified else 'A1-RT/R-Q limited diagnosis',
        next_scope='office2 development; freeze tuning before further office3 use; do not start correction implementation',
        Q0_HK='REFERENCE_UNRESOLVED',office4_predictions_run=False,independent_final_test=False)
    result = dict(experiment='V1 office3',decision=decision,cases=cases,pairs=pairs,table=table,
        ray_control=dict(support_gate=ray['support_gate'],summary=ray['summary']),
        unit_render=dict(status=uc['status'],positive_cases=uc['positive_cases'],negative_cases=uc['negative_cases']),
        evaluation=completion,source=dict(active=maps['active'],strict=maps['strict'],
            full_reference_replaced=maps['full_reference_replaced'],full_reference_fraction=maps['full_reference_fraction']),
        surfaces={a:records[('position_strict',a)]['surface'] for a in ARMS+CZ})
    save_json(dest/'results.json',result)
    save_json(dest/'decision.json',decision)
    write_csv(dest/'V1_four_arms.csv',table)
    write_csv(dest/'V1_effects.csv',[dict(case=n,**c['effects']) for n,c in cases.items() if c['effects']])
    save_json(ROOT/'configs/v1_office3_results_summary.json',result)
    print(json.dumps(decision,indent=2),flush=True)


if __name__=='__main__': main()
