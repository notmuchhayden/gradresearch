#!/usr/bin/env python3
"""Register V1 analysis and build immutable lineage, unit and intervention maps."""
from datetime import datetime
from pathlib import Path
import argparse
import gc
import json
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo
import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT/'thirdparty/Splatt3R-SLAM'
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'src'), str(UP), str(UP/'scripts'), str(UP/'splatt3r_core')]
from v1_common import SPEC, context, checked, definitions, ARMS, CZ, OLD, stats
from prepare_e2b_run import digest, save_json
from pointmap_contract import (array_hash, backproject_z, build_arms, fit_prefix_gauge,
    metric_placement, project, sim3_from_xyzw, sim3_parts, transform_points, transform_covariance)
from scale_reparameterization import absorb_scale, restore_scale, reallocate_scale, absorb_standard_deviations
from canonical_oracles import build_canonical_arms
from gauge_support import orientation_prefix_gauge, change_canonical_gauge, sampling_mask
from e4_budget import pack_parameters
from e0b_audit import Audit
from e1_taxonomy import camera_geometry, resize_depth, depth_masks


def register():
    spec, out = context()
    assert not (out/'analysis_registration.json').exists()
    q = json.loads((out/'baseline/qualification.json').read_text())
    assert q['status'] == 'PASS'
    recipe = json.loads((ROOT/spec['recipe']).read_text())
    for row in recipe['source_specs']:
        assert digest(ROOT/row['path']) == row
    baseline = json.loads((out/'registration.json').read_text())
    assert baseline['specification_file'] == digest(ROOT/spec['baseline_spec'])
    assert baseline['specification']['frozen_recipe'] == digest(ROOT/spec['recipe'])
    code = [SPEC, ROOT/spec['recipe'], ROOT/spec['baseline_spec']]
    code += [ROOT/'scripts'/p for p in ['run_v1_baseline.py', 'v1_common.py', 'build_v1.py', 'evaluate_v1.py', 'analyze_v1.py']]
    code += [ROOT/'src'/p for p in ['pointmap_contract.py','scale_reparameterization.py','canonical_oracles.py','gauge_support.py','a0_metrics.py','e4_budget.py','e1_taxonomy.py','e0b_audit.py']]
    code += [ROOT/'scripts'/p for p in ['run_n1_contract.py','evaluate_e4.py','run_a1_unit_invariance.py']]
    code += [UP/'splatt3r_slam/splatt3r_utils.py', UP/'splatt3r_slam/gaussian_ply_codec.py', UP/'splatt3r_core/utils/geometry.py']
    inputs = [out/'registration.json', out/'baseline/run_manifest.json', out/'baseline/qualification.json',
              ROOT/'configs/n1_coordinate_contract.json', ROOT/spec['unit_spec'], ROOT/spec['C_spec']]
    inputs += [out/'baseline/map'/('office3'+s) for s in ['_frames.txt','_kfgauss.pt','_gaussians.ply']]
    inputs += [out/'baseline/audit/events.jsonl']
    # Check all registered office3/camera inputs; office4 is never inspected.
    manifest = json.loads((ROOT/'configs/n2_dataset_manifest.json').read_text())
    for row in manifest['files']:
        if row['path'].startswith('data/N2/Replica/office3/') or row['path'] == 'data/N2/Replica/cam_params.json':
            actual = digest(ROOT/row['path'])
            assert all(actual[k] == row[k] for k in ['path','bytes','sha256']), row['path']
            inputs.append(ROOT/row['path'])
    for p in code:
        target = out/'registered_code'/p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    save_json(out/'analysis_registration.json', dict(registered_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        phase='after fresh RGB-only qualification, before gauge fit, canonical maps or oracle outcomes',
        baseline_qualification_known=q, inputs=[digest(p) for p in inputs], code=[digest(p) for p in code],
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        upstream_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=UP,text=True).strip(),
        office4_predictions_run=False, correction_algorithm=False))
    print('Registered frozen V1 analysis before oracle outcomes.', flush=True)


