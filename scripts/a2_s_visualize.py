#!/usr/bin/env python3
"""Five-view RGB auxiliary and source-fold/field visualization artifacts."""
import json,sys
from pathlib import Path
import numpy as np,cv2,torch
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/A2_S_scalar_spatial/2026-10-27';sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a2_s_common import kfs,dump_json
from evaluate_e4 import CudaMap,reference_rgb
from e4_budget import image_metrics
from scalar_spatial_diagnostic import tile_masks,bilinear_basis
from e1_taxonomy import camera_geometry

def main(scene):
    if not torch.cuda.is_available():raise RuntimeError('CUDA required for saved RGB auxiliary')
    torch.backends.cuda.matmul.allow_tf32=False;torch.set_num_threads(2);cv2.setNumThreads(2)
    base=ROOT/'data/N2/Replica'/scene;camera=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera'];K,_,crop=camera_geometry(camera);poses=np.loadtxt(base/'traj.txt').reshape(-1,4,4)
    first=cv2.cvtColor(cv2.imread(str(base/'results/frame000000.jpg')),cv2.COLOR_BGR2RGB).astype(np.float32)/255.;mean=first.reshape(-1,3).mean(0)
    frames=[201,401,601,801,999];dest=OUT/scene/'evaluation/rgb';dest.mkdir(parents=True,exist_ok=True);man=json.loads((OUT/scene/'maps/manifest.json').read_text())['maps'];done=set();records=[]
    for m in man:
      key=m['file']['sha256']
      if key in done:continue
      done.add(key);packed=np.memmap(ROOT/m['file']['path'],dtype=np.float32,mode='r',shape=(m['count'],13));g=CudaMap(packed)
      for f in frames:
        target=reference_rgb(base/'results'/f'frame{f:06d}.jpg',mean);pred=g.render(poses[f],K,target.shape[:2]).clamp(0,1).permute(1,2,0).cpu().numpy();err=np.abs(pred-target)
        folder=dest/key;folder.mkdir(exist_ok=True);np.savez_compressed(folder/f'frame{f:04d}.npz',prediction=pred,target=target,absolute_error=err)
        records.append(dict(map_sha256=key,scene=scene,gauge=m['gauge'],fold=m['fold'],method=m['method'],frame=f,**image_metrics(pred,target)))
      del g,packed;torch.cuda.empty_cache()
    import csv
    with (OUT/scene/'evaluation/rgb_metrics.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    # Frozen source fold masks and fitted 4x4 log-depth fields for every strict KF.
    fits=json.loads((OUT/scene/'fits/fit_parameters.json').read_text());src=OUT/scene/'analysis/source_visuals';src.mkdir(parents=True,exist_ok=True)
    for gauge in ['position','orientation']:
      for fold in [0,1]:
        for k in kfs(scene):
          if not k['strict'].any():continue
          fit,ev=tile_masks(k['pixel_indices'],k['ref_valid'],fold=fold);state=np.zeros(288*512,np.uint8);state[k['pixel_indices'][fit]]=1;state[k['pixel_indices'][ev]]=2
          q=fits[gauge][str(fold)]['fits'][str(k['kf_idx'])]
          field=np.zeros(288*512,np.float32)
          if q['support']:field=np.asarray(bilinear_basis(np.arange(288*512)%512,np.arange(288*512)//512)@np.asarray(q['theta']),np.float32)
          strict=np.zeros(288*512,bool);strict[k['pixel_indices'][k['strict']]]=True
          p=src/f'{gauge}_fold{fold}_kf{k["kf_idx"]:03d}.npz';np.savez_compressed(p,mask=state.reshape(288,512),strict=strict.reshape(288,512),log_depth_correction=field.reshape(288,512),theta=np.asarray(q.get('theta',[])))
    dump_json(OUT/scene/'evaluation/rgb_manifest.json',dict(status='PASS',frames=frames,unique_maps=len(done),source_visuals=len(list(src.glob('*.npz'))),artifacts=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size} for p in sorted(dest.rglob('*.npz'))]))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office2','office3'],required=True);main(p.parse_args().scene)
