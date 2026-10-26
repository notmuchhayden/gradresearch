#!/usr/bin/env python3
"""Freeze final native candidates and construct A0b maps and controls."""
from pathlib import Path
import csv
import gzip
import json
import shutil
import sys
import numpy as np
import torch
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1];UP=ROOT/'thirdparty/Splatt3R-SLAM'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(UP),str(UP/'scripts'),str(UP/'splatt3r_core')]
from prepare_e2b_run import digest,save_json
from prepare_a0b import load_context,stats,SPEC
from a0b_geometry import load_calibrations,camera_model,source_rays,resize_contract
from pointmap_contract import build_arms,sim3_from_xyzw,sim3_parts,transform_points,transform_covariance,array_hash,stratified_subset
from run_n1_contract import native_mask
from e4_budget import pack_parameters,unpack_parameters
from splatt3r_slam.splatt3r_utils import prepare_gaussians_local,bake_gaussians_world
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
from utils.geometry import build_covariance


def main():
    torch.set_num_threads(2)
    assert torch.cuda.is_available(), 'Host GPU needed to replay original TF32 native export'
    spec,out,run,frames,mapping,lookup,poses=load_context();pre=out/'preflight';dest=out/'oracles'
    assert json.loads((out/'registration.json').read_text())['spec']==digest(SPEC)
    manifest=json.loads((pre/'manifest.json').read_text())
    for row in manifest['inputs']:assert digest(ROOT/row['path'])==row,row['path']
    assert manifest['gates']['pipeline_reference_coverage'] and manifest['gates']['prefix_epipolar']
    dest.mkdir(exist_ok=False)
    amend=ROOT/'configs/a0b_amendment_A1.json';save_json(dest/'registration.json',dict(spec=digest(SPEC),amendment=digest(amend),
        before_factorial_maps=True,before_local_prediction_residuals=True))
    sources=[SPEC,amend,Path(__file__),ROOT/'src/a0b_geometry.py',ROOT/'src/pointmap_contract.py',ROOT/'scripts/run_n1_contract.py',
        ROOT/'scripts/prepare_a0b.py',ROOT/'src/e4_budget.py',UP/'splatt3r_slam/splatt3r_utils.py',UP/'splatt3r_core/utils/geometry.py']
    for p in sources:
        q=dest/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(dest/'source_manifest.json',[digest(p) for p in sources])
    alignment=json.loads((pre/'alignment.json').read_text());gauge=np.array(alignment['gauge']);C=alignment['C']
    dump=torch.load(run/'map/HKairport01_kfgauss.pt',map_location='cpu',weights_only=True)
    cal=load_calibrations(ROOT/spec['calibration_file']);models={n:camera_model(cal,n) for n in spec['camera_models']}
    nf=json.loads((ROOT/spec['native_filter_contract']).read_text())['native_filter']
    # Extra global gauge is fitted on prefix mapping poses only.
    tr=np.loadtxt(run/'map/HKairport01_frames.txt');times=np.array([f['rgb_timestamp'] for f in mapping])
    ids=np.argmin(np.abs(tr[:,0,None]-times[None,:]),axis=1);grid=np.array([mapping[i]['grid_index'] for i in ids]);take=grid<100
    ref=np.array([poses[i] for i in grid]);predR=Rotation.from_quat(tr[:,4:8]).as_matrix()
    R=Rotation.from_matrix(ref[take,:3,:3]@np.swapaxes(predR[take],1,2)).mean().as_matrix()
    x=tr[take,1:4];y=ref[take,:3,3];xc=x-x.mean(0);yc=y-y.mean(0)
    scale=np.sum((xc@R.T)*yc)/np.sum(xc**2);assert scale>0
    orient=np.eye(4);orient[:3,:3]=scale*R;orient[:3,3]=y.mean(0)-scale*R@x.mean(0)
    orientC=scale*float(dump['keyframes'][0]['T_WC'].reshape(8)[7])
    save_json(dest/'gauge_sensitivity.json',dict(matrix=orient.tolist(),C=orientC,prefix_grid_ids=grid[take].tolist(),
        main_vs_orientation_gauge_rotation_deg=float(np.degrees(Rotation.from_matrix(R@sim3_parts(gauge)[1].T).magnitude())),
        prefix_position_residual_m=stats(np.linalg.norm(transform_points(x,orient)-y,axis=1)),
        post_position_residual_m=stats(np.linalg.norm(transform_points(tr[~take,1:4],orient)-ref[~take,:3,3],axis=1))))
    variants=[]
    def add(scope,arm,model='HKairport_released',factor=1.,gauge_name='position'):
        vid=f'{scope}_{arm}_{model}_C{factor:g}_{gauge_name}'
        variants.append(dict(id=vid,scope=scope,arm=arm,model=model,C_multiplier=factor,gauge=gauge_name,count=0,blocks=[],
            map_file=str((dest/(vid+'.f32')).relative_to(ROOT))))
    for scope in ['strict','full_map']:
        for arm in ['A00','A10','A01','A11']:add(scope,arm)
    for arm in ['Z10','Z11']:add('strict',arm)
    for factor in [.8,1.25]:
        for arm in ['A00','A10','A01','A11']:add('strict',arm,factor=factor)
    for model in list(models)[1:]:
        for arm in ['A00','A10','A01','A11']:add('strict',arm,model=model)
    for arm in ['A00','A10','A01','A11']:add('strict',arm,gauge_name='orientation')
    for v in variants:(ROOT/v['map_file']).touch(exist_ok=False)
    proxies={v['id']:[] for v in variants};rows=[];baked=[];native_replay=[];checks=[]
    h,w=manifest['hw'];yy,xx=np.indices((h,w));uv=np.column_stack([xx.ravel(),yy.ravel()])
    with gzip.open(dest/'candidate_registry.csv.gz','wt',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['candidate_id','kf_idx','mapping_index','grid_index','u','v','native_active','all_camera_reference_valid','strict_selected'])
        for k in dump['keyframes']:
            idx=k['kf_idx'];grid_id=mapping[k['frame_id']]['grid_index'];post=grid_id>=100
            line=next(r for r in alignment['lineage'] if r['kf_idx']==idx)
            native=native_mask(k,nf);local={key:k[key] for key in ['means','scales','rotations','sh','opacities','conf']}
            prepared=prepare_gaussians_local(local,k['img'],h,w,**nf)
            assert torch.equal(prepared[0],k['means'][native])
            cov=build_covariance(prepared[1],prepared[2]).numpy();rgb=prepared[3].numpy();opacity=prepared[4].numpy()
            raw=k['means'].numpy()[native];pix=uv[native];n=len(uv)
            valid_by_model={};refs={}
            for name in models:
                refdata=np.load(pre/'references'/f'{name}_source_{grid_id:03d}.npz');refs[name]=refdata['depth']
                valid_by_model[name]=refdata['valid'].ravel()
            reference_intersection=np.logical_and.reduce(list(valid_by_model.values()))
            common=native&reference_intersection;replace=common[native];select_strict=replace.copy()
            if not post:select_strict[:]=False
            cids=np.array([f"{line['event']}:self:{j}" for j in np.flatnonzero(native)])
            np.savez_compressed(dest/f'kf{idx:03d}_registry.npz',native_mask=native,reference_intersection=reference_intersection,
                strict_mask=common&post,active_candidate_ids=cids,raw_xyz=k['means'].numpy(),uv=uv)
            for j in range(n):writer.writerow([f"{line['event']}:self:{j}",idx,k['frame_id'],grid_id,int(uv[j,0]),int(uv[j,1]),
                int(native[j]),int(reference_intersection[j]),int(common[j] and post)])
            raw_pose=sim3_from_xyzw(k['T_WC'].numpy());gt_pose=poses[grid_id]
            attrs=dict(rgb=rgb,opacity=opacity,raw_scales=k['scales'].numpy()[native],raw_rotations=k['rotations'].numpy()[native])
            sample=stratified_subset(uv,k['means'].numpy()[:,2]*C,common&post,(h,w),idx,[8,8],[25.,50.,75.,100.],8)
            in_active=np.searchsorted(np.flatnonzero(native),sample)
            cache={}
            for v in variants:
                selected=select_strict if v['scope']=='strict' else np.ones(len(raw),bool)
                if not selected.any():continue
                unit=(orientC if v['gauge']=='orientation' else C)*v['C_multiplier'];G=orient if v['gauge']=='orientation' else gauge
                key=(v['model'],unit,v['gauge'])
                if key not in cache:
                    local_ref=raw.astype(float)*unit
                    rays=source_rays(pix[replace],models[v['model']]);z=refs[v['model']].ravel()[native][replace]
                    local_ref[replace]=rays*z[:,None]
                    arms=build_arms(raw,local_ref,raw_pose,gt_pose,G,unit,cov,cids,replace,attrs)
                    cache[key]=arms
                arms=cache[key];arm=v['arm']
                if arm in arms:geometry=arms[arm]
                else:
                    p=raw.astype(float)*unit;z=refs[v['model']].ravel()[native][replace]
                    p[replace]=raw[replace]/raw[replace,2:3]*z[:,None]
                    placement=arms['A10' if arm=='Z10' else 'A11']['placement']
                    geometry=dict(world_points_m=transform_points(p,placement),world_covariance_m2=transform_covariance(cov*unit**2,placement))
                packed=pack_parameters(geometry['world_points_m'][selected],geometry['world_covariance_m2'][selected],rgb[selected],opacity[selected])
                with (ROOT/v['map_file']).open('ab') as f:packed.tofile(f)
                v['count']+=len(packed);v['blocks'].append(dict(kf_idx=idx,grid_index=grid_id,count=len(packed),
                    candidate_id_hash=array_hash(cids[selected]),attribute_hashes={a:array_hash(b[selected]) for a,b in attrs.items()}))
                proxies[v['id']].append(geometry['world_points_m'][in_active])
                # Verify serialized coordinates/attributes, not only construction arrays.
                mu,cworld,crgb,copa=unpack_parameters(packed)
                np.testing.assert_allclose(mu,geometry['world_points_m'][selected],atol=2e-5,rtol=1e-6)
                np.testing.assert_allclose(cworld,geometry['world_covariance_m2'][selected],atol=1e-5,rtol=1e-5)
                np.testing.assert_array_equal(crgb,rgb[selected]);np.testing.assert_array_equal(copa,opacity[selected])
            main=cache[('HKairport_released',C,'position')]
            np.testing.assert_allclose(main['A00']['world_points_m'],transform_points(raw,gauge@raw_pose),atol=1e-9)
            for f in [.8,1.25]:
                if ('HKairport_released',C*f,'position') in cache:
                    np.testing.assert_allclose(cache[('HKairport_released',C*f,'position')]['A00']['world_points_m'],main['A00']['world_points_m'],atol=1e-9)
            p=main['A10']['local_points_m'][replace];pred=raw[replace]*C
            rows.append(dict(kf_idx=idx,mapping_index=k['frame_id'],grid_index=grid_id,post_prefix=post,raw_candidates=n,native_active=int(native.sum()),
                reference_valid_by_model={m:int((native&v).sum()) for m,v in valid_by_model.items()},common_candidates=int(common.sum()),
                strict_candidates=int(select_strict.sum()),raw_scale=sim3_parts(raw_pose)[0],
                local_depth_error_m=stats(np.abs(pred[:,2]-p[:,2])),local_depth_ratio_pred_over_lidar=stats(pred[:,2]/p[:,2]),
                raw_local_z_m=stats(pred[:,2]),lidar_z_m=stats(p[:,2]),
                predicted_vs_physical_ray_angle_deg=stats(np.degrees(np.arccos(np.clip(np.sum(pred*p,axis=1)/np.linalg.norm(pred,axis=1)/np.linalg.norm(p,axis=1),-1,1))))))
            # Native export comparison before global metric gauge, in CPU float64.
            baked.append(dict(means=transform_points(raw,raw_pose),cov=transform_covariance(cov,raw_pose),rgb=rgb,opacity=opacity))
            import lietorch
            torch.backends.cuda.matmul.allow_tf32=True
            native_replay.append(tuple(a.cpu() for a in bake_gaussians_world({key:a.cuda() for key,a in local.items()},
                k['img'].cuda(),h,w,lietorch.Sim3(k['T_WC'].cuda()),**nf)))
            torch.backends.cuda.matmul.allow_tf32=False
            print('Built KF',idx,'grid',grid_id,'strict',select_strict.sum(),flush=True)
    native_ply=run/'map/HKairport01_gaussians.ply'
    ply=decode_gaussians_from_ply(native_ply,device='cpu')
    replay=[torch.cat([a[i] for a in native_replay]) for i in range(4)]
    rc=torch.triu_indices(3,3)
    torch.testing.assert_close(ply['means'],replay[0],atol=1e-5,rtol=1e-5)
    torch.testing.assert_close(ply['covariances'][:,rc[0],rc[1]],replay[1],atol=1e-5,rtol=1e-4)
    torch.testing.assert_close(ply['rgb'],replay[2],atol=1e-5,rtol=1e-5)
    torch.testing.assert_close(ply['opacity'],replay[3],atol=1e-6,rtol=1e-5)
    for key,nkey in [('means','means'),('cov','covariances'),('rgb','rgb'),('opacity','opacity')]:
        expected=np.concatenate([a[key] for a in baked]);actual=ply[nkey].numpy()
        checks.append(dict(field=key,native_TF32_vs_float64_max_abs=float(np.max(np.abs(actual-expected))),original_GPU_export_replay='PASS'))
    assert ply['n']==sum(r['native_active'] for r in rows)
    primary=variants[0];assert primary['count']>=spec['gates']['min_common_candidates']
    assert sum(r['strict_candidates']>0 for r in rows)>=spec['gates']['min_post_prefix_kfs']
    for v in variants:
        assert v['blocks']==(primary['blocks'] if v['scope']=='strict' else variants[4]['blocks'])
        assert (ROOT/v['map_file']).stat().st_size==v['count']*52
        v['hash']=digest(ROOT/v['map_file'])
        np.save(dest/(v['id']+'_center_proxy.npy'),np.concatenate(proxies[v['id']]))
    # Float32 C-invariance must hold in the actual serialized compact maps.
    first=np.memmap(ROOT/primary['map_file'],dtype=np.float32,mode='r',shape=(primary['count'],13))
    invariance=[]
    for v in variants:
        if v['scope']=='strict' and v['arm']=='A00' and v['model']=='HKairport_released' and v['gauge']=='position':
            a=np.memmap(ROOT/v['map_file'],dtype=np.float32,mode='r',shape=(v['count'],13))
            delta=float(np.max(np.abs(first-a)));assert delta==0
            invariance.append(dict(id=v['id'],max_abs_delta=delta))
    save_json(dest/'candidate_manifest.json',rows)
    save_json(dest/'manifest.json',dict(spec=digest(SPEC),amendment=digest(amend),preflight=digest(pre/'manifest.json'),alignment=digest(pre/'alignment.json'),
        variants=variants,C=C,gauge=gauge.tolist(),native_ply_parity=checks,native_ply=digest(native_ply),C_A00_packed_invariance=invariance,
        strict_candidate_count=primary['count'],native_active=ply['n'],all_strict_variants_same_candidate_IDs=True,
        packed_roundtrip='PASS every block',raw_attributes_frozen=True,local_reference_coverage_intersection=True))
    print(json.dumps(dict(variants=len(variants),strict_candidates=primary['count'],native_active=ply['n']),indent=2),flush=True)


if __name__=='__main__':main()
