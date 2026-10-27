#!/usr/bin/env python3
"""Build the registered 20-view position-gauge TSDF diagnostic from saved A2-S depth caches."""
import csv,json,sys,hashlib
from pathlib import Path
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/A2_S_scalar_spatial/2026-10-27';sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src'),str(ROOT/'results/E4_matched_budget/deps')]
from a2_s_common import kfs,base_map,digest,dump_json
from e1_taxonomy import camera_geometry,resize_depth,depth_masks
from evaluate_e4 import volume,integrate,finish_surface
from run_e4 import setup
from e4_budget import surface_metrics

def main(scene):
    spec,_=setup();base=ROOT/'data/N2/Replica'/scene;camera=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera'];K,_,_=camera_geometry(camera);poses=np.loadtxt(base/'traj.txt').reshape(-1,4,4)
    common=json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())['common_mask'];frames=list(range(201,1000,40));view={}
    for f in frames:
        raw=cv2.imread(str(base/'results'/f'depth{f:06d}.png'),cv2.IMREAD_UNCHANGED);gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,common);view[f]=(gt,valid&~edge,poses[f])
    refpath=(ROOT/'results/A0_pointmap_pose_factorial/office2/evaluation/reference_surface_samples.npy') if scene=='office2' else ROOT/'results/V1_office3_diagnostic/2026-10-26/evaluation/reference/surface_samples.npy'
    reference=np.load(refpath);assert len(reference)==100000
    maps=json.loads((OUT/scene/'maps/manifest.json').read_text())['maps'];dep=OUT/scene/'evaluation/depth';surface=OUT/scene/'evaluation/surface';surface.mkdir(parents=True,exist_ok=True);rows=[];done={}
    for m in maps:
      if m['gauge']!='position':continue
      key=m['file']['sha256'];dst=surface/key
      if key in done:continue
      done[key]=dst;dst.mkdir(exist_ok=True);v=volume(spec);cache=dep/key
      for f in frames:
          gt,inter,pose=view[f]
          with np.load(cache/f'frame{f:04d}.npz') as a:
              z=a['depth'];w=a['weight'];pred=np.divide(z,w,out=np.zeros_like(z),where=w>1e-9);use=inter&(w>.001)&np.isfinite(pred)&(pred>0)
          integrate(v,np.where(use,pred,0).astype(np.float32),pose,K)
      points=finish_surface(v,dst/'rendered_depth_tsdf.ply',spec);np.save(dst/'surface_samples.npy',points)
      del v
    for m in maps:
      if m['gauge']!='position':continue
      p=np.load(surface/m['file']['sha256']/'surface_samples.npy');rows.append(dict(scene=scene,gauge=m['gauge'],fold=m['fold'],method=m['method'],map_sha256=m['file']['sha256'],reference_sha256=digest(refpath)['sha256'],n_surface=len(p),**surface_metrics(p,reference,.05)))
    with (OUT/scene/'evaluation/surface_metrics.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    dump_json(OUT/scene/'evaluation/surface_manifest.json',dict(status='PASS',frames=frames,reference=digest(refpath),unique_maps=len(done),geometry=spec['geometry'],artifacts=[digest(p) for p in sorted(surface.rglob('*')) if p.is_file()]))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office2','office3'],required=True);main(p.parse_args().scene)
