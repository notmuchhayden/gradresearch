#!/usr/bin/env python3
"""Register A1-C then build the frozen candidate/covariance intervention maps."""
from datetime import datetime
from pathlib import Path
import argparse
import json
import shutil
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_c_common import context,SPEC,ARMS,ALL_ARMS,OLD_ARMS,prior,prior_group_path,load_views,reference_poses,source_camera,stats
from prepare_e2b_run import digest,save_json
from canonical_oracles import build_canonical_arms
from pointmap_contract import array_hash,backproject_z,project,transform_points
from a0b_geometry import source_rays
from e4_budget import pack_parameters


def code_paths():
    return [SPEC,Path(__file__),ROOT/'scripts/a1_c_common.py',ROOT/'scripts/evaluate_a1.py',ROOT/'src/canonical_oracles.py',ROOT/'tests/test_canonical_oracles.py',
        ROOT/'src/pointmap_contract.py',ROOT/'src/a0_metrics.py',ROOT/'src/scale_reparameterization.py',ROOT/'src/a0b_geometry.py',ROOT/'src/e1_taxonomy.py',ROOT/'src/e4_budget.py',ROOT/'scripts/evaluate_e4.py']


def register():
    spec,out,u=context();assert json.loads((ROOT/spec['A1_U']/'A1_U_contract.json').read_text())['status']=='PASS'
    out.mkdir(parents=True,exist_ok=False);paths=set(code_paths());paths.update([ROOT/spec['A1_U']/'A1_U_contract.json',ROOT/spec['A1_U_spec'],ROOT/spec['native_filter_contract']])
    historical={}
    um=json.loads((ROOT/'configs/a1_u_execution_manifest.json').read_text())
    for r in json.loads((ROOT/um['cache_manifest']['path']).read_text()):historical[r['path']]=r
    am=json.loads((ROOT/'configs/a0_execution_manifest.json').read_text())
    for r in am['render_cache_files']:historical[r['path']]=r
    # A0b caches and references carry their own per-file hashes.
    hp=ROOT/spec['prior_HK']
    hm=json.loads((hp/'preflight/manifest.json').read_text())
    for row in hm['reference_rows']:
        for r in row['models'].values():historical[r['file']['path']]=r['file']
    for case_name,case in spec['cases'].items():
        scene=case['scene'];umf=ROOT/spec['A1_U']/'construction'/scene/'manifest.json';paths.add(umf);umap=json.loads(umf.read_text());uc=u['scenes'][scene]
        root=ROOT/uc['oracle_root'];paths.update([root/'manifest.json',ROOT/uc['alignment'],ROOT/uc['evaluation_poses'],ROOT/uc['camera'],prior_group_path(case)])
        if scene=='HKairport01':paths.add(ROOT/uc['split'])
        for k in umap['keyframes']:
            paths.update([ROOT/k['local_file']['path'],root/uc['registry_template'].format(index=k['kf_idx'])]);historical[k['local_file']['path']]=k['local_file']
            if case['scope']=='sequence_camera_support':
                s=json.loads((ROOT/uc['alignment']).read_text());mapping=reference_poses(scene)[1];grid=mapping[k['frame_id']]['grid_index']
                paths.add(hp/'preflight/references'/f'HKairport_released_source_{grid:03d}.npz')
        if scene=='office2':paths.add(root/'K.npy')
        for arm in OLD_ARMS:
            p=prior(case,arm);paths.add(p['map']);historical[p['map_hash']['path']]=p['map_hash']
            metric=p['folder']/'metrics.json';paths.add(metric);m=json.loads(metric.read_text())
            paths.update([p['folder']/'depth.npy',p['folder']/'covered.npy'])
            for field in ['depth_cache','covered_cache']:
                if field in m:historical[m[field]['path']]=m[field]
            for f in case['saved_views']:
                if scene=='office2':paths.add(p['folder']/f'frame{f:04d}.npz')
        _,viewpaths=load_views(case);paths.update(viewpaths)
        if scene=='office2':
            paths.add(ROOT/'data/N2/Replica/office2/groundtruth.txt')
            old=json.loads((ROOT/spec['prior_office']/'evaluation/input_manifest.json').read_text())
            for r in old:historical[r['path']]=r
            paths.add(ROOT/spec['prior_office']/'evaluation/reference_surface_samples.npy')
    for p in paths:
        rel=str(p.relative_to(ROOT))
        if rel in historical:assert digest(p)==historical[rel],rel
    code=code_paths()
    for p in code:
        q=out/'registered_code'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(out/'registration.json',dict(spec=digest(SPEC),registered_at=datetime.now().astimezone().isoformat(),
        phase='before A1-C synthetic checks, map construction or factorial outcomes',inputs=[digest(p) for p in sorted(paths)],
        code=[digest(p) for p in code],prior_A0_A0b_A1U_results_known=True,HK_reference_status='REFERENCE_UNRESOLVED'))
    print('Registered A1-C;',len(paths),'immutable inputs; no C outcomes inspected.',flush=True)


