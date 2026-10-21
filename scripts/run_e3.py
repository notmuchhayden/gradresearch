"""E3 replay and evaluation; CPU fallback with archived-CUDA parity checks."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import time

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT/'thirdparty/Splatt3R-SLAM/splatt3r_core')]
from prepare_e2b_run import digest, save_json
from e0b_audit import sim3_matrix, transform
from e2_signals import image_rgb, dog
from e1_taxonomy import camera_geometry, resize_depth, depth_masks
from e3_cpu_renderer import render
from e3_admission import Admission, decision_metrics, KEEP, BYPASS, REJECT, DEFER
from utils.geometry import build_covariance

CFG = ROOT/'configs/e3_admission.json'
CODE = ['configs/e3_admission.json','scripts/run_e3.py','src/e3_admission.py',
        'src/e3_cpu_renderer.py','src/e3_splat_cpu.cpp','tests/test_e3.py']


def setup():
    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    spec = json.loads(CFG.read_text())
    out = ROOT/spec['output']
    out.mkdir(parents=True,exist_ok=True)
    return spec,out


@contextmanager
def feature_guard():
    """Block GT, evaluation labels, trajectory and final-map reads in replay."""
    import builtins, io
    original,original_io = builtins.open,io.open
    def check(file,*args,**kwargs):
        if isinstance(file,(str,Path)):
            p = Path(file)
            if ('evaluation' in p.parts or p.name in {'labels.npz','traj.txt','cam_params.json'}
                or p.name.endswith('_frames.txt') or p.suffix=='.ply'
                or p.name.startswith('depth') or ('Replica' in p.parts)):
                raise RuntimeError(f'E3 feature GT/final-map read forbidden: {p}')
        return original(file,*args,**kwargs)
    builtins.open = io.open = check
    try:
        yield
    finally:
        builtins.open,io.open = original,original_io


def load_scene(spec,scene):
    root = ROOT/spec['source']
    score = root/'scores'/scene
    manifest = json.loads((score/'score_manifest.json').read_text())
    # Hash every used feature, snapshot and source artifact against E2b.
    for entry in manifest['code']+manifest['inputs']+manifest['history']+[manifest['features'],manifest['metadata']]:
        assert digest(ROOT/entry['path'])==entry,entry['path']
    assert manifest['gt_reads']=='forbidden' and not manifest['final_poses']
    meta = json.loads((score/'score_metadata.json').read_text())
    f = dict(np.load(score/'features.npz'))
    run = root/'baselines'/scene
    dump = torch.load(run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)
    local = []
    n = meta['raw_per_kf']
    for i,kf in enumerate(dump['keyframes']):
        # Never consume the final T_WC pose stored in the dump during replay.
        q = kf['rotations']/kf['rotations'].norm(dim=-1,keepdim=True).clamp_min(1e-6)
        cov = build_covariance(kf['scales'],q).numpy()
        image = image_rgb(kf)
        rgb = np.clip(kf['sh'].numpy()[:,:,0]*0.28209479177387814+image.reshape(-1,3),0,1)
        active = f['active'][i*n:(i+1)*n]
        local.append(dict(means=kf['means'].numpy(),cov=cov,rgb=rgb,
            opacity=kf['opacities'].numpy().reshape(-1),active=active,image=image,
            conf=kf['conf'].numpy(),hw=tuple(kf['img_shape'])))
    return score,run,meta,f,local


def bake(local, poses, masks):
    means,covs,rgbs,opacities = [],[],[],[]
    for kf,pose,mask in zip(local,poses,masks):
        if not mask.any():
            continue
        A = pose[:3,:3].astype(np.float32)
        means.append(kf['means'][mask]@A.T+pose[:3,3].astype(np.float32))
        covs.append(A@kf['cov'][mask]@A.T)
        rgbs.append(kf['rgb'][mask])
        opacities.append(kf['opacity'][mask])
    if not means:
        return (np.empty((0,3),np.float32),np.empty((0,3,3),np.float32),
                np.empty((0,3),np.float32),np.empty(0,np.float32))
    return tuple(np.concatenate(v) for v in (means,covs,rgbs,opacities))


def dog_score(local,poses,masks,current,camera,base):
    kf = local[current]
    hw = kf['hw']
    K = np.array(camera['K'])
    pose = poses[current].copy()
    pose[:3,:3] /= np.cbrt(np.linalg.det(pose[:3,:3]))
    mu,cov,rgb,opacity = bake(local[:current],poses[:current],masks[:current])
    image = render(mu,cov,opacity,rgb,pose,K,hw)
    h,w = hw
    p = kf['means']
    z = p[:,2]
    x = K[0,0]*p[:,0]/np.maximum(z,1e-12)+K[0,2]
    y = K[1,1]*p[:,1]/np.maximum(z,1e-12)+K[1,2]
    warped = cv2.remap(image,x.reshape(hw).astype(np.float32),y.reshape(hw).astype(np.float32),
                       cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    yy,xx = np.indices(hw)
    ray = np.stack([(xx-K[0,2])/K[0,0],(yy-K[1,2])/K[1,1],np.ones(hw)],-1).reshape(-1,3)
    ray /= np.linalg.norm(ray,axis=1,keepdims=True)
    predicted = p/np.maximum(np.linalg.norm(p,axis=1,keepdims=True),1e-12)
    angle = np.degrees(np.arccos(np.clip((ray*predicted).sum(1),-1,1)))
    margin = int(np.ceil(3*max(base['dog_sigmas_pixels'])))
    good = ((z>0)&(kf['conf']>=base['confidence_min'])&
        (angle<=base['camera_fit_angular_error_max_degrees'])&(x>=0)&(x<=w-1)&(y>=0)&(y<=h-1)&
        ((xx>=margin)&(xx<w-margin)&(yy>=margin)&(yy<h-margin)).reshape(-1))
    score = (dog(warped,base['dog_sigmas_pixels'])-dog(kf['image'],base['dog_sigmas_pixels'])).reshape(-1)
    score[~good] = np.nan
    return score,warped,len(mu)


def snapshot_poses(run,meta,index):
    path = run/'audit'/meta['lineage'][index]['decision_file']
    snap = torch.load(path,map_location='cpu',weights_only=True)
    assert len(snap['metadata'])==index+1
    for j,row in enumerate(snap['metadata']):
        assert row['candidate_sources']==meta['lineage'][j]['source_images']
        assert row['candidate_event']==meta['lineage'][j]['event_id']
        assert max(row['candidate_sources'])<=snap['input_frame']
    return snap,[sim3_matrix(p.numpy()) for p in snap['poses']]


def prepare():
    spec,out = setup()
    seal_path = out/'preregistration.json'
    if seal_path.exists():
        raise RuntimeError('Existing E3 seal preserved; use a new output for protocol changes')
    old_seal_path = ROOT/spec['source']/'thresholds_development_only.json'
    old = json.loads(old_seal_path.read_text())
    assert old['development_scene']==spec['development_scene']
    thresholds = {m:v['0.99'] for m,v in old['thresholds']['active'].items()}
    with feature_guard():
        score,run,meta,f,local = load_scene(spec,spec['development_scene'])
        base = json.loads((ROOT/'configs/e2_discriminability.json').read_text())
        parity = []
        for i in spec['parity']['development_premaps']:
            snap,poses = snapshot_poses(run,meta,i)
            s,image,n = dog_score(local,poses,[kf['active'] for kf in local],i,meta['predicted_cameras'][i],base)
            ref = np.load(score/'premaps'/f'kf{i:04d}.npz')
            delta = image-ref['render']
            mae = float(np.abs(delta).mean())
            psnr = float(-10*np.log10(max(float((delta*delta).mean()),1e-20)))
            common = np.isfinite(s)&np.isfinite(ref['score'].reshape(-1))
            t = thresholds['B8_dog_redundancy']
            flip = float(np.mean((s[common]>t)!=(ref['score'].reshape(-1)[common]>t)))
            parity.append(dict(kf=i,active=n,mae=mae,psnr_db=psnr,threshold_flip_fraction=flip,
                reference=digest(score/'premaps'/f'kf{i:04d}.npz')))
            print('CPU/CUDA parity',json.dumps(parity[-1]),flush=True)
    passed = all(p['mae']<=spec['parity']['max_rgb_mae'] and
                 p['psnr_db']>=spec['parity']['min_rgb_psnr_db'] for p in parity)
    save_json(out/'renderer_parity.json',dict(passed=passed,development_only=True,rows=parity))
    if not passed:
        raise RuntimeError('CPU adaptation failed development renderer parity; do not evaluate policies')
    # Recompute every reused threshold on development labels before sealing.
    from e2_metrics import calibrate_normal_threshold
    labels = np.load(ROOT/spec['source']/'evaluation'/spec['development_scene']/'labels.npz')['creation']
    dev_normal = f['active']&np.isin(labels,[1,2])
    b8 = np.load(score/'b8_features.npz')['B8_dog_redundancy']
    for method,t in thresholds.items():
        values = b8 if method=='B8_dog_redundancy' else f['max__'+method]
        assert calibrate_normal_threshold(values,dev_normal,0.99)==t,method
    from datetime import datetime,timezone
    code = [digest(ROOT/p) for p in CODE]
    for p in CODE:
        target = out/'sealed_code'/p
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/p,target)
    save_json(seal_path,dict(sealed_at_utc=datetime.now(timezone.utc).isoformat(),
        specification=spec,code=code,thresholds=thresholds,threshold_source=digest(old_seal_path),
        parity=digest(out/'renderer_parity.json'),new_evaluation_labels_read=False,
        evaluation_previously_inspected=True,cuda_available=torch.cuda.is_available(),
        development_label_source=digest(ROOT/spec['source']/'evaluation'/spec['development_scene']/'labels.npz')))
    save_json(ROOT/'configs/e3_preregistration.json',json.loads(seal_path.read_text()))
    print('E3 protocol sealed; CPU renderer parity PASS',flush=True)


def checked_seal(spec,out):
    seal = json.loads((out/'preregistration.json').read_text())
    assert seal['specification']==spec
    for entry in seal['code']+[seal['threshold_source'],seal['parity']]:
        assert digest(ROOT/entry['path'])==entry,entry['path']
    return seal


def replay(scene):
    spec,out = setup()
    seal = checked_seal(spec,out)
    dest = out/'replay'/scene
    if (dest/'manifest.json').exists():
        raise RuntimeError('Completed replay preserved')
    dest.mkdir(parents=True,exist_ok=True)
    start = time.monotonic()
    with feature_guard():
        score,run,meta,f,local = load_scene(spec,scene)
        base = json.loads((ROOT/'configs/e2_discriminability.json').read_text())
        created = np.array([r['input_frame'] for r in meta['lineage']])[f['anchor_kf']]
        policies = {p:Admission(p,f['active'],f['anchor_kf'],created,seal['thresholds'],
                        spec['defer_timeout_kfs']) for p in spec['policies']}
        n = meta['raw_per_kf']
        history_paths = sorted((score/'history').glob('*.npz'))
        timings,b8_rows = [],[]
        for i,path in enumerate(history_paths):
            h = dict(np.load(path))
            snap,poses = snapshot_poses(run,meta,i)
            assert int(h['pose_revision'])==snap['pose_revision']
            assert int(h['input_frame'])==snap['input_frame']
            assert int(h['decision_sequence'])==meta['lineage'][i]['decision_sequence']
            for name,p in policies.items():
                tick = time.monotonic()
                b8 = None
                if name=='B8':
                    before = np.isin(p.state,[KEEP,BYPASS]).reshape(-1,n)
                    # This mask excludes current and all future candidate blocks.
                    assert not before[i:].any()
                    s,image,count = dog_score(local,poses,before,i,meta['predicted_cameras'][i],base)
                    b8 = np.full(len(f['active']),np.nan,np.float32)
                    b8[i*n:(i+1)*n] = s
                    b8_rows.append(dict(snapshot=i,policy_active_premap=count,
                        original_active_premap=int(f['active'][:i*n].sum()),
                        pose_revision=snap['pose_revision'],score_finite=int(np.isfinite(s).sum())))
                admitted = p.advance(i,snap['input_frame'],snap['pose_revision'],h,b8)
                elapsed = time.monotonic()-tick
                timings.append(dict(policy=name,snapshot=i,cpu_policy_seconds=elapsed))
                # Packed membership is the actual renderer map input, not a score-only would_reject.
                target = dest/name
                target.mkdir(exist_ok=True)
                np.savez_compressed(target/f'snapshot{i:04d}.npz',
                    admitted=np.packbits(admitted),deferred=np.packbits(p.state==DEFER),
                    candidate_count=len(admitted),input_frame=snap['input_frame'],pose_revision=snap['pose_revision'])
            print(f'{scene} KF {i+1}/{len(history_paths)}: '+', '.join(
                f'{p} active={a.rows[-1]["active"]} queue={a.rows[-1]["deferred"]}' for p,a in policies.items()),flush=True)
        for name,p in policies.items():
            np.savez_compressed(dest/name/'decisions.npz',**p.arrays(),anchor=f['anchor_kf'],
                                created_input=created,original_active=f['active'])
            save_json(dest/name/'timeline.json',p.rows)
        save_json(dest/'timing.json',timings)
        save_json(dest/'b8_causal_maps.json',b8_rows)
        artifacts = sorted(p for p in dest.rglob('*') if p.is_file())
        save_json(dest/'manifest.json',dict(scene=scene,seal=digest(out/'preregistration.json'),
            artifacts=[digest(p) for p in artifacts],feature_manifest=digest(score/'score_manifest.json'),
            gt_reads='forbidden',policy_specific_b8=True,cpu_wall_seconds=time.monotonic()-start,
            candidate_ids='raw_event:branch0:pixel_index; array order anchor_kf then pixel',
            lineage=meta['lineage'],pose_source='actual decision snapshots only',
            hardware='CPU; no GPU or wall-clock online claim'))


def depth_metrics(rendered,gt,valid,edge,lspec):
    weight = rendered[:,:,1]
    pred = np.divide(rendered[:,:,0],weight,out=np.zeros_like(weight),where=weight>1e-9)
    covered = (weight>lspec['render_coverage_weight_min'])&(pred>0)&np.isfinite(pred)
    tol = np.maximum(lspec['depth_tolerance_abs_m'],lspec['depth_tolerance_relative']*gt)
    error = np.abs(pred-gt)
    correct = covered&(error<=tol)
    front = covered&(pred<gt-tol)
    def avg(a,mask):
        return float(a[mask].mean()) if mask.any() else None
    return dict(coverage=avg(covered,valid),correct_coverage=avg(correct,valid),
        depth_l1_m=avg(error,valid&covered),front_fraction=avg(front,valid),
        boundary_correct_coverage=avg(correct,valid&edge),
        interior_correct_coverage=avg(correct,valid&~edge),
        bad_composited_weight=avg(rendered[:,:,2],valid)),pred,weight


def evaluate(scene):
    spec,out = setup()
    seal = checked_seal(spec,out)
    dest = out/'evaluation'/scene
    if (dest/'metrics.json').exists():
        raise RuntimeError('Completed evaluation preserved')
    dest.mkdir(parents=True,exist_ok=True)
    replay_root = out/'replay'/scene
    manifest = json.loads((replay_root/'manifest.json').read_text())
    for entry in manifest['artifacts']:
        assert digest(ROOT/entry['path'])==entry
    score,run,meta,f,local = load_scene(spec,scene)
    labels_path = ROOT/spec['source']/'evaluation'/scene/'labels.npz'
    label_sets = dict(np.load(labels_path))
    label_info_path = labels_path.with_name('label_manifest.json')
    info = json.loads(label_info_path.read_text())
    lspec = json.loads((ROOT/'configs/e1_taxonomy.json').read_text())
    dataset = ROOT/'data/E2b/Replica'
    camera = json.loads((dataset/'cam_params.json').read_text())['camera']
    gt_poses = np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    K = camera_geometry(camera)[0]
    alignment = np.array(info['alignment'])
    final_poses = [sim3_matrix(row['T_WC'].numpy()) for row in torch.load(
        run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)['keyframes']]
    n,nk = meta['raw_per_kf'],meta['keyframes']
    active = f['active']
    decisions = {p:dict(np.load(replay_root/p/'decisions.npz')) for p in spec['policies']}
    common = active.copy()
    for p in ['B2','B6','B7','B8','P2']:
        common &= decisions[p]['ever_eligible']
    summary = dict(scene=scene,scope=spec['evaluation_status'],policies={},common_candidates=int(common.sum()),
        specification=spec,thresholds=seal['thresholds'],cpu_renderer=True,
        label_source=digest(labels_path),replay_manifest=digest(replay_root/'manifest.json'))
    render_inputs = []
    def view(frame):
        path = dataset/scene/'results'/f'depth{frame:06d}.png'
        raw = cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
        assert raw is not None
        gt = resize_depth(raw.astype(np.float32)/camera['scale'],camera)
        valid,edge = depth_masks(gt,lspec)
        render_inputs.append(digest(path))
        return gt,valid,edge
    end_input = meta['lineage'][-1]['input_frame']
    for p,d in decisions.items():
        tick = time.monotonic()
        per_labels = {name:decision_metrics(d['state'],labels,active,d['ever_eligible'])
                      for name,labels in label_sets.items()}
        common_metric = decision_metrics(d['state'],label_sets['creation'],common,d['ever_eligible'])
        state = d['state']
        admitted = active&np.isin(state,[KEEP,BYPASS])
        queued = state==DEFER
        ever_queue = d['queue_enter']>=0
        exited = ever_queue&(d['queue_exit']>=0)
        delays = d['queue_exit'][exited]-d['queue_enter'][exited]
        censored_age = end_input-d['queue_enter'][queued]
        # Serialized tensor payload, including all original SH coefficients,
        # with deterministic bytes; CPU queue payload is separate.
        dump = torch.load(run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)
        raw_bytes = sum(dump['keyframes'][0][k][0].numel()*dump['keyframes'][0][k].element_size()
                        for k in ['means','scales','rotations','sh','opacities','conf'])
        del dump
        timeline = json.loads((replay_root/p/'timeline.json').read_text())
        queue = dict(ever_queued=int(ever_queue.sum()),resolved=int(exited.sum()),right_censored=int(queued.sum()),
            timeout_bypass=int(d['timed_out'].sum()),peak_candidates=max(r['deferred'] for r in timeline),
            queue_payload_bytes_peak=max(r['deferred'] for r in timeline)*raw_bytes,
            state_and_log_bytes=sum(a.nbytes for a in d.values()),
            resolved_delay_input_median=float(np.median(delays)) if len(delays) else None,
            resolved_delay_input_p95=float(np.percentile(delays,95)) if len(delays) else None,
            censored_age_input_p95=float(np.percentile(censored_age,95)) if len(censored_age) else None,
            total_queue_candidate_kf_snapshots=sum(r['deferred'] for r in timeline),
            payload_bytes_per_candidate=raw_bytes)
        # Final actual compact tensor map, same final poses for every policy.
        mu,cov,rgb,opacity = bake(local,[alignment@pose for pose in final_poses],admitted.reshape(nk,n))
        np.savez_compressed(dest/f'{p}_compact_map.npz',means=mu,covariances=cov,rgb=rgb,opacity=opacity)
        bad = (label_sets['final_estimated'][admitted]==3).astype(np.float32)
        rows = []
        image_dir = dest/'render'/p
        image_dir.mkdir(parents=True,exist_ok=True)
        for frame in spec['render_frames']:
            gt,valid,edge = view(frame)
            pose = gt_poses[frame]
            z = (mu-pose[:3,3])@pose[:3,2]
            result = render(mu,cov,opacity,np.stack([z,np.ones_like(z),bad],-1),pose,K,gt.shape)
            metrics,pred,weight = depth_metrics(result,gt,valid,edge,lspec)
            rows.append(dict(frame=frame,**metrics))
            if frame in [201,701]:
                np.savez_compressed(image_dir/f'frame{frame:06d}.npz',gt=gt,pred=pred,weight=weight,valid=valid)
        render_mean = {k:float(np.mean([r[k] for r in rows if r[k] is not None])) for k in rows[0] if k!='frame'}
        del mu,cov,rgb,opacity
        temporal = []
        normal_exposure,total_normal = 0,0
        for i in range(nk):
            h = np.load(replay_root/p/f'snapshot{i:04d}.npz')
            mask = np.unpackbits(h['admitted'])[:len(active)].astype(bool)
            pending = np.unpackbits(h['deferred'])[:len(active)].astype(bool)
            normal = active&(f['anchor_kf']<=i)&np.isin(label_sets['creation'],[1,2])
            normal_exposure += int((pending&normal).sum())
            total_normal += int(normal.sum())
            snap,poses = snapshot_poses(run,meta,i)
            frame = 2*snap['input_frame']+1
            gt,valid,edge = view(frame)
            mu,cov,rgb,opacity = bake(local[:i+1],[alignment@v for v in poses],mask.reshape(nk,n)[:i+1])
            z = (mu-gt_poses[frame,:3,3])@gt_poses[frame,:3,2]
            values = np.stack([z,np.ones_like(z),np.zeros_like(z)],-1)
            result = render(mu,cov,opacity,values,gt_poses[frame],K,gt.shape)
            metrics,_,_ = depth_metrics(result,gt,valid,edge,lspec)
            temporal.append(dict(snapshot=i,frame=frame,**metrics))
        queue['normal_withheld_candidate_snapshot_fraction'] = normal_exposure/max(total_normal,1)
        summary['policies'][p] = dict(decision=per_labels,common=common_metric,queue=queue,
            final_render=render_mean,frames=rows,temporal_frames=temporal,
            temporal_mean={k:float(np.mean([r[k] for r in temporal if r[k] is not None]))
                           if any(r[k] is not None for r in temporal) else None
                           for k in temporal[0] if k not in ['snapshot','frame']},
            compact_map_file=digest(dest/f'{p}_compact_map.npz'),
            compact_tensor_payload_bytes=int(admitted.sum())*raw_bytes,
            evaluation_cpu_seconds=time.monotonic()-tick)
        print(f'{scene} {p}: rejected={per_labels["creation"]["rejected"]}, bad={per_labels["creation"]["bad_rejected"]}, '+
            f'normal={per_labels["creation"]["normal_rejected"]}, depth={render_mean["depth_l1_m"]:.5f}, coverage={render_mean["coverage"]:.6f}',flush=True)
    r = spec['progress']
    base = summary['policies']['B1']['final_render']
    summary['decision'] = {}
    for p in ['P2','P3']:
        a = summary['policies'][p]
        m = a['decision']['creation']
        checks = dict(normal_active_retention=m['normal_active_retention']>=r['normal_active_retention_min'],
            finite_normal_retention=m['finite_normal_retention'] is not None and m['finite_normal_retention']>=r['finite_normal_retention_min'],
            common_normal_retention=a['common']['normal_not_rejected'] is not None and a['common']['normal_not_rejected']>=r['common_normal_retention_min'],
            bad_recall=m['bad_recall']>=r['bad_recall_min'],
            coverage=a['final_render']['coverage']>=base['coverage']-r['coverage_loss_max'],
            depth_l1=a['final_render']['depth_l1_m']<=base['depth_l1_m']+r['depth_l1_increase_m_max'])
        checks['precision_vs_each_strong_baseline'] = all(m['precision'] is not None and
            summary['policies'][b]['decision']['creation']['precision'] is not None and
            m['precision']>=summary['policies'][b]['decision']['creation']['precision']+r['precision_gain_min']
            for b in ['B6','B7','B8'])
        summary['decision'][p] = dict(checks=checks,passed=all(checks.values()),
            failed=[k for k,v in checks.items() if not v])
    summary['status'] = 'DESCRIPTIVE_PASS' if any(v['passed'] for v in summary['decision'].values()) else 'REVISE'
    summary['research_wide_go'] = False
    save_json(dest/'metrics.json',summary)
    save_json(ROOT/f'configs/e3_{scene}_results_summary.json',summary)
    save_json(dest/'evaluation_manifest.json',dict(labels=digest(labels_path),label_manifest=digest(label_info_path),
        camera=digest(dataset/'cam_params.json'),gt_poses=digest(dataset/scene/'traj.txt'),
        depths=list({p['path']:p for p in render_inputs}.values()),metrics=digest(dest/'metrics.json'),
        seal=digest(out/'preregistration.json'),creation_labels_fixed=True))


if __name__=='__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage',choices=['prepare','replay','evaluate'])
    ap.add_argument('scene',nargs='?',choices=['office0','room0'],default='room0')
    args = ap.parse_args()
    if args.stage=='prepare':
        prepare()
    elif args.stage=='replay':
        replay(args.scene)
    else:
        evaluate(args.scene)
