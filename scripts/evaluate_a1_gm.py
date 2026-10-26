#!/usr/bin/env python3
"""Render only new G/M maps; prior C maps and target-only caches are reused."""
from pathlib import Path
import gc
import json
import sys
import time
import cv2
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_gm_common import context,cases,prior_metric,get_views,ARMS
from build_a1_gm import checked
from prepare_e2b_run import digest,save_json
from evaluate_e4 import CudaMap
from e4_budget import pack_parameters
from a0_metrics import depth_state


@torch.no_grad()
def main():
    for exp in ['G','M']:checked(exp)
    assert torch.cuda.is_available(),'Host CUDA required'
    torch.set_num_threads(2);cv2.setNumThreads(2);torch.backends.cuda.matmul.allow_tf32=False;viewcache={}
    for exp in ['G','M']:
        spec,out,c,_=context(exp);folder=out/'evaluation';folder.mkdir(exist_ok=False)
        construction=json.loads((out/'maps/completion.json').read_text());assert construction['status']=='PASS'
        save_json(folder/'environment.json',dict(torch=torch.__version__,CUDA=torch.version.cuda,GPU=torch.cuda.get_device_name(0),TF32=False,
            renderer='existing compact CUDA expected-Z',new_inference=False,RGB='saved views only'))
        if exp=='G':
            K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
            g=CudaMap(pack_parameters(np.array([[0,0,70.],[0,0,90.]]),np.repeat((np.eye(3)*.5)[None],2,axis=0),np.array([[1.,0,0],[0,0,1.]]),np.array([.5,.5])))
            raw=g.depth(np.eye(4),K,(64,64));z=float(raw[32,32,0]/raw[32,32,1]);assert 70<z<90
            save_json(folder/'smoke.json',dict(status='PASS',depth_70_90m=z));del g;torch.cuda.empty_cache()
        records={};new_views=0;reused_views=0
        for name,case in cases(exp).items():
            mp=out/'maps'/name/'manifest.json';assert digest(mp)==construction['cases'][name];m=json.loads(mp.read_text())
            dest=folder/name;dest.mkdir();views=get_views(case['scene'],viewcache);ids=list(views);saved=c['cases'][case['base']]['saved_views']
            metrics=[]
            for v in m['variants']:
                arm=v['arm'];vf=dest/arm;vf.mkdir();p=ROOT/v['map_file']['path'];assert digest(p)==v['map_file']
                if case['reuse']:
                    pm=prior_metric(case['base'],arm)
                    row=dict(arm=arm,count=v['count'],frame_ids=pm['frame_ids'],depth_cache=pm['depth_cache'],coverage_cache=pm['coverage_cache'],
                        reused_A1C=True,base_case=case['base'],no_new_render=True)
                    for field in ['depth_cache','coverage_cache']:assert digest(ROOT/row[field]['path'])==row[field]
                    reused_views+=len(ids)
                else:
                    gc.collect();torch.cuda.empty_cache();g=CudaMap(np.array(np.memmap(p,dtype=np.float32,mode='r',shape=(v['count'],13)),copy=True))
                    hw=next(iter(views.values()))['hw'];d=np.lib.format.open_memmap(vf/'depth.npy',mode='w+',dtype=np.float32,shape=(len(ids),*hw));cov=np.lib.format.open_memmap(vf/'covered.npy',mode='w+',dtype=bool,shape=(len(ids),*hw))
                    start=time.monotonic()
                    for j,f in enumerate(ids):
                        a=views[f];raw=g.depth(a['pose'],a['K'],a['hw']);pred,covered,_,_=depth_state(raw[:,:,0],raw[:,:,1],a['gt'],a['valid'],.001,c['cases'][case['base']]['absolute_tolerance_m'],.02)
                        d[j]=pred;cov[j]=covered
                        if f in saved:
                            rgb=g.render(a['pose'],a['K'],a['hw']).clamp(0,1).permute(1,2,0).cpu().numpy()
                            np.savez_compressed(vf/f'frame{f:04d}.npz',depth=pred,covered=covered,rgb=rgb,gt=a['gt'],valid=a['valid'],target=a['target'])
                        if j%100==0:print(exp,name,arm,j+1,'/',len(ids),flush=True)
                    d.flush();cov.flush();del d,cov,g;gc.collect();torch.cuda.empty_cache()
                    row=dict(arm=arm,count=v['count'],frame_ids=ids,depth_cache=digest(vf/'depth.npy'),coverage_cache=digest(vf/'covered.npy'),wall_seconds=time.monotonic()-start,reused_A1C=False)
                    new_views+=len(ids)
                save_json(vf/'metrics.json',row);metrics.append(digest(vf/'metrics.json'))
            save_json(dest/'manifest.json',dict(case=name,definition=case,metrics=metrics));records[name]=digest(dest/'manifest.json')
            print('Completed',exp,name,'reuse' if case['reuse'] else 'new CUDA renders',flush=True)
        save_json(folder/'completion.json',dict(status='COMPLETE',cases=records,new_depth_views=new_views,reused_depth_views=reused_views))
    print('A1-G/M evaluation COMPLETE.',flush=True)


if __name__=='__main__':main()