def checked():
    spec,out,u=context();m=json.loads((out/'registration.json').read_text());assert m['spec']==digest(SPEC)
    for r in m['inputs']+m['code']:assert digest(ROOT/r['path'])==r,r['path']
    return spec,out,u


def build():
    spec,out,u=checked();dest=out/'oracles';dest.mkdir(exist_ok=False);results={}
    for name,case in spec['cases'].items():
        scene=case['scene'];uc=u['scenes'][scene];uf=ROOT/spec['A1_U']/'construction'/scene
        umap=json.loads((uf/'manifest.json').read_text());oldroot=ROOT/uc['oracle_root'];fullm=json.loads((oldroot/'manifest.json').read_text());full=next(v for v in fullm['variants'] if v['id']==uc['full_variant'])
        packed_full=np.memmap(ROOT/full['map_file'],dtype=np.float32,mode='r',shape=(full['count'],13))
        folder=dest/name;folder.mkdir();variants=[dict(id=a,arm=a,covariance_policy='rigid_transport') for a in ALL_ARMS]
        if scene=='office2':variants += [dict(id='W_'+a,arm=a,covariance_policy='fixed_C00_world') for a in ARMS]
        for v in variants:(folder/(v['id']+'.f32')).touch(exist_ok=False)
        gtposes,mapping=reference_poses(scene);K,cam=source_camera(scene);offset=0;count=0;rows=[];blocks=[];proxies={v['id']:[] for v in variants}
        old0=prior(case,'A00');prior00=np.memmap(old0['map'],dtype=np.float32,mode='r',shape=(old0['count'],13))
        old11=prior(case,'A11');prior11=np.memmap(old11['map'],dtype=np.float32,mode='r',shape=(old11['count'],13))
        for k in umap['keyframes']:
            idx=k['kf_idx'];n=k['active'];reg=np.load(oldroot/uc['registry_template'].format(index=idx));local=np.load(ROOT/k['local_file']['path'])
            native=reg['native_mask'];native_ids=np.flatnonzero(native);np.testing.assert_array_equal(native_ids,local['active_pixel_indices'])
            if scene=='office2':
                frame=2*k['frame_id'];use=reg['common_mask'][native] if frame>=200 else np.zeros(n,bool)
                depth=reg['gt_depth'][native];uv=reg['pixel_uv'][native];Qref=gtposes[frame]
            else:
                frame=mapping[k['frame_id']]['grid_index'];h,w=416,512;uv=np.column_stack([native_ids%w,native_ids//w])
                if case['scope']=='camera_common':use=reg['strict_mask'][native]
                else:
                    r=np.load(ROOT/spec['prior_HK']/'preflight/references'/f'HKairport_released_source_{frame:03d}.npz');use=r['valid'].ravel()[native]&(frame>=100)
                depth=np.load(ROOT/spec['prior_HK']/'preflight/references'/f'HKairport_released_source_{frame:03d}.npz')['depth'].ravel()[native]
                Qref=gtposes[frame]
            if not use.any():offset+=n;continue
            y=local['y'][use];cov=local['covariance_y'][use];Q=local['rigid_Q'];rgb=packed_full[offset:offset+n,9:12][use];opa=packed_full[offset:offset+n,12][use]
            ids=np.array([f"{k['candidate_event']}:self:{i}" for i in native_ids[use]])
            ref=backproject_z(uv[use],depth[use],K) if scene=='office2' else source_rays(uv[use],cam)*depth[use,None]
            attrs=dict(rgb=rgb,opacity=opa)
            arms=build_canonical_arms(y,ref,cov,Q,Qref,ids,attrs);block=dict(kf_idx=idx,source_frame=frame,count=len(y),candidate_id_hash=array_hash(ids),
                local_covariance_hash=array_hash(cov),attributes={key:array_hash(value) for key,value in attrs.items()})
            blocks.append(block)
            if scene=='office2':
                oldblock=next(b for b in fullm['variants'] if b['id']==uc['strict_variant'])['blocks'];oldblock=next(b for b in oldblock if b['kf_idx']==idx)
                assert block['candidate_id_hash']==oldblock['id_hash']
            elif case['scope']=='camera_common':
                oldblock=next(b for b in fullm['variants'] if b['id']==uc['strict_variant'])['blocks'];oldblock=next(b for b in oldblock if b['kf_idx']==idx)
                assert block['candidate_id_hash']==oldblock['candidate_id_hash']
            else:
                sm=json.loads((ROOT/spec['prior_HK']/'support_control/map_manifest.json').read_text());b=next(b for b in sm['blocks'] if b['kf_idx']==idx)
                assert block['candidate_id_hash']==b['candidate_id_hash']
            for v in variants:
                a=arms[v['arm']];wc=arms['C00']['world_covariance'] if v['covariance_policy']=='fixed_C00_world' else a['world_covariance']
                packed=pack_parameters(a['world_points'],wc,rgb,opa)
                if v['id']=='C00':np.testing.assert_array_equal(packed,prior00[count:count+len(y)])
                if v['id']=='C11':np.testing.assert_array_equal(packed[:,:3],prior11[count:count+len(y),:3])
                np.testing.assert_array_equal(packed[:,9:],prior00[count:count+len(y),9:])
                recovered=transform_points(packed[:,:3].astype(float),np.linalg.inv(a['placement']))
                np.testing.assert_allclose(recovered,a['local'],atol=2e-5,rtol=1e-6)
                with (folder/(v['id']+'.f32')).open('ab') as f:packed.tofile(f)
                sample=np.arange(0,len(y),max(1,len(y)//500));proxies[v['id']].append(a['world_points'][sample])
            yz=y[:,2];rz=ref[:,2];rayangle=np.degrees(np.arccos(np.clip(np.sum(y*ref,axis=1)/np.linalg.norm(y,axis=1)/np.linalg.norm(ref,axis=1),-1,1)))
            rows.append(dict(kf_idx=idx,source_frame=frame,count=len(y),metric_a=k['metric_a'],
                effective_Z_abs_error_m=stats(np.abs(yz-rz)),effective_Z_relative_error=stats(np.abs(yz-rz)/rz),
                raw_C_scaled_Z_abs_error_m=stats(np.abs(yz/k['metric_a']-rz)),effective_Z_ratio=stats(yz/rz),
                effective_3D_error_m=stats(np.linalg.norm(y-ref,axis=1)),ray_angle_deg=stats(rayangle),
                reference_local_roundtrip_error_m=stats(np.linalg.norm(transform_points(arms['C11']['world_points'],np.linalg.inv(Qref))-ref,axis=1))))
            offset+=n;count+=len(y);print(name,'KF',idx,'candidates',len(y),flush=True)
        assert offset==full['count'] and count==case['expected_candidates']
        for v in variants:
            p=folder/(v['id']+'.f32');assert p.stat().st_size==count*52;v.update(count=count,map_file=digest(p))
            np.save(folder/(v['id']+'_center_proxy.npy'),np.concatenate(proxies[v['id']]))
        assert variants[0]['map_file']['sha256']==old0['map_hash']['sha256']
        save_json(folder/'manifest.json',dict(case=name,scene=scene,count=count,variants=variants,blocks=blocks,source_residuals=rows,
            C00_A00_SHA256_equal=True,C11_A11_centers_bitwise_equal=True,attributes_frozen=True,canonical_covariance_frozen=True,
            independent_interventions='PASS',packed_inverse_roundtrip='PASS',reference_status=case['reference_status']))
        results[name]=digest(folder/'manifest.json')
    save_json(dest/'completion.json',dict(status='PASS',cases=results,registration=digest(out/'registration.json')))
    print('A1-C map construction PASS.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['register','build']);a=p.parse_args();{'register':register,'build':build}[a.stage]()