def build():
    spec, out = checked()
    assert torch.cuda.is_available()
    from run_n1_contract import native_mask
    from splatt3r_slam.splatt3r_utils import prepare_gaussians_local, bake_gaussians_world
    from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
    from utils.geometry import build_covariance
    import lietorch
    from scipy.spatial.transform import Rotation
    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    dest = out/'maps'
    dest.mkdir(exist_ok=False)
    (dest/'local').mkdir()
    run = out/'baseline'
    # Filename-only read-only adapter for the proven E0b journal replay.
    av = dest/'audit_view'
    (av/'map').mkdir(parents=True)
    for name in ['exports','audit']:
        (av/name).symlink_to(run/name, target_is_directory=True)
    for suffix in ['_kfgauss.pt','_frames.txt']:
        (av/'map'/f'office0{suffix}').symlink_to(run/'map'/f'office3{suffix}')
    audit_spec = json.loads((ROOT/'configs/e0b_audit.json').read_text())
    audit_spec['cases']['v1'] = dict(expected_inputs=500)
    save_json(av/'run_manifest.json', dict(case='v1', specification=audit_spec))
    audit = Audit(av)
    journal = audit.validate()
    save_json(dest/'journal_checks.json', journal)
    last = next(e for e in reversed(audit.events) if e['kind']=='snapshot' and e['stage']=='final')
    final = torch.load(run/'audit'/last['file'], map_location='cpu', weights_only=True)
    dump = torch.load(run/'map/office3_kfgauss.pt', map_location='cpu', weights_only=True)
    trajectory = np.loadtxt(run/'map/office3_frames.txt')
    frame_ids = trajectory[:,0].astype(int)
    gt = np.loadtxt(ROOT/'data/N2/Replica/office3/groundtruth.txt')
    np.testing.assert_array_equal(gt[frame_ids,0], frame_ids)
    G, prefix = fit_prefix_gauge(trajectory[:,1:4],gt[frame_ids,1:4],frame_ids,200)
    est = np.array([sim3_from_xyzw([*r[1:8],1.]) for r in trajectory])
    refpose = np.array([sim3_from_xyzw([*r[1:8],1.]) for r in gt])
    Go, observability = orientation_prefix_gauge(est,refpose[frame_ids],frame_ids,200)
    assert prefix.tolist() == observability['prefix_ids']
    D = Go @ np.linalg.inv(G)
    C = sim3_parts(G)[0]*float(dump['keyframes'][0]['T_WC'].reshape(8)[7])
    save_json(dest/'alignment.json', dict(position=G.tolist(),orientation=Go.tolist(),relative=D.tolist(),C=C,
        prefix_ids=prefix.tolist(),observability=observability,pose_revision=final['pose_revision'],
        rotation_difference_deg=float(np.degrees(Rotation.from_matrix(sim3_parts(D)[1]).magnitude())),
        post_prefix_GT_fit=False,offline_final_revision=True))
    camera = json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera']
    K, _, _ = camera_geometry(camera)
    nf_spec = json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())
    nf, mask_spec = nf_spec['native_filter'], nf_spec['common_mask']
    unit = json.loads((ROOT/spec['unit_spec']).read_text())
    tol = unit['thresholds']['float64']
    from run_a1_unit_invariance import compare
    cases = definitions()
    allmaps = {}
    for case, definition in cases.items():
        if definition['kind'] == 'target_only': continue
        folder = dest/case
        folder.mkdir()
        for arm in definition['arms']:
            p = folder/(arm+'.f32')
            p.touch(exist_ok=False)
            allmaps[(case,arm)] = dict(case=case,arm=arm,count=0,path=p)
    uf = dest/'units'
    uf.mkdir()
    unitnames = ['original']+list(unit['variants'])+list(unit['negative_controls'])
    for name in unitnames: (uf/(name+'.f32')).touch(exist_ok=False)
    unitrows, blocks, baked, inputs, source_rows = [], [], [], [], []
    rng = np.random.default_rng(0)
    active_total = strict_total = replaced_total = 0
    def append(case, arm, packed):
        m = allmaps[(case,arm)]
        with m['path'].open('ab') as f: packed.tofile(f)
        m['count'] += len(packed)
    for kf, meta, final_pose in zip(dump['keyframes'], final['metadata'], final['poses']):
        index, frame = kf['kf_idx'], 2*kf['frame_id']
        assert meta['kf_idx'] == index and meta['frame_id'] == kf['frame_id']
        assert torch.equal(kf['T_WC'].reshape(8),final_pose.reshape(8))
        rawpath = run/'exports/raw_pairs'/(meta['candidate_event']+'.pt')
        raw = torch.load(rawpath,map_location='cpu',weights_only=True)
        assert raw['coordinate_frame'] == 'first_source_camera' and raw['source_pair_ids'][0][0] == kf['frame_id']
        assert torch.equal(raw['outputs'][0]['means'],raw['outputs'][0]['pts3d'])
        for key in ['means','scales','rotations','sh','opacities','conf']:
            assert torch.equal(kf[key],raw['outputs'][0][key].reshape_as(kf[key]))
        mask = native_mask(kf,nf)
        local = {key:kf[key] for key in ['means','scales','rotations','sh','opacities','conf']}
        h,w = kf['img_shape']
        prepared = prepare_gaussians_local(local,kf['img'],h,w,**nf)
        torch.testing.assert_close(prepared[0],kf['means'][mask],atol=0,rtol=0)
        xraw = prepared[0].numpy().astype(float)
        covraw = build_covariance(prepared[1],prepared[2]).numpy().astype(float)
        rgb, opacity = prepared[3].numpy(), prepared[4].numpy()
        pixids = np.flatnonzero(mask)
        ids = np.array([f"{meta['candidate_event']}:self:{i}" for i in pixids])
        uv = np.column_stack([pixids%w,pixids//w])
        rawpose = sim3_from_xyzw(kf['T_WC'].numpy())
        P = metric_placement(rawpose,G,C)
        x, cov = xraw*C,covraw*C**2
        can = absorb_scale(x,cov,P)
        y, cy, Q = can.points,can.covariance,can.rigid_placement
        mu, wc = transform_points(x,P),transform_covariance(cov,P)
        original = pack_parameters(mu,wc,rgb,opacity)
        rp, rc, rt = restore_scale(can)
        for a,b,atol in [(rp,x,tol['point_atol_m']),(rc,cov,tol['covariance_atol_m2']),(rt,P,tol['pose_atol'])]:
            compare(a,b,atol,tol['rtol'])
        stdx = prepared[1].numpy().astype(float)*C
        stdy = absorb_standard_deviations(stdx,can.absorbed_scale)
        compare(build_covariance(torch.from_numpy(stdy),prepared[2].double()).numpy(),
            build_covariance(torch.from_numpy(stdx),prepared[2].double()).numpy()*can.absorbed_scale**2,tol['covariance_atol_m2'],tol['rtol'])
        q = float(np.exp(rng.uniform(np.log(.5),np.log(2.))))
        positive_checks = []
        for name, definition in unit['variants'].items():
            cm = C*definition['C_multiplier']
            xp, cp, pp = xraw*cm,covraw*cm**2,metric_placement(rawpose,G,cm)
            if definition['KF_reallocation']: xp,cp,pp = reallocate_scale(xp,cp,pp,q)
            c = absorb_scale(xp,cp,pp)
            for a,b,atol in [(c.points,y,tol['point_atol_m']),(c.covariance,cy,tol['covariance_atol_m2']),
                              (c.rigid_placement,Q,tol['pose_atol']),
                              (transform_points(c.points,c.rigid_placement),mu,tol['point_atol_m']),
                              (transform_covariance(c.covariance,c.rigid_placement),wc,tol['covariance_atol_m2'])]:
                compare(a,b,atol,tol['rtol'])
            packed = pack_parameters(transform_points(c.points,c.rigid_placement),transform_covariance(c.covariance,c.rigid_placement),rgb,opacity)
            np.testing.assert_allclose(packed[:,:3],original[:,:3],atol=2e-5,rtol=1e-6)
            np.testing.assert_allclose(packed[:,3:9],original[:,3:9],atol=1e-5,rtol=1e-6)
            np.testing.assert_array_equal(packed[:,9:],original[:,9:])
            with (uf/(name+'.f32')).open('ab') as f: packed.tofile(f)
            positive_checks.append(name)
        badcov = transform_covariance(cov,Q)
        badmu = transform_points(x,Q)
        nonunit = not np.isclose(can.absorbed_scale,1.,atol=1e-8,rtol=0)
        if nonunit:
            assert not np.allclose(badcov,wc,atol=tol['covariance_atol_m2'],rtol=tol['rtol'])
            assert not np.allclose(badmu,mu,atol=tol['point_atol_m'],rtol=tol['rtol'])
        for name, points, covar in [('original',mu,wc),('mean_only_absorption',mu,badcov),('naive_scale_removal',badmu,wc)]:
            with (uf/(name+'.f32')).open('ab') as f: pack_parameters(points,covar,rgb,opacity).tofile(f)
        dp = ROOT/'data/N2/Replica/office3/results'/f'depth{frame:06d}.png'
        depth = resize_depth(cv2.imread(str(dp),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera['scale'],camera)
        valid,edge = depth_masks(depth,mask_spec)
        replace = (valid & ~edge).ravel()[mask]
        use = replace & (frame>=200)
        reference = y.copy()
        reference[replace] = backproject_z(uv[replace],depth.ravel()[mask][replace],K)
        attrs = dict(rgb=rgb,opacity=opacity)
        full = build_canonical_arms(y,reference,cy,Q,refpose[frame],ids,attrs)
        for arm in ARMS:
            a = full[arm]
            append('position_full',arm,pack_parameters(a['world_points'],a['world_covariance'],rgb,opacity))
        np.testing.assert_array_equal(pack_parameters(full['C00']['world_points'],full['C00']['world_covariance'],rgb,opacity),original)
        selections = {}
        if use.any():
            ca = build_canonical_arms(y[use],reference[use],cy[use],Q,refpose[frame],ids[use],{k:v[use] for k,v in attrs.items()})
            yo,co,Qo = change_canonical_gauge(y[use],cy[use],Q,D)
            oa = build_canonical_arms(yo,reference[use],co,Qo,refpose[frame],ids[use],{k:v[use] for k,v in attrs.items()})
            np.testing.assert_allclose(oa['C00']['world_points'],transform_points(ca['C00']['world_points'],D),atol=1e-10,rtol=1e-9)
            np.testing.assert_allclose(oa['C00']['world_covariance'],transform_covariance(ca['C00']['world_covariance'],D),atol=1e-10,rtol=1e-9)
            oldref = x.copy()
            oldref[replace] = reference[replace]
            aa = build_arms(xraw[use],oldref[use],rawpose,refpose[frame],G,C,covraw[use],ids[use],np.ones(use.sum(),bool),{k:v[use] for k,v in attrs.items()})
            strict_packed = {}
            for arm in ARMS+CZ:
                a = ca[arm]
                packed = pack_parameters(a['world_points'],a['world_covariance'],rgb[use],opacity[use])
                append('position_strict',arm,packed)
                strict_packed[arm] = packed
                if arm in ARMS:
                    append('fixed_world_strict',arm,pack_parameters(a['world_points'],ca['C00']['world_covariance'],rgb[use],opacity[use]))
                    b = oa[arm]
                    append('orientation_strict',arm,pack_parameters(b['world_points'],b['world_covariance'],rgb[use],opacity[use]))
            np.testing.assert_array_equal(strict_packed['C00'],original[use])
            for arm in OLD:
                a = aa[arm]
                packed = pack_parameters(a['world_points_m'],a['world_covariance_m2'],rgb[use],opacity[use])
                append('original_strict',arm,packed)
                if arm=='A00': np.testing.assert_array_equal(packed,strict_packed['C00'])
                if arm=='A11': np.testing.assert_array_equal(packed[:,:3],strict_packed['C11'][:,:3])
            for name,definition in cases.items():
                if definition['kind']!='source_only': continue
                sampled = sampling_mask((h,w),frame,definition['pattern'],definition['density'],0).ravel()[mask][use]
                selections[name] = dict(count=int(sampled.sum()),candidate_id_hash=array_hash(ids[use][sampled]))
                np.save(dest/'local'/f'kf{index:03d}_{name}.npy',sampled)
                for arm in ARMS: append(name,arm,strict_packed[arm][sampled])
            err = np.abs(y[use,2]-reference[use,2])
            conf = kf['conf'].numpy().reshape(-1)[mask][use]
            bins = {}
            for lo,hi in zip([.1,1,2,4],[1,2,4,10]):
                take = (reference[use,2]>=lo)&(reference[use,2]<hi)
                bins[f'depth_{lo}_{hi}'] = stats(err[take])
            for lo,hi in [(1.5,2),(2,5),(5,10),(10,float('inf'))]:
                bins[f'confidence_{lo}_{hi}'] = stats(err[(conf>=lo)&(conf<hi)])
            source_rows.append(dict(kf_idx=index,frame=frame,count=int(use.sum()),effective_Z_error_m=stats(err),
                raw_C_Z_error_m=stats(np.abs(x[use,2]-reference[use,2])),
                effective_3D_error_m=stats(np.linalg.norm(y[use]-reference[use],axis=1)),
                ray_reprojection_px=stats(np.linalg.norm(project(y[use],K)-uv[use],axis=1)),
                ray_angle_deg=stats(np.degrees(np.arccos(np.clip(np.sum(y[use]*reference[use],axis=1)/np.linalg.norm(y[use],axis=1)/np.linalg.norm(reference[use],axis=1),-1,1)))),strata=bins))
        np.savez_compressed(dest/'local'/f'kf{index:03d}.npz',y=y,covariance_y=cy,rigid_Q=Q,active_pixel_indices=pixids,
            reference=reference,reference_replace=replace,strict=use,native_mask=mask,candidate_ids=ids,
            standard_deviations_y=stdy,raw_local_rotation=prepared[2].numpy(),source_frame=frame)
        block = dict(kf_idx=index,frame=frame,active=len(y),strict=int(use.sum()),local_reference=int(replace.sum()),
            candidate_event=meta['candidate_event'],candidate_id_hash=array_hash(ids),strict_id_hash=array_hash(ids[use]),
            native_mask_hash=array_hash(mask),attributes={k:array_hash(v) for k,v in attrs.items()},source_selections=selections)
        blocks.append(block)
        unitrows.append(dict(kf_idx=index,C=C,a=can.absorbed_scale,q=q,active=len(y),nonunit=bool(nonunit),
            positive_checks=positive_checks,negative_covariance_error_max=float(np.max(np.abs(badcov-wc))),
            negative_mean_error_max=float(np.max(np.abs(badmu-mu))),inverse='PASS',std_covariance='PASS'))
        torch.backends.cuda.matmul.allow_tf32=True
        baked.append(tuple(a.cpu() for a in bake_gaussians_world({k:a.cuda() for k,a in local.items()},kf['img'].cuda(),h,w,lietorch.Sim3(kf['T_WC'].cuda()),**nf)))
        torch.backends.cuda.matmul.allow_tf32=False
        inputs.extend([digest(rawpath),digest(dp),digest(dest/'local'/f'kf{index:03d}.npz')])
        active_total += len(y)
        strict_total += int(use.sum())
        replaced_total += int(replace.sum())
        print('V1 built KF',index,'source',frame,'active',len(y),'strict',int(use.sum()),flush=True)
    ply = decode_gaussians_from_ply(run/'map/office3_gaussians.ply',device='cpu')
    ij = torch.triu_indices(3,3)
    replay = [torch.cat([b[i] for b in baked]) for i in range(4)]
    assert ply['n'] == active_total
    torch.testing.assert_close(replay[0],ply['means'],atol=1e-5,rtol=1e-5)
    torch.testing.assert_close(replay[1],ply['covariances'][:,ij[0],ij[1]],atol=1e-5,rtol=1e-4)
    torch.testing.assert_close(replay[2],ply['rgb'],atol=1e-5,rtol=1e-5)
    torch.testing.assert_close(replay[3],ply['opacity'],atol=1e-6,rtol=1e-5)
    maprows = []
    for (case,arm),m in allmaps.items():
        assert m['path'].stat().st_size == m['count']*52
        assert m['count']>0
        maprows.append(dict(case=case,arm=arm,count=m['count'],file=digest(m['path'])))
    for name,definition in cases.items():
        if definition['kind']=='target_only':continue
        counts = [m['count'] for m in maprows if m['case']==name]
        assert len(set(counts))==1
    unitmaps = [dict(id=name,count=active_total,negative=name in unit['negative_controls'],file=digest(uf/(name+'.f32'))) for name in unitnames]
    baseline_hash = unitmaps[0]['file']['sha256']
    for m in unitmaps:
        if not m['negative']: assert m['file']['sha256']==baseline_hash
    save_json(dest/'unit_contract.json',dict(status='PASS',native_GPU_PLY_parity='PASS',algebraic_checks='PASS',
        positive_maps_byte_identical=True,negative_nonunit_KFs=sum(r['nonunit'] for r in unitrows),keyframes=unitrows,maps=unitmaps))
    save_json(dest/'manifest.json',dict(status='PASS',maps=maprows,active=active_total,strict=strict_total,
        full_reference_replaced=replaced_total,full_reference_fraction=replaced_total/active_total,
        blocks=blocks,source_residuals=source_rows,inputs=inputs,pose_revision=final['pose_revision'],
        candidate_order_and_attributes_frozen=True,C00_A00_byte_equal=True,native_lineage='PASS',
        canonical_independent_interventions='PASS',journal_checks=digest(dest/'journal_checks.json'),
        alignment=digest(dest/'alignment.json'),unit_contract=digest(dest/'unit_contract.json')))
    print('V1 construction PASS',active_total,'native;',strict_total,'strict',flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage',choices=['register','build'])
    a = p.parse_args()
    {'register':register,'build':build}[a.stage]()
