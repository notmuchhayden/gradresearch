#!/usr/bin/env python3
"""Register, construct and render the A1-U invariance experiment.

No new network inference, oracle intervention, gauge estimation or GT fitting.
Original A0/A0b files are read only; every stage preserves its inputs by hash.
"""
from datetime import datetime
from pathlib import Path
import argparse
import csv
import gc
import json
import shutil
import sys

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / 'thirdparty/Splatt3R-SLAM'
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts'), str(UP), str(UP/'scripts'), str(UP/'splatt3r_core')]
from prepare_e2b_run import digest, save_json
from pointmap_contract import array_hash, metric_placement, sim3_from_xyzw, sim3_parts, transform_points, transform_covariance
from scale_reparameterization import absorb_scale, restore_scale, reallocate_scale, absorb_standard_deviations
from e4_budget import pack_parameters

SPEC = ROOT / 'configs/a1_unit_reparameterization.json'


def context():
    spec = json.loads(SPEC.read_text())
    return spec, ROOT/spec['output']


def variant(manifest, name):
    return next(v for v in manifest['variants'] if v['id'] == name)


def capture(paths, destination):
    for p in paths:
        q = destination/p.relative_to(ROOT)
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, q)


def source_paths():
    return [SPEC, Path(__file__), ROOT/'src/scale_reparameterization.py', ROOT/'tests/test_scale_reparameterization.py',
            ROOT/'src/pointmap_contract.py', ROOT/'src/e4_budget.py', ROOT/'scripts/evaluate_e4.py',
            ROOT/'scripts/run_n1_contract.py', ROOT/'src/a0b_geometry.py', ROOT/'src/e1_taxonomy.py',
            UP/'splatt3r_slam/splatt3r_utils.py', UP/'splatt3r_core/utils/geometry.py']


def register():
    spec, out = context()
    out.mkdir(parents=True, exist_ok=False)
    capture(source_paths(), out/'registered_code')
    paths = {SPEC, ROOT/spec['native_filter_contract']}
    for scene, case in spec['scenes'].items():
        run, oracle = ROOT/case['baseline'], ROOT/case['oracle_root']
        paths.update([run/case['dump'], run/case['native_ply'], run/'run_manifest.json', run/'audit/events.jsonl',
                      ROOT/case['alignment'], oracle/'manifest.json', ROOT/case['camera'], ROOT/case['evaluation_poses']])
        old = json.loads((oracle/'manifest.json').read_text())
        for key in ['full_variant', 'strict_variant']:
            v = variant(old, case[key]);p = ROOT/v['map_file']
            assert digest(p) == v.get('map_hash', v.get('hash'))
            paths.add(p)
        dump = torch.load(run/case['dump'], map_location='cpu', weights_only=True)
        assert dump['n'] == case['expected_keyframes']
        for kf in dump['keyframes']:
            paths.add(oracle/case['registry_template'].format(index=kf['kf_idx']))
        events = [json.loads(line) for line in (run/'audit/events.jsonl').read_text().splitlines()]
        final = next(e for e in reversed(events) if e['kind']=='snapshot' and e['stage']=='final')
        sp = run/'audit'/final['file'];paths.add(sp)
        snapshot = torch.load(sp, map_location='cpu', weights_only=True)
        for kf in dump['keyframes']:
            m = next(m for m in snapshot['metadata'] if m['kf_idx']==kf['kf_idx'] and m['frame_id']==kf['frame_id'])
            paths.add(run/'exports/raw_pairs'/(m['candidate_event']+'.pt'))
        historical = old.get('inputs')
        if historical is None:
            pp = ROOT/case['prior_manifest'];paths.add(pp)
            historical = json.loads(pp.read_text())['inputs']
            paths.add(ROOT/case['split'])
        historical = {r['path']: r for r in historical}
        for p in [run/case['dump'], ROOT/case['alignment']] if scene=='office2' else [run/case['dump']]:
            rel = str(p.relative_to(ROOT))
            if rel in historical:
                assert digest(p) == historical[rel], rel
    inputs = [digest(p) for p in sorted(paths)]
    save_json(out/'registration.json', dict(experiment='A1-U', spec=digest(SPEC),
        registered_at=datetime.now().astimezone().isoformat(),
        phase='before synthetic tests, real-map construction, CUDA smoke or invariance outcomes',
        inputs=inputs, code=[digest(p) for p in source_paths()],
        original_results_known=['office2 A0', 'HKairport01 A0b'], no_A1_results_inspected=True))
    print('Registered A1-U thresholds and', len(inputs), 'immutable input files.', flush=True)


