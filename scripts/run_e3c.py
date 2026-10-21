"""E3c matched causal replay, development-only calibration and evaluation."""
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
from run_e3 import feature_guard,load_scene,snapshot_poses,bake,depth_metrics
from e3_cpu_renderer import render
from e3b_provisional import cumulative_scores,calibrate,ProvisionalAdmission,metrics,PROVISIONAL,KEEP,REJECT
from e1_taxonomy import camera_geometry,resize_depth,depth_masks
from e0b_audit import sim3_matrix

CFG = ROOT/'configs/e3c_matched_evidence.json'
CODE = ['configs/e3c_matched_evidence.json','src/e3c_matched.py','scripts/run_e3c.py',
        'scripts/score_e3c.py','scripts/e3c_fresh.py','tests/test_e3c.py','scripts/run_e3c.sh',
        'src/e3b_provisional.py','src/e2b_transfer.py','src/e2_signals.py',
        'scripts/score_e2b.py','scripts/score_e2.py','scripts/run_e3.py',
        'src/e3_cpu_renderer.py','src/e3_splat_cpu.cpp','src/e1_taxonomy.py',
        'src/e0b_audit.py','src/e0_export.py','src/e0b_export.py',
        'scripts/prepare_e2b_run.py','scripts/download_e3b_replica.py','scripts/download_e0_replica.py',
        'configs/e2_discriminability.json','configs/e1_taxonomy.json',
        'thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py']

def setup():
    torch.set_num_threads(2);cv2.setNumThreads(2)
    spec = json.loads(CFG.read_text());out = ROOT/spec['output']
    out.mkdir(parents=True,exist_ok=True)
    return spec,out



def source_spec(spec,scene):
    return dict(source=spec['source'])


def initialize():
    spec,out=setup()
    registration=json.loads((out/'protocol_registration.json').read_text())
    assert registration['specification']==spec
    assert digest(CFG)['sha256']==registration['spec_sha256']
    for scene,source in spec['previous_sources'].items():
        target=out/'baselines'/scene;target.parent.mkdir(exist_ok=True)
        origin=ROOT/source/'baselines'/scene
        if not target.exists():target.symlink_to(origin, target_is_directory=True)
        assert target.resolve()==origin.resolve()
    copy_labels(spec,spec['development_scene'])


def copy_labels(spec,scene):
    if scene not in spec['previous_sources']:return
    src=ROOT/spec['previous_sources'][scene]/'evaluation'/scene
    dst=ROOT/spec['output']/'evaluation'/scene;dst.mkdir(parents=True,exist_ok=True)
    for name in ['labels.npz','label_manifest.json']:
        if not (dst/name).exists():shutil.copy2(src/name,dst/name)
        assert digest(src/name)['sha256']==digest(dst/name)['sha256']


