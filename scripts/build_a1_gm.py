#!/usr/bin/env python3
"""Register both experiments, fit prefix gauges and construct isolated maps."""
from datetime import datetime
from pathlib import Path
import argparse
import json
import shutil
import sys
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_gm_common import context,cases,SPECS,prior_map,prior_metric,ARMS
from a1_c_common import load_views,reference_poses,source_camera,stats
from gauge_support import orientation_prefix_gauge,change_canonical_gauge,sampling_mask
from pointmap_contract import sim3_from_xyzw,sim3_parts,transform_points,transform_covariance,fit_prefix_gauge,backproject_z,array_hash
from canonical_oracles import build_canonical_arms
from a0b_geometry import source_rays
from e4_budget import pack_parameters
from prepare_e2b_run import digest,save_json


def source_paths():
    return [*SPECS.values(),Path(__file__),ROOT/'scripts/a1_gm_common.py',ROOT/'scripts/evaluate_a1_gm.py',
        ROOT/'src/gauge_support.py',ROOT/'tests/test_gauge_support.py',ROOT/'src/canonical_oracles.py',ROOT/'src/pointmap_contract.py',
        ROOT/'scripts/a1_c_common.py',ROOT/'src/a0_metrics.py',ROOT/'src/e4_budget.py',ROOT/'scripts/evaluate_e4.py',
        ROOT/'src/a0b_geometry.py',ROOT/'src/e1_taxonomy.py']


def register():
    common,_,c,u=context('G');oldroot=ROOT/common['A1_C'];old=json.loads((oldroot/'registration.json').read_text())
    paths={ROOT/r['path'] for r in old['inputs']};historical={r['path']:r for r in old['inputs']}
    paths.update(source_paths());paths.update([ROOT/'configs/a1_c_results_summary.json',oldroot/'analysis/results.json',oldroot/'oracles/completion.json',oldroot/'evaluation/completion.json'])
    for scene,uc in u['scenes'].items():
        uf=ROOT/common['A1_U']/'construction'/scene/'manifest.json';paths.add(uf);um=json.loads(uf.read_text())
        v=next(v for v in um['maps'] if v['id']=='canonical_C1');paths.add(ROOT/v['file']['path']);historical[v['file']['path']]=v['file']
        tp=ROOT/uc['baseline']/'map'/f'{scene}_frames.txt';paths.add(tp)
        if scene=='office2':previous=json.loads((ROOT/uc['oracle_root']/'manifest.json').read_text())['inputs']
        else:previous=json.loads((ROOT/uc['prior_manifest']).read_text())['inputs']
        for r in previous:historical[r['path']]=r
    for base in c['cases']:
        mp=oldroot/'oracles'/base/'manifest.json';paths.add(mp)
        for arm in ARMS:
            v=prior_map(base,arm);paths.add(ROOT/v['map_file']['path']);historical[v['map_file']['path']]=v['map_file']
            m=prior_metric(base,arm);paths.add(oldroot/'evaluation'/base/arm/'metrics.json')
            for key in ['depth_cache','coverage_cache']:
                paths.add(ROOT/m[key]['path']);historical[m[key]['path']]=m[key]
    for p in paths:
        rel=str(p.relative_to(ROOT))
        if rel in historical:assert digest(p)==historical[rel],rel
    inputs=[digest(p) for p in sorted(paths)];codes=[digest(p) for p in source_paths()]
    for exp in ['G','M']:
        spec,out,_,_=context(exp);out.mkdir(parents=True,exist_ok=False)
        for p in source_paths():
            q=out/'registered_code'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        save_json(out/'registration.json',dict(experiment='A1-'+exp,spec=digest(SPECS[exp]),registered_at=datetime.now().astimezone().isoformat(),
            phase='before new gauge fitting, masks, synthetic tests, construction or G/M outcome inspection',
            inputs=inputs,code=codes,cases=cases(exp),prior_A1C_results_known=True,office3_office4_unrun=True))
        print('Registered A1-'+exp,len(inputs),'inputs',len(cases(exp)),'scopes',flush=True)


