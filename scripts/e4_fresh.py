"""Resume the registered, unchanged-backbone office1 arm when CUDA is available."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src'),str(ROOT/'thirdparty/Splatt3R-SLAM/splatt3r_core')]
from prepare_e2b_run import digest,save_json
from e0b_audit import sim3_matrix,transform
from e1_taxonomy import fit_sim3,camera_geometry,resize_depth,depth_masks,classify
from utils.geometry import build_covariance


def baseline(spec):
    # Do not substitute GT poses, a different predictor, sparse handpicked KFs,
    # or a CPU tracker for the frozen baseline when CUDA is unavailable.
    if not torch.cuda.is_available():
        raise RuntimeError('Fresh baseline requires CUDA; registered arm remains pending')
    from run_e4 import checked_seal,setup
    _,out=setup();checked_seal(spec,out)
    hardware=dict(torch=torch.__version__,cuda=torch.version.cuda,device=torch.cuda.get_device_name(0),
        nvidia_smi=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv'],text=True))
    save_json(out/'gpu_environment.json',hardware);save_json(ROOT/'configs/e4_gpu_environment.json',hardware)
    scene=spec['fresh_scene'];dataset=ROOT/spec['fresh_dataset']/scene
    run=ROOT/spec['fresh_source']/'baselines'/scene
    if (run/'audit/events.jsonl').exists():
        raise RuntimeError('Existing baseline preserved; do not overwrite')
    images=sorted((dataset/'results').glob('frame*.jpg'))
    assert [p.name for p in images]==[f'frame{i:06d}.jpg' for i in range(spec['fresh_original_frames'])]
    download_manifest=json.loads((ROOT/f'configs/e4_{scene}_download_manifest.json').read_text())
    for e in download_manifest['files']:
        assert digest(ROOT/e['path'])['sha256']==e['sha256']
    for sub in ['logs','exports','audit']: (run/sub).mkdir(parents=True,exist_ok=True)
    upstream=ROOT/'thirdparty/Splatt3R-SLAM'
    weights=json.loads((ROOT/'configs/e0_weights_manifest.json').read_text())
    for entry in weights:
        assert digest(ROOT/entry['file'])['sha256']==entry['sha256']
    code=[ROOT/p for p in ['scripts/e4_fresh.py','src/e0_export.py','src/e0b_export.py',
                          'configs/e0b_replica_office0.yaml','configs/e4_matched_budget.json']]
    code += [upstream/p for p in ['main.py','config/base.yaml','splatt3r_slam/tracker.py',
        'splatt3r_slam/frame.py','splatt3r_slam/splatt3r_utils.py','splatt3r_slam/dataloader.py']]
    for p in code:
        target=run/'code'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    command=[str(ROOT/'.venv/bin/python'),'main.py','--dataset',str(dataset),
        '--config',str(ROOT/'configs/e0b_replica_office0.yaml'),'--checkpoint',str(ROOT/'checkpoints/e0/epoch=19-step=1200.ckpt'),
        '--retriever-path',str(ROOT/'checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth'),
        '--no-viz','--no-render-gaussians','--keyframe-buffer','32','--dump-keyframe-gaussians',
        '--spatial-stride','1','--max-gaussians','16777216','--depth-max-percentile','0.98',
        '--max-scale','1.0','--min-confidence','1.5','--refiner-conf-fade','0','--save-as',str(run/'map'),
        '--render-dir',str(run/'render'),'--frame-timing',str(run/'timing.csv')]
    env=os.environ.copy();venv=str(ROOT/'.venv')
    env.update(PATH=venv+'/bin:'+env.get('PATH',''),CONDA_PREFIX=venv,
        CUDA_HOME=venv+'/lib/python3.11/site-packages/nvidia/cu13',CUDA_VISIBLE_DEVICES='0',
        PYTHONPATH=str(ROOT/'src')+(':'+env['PYTHONPATH'] if env.get('PYTHONPATH') else ''),
        PYTHONHASHSEED='0',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',
        E0_EXPORT_DIR=str(run/'exports'),E0B_AUDIT_DIR=str(run/'audit'),E0_SEED='0',
        E0_DISABLE_GT='1',E0_FAISS_TEMP_MB='64',E0_LOW_VRAM='1',
        MPLCONFIGDIR=str(run/'.mplconfig'),XDG_CACHE_HOME=str(ROOT/'results/E0_baseline_reproduction/setup/cache'),
        TORCH_HOME=str(ROOT/'results/E0_baseline_reproduction/setup/torch-cache'),
        HF_HOME=str(ROOT/'results/E0_baseline_reproduction/setup/huggingface'))
    save_json(run/'run_manifest.json',dict(scene=scene,specification=spec,code=[digest(p) for p in code],
        inputs=[digest(p) for p in images[::2]],weights=weights,seed=0,command=command,
        upstream_commit=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip(),
        gt_depth_trajectory_used=False,calibration='use_calib=false; identical E2b original loader'))
    with (run/'logs/baseline.log').open('w') as log:
        subprocess.run(command,cwd=upstream,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)


def labels(spec):
    """Independent GT evaluation, only after all fresh admission decisions exist."""
    torch.set_num_threads(2);scene=spec['fresh_scene'];source=ROOT/spec['fresh_source']
    assert (ROOT/spec['output']/'replay'/scene/'manifest.json').exists(),'Run label-free replay before GT labels'
    out=source/'evaluation'/scene;out.mkdir(parents=True,exist_ok=True)
    if (out/'labels.npz').exists():raise RuntimeError('Existing labels preserved')
    dataset=ROOT/spec['fresh_dataset'];score=source/'scores'/scene;run=source/'baselines'/scene
    meta=json.loads((score/'score_metadata.json').read_text());f=dict(np.load(score/'features.npz'))
    lspec=json.loads((ROOT/spec['label_base_config']).read_text())
    camera=json.loads((dataset/'cam_params.json').read_text())['camera']
    poses=np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    trajectory=np.loadtxt(run/'map'/f'{scene}_frames.txt');ids=trajectory[:,0].astype(int)
    np.testing.assert_array_equal(ids,np.arange(0,spec['fresh_original_frames'],2))
    alignment=fit_sim3(trajectory[:,1:4],poses[ids,:3,3]);scale=np.cbrt(np.linalg.det(alignment[:3,:3]))
    view_ids=sorted(set(range(0,spec['fresh_original_frames'],20))|{r['original_frame'] for r in meta['lineage']})
    views=[];depth_paths=[]
    for frame in view_ids:
        path=dataset/scene/'results'/f'depth{frame:06d}.png';raw=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
        assert raw is not None;depth=resize_depth(raw.astype(np.float32)/camera['scale'],camera)
        valid,edge=depth_masks(depth,lspec);views.append(dict(frame=frame,depth=depth,valid=valid,edge=edge,pose=poses[frame]));depth_paths.append(path)
    K=camera_geometry(camera)[0];dump=torch.load(run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)
    output={k:[] for k in ['creation','final_estimated','gt_anchor']}
    for i,kf in enumerate(dump['keyframes']):
        q=kf['rotations']/kf['rotations'].norm(dim=-1,keepdim=True).clamp_min(1e-6)
        cov=build_covariance(kf['scales'],q).numpy()
        gt_anchor=poses[meta['lineage'][i]['original_frame']].copy()
        gt_anchor[:3,:3] *= scale*np.cbrt(np.linalg.det(f['creation_poses'][i,:3,:3]))
        placements=dict(creation=alignment@f['creation_poses'][i],
            final_estimated=alignment@sim3_matrix(kf['T_WC'].numpy()),gt_anchor=gt_anchor)
        for name,matrix in placements.items():
            output[name].append(classify(transform(kf['means'].numpy(),matrix),
                matrix[:3,:3]@cov@matrix[:3,:3].T,views,K,lspec)['labels'])
    output={k:np.concatenate(v) for k,v in output.items()};a,b=output['creation'],output['gt_anchor']
    consensus=np.zeros(len(a),np.uint8);consensus[(a==3)&(b==3)]=3
    consensus[np.isin(a,[1,2])&np.isin(b,[1,2])]=1;output['cross_pose_consensus']=consensus
    np.savez_compressed(out/'labels.npz',**output)
    save_json(out/'label_manifest.json',dict(scene=scene,primary='creation',specification=lspec,views=view_ids,
        alignment=alignment.tolist(),global_scale=float(scale),creation_pose_fixed_label=True,
        gt_use='evaluation only; sealed office0 thresholds; replay predates label creation',
        label_counts={k:{str(c):int((v==c).sum()) for c in [0,1,2,3]} for k,v in output.items()},
        inputs=[digest(p) for p in [dataset/'cam_params.json',dataset/scene/'traj.txt',
            run/'map'/f'{scene}_frames.txt',run/'map'/f'{scene}_kfgauss.pt',*depth_paths]]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['fresh-download','fresh-baseline','fresh-labels']);args=p.parse_args()
    spec=json.loads((ROOT/'configs/e4_matched_budget.json').read_text())
    if args.stage=='fresh-baseline':baseline(spec)
    elif args.stage=='fresh-labels':labels(spec)
    else:
        subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/download_e3b_replica.py'),
            '--scene',spec['fresh_scene'],'--frames',str(spec['fresh_original_frames']),
            '--destination',str(ROOT/spec['fresh_dataset']),'--manifest',
            str(ROOT/f'configs/e4_{spec["fresh_scene"]}_download_manifest.json'),'--workers','8'],check=True,cwd=ROOT)
