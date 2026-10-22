"""Seal E4 development, replay natural policies, and generate separate quota arms."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest,save_json
from run_e3 import load_scene as inherited_load,feature_guard,snapshot_poses,dog_score
from e3b_provisional import ProvisionalAdmission,calibrate,KEEP,REJECT,PROVISIONAL
from e4_budget import select_budget,voxel_birth_score
from e0b_audit import transform

CFG=ROOT/'configs/e4_matched_budget.json'
CODE=['configs/e4_matched_budget.json','scripts/run_e4.py','scripts/score_e4.py','scripts/e4_fresh.py',
      'scripts/evaluate_e4.py','scripts/run_e4.sh','src/e4_budget.py','tests/test_e4.py',
      'src/e3c_matched.py','src/e3b_provisional.py','src/e2_signals.py','src/e2b_transfer.py',
      'scripts/run_e3.py','scripts/render_e1.py','src/e3_cpu_renderer.py','src/e3_splat_cpu.cpp',
      'src/e1_taxonomy.py','src/e0b_audit.py','src/e0_export.py','src/e0b_export.py',
      'scripts/prepare_e2b_run.py','scripts/score_e2b.py','scripts/score_e2.py',
      'configs/e2_discriminability.json','configs/e1_taxonomy.json','configs/e0b_replica_office0.yaml',
      'thirdparty/Splatt3R-SLAM/splatt3r_slam/image.py',
      'thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py']


def setup():
    torch.set_num_threads(2)
    spec=json.loads(CFG.read_text());out=ROOT/spec['output'];out.mkdir(parents=True,exist_ok=True)
    return spec,out


def initialize():
    spec,out=setup();registration=json.loads((out/'protocol_registration.json').read_text())
    assert registration['specification']==spec and registration['spec_sha256']==digest(CFG)['sha256']
    for scene,source in spec['previous_sources'].items():
        p=out/'baselines'/scene;p.parent.mkdir(exist_ok=True)
        origin=ROOT/source/'baselines'/scene
        if not p.exists():p.symlink_to(origin,target_is_directory=True)
        assert p.resolve()==origin.resolve()


def load_scene(spec,scene):
    source=spec['output'] if scene in ['room2',spec['fresh_scene']] else spec['prior']
    score,run,meta,f,local=inherited_load(dict(source=source),scene)
    if scene in ['office0','room0','room1']:
        broad=ROOT/spec['previous_sources'][scene]/'scores'/scene
        m=json.loads((broad/'score_manifest.json').read_text())
        for e in m['code']+m['inputs']+m['history']+[m['features'],m['metadata']]:assert digest(ROOT/e['path'])==e
        bf=dict(np.load(broad/'features.npz'))
        f['max__B7_rgb_ncc_region']=bf['max__B7_rgb_ncc_region']
        f['creation__B7_rgb_ncc_region']=bf['creation__B7_rgb_ncc_region']
    else:broad=score
    return score,broad,run,meta,f,local


def extras(local,run,meta,active,side):
    n,nk=meta['raw_per_kf'],meta['keyframes'];voxel=np.full(n*nk,np.nan,np.float32);self_score=voxel.copy()
    for i,kf in enumerate(local):
        snap,poses=snapshot_poses(run,meta,i)
        older=[transform(local[j]['means'][active[j*n:(j+1)*n]],poses[j]) for j in range(i)]
        old=np.concatenate(older) if older else np.empty((0,3))
        born=active[i*n:(i+1)*n];ids=np.flatnonzero(born)+i*n
        voxel[ids]=voxel_birth_score(old,transform(kf['means'][born],poses[i]),side)
        rawpath=run/'exports/raw_pairs'/f"{meta['lineage'][i]['event_id']}.pt"
        raw=torch.load(rawpath,map_location='cpu',weights_only=True)['outputs'][0]['pts3d'].numpy().reshape(-1,3)
        self_score[i*n:(i+1)*n]=np.linalg.norm(kf['means']-raw,axis=1)/np.maximum(np.linalg.norm(raw,axis=1),1e-12)
    return dict(B4_voxel=voxel,B5_self=self_score)


def definitions():
    return {'B1':dict(kind='original'),
        **{f'B3_random_s{s}':dict(kind='original') for s in [0,1,2]},
        'B2_confidence':dict(kind='creation'),'B4_voxel':dict(kind='creation'),'B5_self':dict(kind='creation'),
        'B6_depth':dict(kind='review'),'B7_rgb':dict(kind='review'),'B8_dog':dict(kind='dog'),
        'D_shared':dict(kind='review'),'D_maskmedian':dict(kind='review'),
        'P1_creation':dict(kind='creation'),'P2_plane':dict(kind='review'),'P3_rgb_and':dict(kind='review')}


def prepare():
    spec,out=setup()
    if (out/'seal.json').exists():raise RuntimeError('Completed E4 seal preserved')
    score,broad,run,meta,f,local=load_scene(spec,'office0')
    lp=ROOT/spec['prior']/'evaluation/office0/labels.npz';y=np.load(lp)['creation']
    radius=np.concatenate([np.linalg.norm(k['means'][k['active']],axis=1) for k in local])
    side=.01*float(np.median(radius));ex=extras(local,run,meta,f['active'],side)
    old=json.loads((ROOT/'configs/e3b_preregistration.json').read_text());prior=json.loads((ROOT/'configs/e3c_preregistration.json').read_text())
    threshold={'B1':None,**{f'B3_random_s{s}':None for s in [0,1,2]}}
    for name,key in [('B2_confidence','B2_legacy'),('B6_depth','B6_safe'),('B7_rgb','B7_safe'),('B8_dog','B8_safe')]:threshold[name]=old['thresholds'][key]
    for name,key in [('D_shared','D_shared'),('D_maskmedian','D_maskmedian'),('P2_plane','P_shared')]:threshold[name]=prior['thresholds'][key]
    common=f['active']&np.isfinite(f['max__P_shared']);calibration={}
    rgb=f['max__B7_rgb_ncc_region'];p3=np.full(len(rgb),np.nan,np.float32)
    # Compute joint temporal maximum, not min of independent temporal maxima.
    for hp in sorted((score/'history').glob('*.npz')):
        a=np.load(hp)['P_shared'].reshape(-1);b=np.load(broad/'history'/hp.name)['B7_rgb_ncc_region'].reshape(-1)
        v=np.minimum(a/threshold['P2_plane'],b/threshold['B7_rgb']);p3[:len(v)]=np.fmax(p3[:len(v)],v)
    values={**ex,'P1_creation':f['creation__P_shared'],'P3_rgb_and':p3}
    for name,v in values.items():
        c=calibrate(v,y,f['active'],common,f['anchor_kf'],.99,100);threshold[name]=c['threshold'];calibration[name]=c
    np.savez_compressed(out/'development_extra_scores.npz',**values)
    for p in CODE:
        dest=out/'sealed_code'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dest)
    import open3d,lpips
    assert open3d.__version__=='0.19.0'
    env=dict(python=sys.version,torch=torch.__version__,numpy=np.__version__,open3d=open3d.__version__,
        thread_env={k:os.environ.get(k) for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']})
    save_json(out/'development_environment.json',env);save_json(ROOT/'configs/e4_development_environment.json',env)
    runtime_inputs=[digest(p) for p in (out/'deps/open3d/cpu').glob('pybind*.so')]
    runtime_inputs += [digest(ROOT/'results/E0_baseline_reproduction/setup/torch-cache/hub/checkpoints/alexnet-owt-7be5be79.pth'),digest(Path(lpips.__file__).parent/'weights/v0.1/alex.pth')]
    seal=dict(sealed_at_utc=datetime.now(timezone.utc).isoformat(),specification=spec,runtime_inputs=runtime_inputs,
        thresholds=threshold,calibration=calibration,voxel_side_predicted_units=side,
        code=[digest(ROOT/p) for p in CODE],definitions=definitions(),fresh_evaluation_read=False,
        inputs=[digest(lp),digest(score/'score_manifest.json'),digest(broad/'score_manifest.json'),
                digest(ROOT/'configs/e3b_preregistration.json'),digest(ROOT/'configs/e3c_preregistration.json'),
                digest(out/'protocol_registration.json'),digest(out/'development_extra_scores.npz')])
    save_json(out/'seal.json',seal);save_json(ROOT/'configs/e4_preregistration.json',seal)
    print(json.dumps(dict(thresholds=threshold,voxel_side=side),indent=2),flush=True)


def checked_seal(spec,out):
    seal=json.loads((out/'seal.json').read_text());assert seal['specification']==spec
    for e in seal['code']+seal['inputs']+seal['runtime_inputs']:assert digest(ROOT/e['path'])==e,e['path']
    return seal


def replay(scene):
    spec,out=setup();seal=checked_seal(spec,out);dest=out/'replay'/scene
    if (dest/'manifest.json').exists():raise RuntimeError('Completed replay preserved')
    dest.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    with feature_guard():
        score,broad,run,meta,f,local=load_scene(spec,scene)
        base=json.loads((ROOT/spec['feature_base_config']).read_text());n,nk=meta['raw_per_kf'],meta['keyframes']
        ex=extras(local,run,meta,f['active'],seal['voxel_side_predicted_units'])
        policies={name:ProvisionalAdmission(d,f['active'],f['anchor_kf'],seal['thresholds'][name]) for name,d in seal['definitions'].items()}
        peaks={name:np.full(len(f['active']),np.nan,np.float32) for name in policies};dog_audit=[]
        for i,hp in enumerate(sorted((score/'history').glob('*.npz'))):
            h=dict(np.load(hp));bh=np.load(broad/'history'/hp.name);snap,poses=snapshot_poses(run,meta,i);end=(i+1)*n
            assert int(h['input_frame'])==snap['input_frame'] and int(h['pose_revision'])==snap['pose_revision']
            scores={'B2_confidence':-np.concatenate([v['conf'] for v in local[:i+1]]),
                'B4_voxel':ex['B4_voxel'][:end],'B5_self':ex['B5_self'][:end],
                'B6_depth':h['D_native'].reshape(-1),'B7_rgb':bh['B7_rgb_ncc_region'].reshape(-1),
                'D_shared':h['D_shared'].reshape(-1),'D_maskmedian':h['D_maskmedian'].reshape(-1),
                'P1_creation':h['P_shared'].reshape(-1),'P2_plane':h['P_shared'].reshape(-1)}
            scores['P3_rgb_and']=np.minimum(scores['P2_plane']/seal['thresholds']['P2_plane'],scores['B7_rgb']/seal['thresholds']['B7_rgb'])
            before=np.isin(policies['B8_dog'].state,[PROVISIONAL,KEEP]).reshape(nk,n)
            dog,_,count=dog_score(local,poses,before,i,meta['predicted_cameras'][i],base)
            dog_audit.append(dict(snapshot=i,premap_count=count,expected=int(before[:i].sum()),pose_revision=snap['pose_revision']))
            assert count==int(before[:i].sum())
            scores['B8_dog']=np.full(end,np.nan,np.float32);scores['B8_dog'][i*n:end]=dog
            for name,p in policies.items():
                v=scores.get(name,np.full(end,np.nan,np.float32));p.advance(i,snap['input_frame'],snap['pose_revision'],v)
                vv=v.copy()
                if p.definition['kind'] in ['creation','dog']:vv[:i*n]=np.nan
                peaks[name][:end]=np.fmax(peaks[name][:end],vv)
            print(f'{scene}: causal KF {i+1}/{nk}; plane rejects={int((policies["P2_plane"].state==REJECT).sum())}',flush=True)
        rows=[];targets=out/'selection'/scene;targets.mkdir(parents=True,exist_ok=True)
        for name,p in policies.items():
            natural=f['active']&np.isin(p.state,[PROVISIONAL,KEEP]);seed=int(name[-1]) if name.startswith('B3_') else 0
            if name.startswith('B3_'):natural,_=select_budget(f['active'],f['active'],peaks[name],.95,'random',seed)
            target=dest/name;target.mkdir(exist_ok=True)
            np.savez_compressed(target/'decisions.npz',**p.arrays(),natural_membership=natural,active=f['active'],score=peaks[name],anchors=f['anchor_kf'])
            ident=f'{name}__natural';np.savez_compressed(targets/f'{ident}.npz',mask=np.packbits(natural),size=len(natural))
            rows.append(dict(id=ident,method=name,arm='natural',fraction=None,count=int(natural.sum()),reachable=True,seed=seed))
            for fraction in spec['keep_fractions']:
                for arm in ['rank_only','policy_fallback']:
                    actual='random' if name=='B1' or name.startswith('B3_') else arm
                    selected,detail=select_budget(f['active'],natural,peaks[name],fraction,actual,seed)
                    ident=f'{name}__{arm}__{fraction:g}'
                    row=dict(id=ident,method=name,arm=arm,fraction=fraction,seed=seed,reachable=selected is not None,**detail)
                    if selected is not None:np.savez_compressed(targets/f'{ident}.npz',mask=np.packbits(selected),size=len(selected));row['count']=int(selected.sum())
                    rows.append(row)
        save_json(dest/'dog_audit.json',dog_audit);save_json(targets/'index.json',rows)
        artifacts=[digest(p) for p in sorted(dest.rglob('*')) if p.is_file()]+[digest(p) for p in sorted(targets.glob('*')) if p.is_file()]
        save_json(dest/'manifest.json',dict(scene=scene,gt_reads='forbidden',seal=digest(out/'seal.json'),artifacts=artifacts,
            source_features=digest(score/'score_manifest.json'),broad_features=digest(broad/'score_manifest.json'),
            causal_natural_only=True,quota_selection='retrospective resource diagnostic, not online admission',
            wall_seconds=time.monotonic()-start))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['initialize','prepare','replay']);p.add_argument('scene',nargs='?',default='office0');a=p.parse_args()
    if a.stage=='initialize':initialize()
    elif a.stage=='prepare':prepare()
    else:replay(a.scene)
