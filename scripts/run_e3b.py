"""Office0-only E3b calibration, causal provisional replay and GT evaluation."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest,save_json
from run_e3 import feature_guard,load_scene,snapshot_poses,bake,dog_score,depth_metrics
from e3_cpu_renderer import render
from e3b_provisional import cumulative_scores,calibrate,ProvisionalAdmission,metrics,PROVISIONAL,KEEP,REJECT
from e1_taxonomy import camera_geometry,resize_depth,depth_masks
from e0b_audit import sim3_matrix

CFG = ROOT/'configs/e3b_provisional.json'
CODE = ['configs/e3b_provisional.json','src/e3b_provisional.py','scripts/run_e3b.py',
        'scripts/run_e3b.sh','scripts/e3b_fresh.py','scripts/score_e3b_fresh.py','tests/test_e3b.py',
        'scripts/run_e3.py','src/e3_cpu_renderer.py','src/e3_splat_cpu.cpp','src/e1_taxonomy.py',
        'src/e0b_audit.py','src/e2_signals.py','scripts/prepare_e2b_run.py',
        'thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py']


def setup():
    torch.set_num_threads(2);cv2.setNumThreads(2)
    spec = json.loads(CFG.read_text());out = ROOT/spec['output']
    out.mkdir(parents=True,exist_ok=True)
    return spec,out


def source_spec(spec,scene):
    return dict(source=spec['fresh_source'] if scene==spec['fresh_scene'] else spec['source'])


def feature_arrays(spec,scene):
    source = ROOT/source_spec(spec,scene)['source']
    root = source/'scores'/scene
    manifest = json.loads((root/'score_manifest.json').read_text())
    for e in manifest['code']+manifest['inputs']+manifest['history']+[manifest['features'],manifest['metadata']]:
        assert digest(ROOT/e['path'])==e,e['path']
    assert manifest['gt_reads']=='forbidden' and not manifest['final_poses']
    return dict(np.load(root/'features.npz')),root


def prepare():
    spec,out = setup()
    if (out/'seal.json').exists():
        raise RuntimeError('E3b seal exists; use a fresh output for a new development iteration')
    f,score = feature_arrays(spec,spec['development_scene'])
    lp = ROOT/spec['source']/'evaluation'/spec['development_scene']/'labels.npz'
    labels = np.load(lp)['creation']
    b8path = score/'b8_features.npz'
    b8 = np.load(b8path)['B8_dog_redundancy']
    common = f['active'].copy()
    values = {m:(b8 if m=='B8_dog_redundancy' else f['max__'+m]) for m in spec['common_scores']}
    for v in values.values():
        common &= np.isfinite(v)
    paths = sorted((score/'history').glob('*.npz'))
    peak,persistent = cumulative_scores((np.load(p)['P1_second_front_relative'] for p in paths),len(labels))
    np.testing.assert_array_equal(peak,f['max__P1_second_front_relative'])
    values['persistent'] = persistent
    old_path = ROOT/spec['source']/'thresholds_development_only.json'
    old = json.loads(old_path.read_text())
    assert old['development_scene']==spec['development_scene']
    thresholds,calibration = {},{}
    risk = spec['risk_calibration']
    for name,d in spec['methods'].items():
        if d['kind']=='original':
            thresholds[name] = None;continue
        if d['calibration']=='legacy':
            thresholds[name] = old['thresholds']['active'][d['score']]['0.99']
            calibration[name] = dict(source='E2b development-only active legacy',calibrated=True)
        else:
            v = persistent if d['kind']=='persistent' else values[d['score']]
            result = calibrate(v,labels,f['active'],common,f['anchor_kf'],
                risk['normal_retention'],risk['anchor_group_min_normal'])
            thresholds[name] = result['threshold'];calibration[name] = result
        v = persistent if d['kind']=='persistent' else values[d['score']]
        t = thresholds[name]
        reject = f['active']&np.isfinite(v)&(v>t) if t is not None else np.zeros(len(v),bool)
        state = np.where(f['active'],KEEP,4).astype(np.uint8);state[reject] = REJECT
        calibration[name]['development_score_diagnostic'] = metrics(
            dict(state=state,ever_finite=np.isfinite(v)),labels,f['active'])
        calibration[name]['development_common_diagnostic'] = metrics(
            dict(state=state,ever_finite=np.isfinite(v)),labels,common)
    for p in CODE:
        target = out/'sealed_code'/p;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/p,target)
    env = dict(platform=platform.platform(),python=sys.version,torch=torch.__version__,numpy=np.__version__,
        cuda_available=torch.cuda.is_available(),nvidia_devices=[p for p in os.listdir('/dev') if p.startswith('nvidia')],
        compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        cpu_count=os.cpu_count(),threads=dict(OMP_NUM_THREADS=os.environ.get('OMP_NUM_THREADS'),torch=2,opencv=2))
    save_json(out/'environment.json',env);save_json(ROOT/'configs/e3b_environment.json',env)
    seal = dict(sealed_at_utc=datetime.now(timezone.utc).isoformat(),specification=spec,
        thresholds=thresholds,calibration=calibration,code=[digest(ROOT/p) for p in CODE],
        development_scene=spec['development_scene'],development_common_candidates=int(common.sum()),
        development_inputs=[digest(lp),digest(b8path),digest(score/'score_manifest.json'),digest(old_path)],
        regression_scene_previously_inspected=True,new_regression_labels_read=False,
        fresh_scene=spec['fresh_scene'],fresh_evaluation_read=False,
        inherited_renderer_parity=digest(ROOT/'results/E3_admission_decision/renderer_parity.json'))
    save_json(out/'seal.json',seal);save_json(ROOT/'configs/e3b_preregistration.json',seal)
    print(json.dumps(dict(thresholds=thresholds,development_common=int(common.sum()),
        fresh_evaluation='PENDING; requires unchanged GPU baseline'),indent=2),flush=True)


def checked_seal(spec,out):
    seal = json.loads((out/'seal.json').read_text())
    assert seal['specification']==spec
    for e in seal['code']+seal['development_inputs']+[seal['inherited_renderer_parity']]:
        assert digest(ROOT/e['path'])==e,e['path']
    return seal


def replay(scene):
    spec,out = setup();seal = checked_seal(spec,out)
    dest = out/'replay'/scene
    if (dest/'manifest.json').exists():
        raise RuntimeError('Completed replay preserved')
    dest.mkdir(parents=True,exist_ok=True)
    start = time.monotonic()
    with feature_guard():
        score,run,meta,f,local = load_scene(source_spec(spec,scene),scene)
        base = json.loads((ROOT/spec['feature_base_config']).read_text())
        methods = {name:ProvisionalAdmission(d,f['active'],f['anchor_kf'],seal['thresholds'][name])
                   for name,d in spec['methods'].items()}
        n,nk = meta['raw_per_kf'],meta['keyframes'];timing=[];dogrows=[]
        for i,path in enumerate(sorted((score/'history').glob('*.npz'))):
            h = dict(np.load(path));snap,poses = snapshot_poses(run,meta,i)
            assert int(h['input_frame'])==snap['input_frame']
            assert int(h['pose_revision'])==snap['pose_revision']
            for name,p in methods.items():
                tick=time.monotonic();d=spec['methods'][name]
                if d['kind']=='original':
                    v=np.full((i+1)*n,np.nan,np.float32)
                elif d['kind']=='dog':
                    before=np.isin(p.state,[PROVISIONAL,KEEP]).reshape(nk,n)
                    assert not before[i:].any()
                    value,image,count=dog_score(local,poses,before,i,meta['predicted_cameras'][i],base)
                    v=np.full((i+1)*n,np.nan,np.float32);v[i*n:(i+1)*n]=value
                    dogrows.append(dict(method=name,snapshot=i,premap_candidates=count,
                        original_prefix=int(f['active'][:i*n].sum()),pose_revision=snap['pose_revision']))
                else:
                    v=h[d['score']].reshape(-1)
                    if d['score']=='P1_second_front_relative':
                        assert np.all(h['support_count'].reshape(-1)[np.isfinite(v)]>=2)
                admitted=p.advance(i,snap['input_frame'],snap['pose_revision'],v)
                target=dest/name;target.mkdir(exist_ok=True)
                np.savez_compressed(target/f'snapshot{i:04d}.npz',admitted=np.packbits(admitted),
                    input_frame=snap['input_frame'],pose_revision=snap['pose_revision'])
                timing.append(dict(method=name,snapshot=i,policy_cpu_seconds=time.monotonic()-tick))
            print(f'{scene}: KF {i+1}/{nk}; '+', '.join(f'{name} reject={int((p.state==REJECT).sum())}'
                for name,p in methods.items() if name in ['B6_safe','P_legacy','P_safe','P_persist']),flush=True)
        for name,p in methods.items():
            np.savez_compressed(dest/name/'decisions.npz',**p.arrays(),original_active=f['active'],
                anchors=f['anchor_kf'],created_input=np.array([v['input_frame'] for v in meta['lineage']])[f['anchor_kf']])
            save_json(dest/name/'timeline.json',p.timeline)
        save_json(dest/'timing.json',timing);save_json(dest/'dog_maps.json',dogrows)
        artifacts=[digest(p) for p in sorted(dest.rglob('*')) if p.is_file()]
        save_json(dest/'manifest.json',dict(scene=scene,gt_reads='forbidden',seal=digest(out/'seal.json'),
            feature_manifest=digest(score/'score_manifest.json'),artifacts=artifacts,
            lineage=meta['lineage'],provisional_renderable=True,deferred_queue=False,
            wall_seconds=time.monotonic()-start))


def summarize(rows,exclude):
    return {k:float(np.mean([r[k] for r in rows if r[k] is not None]))
            if any(r[k] is not None for r in rows) else None for k in rows[0] if k not in exclude}


def evaluate(scene):
    spec,out=setup();seal=checked_seal(spec,out)
    dest=out/'evaluation'/scene;dest.mkdir(parents=True,exist_ok=True)
    if (dest/'metrics.json').exists():
        raise RuntimeError('Completed evaluation preserved')
    replay_root=out/'replay'/scene
    manifest=json.loads((replay_root/'manifest.json').read_text())
    for e in manifest['artifacts']:
        assert digest(ROOT/e['path'])==e
    source=ROOT/source_spec(spec,scene)['source']
    score,run,meta,f,local=load_scene(source_spec(spec,scene),scene)
    lp=source/'evaluation'/scene/'labels.npz'
    labelsets=dict(np.load(lp));label_info=json.loads(lp.with_name('label_manifest.json').read_text())
    lspec=json.loads((ROOT/spec['label_base_config']).read_text())
    dataset=ROOT/(spec['fresh_dataset'] if scene==spec['fresh_scene'] else 'data/E2b/Replica')
    camera=json.loads((dataset/'cam_params.json').read_text())['camera']
    poses=np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    K=camera_geometry(camera)[0];alignment=np.array(label_info['alignment'])
    dump_path=run/'map'/f'{scene}_kfgauss.pt'
    final_poses=[sim3_matrix(row['T_WC'].numpy()) for row in torch.load(dump_path,map_location='cpu',weights_only=True)['keyframes']]
    decisions={p:dict(np.load(replay_root/p/'decisions.npz')) for p in spec['methods']}
    common=f['active'].copy()
    for p in ['B2_legacy','B6_legacy','B7_legacy','B8_legacy','P_legacy']:
        common &= decisions[p]['ever_finite']
    n,nk=meta['raw_per_kf'],meta['keyframes'];inputs=[]
    def view(frame):
        path=dataset/scene/'results'/f'depth{frame:06d}.png'
        raw=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
        assert raw is not None
        gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera)
        valid,edge=depth_masks(gt,lspec);inputs.append(digest(path))
        return gt,valid,edge
    result=dict(scene=scene,fresh=scene==spec['fresh_scene'],seal=digest(out/'seal.json'),
        specification=spec,methods={},common_candidates=int(common.sum()),
        labels=digest(lp),replay=digest(replay_root/'manifest.json'))
    for name,d in decisions.items():
        tick=time.monotonic();mask=f['active']&np.isin(d['state'],[PROVISIONAL,KEEP])
        m={mode:metrics(d,y,f['active']) for mode,y in labelsets.items()}
        cohort=metrics(d,labelsets['creation'],common)
        anchor=[]
        for a in range(nk):
            entry=metrics(d,labelsets['creation'],f['active']&(f['anchor_kf']==a))
            anchor.append(dict(anchor=a,**entry))
        mu,cov,rgb,opacity=bake(local,[alignment@p for p in final_poses],mask.reshape(nk,n))
        map_path=dest/f'{name}_compact_map.npz'
        np.savez_compressed(map_path,means=mu,covariances=cov,rgb=rgb,opacity=opacity)
        bad=(labelsets['final_estimated'][mask]==3).astype(np.float32)
        rows=[];image_dir=dest/'render'/name;image_dir.mkdir(parents=True,exist_ok=True)
        for frame in spec['render_frames']:
            gt,valid,edge=view(frame);pose=poses[frame]
            z=(mu-pose[:3,3])@pose[:3,2]
            rendered=render(mu,cov,opacity,np.stack([z,np.ones_like(z),bad],-1),pose,K,gt.shape)
            stat,pred,weight=depth_metrics(rendered,gt,valid,edge,lspec)
            rows.append(dict(frame=frame,**stat))
            if frame in [201,701]:
                np.savez_compressed(image_dir/f'frame{frame:06d}.npz',gt=gt,pred=pred,weight=weight,valid=valid)
        del mu,cov,rgb,opacity
        temporal=[]
        for i in range(nk):
            packed=np.load(replay_root/name/f'snapshot{i:04d}.npz')
            selected=np.unpackbits(packed['admitted'])[:len(mask)].astype(bool).reshape(nk,n)
            snap,actual_poses=snapshot_poses(run,meta,i);frame=2*snap['input_frame']+1
            gt,valid,edge=view(frame);pose=poses[frame]
            mu,cov,rgb,opacity=bake(local[:i+1],[alignment@p for p in actual_poses],selected[:i+1])
            z=(mu-pose[:3,3])@pose[:3,2]
            rendered=render(mu,cov,opacity,np.stack([z,np.ones_like(z),np.zeros_like(z)],-1),pose,K,gt.shape)
            stat,_,_=depth_metrics(rendered,gt,valid,edge,lspec)
            temporal.append(dict(snapshot=i,frame=frame,**stat))
        result['methods'][name]=dict(decision=m,common=cohort,anchors=anchor,frames=rows,
            final_render=summarize(rows,{'frame'}),temporal_frames=temporal,
            temporal_mean=summarize(temporal,{'snapshot','frame'}),map=digest(map_path),
            queue_candidates=0,parameter_retuning=False,evaluation_seconds=time.monotonic()-tick)
        print(f'{scene} {name}: bad={m["creation"]["bad_rejected"]}, normal={m["creation"]["normal_rejected"]}, '+
            f'finite retention={m["creation"]["finite_normal_retention"]}, coverage={result["methods"][name]["final_render"]["coverage"]:.6f}',flush=True)
    rule=spec['progress'];base=result['methods']['B1']['final_render'];result['assessment']={}
    for name in ['P_safe','P_persist']:
        a=result['methods'][name];m=a['decision']['creation'];c=a['common']
        ge=lambda v,t:v is not None and v>=t
        anchors=[v for v in a['anchors'] if v['finite_normal']>=spec['risk_calibration']['anchor_group_min_normal']]
        checks=dict(calibrated=seal['calibration'][name]['calibrated'],
            global_normal=ge(m['normal_active_retention'],rule['normal_retention_min']),
            finite_normal=ge(m['finite_normal_retention'],rule['normal_retention_min']),
            common_normal=ge(c['normal_active_retention'],rule['normal_retention_min']),
            anchor_normal=bool(anchors) and all(ge(v['finite_normal_retention'],rule['normal_retention_min']) for v in anchors),
            bad_recall=ge(m['bad_recall'],rule['bad_recall_min']),bad_rejected=m['bad_rejected']>=rule['bad_rejected_min'],
            coverage=a['final_render']['coverage']>=base['coverage']-rule['coverage_loss_max'],
            depth_l1=a['final_render']['depth_l1_m']<=base['depth_l1_m']+rule['depth_l1_increase_max_m'])
        for scope,candidate in [('global',m),('common',c)]:
            baseline_precision=[(result['methods'][b]['common'] if scope=='common' else
                result['methods'][b]['decision']['creation'])['precision'] for b in ['B6_safe','B7_safe','B8_safe']]
            checks[f'{scope}_precision_gain_each_strong_baseline']=all(
                candidate['precision'] is not None and v is not None and
                candidate['precision']>=v+rule['precision_gain_min'] for v in baseline_precision)
        result['assessment'][name]=dict(checks=checks,passed=all(checks.values()),failed=[k for k,v in checks.items() if not v])
    passed=any(v['passed'] for v in result['assessment'].values())
    result['status']='FRESH_PASS' if passed and result['fresh'] else 'REGRESSION_PASS_ONLY' if passed else 'REVISE'
    result['go_for_e4']=passed and result['fresh'];result['research_wide_go']=False
    save_json(dest/'metrics.json',result);save_json(ROOT/f'configs/e3b_{scene}_results_summary.json',result)
    save_json(dest/'manifest.json',dict(metrics=digest(dest/'metrics.json'),labels=digest(lp),
        label_manifest=digest(lp.with_name('label_manifest.json')),camera=digest(dataset/'cam_params.json'),
        gt_poses=digest(dataset/scene/'traj.txt'),depths=list({v['path']:v for v in inputs}.values()),
        original_dump=digest(dump_path),seal=digest(out/'seal.json')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','replay','evaluate'])
    p.add_argument('scene',nargs='?',default='room0',choices=['office0','room0','room1']);args=p.parse_args()
    if args.stage=='prepare':prepare()
    elif args.stage=='replay':replay(args.scene)
    else:evaluate(args.scene)
