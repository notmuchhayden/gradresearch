"""E4c staged, immutable development execution; external GT never in features."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import numpy as np
import torch
from prepare_e2b_run import digest, save_json
from run_e4b import load_geometry, eligible
from run_e3 import feature_guard
from e4c_surface_v2 import partition, fit_patches, view_geometry, states, diverse_pair, second_diverse

OUT=ROOT/'results/E4c_surface_consistency_pruning/v2'
CFG=ROOT/'configs/e4c_v2_surface_consistency_pruning.json'
COMBOS=[(3,1),(3,2),(5,1),(5,2)]
CODE=['src/e4c_surface_v2.py','scripts/run_e4c_v2.py','tests/test_e4c_v2.py',
      'scripts/run_e4b.py','scripts/run_e3.py','scripts/prepare_e2b_run.py',
      'src/e0b_audit.py','src/e2_signals.py','src/e3c_matched.py',
      'thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py']


def stamp():return datetime.now(timezone.utc).isoformat()


def initialize():
    if (OUT/'seal.json').exists() or CFG.exists():raise RuntimeError('Existing E4c registration preserved')
    prior=ROOT/'configs/e4b_protocol_registration.json'
    sources=json.loads(prior.read_text())['scene_sources']
    spec=dict(experiment='E4c surface consistency pruning',stage='development_feasibility',
              output=str(OUT.relative_to(ROOT)),development=['office0','office1'],
              regression=['room0','room1','room2'],fresh_reserved=['office2','office3'],
              source_registration=digest(prior),scene_sources=sources,
              audit_keyframes=[2,3],combinations=COMBOS,
              amendment='docs/experiments/E4c_v2_execution_amendment.md',
              evaluation_not_opened=True,seed=0,threads=2)
    OUT.mkdir(parents=True,exist_ok=True);save_json(CFG,spec)
    inputs=[digest(prior)];splits={};raw_failure={}
    for scene,p in sources.items():
        mp=ROOT/p['scores']/'score_metadata.json';ep=ROOT/p['baseline']/'audit/events.jsonl'
        fp=ROOT/p['scores']/'features.npz';sm=ROOT/p['scores']/'score_manifest.json'
        m=json.loads(mp.read_text());events=[json.loads(s) for s in ep.read_text().splitlines()]
        raw=[e for e in events if e['kind']=='raw_pair']
        audit_images={x for i,e in enumerate(raw) if i%3==2 for x in e['source_image_ids']}
        surviving=[e['event_id'] for i,e in enumerate(raw) if i%3!=2 and not audit_images.intersection(e['source_image_ids'])]
        raw_failure[scene]=dict(raw_events=len(raw),audit_events=sum(i%3==2 for i in range(len(raw))),
                                policy_events_after_source_exclusion=len(surviving))
        policy,audit=partition(m['lineage']);splits[scene]=dict(policy=policy,audit=audit,lineage=m['lineage'])
        manifest=json.loads(sm.read_text())
        for used in [mp,fp]:
            expected=manifest['metadata' if used==mp else 'features']
            assert digest(used)==expected
        inputs += [digest(x) for x in [mp,ep,fp,sm]]
        for line in m['lineage']:
            inputs += [digest(ROOT/p['baseline']/'exports/raw_pairs'/f"{line['event_id']}.pt"),
                       digest(ROOT/p['baseline']/'audit'/line['decision_file'])]
        inputs.append(digest(ROOT/p['baseline']/'map'/f'{scene}_kfgauss.pt'))
    save_json(OUT/'evidence_split.json',dict(original_failure=raw_failure,amended=splits))
    fresh={s:dict(local_dataset_present=any((ROOT/d/'Replica'/s).exists() for d in
           ['data/E0b','data/E1','data/E2b','data/E3b','data/E3c','data/E4','data']),
           prior_result_directory_present=any(p.name==s for p in (ROOT/'results').glob('**/'+s) if p.is_dir()),
           new_scene_content_opened=False) for s in ['office2','office3','office4']}
    save_json(OUT/'exposure_audit.json',dict(checked_at_utc=stamp(),known_inspected=list(sources),
        fresh_candidates=fresh,limitation='Local names/manifests only; user exposure outside workspace cannot be inferred'))
    save_json(OUT/'input_manifest.json',dict(inputs=inputs,source_read_only=True))
    save_json(OUT/'environment.json',dict(python=sys.version,numpy=np.__version__,torch=torch.__version__,
              platform=platform.platform(),threads=2,device='CPU',cuda_available=torch.cuda.is_available()))
    registration=dict(registered_at_utc=stamp(),client_date='2026-10-22',specification=spec,
        configuration=digest(CFG),protocol=digest(ROOT/'docs/experiments/E4c_surface_consistency_pruning.md'),
        amendment=digest(ROOT/spec['amendment']),
        prior_metadata_inspection='Ancestry-only original/amended split feasibility; no coordinates, GT or outcome inspection',
        fresh_data_opened=False)
    save_json(ROOT/'configs/e4c_v2_protocol_registration.json',registration)
    save_json(OUT/'protocol_registration.json',registration)
    for rel in CODE+['docs/experiments/E4c_surface_consistency_pruning.md',spec['amendment']]:
        target=OUT/'sealed_code'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,target)
    seal=dict(sealed_at_utc=stamp(),code=[digest(ROOT/p) for p in CODE],configuration=digest(CFG),
              registration=digest(ROOT/'configs/e4c_v2_protocol_registration.json'),
              inputs=digest(OUT/'input_manifest.json'),split=digest(OUT/'evidence_split.json'),
              tests=digest(OUT/'logs/tests.log'),geometric_analysis_before_seal=False)
    save_json(OUT/'seal.json',seal);save_json(ROOT/'configs/e4c_v2_preregistration.json',seal)
    print('Registered E4c development; original zero-policy split and A1 preserved',flush=True)


def checked():
    seal=json.loads((OUT/'seal.json').read_text())
    for e in seal['code']+[seal['configuration'],seal['registration'],seal['inputs'],seal['split']]:
        assert digest(ROOT/e['path'])==e,e['path']
    return json.loads(CFG.read_text())


def label_audit(meta,local,obs,snaps,audit,dest):
    """Offline development labels, never an online feature."""
    n=meta['raw_per_kf'];nk=meta['keyframes'];labels=np.zeros(n*nk,np.uint8)
    fits={j:fit_patches(obs[j],radius=3,audit=True) for j in audit}
    snap=snaps[-1];rows=[];counts=[]
    for i in range(nk):
        supports=[];conflicts=[];directions=[];ids=[]
        for j in audit:
            if not eligible(meta,i,j,snap):continue
            g=view_geometry(local[i]['means'],local[i]['cov'],obs[i],obs[j],fits[j],snap['poses'][i],snap['poses'][j])
            support,score,_=states(g,fits[j],audit=True)
            conflict=np.isfinite(score)&(score>1)&g['front']
            supports.append(support);conflicts.append(conflict);directions.append(g['direction']);ids.append(j)
            rows.append(dict(candidate_kf=i,evidence_kf=j,support=int(support.sum()),conflict=int(conflict.sum()),
                             eligible=int(g['eligible'].sum())))
        if supports:
            s=diverse_pair(supports,directions,ids)&~np.any(conflicts,axis=0)
            o=diverse_pair(conflicts,directions,ids)&~np.any(supports,axis=0)
            labels[i*n:(i+1)*n]=np.where(s,1,np.where(o,2,0))
        counts.append(dict(candidate_kf=i,S=int((labels[i*n:(i+1)*n]==1).sum()),O=int((labels[i*n:(i+1)*n]==2).sum())))
        print(f'{meta["scene"]}: audit candidate KF {i+1}/{nk}',flush=True)
    np.savez_compressed(dest/'audit_labels.npz',labels=labels)
    save_json(dest/'audit_summary.json',dict(rows=rows,by_kf=counts,pose_revision=snap['revision'],
        offline_final_revision=True,GT_used=False,policy_membership_used=False))
    del fits
    return labels


def geometry(scene):
    started=time.monotonic();spec=checked();dest=OUT/'development'/scene
    if (dest/'geometry_summary.json').exists():raise RuntimeError('Completed geometry preserved')
    dest.mkdir(parents=True,exist_ok=True);torch.set_num_threads(2)
    with feature_guard():
        paths,meta,f,base,local,obs,snaps=load_geometry(scene,dict(scene_sources=spec['scene_sources']))
        meta['scene']=scene;n=meta['raw_per_kf'];nk=meta['keyframes'];total=n*nk;active=f['active']
        policy,audit=partition(meta['lineage'])
        labels=label_audit(meta,local,obs,snaps,audit,dest)
        fits={}
        # Also retain local surfaces for every candidate, even when its source is in audit.
        for i in range(nk):
            fits[i]=fit_patches(obs[i]);print(f'{scene}: policy/local patch {i+1}/{nk}',flush=True)
        local_support={};local_geometry={}
        for i in range(nk):
            local_geometry[i]=view_geometry(local[i]['means'],local[i]['cov'],obs[i],obs[i],fits[i],np.eye(4),np.eye(4),local=True)
        for cs,ch in COMBOS:
            key=f'c{cs}_{ch}'
            local_support[key]=np.concatenate([states(local_geometry[i],fits[i],cs,ch)[0] for i in range(nk)])
        del local_geometry
        history=dest/'history';history.mkdir(exist_ok=True)
        peak={f'{key}_{kind}':np.full(total,np.nan,np.float32) for key in local_support for kind in ['shadow_s','shadow_d','s','d']}
        rows=[]
        for index,snap in enumerate(snaps):
            values={k:np.full((index+1,n),np.nan,np.float32) for k in peak}
            for i in range(index+1):
                gs=[];views=[]
                for j in policy:
                    if j>index or not eligible(meta,i,j,snap):continue
                    assert j not in audit
                    g=view_geometry(local[i]['means'],local[i]['cov'],obs[i],obs[j],fits[j],snap['poses'][i],snap['poses'][j])
                    gs.append(g);views.append(j)
                if len(gs)<2:continue
                directions=[g['direction'] for g in gs]
                for cs,ch in COMBOS:
                    key=f'c{cs}_{ch}';support=[];planes=[];depths=[];front_s=[];front_d=[]
                    for g,j in zip(gs,views):
                        sup,p,d=states(g,fits[j],cs,ch);support.append(sup);planes.append(p);depths.append(d)
                        front_s.append(np.where(g['front'],p,np.nan));front_d.append(np.where(g['front'],d,np.nan))
                    shadow_s=second_diverse(planes,directions,views);shadow_d=second_diverse(depths,directions,views)
                    protect=local_support[key][i*n:(i+1)*n]|np.any(support,axis=0)
                    s=second_diverse(front_s,directions,views);d=second_diverse(front_d,directions,views)
                    s[protect]=np.nan;d[protect]=np.nan
                    for kind,a in [('shadow_s',shadow_s),('shadow_d',shadow_d),('s',s),('d',d)]:values[key+'_'+kind][i]=a
            for k,a in values.items():peak[k][:a.size]=np.fmax(peak[k][:a.size],a.reshape(-1))
            np.savez_compressed(history/f'snapshot{index:04d}.npz',**values,
                input_frame=snap['frame'],pose_revision=snap['revision'],decision_sequence=snap['sequence'])
            rows.append(dict(snapshot=index,input_frame=snap['frame'],revision=snap['revision'],
                         possible_s=int(np.isfinite(values['c3_1_s']).sum())))
            print(f'{scene}: causal snapshot {index+1}/{nk}; eligible unprotected {rows[-1]["possible_s"]}',flush=True)
        np.savez_compressed(dest/'features.npz',**peak,**{k+'_local':v for k,v in local_support.items()},
             active=active,anchor_kf=np.repeat(np.arange(nk),n),pixel_index=np.tile(np.arange(n),nk))
    stats={}
    for cs,ch in COMBOS:
        key=f'c{cs}_{ch}';finite=np.isfinite(peak[key+'_shadow_s'])&np.isfinite(peak[key+'_shadow_d'])
        stats[key]=dict(active=int(active.sum()),S=int((active&(labels==1)).sum()),O=int((active&(labels==2)).sum()),
             common_S=int((active&finite&(labels==1)).sum()),common_O=int((active&finite&(labels==2)).sum()),
             common_active=int((active&finite).sum()),local_support=int((active&local_support[key]).sum()),
             unprotected_ever_finite=int((active&np.isfinite(peak[key+'_s'])).sum()))
    summary=dict(scene=scene,policy=policy,audit=audit,combinations=stats,snapshots=rows,
                 cpu_seconds=time.monotonic()-started,external_GT_read=False,
                 artifacts=[digest(p) for p in sorted(dest.rglob('*.npz'))])
    save_json(dest/'geometry_summary.json',summary)
    print(json.dumps(dict(scene=scene,combinations=stats)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['initialize','geometry']);parser.add_argument('scene',nargs='?')
    args=parser.parse_args()
    if args.command=='initialize':initialize()
    else:geometry(args.scene)