def checked():
    spec, out = context()
    r = json.loads((out/'registration.json').read_text())
    assert digest(SPEC) == r['spec']
    for row in r['code'] + r['inputs']:
        assert digest(ROOT/row['path']) == row, row['path']
    return spec, out


def compare(a, b, atol, rtol):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
    error = np.abs(a-b)
    np.testing.assert_allclose(a, b, atol=atol, rtol=rtol)
    normalized = error/(atol+rtol*np.abs(b))
    return dict(max_abs=float(error.max()) if error.size else 0.,
                max_tolerance_fraction=float(normalized.max()) if normalized.size else 0.)


def build():
    spec, out = checked()
    assert torch.cuda.is_available(), 'Host GPU needed for exact native TF32 export replay'
    from run_n1_contract import native_mask
    from splatt3r_slam.splatt3r_utils import prepare_gaussians_local, bake_gaussians_world
    from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
    from utils.geometry import build_covariance
    import lietorch
    torch.set_num_threads(2)
    dest = out/'construction';dest.mkdir(exist_ok=False)
    nf = json.loads((ROOT/spec['native_filter_contract']).read_text())['native_filter']
    tol = spec['thresholds']['float64'];packed_tol = spec['thresholds']['packed_float32']
    scene_results = {}
    for scene, case in spec['scenes'].items():
        folder = dest/scene;folder.mkdir();(folder/'local').mkdir()
        run, oldroot = ROOT/case['baseline'], ROOT/case['oracle_root']
        old = json.loads((oldroot/'manifest.json').read_text())
        full, strict = [variant(old, case[k]) for k in ['full_variant','strict_variant']]
        oldfull = np.memmap(ROOT/full['map_file'], dtype=np.float32, mode='r', shape=(full['count'],13))
        oldstrict = np.memmap(ROOT/strict['map_file'], dtype=np.float32, mode='r', shape=(strict['count'],13))
        alignment = json.loads((ROOT/case['alignment']).read_text())
        G, C = np.array(alignment[case['alignment_gauge_key']]), alignment[case['alignment_C_key']]
        dump = torch.load(run/case['dump'], map_location='cpu', weights_only=True)
        events = [json.loads(line) for line in (run/'audit/events.jsonl').read_text().splitlines()]
        last = next(e for e in reversed(events) if e['kind']=='snapshot' and e['stage']=='final')
        snapshot = torch.load(run/'audit'/last['file'], map_location='cpu', weights_only=True)
        names = list(spec['variants']) + list(spec['negative_controls'])
        for name in names:(folder/(name+'.f32')).touch(exist_ok=False)
        strict_offsets = {};cursor=0
        for block in strict['blocks']:
            strict_offsets[block['kf_idx']] = (cursor, block['count']);cursor += block['count']
        assert cursor == case['expected_strict']
        rng=np.random.default_rng(spec['KF_reallocation']['seed']);offset=0;rows=[];checks=[];native_replay=[]
        for kf, fullblock in zip(dump['keyframes'], full['blocks']):
            index = kf['kf_idx'];assert index==fullblock['kf_idx']
            matching = [i for i,m in enumerate(snapshot['metadata']) if m['kf_idx']==index and m['frame_id']==kf['frame_id']]
            assert len(matching)==1
            slot=matching[0];meta=snapshot['metadata'][slot]
            assert torch.equal(kf['T_WC'].reshape(8), snapshot['poses'][slot].reshape(8))
            rawpath=run/'exports/raw_pairs'/(meta['candidate_event']+'.pt')
            rawpair=torch.load(rawpath, map_location='cpu', weights_only=True)
            assert rawpair['source_pair_ids'][0][0]==kf['frame_id'] and rawpair['coordinate_frame']=='first_source_camera'
            assert torch.equal(rawpair['outputs'][0]['means'], rawpair['outputs'][0]['pts3d'])
            for key in ['means','scales','rotations','sh','opacities','conf']:
                assert torch.equal(kf[key], rawpair['outputs'][0][key].reshape_as(kf[key]))
            registry=np.load(oldroot/case['registry_template'].format(index=index))
            mask=registry['native_mask'];np.testing.assert_array_equal(mask, native_mask(kf,nf))
            ids=np.array([f"{meta['candidate_event']}:self:{i}" for i in np.flatnonzero(mask)])
            idhash=array_hash(ids);assert idhash==fullblock.get('id_hash',fullblock.get('candidate_id_hash'))
            np.testing.assert_array_equal(ids, registry['active_candidate_ids'])
            local={key:kf[key] for key in ['means','scales','rotations','sh','opacities','conf']}
            h,w=kf['img_shape'];prepared=prepare_gaussians_local(local,kf['img'],h,w,**nf)
            torch.testing.assert_close(prepared[0],kf['means'][mask],atol=0,rtol=0)
            raw=prepared[0].numpy().astype(np.float64);covraw=build_covariance(prepared[1],prepared[2]).numpy().astype(np.float64)
            rgb=prepared[3].numpy();opacity=prepared[4].numpy();n=len(raw);assert n==fullblock['count']
            pose=sim3_from_xyzw(kf['T_WC'].numpy());P=metric_placement(pose,G,C)
            x, covariance=raw*C,covraw*C**2
            wm,wc=transform_points(x,P),transform_covariance(covariance,P)
            original_packed=pack_parameters(wm,wc,rgb,opacity)
            # Recompute the old A00 path independently; do not use canonical values as baseline.
            compare(original_packed[:,:3], oldfull[offset:offset+n,:3],packed_tol['point_atol_m'],packed_tol['rtol'])
            compare(original_packed[:,3:9],oldfull[offset:offset+n,3:9],packed_tol['covariance_atol_m2'],packed_tol['rtol'])
            np.testing.assert_array_equal(original_packed[:,9:],oldfull[offset:offset+n,9:])
            attrs=dict(rgb=rgb,opacity=opacity,raw_scales=kf['scales'].numpy()[mask],
                       raw_rotation=kf['rotations'].numpy()[mask],raw_sh=kf['sh'].numpy()[mask])
            oldattrs=fullblock.get('attributes_hashes',fullblock.get('attribute_hashes'))
            for attr,value in oldattrs.items():
                source_key='raw_rotation' if attr=='raw_rotations' else attr
                assert array_hash(attrs[source_key])==value, attr
            canonical=absorb_scale(x,covariance,P)
            rp,rc,rt=restore_scale(canonical)
            inverse_checks=dict(points=compare(rp,x,tol['point_atol_m'],tol['rtol']),
                covariance=compare(rc,covariance,tol['covariance_atol_m2'],tol['rtol']),pose=compare(rt,P,tol['pose_atol'],tol['rtol']))
            np.testing.assert_array_equal(canonical.rigid_placement[:3,3],P[:3,3])
            q=float(np.exp(rng.uniform(np.log(.5),np.log(2.))))
            stdmetric=prepared[1].numpy().astype(float)*C
            effective_std=absorb_standard_deviations(stdmetric,canonical.absorbed_scale)
            # Check the std->covariance rule independently in float64. The frozen
            # original covariance remains the exact float32-built source for maps.
            rot64=prepared[2].double()
            base_std_cov=build_covariance(torch.from_numpy(stdmetric),rot64).numpy()
            scaled_std_cov=build_covariance(torch.from_numpy(effective_std),rot64).numpy()
            stdcheck=compare(scaled_std_cov,base_std_cov*canonical.absorbed_scale**2,tol['covariance_atol_m2'],tol['rtol'])
            np.savez_compressed(folder/'local'/f'kf{index:03d}.npz',y=canonical.points,covariance_y=canonical.covariance,
                standard_deviations_y=effective_std,raw_local_rotation=prepared[2].numpy(),rigid_Q=canonical.rigid_placement,
                absorbed_scale=canonical.absorbed_scale,C=C,reallocation_q=q,active_pixel_indices=np.flatnonzero(mask),
                candidate_event=meta['candidate_event'])
            s_use=(registry['common_mask'] if scene=='office2' else registry['strict_mask'])[mask] if index in strict_offsets else np.zeros(n,bool)
            if index in strict_offsets:
                so,sn=strict_offsets[index];assert s_use.sum()==sn
                assert array_hash(ids[s_use])==next(b for b in strict['blocks'] if b['kf_idx']==index).get('id_hash',next(b for b in strict['blocks'] if b['kf_idx']==index).get('candidate_id_hash'))
            for name,definition in spec['variants'].items():
                cm=C*definition['C_multiplier'];metric=metric_placement(pose,G,cm)
                points,cov=raw*cm,covraw*cm**2
                if definition['KF_reallocation']:points,cov,metric=reallocate_scale(points,cov,metric,q)
                c=absorb_scale(points,cov,metric)
                local_check=dict(points=compare(c.points,canonical.points,tol['point_atol_m'],tol['rtol']),
                    covariance=compare(c.covariance,canonical.covariance,tol['covariance_atol_m2'],tol['rtol']),
                    Q=compare(c.rigid_placement,canonical.rigid_placement,tol['pose_atol'],tol['rtol']))
                mu,worldcov=transform_points(c.points,c.rigid_placement),transform_covariance(c.covariance,c.rigid_placement)
                checks.append(dict(kf_idx=index,variant=name,
                    world_points=compare(mu,wm,tol['point_atol_m'],tol['rtol']),
                    world_covariance=compare(worldcov,wc,tol['covariance_atol_m2'],tol['rtol']),canonical_local=local_check))
                packed=pack_parameters(mu,worldcov,rgb,opacity)
                compare(packed[:,:3],oldfull[offset:offset+n,:3],packed_tol['point_atol_m'],packed_tol['rtol'])
                compare(packed[:,3:9],oldfull[offset:offset+n,3:9],packed_tol['covariance_atol_m2'],packed_tol['rtol'])
                np.testing.assert_array_equal(packed[:,9:],oldfull[offset:offset+n,9:])
                if index in strict_offsets:
                    compare(packed[s_use,:9],oldstrict[so:so+sn,:9],packed_tol['covariance_atol_m2'],packed_tol['rtol'])
                    np.testing.assert_array_equal(packed[s_use,9:],oldstrict[so:so+sn,9:])
                with (folder/(name+'.f32')).open('ab') as f:packed.tofile(f)
            bad_cov=transform_covariance(covariance,canonical.rigid_placement)
            bad_points=transform_points(x,canonical.rigid_placement)
            badcov_rejected=not np.allclose(bad_cov,wc,atol=tol['covariance_atol_m2'],rtol=tol['rtol'])
            badpoint_rejected=not np.allclose(bad_points,wm,atol=tol['point_atol_m'],rtol=tol['rtol'])
            nonunit=not np.isclose(canonical.absorbed_scale,1.,atol=1e-8,rtol=0)
            if nonunit:assert badcov_rejected and badpoint_rejected
            for name,point,cov in [('mean_only_absorption',wm,bad_cov),('naive_scale_removal',bad_points,wc)]:
                with (folder/(name+'.f32')).open('ab') as f:pack_parameters(point,cov,rgb,opacity).tofile(f)
            rows.append(dict(kf_idx=index,frame_id=kf['frame_id'],candidate_event=meta['candidate_event'],active=n,strict_count=int(s_use.sum()),
                C=C,raw_pose_scale=sim3_parts(pose)[0],metric_a=canonical.absorbed_scale,q=q,
                effective_m_per_raw=C*canonical.absorbed_scale,pose_revision=snapshot['pose_revision'],
                candidate_id_hash=idhash,native_mask_hash=array_hash(mask),attributes={k:array_hash(v) for k,v in attrs.items()},
                inverse=inverse_checks,standard_deviation_rule=stdcheck,
                negative_control_nonunit_KF=bool(nonunit),mean_only_covariance_error_max_m2=float(np.abs(bad_cov-wc).max()),
                naive_scale_removal_point_error_max_m=float(np.abs(bad_points-wm).max()),
                negative_covariance_rejected=badcov_rejected,negative_mean_rejected=badpoint_rejected,
                local_file=digest(folder/'local'/f'kf{index:03d}.npz')))
            torch.backends.cuda.matmul.allow_tf32=True
            native_replay.append(tuple(a.cpu() for a in bake_gaussians_world({key:a.cuda() for key,a in local.items()},
                kf['img'].cuda(),h,w,lietorch.Sim3(kf['T_WC'].cuda()),**nf)))
            torch.backends.cuda.matmul.allow_tf32=False
            offset+=n
            print(scene,'KF',index,'a=',canonical.absorbed_scale,'active=',n,flush=True)
        assert offset==case['expected_active'] and len(rows)==case['expected_keyframes']
        ply=decode_gaussians_from_ply(run/case['native_ply'],device='cpu');assert ply['n']==offset
        replay=[torch.cat([p[i] for p in native_replay]) for i in range(4)];ij=torch.triu_indices(3,3)
        nt=spec['thresholds']['original_GPU_export_replay']
        torch.testing.assert_close(replay[0],ply['means'],atol=nt['means_atol'],rtol=nt['means_rtol'])
        torch.testing.assert_close(replay[1],ply['covariances'][:,ij[0],ij[1]],atol=nt['covariance_atol'],rtol=nt['covariance_rtol'])
        torch.testing.assert_close(replay[2],ply['rgb'],atol=nt['RGB_atol'],rtol=nt['means_rtol'])
        torch.testing.assert_close(replay[3],ply['opacity'],atol=nt['opacity_atol'],rtol=nt['means_rtol'])
        maps=[]
        for name in names:
            path=folder/(name+'.f32');assert path.stat().st_size==offset*52
            packed=np.memmap(path,dtype=np.float32,mode='r',shape=(offset,13))
            difference=np.abs(packed-oldfull)
            maps.append(dict(id=name,negative=name in spec['negative_controls'],count=offset,file=digest(path),
                changed_float_count=int(np.count_nonzero(difference)),point_max_abs_m=float(difference[:,:3].max()),
                covariance_max_abs_m2=float(difference[:,3:9].max()),attributes_bitwise_equal=bool(np.array_equal(packed[:,9:],oldfull[:,9:]))))
            assert maps[-1]['attributes_bitwise_equal']
        result=dict(scene=scene,status='PASS',active=offset,strict_checked=case['expected_strict'],keyframes=rows,maps=maps,
            algebraic_checks=checks,native_GPU_TF32_replay='PASS',prior_A00_replay='PASS',
            negative_controls_rejected_KFs=sum(x['negative_control_nonunit_KF'] for x in rows),
            reference_status=case['reference_status'],gauge=G.tolist(),C=C)
        save_json(folder/'manifest.json',result);scene_results[scene]=digest(folder/'manifest.json')
        del dump,snapshot,oldfull,oldstrict,ply,replay,native_replay;gc.collect();torch.cuda.empty_cache()
    save_json(dest/'completion.json',dict(status='PASS',scenes=scene_results,registration=digest(out/'registration.json')))
    print('A1-U construction and full native-map provenance PASS.',flush=True)