def prepare():
    spec,out=setup()
    if (out/'seal.json').exists():raise RuntimeError('Completed seal preserved')
    registration=json.loads((out/'protocol_registration.json').read_text())
    assert registration['specification']==spec
    score,run,meta,f,local=load_scene(source_spec(spec,spec['development_scene']),spec['development_scene'])
    del local
    lp=out/'evaluation'/spec['development_scene']/'labels.npz';labels=np.load(lp)['creation']
    common=f['active']&np.isfinite(f['max__P_shared'])
    np.testing.assert_array_equal(np.isfinite(f['max__P_shared']),np.isfinite(f['max__D_shared']))
    thresholds,calibration={},{}
    risk=spec['risk_calibration']
    for name,d in spec['methods'].items():
        if d['kind']=='original':thresholds[name]=None;continue
        v=f['max__'+d['score']]
        c=calibrate(v,labels,f['active'],common,f['anchor_kf'],risk['normal_retention'],risk['anchor_group_min_normal'])
        thresholds[name]=c['threshold'];calibration[name]=c
    for p in CODE:
        dest=out/'sealed_code'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dest)
    env=dict(platform=platform.platform(),python=sys.version,torch=torch.__version__,numpy=np.__version__,
        compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),cpu_count=os.cpu_count(),
        threads=dict(OMP_NUM_THREADS=os.environ.get('OMP_NUM_THREADS'),torch=2,opencv=2))
    save_json(out/'environment.json',env);save_json(ROOT/'configs/e3c_environment.json',env)
    seal=dict(sealed_at_utc=datetime.now(timezone.utc).isoformat(),specification=spec,thresholds=thresholds,
        calibration=calibration,code=[digest(ROOT/p) for p in CODE],
        development_inputs=[digest(lp),digest(score/'score_manifest.json'),digest(out/'protocol_registration.json')],
        development_scene='office0',development_common_candidates=int(common.sum()),
        regression_scenes_previously_inspected=spec['regression_scenes'],fresh_scene=spec['fresh_scene'],
        fresh_evaluation_read=False,inherited_renderer_parity=digest(ROOT/'results/E3_admission_decision/renderer_parity.json'))
    save_json(out/'seal.json',seal);save_json(ROOT/'configs/e3c_preregistration.json',seal)
    print(json.dumps(dict(thresholds=thresholds,common_candidates=int(common.sum())),indent=2),flush=True)


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
        methods = {name:ProvisionalAdmission(d,f['active'],f['anchor_kf'],seal['thresholds'][name])
                   for name,d in spec['methods'].items()}
        n,nk = meta['raw_per_kf'],meta['keyframes'];timing=[]
        for i,path in enumerate(sorted((score/'history').glob('*.npz'))):
            h = dict(np.load(path));snap,poses = snapshot_poses(run,meta,i)
            assert int(h['input_frame'])==snap['input_frame']
            assert int(h['pose_revision'])==snap['pose_revision']
            for name,p in methods.items():
                tick=time.monotonic();d=spec['methods'][name]
                if d['kind']=='original':
                    v=np.full((i+1)*n,np.nan,np.float32)
                else:
                    v=h[d['score']].reshape(-1)
                admitted=p.advance(i,snap['input_frame'],snap['pose_revision'],v)
                target=dest/name;target.mkdir(exist_ok=True)
                np.savez_compressed(target/f'snapshot{i:04d}.npz',admitted=np.packbits(admitted),
                    input_frame=snap['input_frame'],pose_revision=snap['pose_revision'])
                timing.append(dict(method=name,snapshot=i,policy_cpu_seconds=time.monotonic()-tick))
            print(f'{scene}: KF {i+1}/{nk}; '+', '.join(f'{name} reject={int((p.state==REJECT).sum())}'
                for name,p in methods.items() if name in ['D_shared','P_shared','D_union','P_union']),flush=True)
        for name,p in methods.items():
            np.savez_compressed(dest/name/'decisions.npz',**p.arrays(),original_active=f['active'],
                anchors=f['anchor_kf'],created_input=np.array([v['input_frame'] for v in meta['lineage']])[f['anchor_kf']])
            save_json(dest/name/'timeline.json',p.timeline)
        save_json(dest/'timing.json',timing)
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
    copy_labels(spec,scene)
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
    dataset=ROOT/spec['datasets'][scene]
    camera=json.loads((dataset/'cam_params.json').read_text())['camera']
    poses=np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    K=camera_geometry(camera)[0];alignment=np.array(label_info['alignment'])
    dump_path=run/'map'/f'{scene}_kfgauss.pt'
    final_poses=[sim3_matrix(row['T_WC'].numpy()) for row in torch.load(dump_path,map_location='cpu',weights_only=True)['keyframes']]
    decisions={p:dict(np.load(replay_root/p/'decisions.npz')) for p in spec['methods']}
    common=f['active']&decisions['P_shared']['ever_finite']
    np.testing.assert_array_equal(decisions['D_shared']['ever_finite'],decisions['P_shared']['ever_finite'])
    union=f['active']&decisions['P_union']['ever_finite']
    np.testing.assert_array_equal(decisions['D_union']['ever_finite'],decisions['P_union']['ever_finite'])
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
            union_common=metrics(d,labelsets['creation'],union),
            queue_candidates=0,parameter_retuning=False,evaluation_seconds=time.monotonic()-tick)
        print(f'{scene} {name}: bad={m["creation"]["bad_rejected"]}, normal={m["creation"]["normal_rejected"]}, '+
            f'finite retention={m["creation"]["finite_normal_retention"]}, coverage={result["methods"][name]["final_render"]["coverage"]:.6f}',flush=True)
    rule=spec['progress'];base=result['methods']['B1']['final_render'];result['assessment']={}
    ge=lambda v,t:v is not None and v>=t
    for name,a in result['methods'].items():
        if name=='B1':continue
        m=a['decision']['creation'];c=a['common']
        anchors=[v for v in a['anchors'] if v['finite_normal']>=spec['risk_calibration']['anchor_group_min_normal']]
        checks=dict(calibrated=seal['calibration'][name]['calibrated'],
            global_normal=ge(m['normal_active_retention'],rule['normal_retention_min']),
            finite_normal=ge(m['finite_normal_retention'],rule['normal_retention_min']),
            common_normal=ge(c['normal_active_retention'],rule['normal_retention_min']),
            anchor_normal=bool(anchors) and all(ge(v['finite_normal_retention'],rule['normal_retention_min']) for v in anchors),
            bad_recall=ge(m['bad_recall'],rule['bad_recall_min']),bad_rejected=m['bad_rejected']>=rule['bad_rejected_min'],
            coverage=a['final_render']['coverage']>=base['coverage']-rule['coverage_loss_max'],
            depth_l1=a['final_render']['depth_l1_m']<=base['depth_l1_m']+rule['depth_l1_increase_max_m'])
        result['assessment'][name]=dict(checks=checks,passed=all(checks.values()),failed=[k for k,v in checks.items() if not v])
    result['paired_comparison']={}
    for suffix,key in [('shared','common'),('union','union_common')]:
        d=result['methods']['D_'+suffix][key];p=result['methods']['P_'+suffix][key]
        gain=p['bad_recall']-d['bad_recall'] if p['bad_recall'] is not None and d['bad_recall'] is not None else None
        precision_delta=p['precision']-d['precision'] if p['precision'] is not None and d['precision'] is not None else None
        checks=dict(both_safe=all(result['assessment'][n+'_'+suffix]['passed'] for n in ['D','P']),
            recall_gain=ge(gain,rule['eligible_recall_gain_min']) if suffix=='shared' else gain is not None and gain>0,
            precision_noninferior=ge(precision_delta,-rule['precision_loss_max']))
        result['paired_comparison'][suffix]=dict(depth=d,plane=p,eligible_recall_gain=gain,
            precision_delta=precision_delta,checks=checks,passed=all(checks.values()))
    passed=all(v['passed'] for v in result['paired_comparison'].values())
    result['status']='FRESH_PASS' if passed and result['fresh'] else 'REGRESSION_PASS_ONLY' if passed else 'REVISE'
    result['go_for_e4']=passed and result['fresh'];result['research_wide_go']=False
    save_json(dest/'metrics.json',result);save_json(ROOT/f'configs/e3c_{scene}_results_summary.json',result)
    save_json(dest/'manifest.json',dict(metrics=digest(dest/'metrics.json'),labels=digest(lp),
        label_manifest=digest(lp.with_name('label_manifest.json')),camera=digest(dataset/'cam_params.json'),
        gt_poses=digest(dataset/scene/'traj.txt'),depths=list({v['path']:v for v in inputs}.values()),
        original_dump=digest(dump_path),seal=digest(out/'seal.json')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['initialize','prepare','replay','evaluate'])
    p.add_argument('scene',nargs='?',default='room0',choices=['office0','room0','room1','room2']);args=p.parse_args()
    if args.stage=='initialize':initialize()
    elif args.stage=='prepare':prepare()
    elif args.stage=='replay':replay(args.scene)
    else:evaluate(args.scene)