def checked(exp):
    spec,out,c,u=context(exp);reg=json.loads((out/'registration.json').read_text());assert reg['spec']==digest(SPECS[exp]) and reg['cases']==cases(exp)
    for r in reg['inputs']+reg['code']:assert digest(ROOT/r['path'])==r,r['path']
    return spec,out,c,u


def gauges():
    spec,out,_,u=checked('G');folder=out/'gauges';folder.mkdir(exist_ok=False);result={}
    for scene,uc in u['scenes'].items():
        alignment=json.loads((ROOT/uc['alignment']).read_text());original=np.array(alignment[uc['alignment_gauge_key']])
        tr=np.loadtxt(ROOT/uc['baseline']/'map'/f'{scene}_frames.txt');ref,mapping=reference_poses(scene)
        if scene=='office2':ids=tr[:,0].astype(int);stop=200;target=np.array([ref[i] for i in ids])
        else:
            times=np.array([f['rgb_timestamp'] for f in mapping]);matches=np.argmin(np.abs(tr[:,0,None]-times[None,:]),axis=1)
            assert np.max(np.abs(tr[:,0]-times[matches]))<1e-5
            ids=np.array([mapping[i]['grid_index'] for i in matches]);stop=100;target=np.array([ref[i] for i in ids])
        estimated=np.array([sim3_from_xyzw([*row[1:8],1.]) for row in tr])
        position,calids=fit_prefix_gauge(estimated[:,:3,3],target[:,:3,3],ids,stop)
        np.testing.assert_allclose(position,original,rtol=1e-9,atol=1e-10)
        orientation,metadata=orientation_prefix_gauge(estimated,target,ids,stop);np.testing.assert_array_equal(calids,metadata['prefix_ids'])
        relative=orientation@np.linalg.inv(original);relative_scale,relative_R,_=sim3_parts(relative)
        if scene=='HKairport01':
            prior=ROOT/'results/A0b_pointmap_pose_factorial/HKairport01/oracles/gauge_sensitivity.json'
            np.testing.assert_allclose(orientation,np.array(json.loads(prior.read_text())['matrix']),rtol=1e-9,atol=1e-10)
        evaluation={}
        for name,G in [('position',position),('orientation',orientation)]:
            _,Rg,_=sim3_parts(G);p=transform_points(estimated[:,:3,3],G)
            angles=np.degrees(Rotation.from_matrix(np.swapaxes(target[:,:3,:3],1,2)@(Rg@estimated[:,:3,:3])).magnitude())
            take=ids>=stop
            evaluation[name]=dict(global_scale=sim3_parts(G)[0],prefix_position_residual_m=stats(np.linalg.norm(p[~take]-target[~take,:3,3],axis=1)),
                post_position_residual_m=stats(np.linalg.norm(p[take]-target[take,:3,3],axis=1)),post_orientation_residual_deg=stats(angles[take]))
        row=dict(scene=scene,position=position.tolist(),orientation=orientation.tolist(),relative=relative.tolist(),
            relative_scale=relative_scale,relative_rotation_deg=float(np.degrees(Rotation.from_matrix(relative_R).magnitude())),prefix=metadata,
            fit_uses_post_prefix=False,evaluation=evaluation,pose_revision=520 if scene=='office2' else 281)
        save_json(folder/(scene+'.json'),row);result[scene]=row
    return result