def views(scene,case):
    from e1_taxonomy import camera_geometry
    if scene=='office2':
        camera=json.loads((ROOT/case['camera']).read_text())['camera']
        K,_,crop=camera_geometry(camera);hw=tuple(crop[2:])
        poses=np.loadtxt(ROOT/case['evaluation_poses']).reshape(-1,4,4)
        return {f:(poses[f],K,hw) for f in case['view_ids']}
    from a0b_geometry import camera_model,load_calibrations,resize_contract
    m=camera_model(load_calibrations(ROOT/case['camera']),'HKairport_released');A,hw,_,_=resize_contract();K=A@m['K']
    records=json.loads((ROOT/case['evaluation_poses']).read_text());lookup={r['OriginalImageName']:r for r in records}
    frames=json.loads((ROOT/case['split']).read_text())['scene_splits'][scene]['frames']
    return {f:(np.array(lookup[Path(frames[f]['rgb_member']).name]['T4x4']),K,hw) for f in case['view_ids']}


def render_difference(test,ref,tol):
    def error(a,b):
        d=np.abs(a.astype(np.float64)-b);assert np.isfinite(d).all()
        return dict(max_abs=float(d.max()) if d.size else 0.,mean_abs=float(d.mean()) if d.size else 0.)
    w0,w1=ref['weight'],test['weight'];covered0=w0>tol['weight_min'];covered1=w1>tol['weight_min']
    common=covered0&covered1
    def depth(a,w):return np.divide(a,w,out=np.zeros_like(a),where=w>tol['weight_min'])
    d0=depth(ref['numerator'],w0);d1=depth(test['numerator'],w1)
    rgb=error(test['rgb'],ref['rgb']);weight=error(w1,w0);dep=error(d1[common],d0[common])
    mismatch=int(np.count_nonzero(covered0!=covered1))
    passed=(rgb['max_abs']<=tol['RGB_max_abs'] and rgb['mean_abs']<=tol['RGB_mean_abs'] and
        weight['max_abs']<=tol['weight_max_abs'] and weight['mean_abs']<=tol['weight_mean_abs'] and
        dep['max_abs']<=tol['depth_max_abs_m'] and dep['mean_abs']<=tol['depth_mean_abs_m'] and
        mismatch<=tol['covered_mask_disagreements'])
    return dict(status='PASS' if passed else 'FAIL',RGB=rgb,weight=weight,depth_m=dep,
        coverage_mask_disagreements=mismatch,common_covered_pixels=int(common.sum()),
        total_image_pixels=int(w0.size),numerator=error(test['numerator'],ref['numerator']))