def new_case(exp,name,case,gauge_info):
    spec,out,c,u=context(exp);uc=u['scenes'][case['scene']];folder=out/'maps'/name;folder.mkdir(parents=True,exist_ok=False)
    for arm in ARMS:(folder/(arm+'.f32')).touch(exist_ok=False)
    base=case['base'];root=ROOT/uc['oracle_root'];uf=ROOT/spec['A1_U']/'construction'/case['scene'];um=json.loads((uf/'manifest.json').read_text())
    fullv=next(v for v in um['maps'] if v['id']=='canonical_C1');full=np.memmap(ROOT/fullv['file']['path'],dtype=np.float32,mode='r',shape=(um['active'],13))
    bm=json.loads((ROOT/spec['A1_C']/'oracles'/base/'manifest.json').read_text());bc={b['kf_idx']:b for b in bm['blocks']}
    oldmaps={a:np.memmap(ROOT/prior_map(base,a)['map_file']['path'],dtype=np.float32,mode='r',shape=(bm['count'],13)) for a in ARMS}
    oldoffsets={};o=0
    for b in bm['blocks']:oldoffsets[b['kf_idx']]=o;o+=b['count']
    refposes,mapping=reference_poses(case['scene']);K,cam=source_camera(case['scene']);offset=0;count=0;replaced=0;blocks=[];proof=[];proxies={a:[] for a in ARMS}
    for k in um['keyframes']:
        idx=k['kf_idx'];n=k['active'];local=np.load(ROOT/k['local_file']['path']);reg=np.load(root/uc['registry_template'].format(index=idx));native=reg['native_mask'];pixidx=local['active_pixel_indices']
        if case['scene']=='office2':
            frame=2*k['frame_id'];uv=reg['pixel_uv'][native];depth=reg['gt_depth'][native];valid=reg['common_mask'][native]
            scope=valid&(frame>=200) if case['kind']!='full_mixed' else np.ones(n,bool)
        else:
            frame=mapping[k['frame_id']]['grid_index'];uv=np.column_stack([pixidx%512,pixidx//512])
            rr=np.load(ROOT/'results/A0b_pointmap_pose_factorial/HKairport01/preflight/references'/f'HKairport_released_source_{frame:03d}.npz');depth=rr['depth'].ravel()[native]
            valid=reg['reference_intersection'][native] if 'common' in base else rr['valid'].ravel()[native]
            scope=valid&(frame>=100) if case['kind']!='full_mixed' else np.ones(n,bool)
        if case['kind']=='source_only':
            mask=sampling_mask((288,512),frame,case['pattern'],case['density'],spec['sparsification']['seed']).ravel()[pixidx]
            scope &= mask
        select=np.flatnonzero(scope)
        if not len(select):offset+=n;continue
        ids=np.array([f"{k['candidate_event']}:self:{i}" for i in pixidx[select]])
        if case['kind']=='source_only':
            base_selection=np.flatnonzero(valid&(frame>=200));subset=np.searchsorted(base_selection,select)
            assert np.all(base_selection[subset]==select);start=oldoffsets[idx]
            for arm in ARMS:
                packed=np.array(oldmaps[arm][start:start+bc[idx]['count']][subset],copy=True)
                with (folder/(arm+'.f32')).open('ab') as f:packed.tofile(f)
                proxies[arm].append(packed[::max(1,len(packed)//200),:3])
            replacement=len(select)
        else:
            y=local['y'][select];cov=local['covariance_y'][select];Q=local['rigid_Q'];y_original=y.copy();cov_original=cov.copy();Qoriginal=Q.copy()
            if case['gauge']=='orientation':
                D=np.array(gauge_info[case['scene']]['relative']);y,cov,Q=change_canonical_gauge(y,cov,Q,D)
                np.testing.assert_allclose(transform_points(y,Q),transform_points(transform_points(y_original,Qoriginal),D),atol=1e-10,rtol=1e-9)
                np.testing.assert_allclose(transform_covariance(cov,Q),transform_covariance(transform_covariance(cov_original,Qoriginal),D),atol=1e-10,rtol=1e-9)
                proof.append(dict(kf_idx=idx,world_similarity_roundtrip='PASS'))
            ref=y.copy();replace=valid[select]
            if case['kind']!='full_mixed':assert replace.all()
            ref[replace]=backproject_z(uv[select][replace],depth[select][replace],K) if case['scene']=='office2' else source_rays(uv[select][replace],cam)*depth[select][replace,None]
            rgb=full[offset:offset+n,9:12][select];opacity=full[offset:offset+n,12][select]
            arms=build_canonical_arms(y,ref,cov,Q,refposes[frame],ids,dict(rgb=rgb,opacity=opacity))
            for arm in ARMS:
                packed=pack_parameters(arms[arm]['world_points'],arms[arm]['world_covariance'],rgb,opacity)
                np.testing.assert_array_equal(packed[:,9:],full[offset:offset+n,9:][select])
                if case['kind']=='full_mixed' and arm=='C00':np.testing.assert_array_equal(packed,full[offset:offset+n])
                if arm=='C11' and case['kind']=='strict':
                    start=oldoffsets[idx];np.testing.assert_array_equal(packed[:,:3],oldmaps['C11'][start:start+len(select),:3])
                with (folder/(arm+'.f32')).open('ab') as f:packed.tofile(f)
                proxies[arm].append(packed[::max(1,len(packed)//200),:3])
            replacement=int(replace.sum())
        blocks.append(dict(kf_idx=idx,source_frame=frame,count=len(select),reference_replaced_count=replacement,candidate_id_hash=array_hash(ids),
            source_pixel_hash=array_hash(pixidx[select])))
        count+=len(select);replaced+=replacement;offset+=n
    assert offset==um['active'] and count>0
    if 'expected_candidates' in case:assert count==case['expected_candidates']
    variants=[]
    for arm in ARMS:
        p=folder/(arm+'.f32');assert p.stat().st_size==count*52;row=dict(arm=arm,count=count,map_file=digest(p));variants.append(row)
        np.save(folder/(arm+'_center_proxy.npy'),np.concatenate(proxies[arm]))
        if case['kind']=='full_mixed' and arm=='C00':assert row['map_file']['sha256']==fullv['file']['sha256']
    if case['gauge']=='orientation':
        assert [(b['kf_idx'],b['count'],b['candidate_id_hash']) for b in blocks]==[(b['kf_idx'],b['count'],b['candidate_id_hash']) for b in bm['blocks']]
    result=dict(case=name,definition=case,count=count,reference_replaced_count=replaced,reference_replacement_fraction=replaced/count,
        fraction_of_native=count/um['active'],blocks=blocks,variants=variants,world_similarity_checks=proof,
        frozen_attributes=True,reference_status='dense GT development' if case['scene']=='office2' else 'REFERENCE_UNRESOLVED')
    save_json(folder/'manifest.json',result);print(exp,name,'candidates',count,'reference replacement',replaced,flush=True);return result


def build():
    for e in ['G','M']:checked(e)
    info=gauges()
    for exp in ['G','M']:
        spec,out,c,u=context(exp);(out/'maps').mkdir(exist_ok=False);records={}
        for name,case in cases(exp).items():
            if not case['reuse']:record=new_case(exp,name,case,info)
            else:
                folder=out/'maps'/name;folder.mkdir();record=dict(case=name,definition=case,count=c['cases'][case['base']]['expected_candidates'],reuse_A1C=True,
                    variants=[dict(arm=a,count=prior_map(case['base'],a)['count'],map_file=prior_map(case['base'],a)['map_file']) for a in ARMS])
                save_json(folder/'manifest.json',record)
            records[name]=digest(out/'maps'/name/'manifest.json')
        if exp=='M':
            left=json.loads((out/'maps/HKairport01_full_common/manifest.json').read_text());right=json.loads((out/'maps/HKairport01_full_wide/manifest.json').read_text())
            for a in ['C00','C01']:
                assert next(v['map_file']['sha256'] for v in left['variants'] if v['arm']==a)==next(v['map_file']['sha256'] for v in right['variants'] if v['arm']==a)
        save_json(out/'maps/completion.json',dict(status='PASS',cases=records,registration=digest(out/'registration.json')))
    print('A1-G and A1-M construction PASS.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['register','build']);a=p.parse_args();{'register':register,'build':build}[a.stage]()