@torch.no_grad()
def evaluate():
    spec,out=checked();assert torch.cuda.is_available()
    from evaluate_e4 import CudaMap
    torch.set_num_threads(2);torch.backends.cuda.matmul.allow_tf32=False
    complete=json.loads((out/'construction/completion.json').read_text());assert complete['status']=='PASS'
    dest=out/'render';dest.mkdir(exist_ok=False)
    save_json(dest/'environment.json',dict(torch=torch.__version__,CUDA=torch.version.cuda,device=torch.cuda.get_device_name(0),TF32=False,
        renderer='existing E4 compact CUDA; no new model inference; unclamped RGB for comparisons'))
    # Verify UAV-distance expected depth and scale/covariance-render equivalence
    # independently of the real maps, using thresholds fixed at registration.
    K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
    xyz=np.array([[0.,0,70.],[0,0,90.]]);cov=np.repeat((np.eye(3)*.5)[None],2,axis=0)
    colors=np.array([[1.,0,0],[0,0,1.]]);opacity=np.array([.5,.5])
    g=CudaMap(pack_parameters(xyz,cov,colors,opacity));d=g.depth(np.eye(4),K,(64,64));z=float(d[32,32,0]/d[32,32,1]);assert 70<z<90
    save_json(dest/'smoke.json',dict(status='PASS',expected_Z_m=[70,90],rendered_Z_m=z));del g;torch.cuda.empty_cache()
    allrows=[]
    def render(path,count,cameras,folder):
        packed=np.array(np.memmap(path,dtype=np.float32,mode='r',shape=(count,13)),copy=True)
        g=CudaMap(packed);del packed
        for view,(pose,K,hw) in cameras.items():
            raw=g.depth(pose,K,hw);rgb=g.render(pose,K,hw).permute(1,2,0).cpu().numpy()
            np.savez_compressed(folder/f'view{view:04d}.npz',rgb=rgb,numerator=raw[:,:,0],weight=raw[:,:,1])
        del g;gc.collect();torch.cuda.empty_cache()
    for scene,case in spec['scenes'].items():
        folder=dest/scene;folder.mkdir();manifest_path=out/'construction'/scene/'manifest.json'
        assert digest(manifest_path)==complete['scenes'][scene]
        construction=json.loads(manifest_path.read_text());n=construction['active'];cameras=views(scene,case)
        old=json.loads((ROOT/case['oracle_root']/'manifest.json').read_text());original=variant(old,case['full_variant'])
        original_path=ROOT/original['map_file'];assert digest(original_path)==original.get('map_hash',original.get('hash'))
        baseline=folder/'original_A00';baseline.mkdir();render(original_path,n,cameras,baseline)
        repeat=folder/'baseline_repeat';repeat.mkdir();first=case['view_ids'][0];render(original_path,n,{first:cameras[first]},repeat)
        with np.load(baseline/f'view{first:04d}.npz') as ref,np.load(repeat/f'view{first:04d}.npz') as other:
            determinism=render_difference(other,ref,spec['thresholds']['render']);assert determinism['status']=='PASS'
        rows=[]
        for m in construction['maps']:
            assert digest(ROOT/m['file']['path'])==m['file']
            target=folder/m['id'];target.mkdir()
            requested=case['negative_render_views'] if m['negative'] else case['view_ids']
            render(ROOT/m['file']['path'],n,{v:cameras[v] for v in requested},target)
            for view in requested:
                with np.load(baseline/f'view{view:04d}.npz') as ref,np.load(target/f'view{view:04d}.npz') as other:
                    difference=render_difference(other,ref,spec['thresholds']['render'])
                row=dict(scene=scene,variant=m['id'],view=view,negative=m['negative'],**difference);rows.append(row)
                if not m['negative']:assert difference['status']=='PASS',row
            if m['negative']:
                assert any(row['status']=='FAIL' for row in rows if row['variant']==m['id']), 'Negative map must visibly violate invariance on registered views'
            print(scene,m['id'],'render checks complete',flush=True)
        save_json(folder/'invariance.json',dict(status='PASS',baseline_determinism=determinism,rows=rows,reference_status=case['reference_status']))
        allrows.extend(rows)
    save_json(dest/'completion.json',dict(status='PASS',rows=allrows,positive_cases=sum(not r['negative'] for r in allrows),
        negative_cases=sum(r['negative'] for r in allrows),positive_failures=sum(not r['negative'] and r['status']!='PASS' for r in allrows)))
    print('A1-U rendered invariance PASS.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['register','build','evaluate']);args=parser.parse_args()
    {'register':register,'build':build,'evaluate':evaluate}[args.stage]()
