#!/usr/bin/env python3
"""CUDA evaluation of A1-C; no method fitting or candidate changes."""
from pathlib import Path
import gc
import json
import sys
import time
import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
sys.path.append(str(ROOT/'results/E4_matched_budget/deps'))
from a1_c_common import context,ARMS,ALL_ARMS,OLD_ARMS,prior,load_views,stats,frames
from build_a1_canonical_oracles import checked
from prepare_e2b_run import digest,save_json
from evaluate_e4 import CudaMap,integrate
from e4_budget import pack_parameters,sample_mesh,surface_metrics,image_metrics
from a0_metrics import depth_state,mean_rows


@torch.no_grad()
def main():
    spec,out,_=checked();assert torch.cuda.is_available(),'Host CUDA required'
    torch.set_num_threads(2);cv2.setNumThreads(2);torch.backends.cuda.matmul.allow_tf32=False
    construction=json.loads((out/'oracles/completion.json').read_text());assert construction['status']=='PASS'
    dest=out/'evaluation';dest.mkdir(exist_ok=False)
    save_json(dest/'environment.json',dict(torch=torch.__version__,CUDA=torch.version.cuda,GPU=torch.cuda.get_device_name(0),
        TF32=False,renderer='existing E4 compact CUDA',SH_degree=0,refiner=0,model_inference=False))
    K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
    smoke=CudaMap(pack_parameters(np.array([[0.,0,70.],[0,0,90.]]),np.repeat((np.eye(3)*.5)[None],2,axis=0),np.array([[1.,0,0],[0,0,1.]]),np.array([.5,.5])))
    d=smoke.depth(np.eye(4),K,(64,64));z=float(d[32,32,0]/d[32,32,1]);assert 70<z<90
    save_json(dest/'smoke.json',dict(status='PASS',known_depth_70_90m=z));del smoke;torch.cuda.empty_cache()
    completed=[];replays=[]
    for name,case in spec['cases'].items():
        folder=dest/name;folder.mkdir();mp=out/'oracles'/name/'manifest.json';assert digest(mp)==construction['cases'][name]
        maps=json.loads(mp.read_text());views,inputs=load_views(case);save_json(folder/'input_manifest.json',[digest(p) for p in inputs])
        replay=[]
        for arm in OLD_ARMS:
            old=prior(case,arm);assert digest(old['map'])==old['map_hash']
            g=CudaMap(np.array(np.memmap(old['map'],dtype=np.float32,mode='r',shape=(old['count'],13)),copy=True))
            olddepth=np.load(old['folder']/'depth.npy',mmap_mode='r');oldcover=np.load(old['folder']/'covered.npy',mmap_mode='r');oldids=json.loads((old['folder']/'metrics.json').read_text())['frame_ids']
            for f in case['saved_views']:
                a=views[f];raw=g.depth(a['pose'],a['K'],a['hw']);pred,covered,_,_=depth_state(raw[:,:,0],raw[:,:,1],a['gt'],a['valid'],spec['evaluation']['weight_min'],case['absolute_tolerance_m'],.02)
                j=oldids.index(f);common=covered&oldcover[j];delta=float(np.abs(pred[common]-olddepth[j][common]).max()) if common.any() else 0.
                disagreements=int(np.count_nonzero(covered!=oldcover[j]));assert delta<=spec['implementation_checks']['prior_replay_depth_max_difference_m'] and disagreements==0
                replay.append(dict(arm=arm,frame=f,depth_max_difference_m=delta,coverage_disagreements=disagreements))
            del g;gc.collect();torch.cuda.empty_cache()
        replays.append(dict(case=name,status='PASS',checks=replay));save_json(folder/'prior_CUDA_replay.json',replays[-1])
        for v in maps['variants']:
            p=ROOT/v['map_file']['path'];assert digest(p)==v['map_file'];vf=folder/v['id'];vf.mkdir()
            ids=case['covariance_views'] if v['covariance_policy']=='fixed_C00_world' else frames(case)
            g=CudaMap(np.array(np.memmap(p,dtype=np.float32,mode='r',shape=(v['count'],13)),copy=True))
            hw=next(iter(views.values()))['hw'];depth=np.lib.format.open_memmap(vf/'depth.npy',mode='w+',dtype=np.float32,shape=(len(ids),*hw));coverage=np.lib.format.open_memmap(vf/'covered.npy',mode='w+',dtype=bool,shape=(len(ids),*hw))
            volume=None
            if case['scene']=='office2' and v['covariance_policy']=='rigid_transport':
                import open3d as o
                volume=o.pipelines.integration.ScalableTSDFVolume(.04,.12,o.pipelines.integration.TSDFVolumeColorType.NoColor)
            old00=prior(case,'A00');olddepth=np.load(old00['folder']/'depth.npy',mmap_mode='r') if v['id']=='C00' else None
            oldcover=np.load(old00['folder']/'covered.npy',mmap_mode='r') if v['id']=='C00' else None
            rows=[];start=time.monotonic()
            for j,f in enumerate(ids):
                a=views[f];raw=g.depth(a['pose'],a['K'],a['hw'])
                pred,covered,correct,s=depth_state(raw[:,:,0],raw[:,:,1],a['gt'],a['all_valid'],spec['evaluation']['weight_min'],case['absolute_tolerance_m'],.02)
                depth[j]=pred;coverage[j]=covered
                if v['id']=='C00':np.testing.assert_array_equal(pred,olddepth[j]);np.testing.assert_array_equal(covered,oldcover[j])
                good=a['valid']&covered;error=np.abs(pred-a['gt']);row=dict(frame=f,**s,interior_error_m=stats(error[good]),depth_bins={})
                for lo,hi in zip(case['depth_bins_m'][:-1],case['depth_bins_m'][1:]):
                    m=a['valid']&(a['gt']>=lo)&(a['gt']<hi);ok=m&covered
                    row['depth_bins'][f'{lo}-{hi}']=dict(reference_pixels=int(m.sum()),covered_pixels=int(ok.sum()),
                        MAE_m=float(error[ok].mean()) if ok.any() else None,correct_coverage=float(correct[m].mean()) if m.any() else None)
                rgb=g.render(a['pose'],a['K'],a['hw']).clamp(0,1).permute(1,2,0).cpu().numpy();row.update(image_metrics(rgb,a['target']))
                if volume is not None and f in case['covariance_views']:integrate(volume,np.where(a['valid']&covered,pred,0),a['pose'],a['K'])
                if f in case['saved_views']:
                    np.savez_compressed(vf/f'frame{f:04d}.npz',depth=pred,covered=covered,weight=raw[:,:,1],gt=a['gt'],valid=a['valid'],rgb=rgb,target=a['target'])
                rows.append(row)
                if j%100==0:print(name,v['id'],j+1,'/',len(ids),flush=True)
            depth.flush();coverage.flush();del depth,coverage
            surface=None
            if volume is not None:
                mesh=volume.extract_triangle_mesh();assert len(mesh.triangles)>0
                assert o.io.write_triangle_mesh(str(vf/'rendered_depth_tsdf.ply'),mesh)
                points=sample_mesh(np.asarray(mesh.vertices),np.asarray(mesh.triangles),100000,0);np.save(vf/'surface_samples.npy',points)
                reference=np.load(ROOT/spec['prior_office']/'evaluation/reference_surface_samples.npy');surface=surface_metrics(points,reference,.05)
            metric=dict(variant=v,frame_ids=ids,frames=rows,summary=mean_rows(rows,['mae_m','absrel','coverage','correct_coverage','psnr_db','ssim']),surface=surface,
                depth_cache=digest(vf/'depth.npy'),coverage_cache=digest(vf/'covered.npy'),wall_seconds=time.monotonic()-start)
            save_json(vf/'metrics.json',metric);completed.append(digest(vf/'metrics.json'))
            print('Completed',name,v['id'],json.dumps(metric['summary']),flush=True)
            del g,volume;gc.collect();torch.cuda.empty_cache()
    save_json(dest/'completion.json',dict(status='COMPLETE',metric_files=completed,prior_GPU_replays=replays))
    print('A1-C CUDA evaluation COMPLETE.',flush=True)


if __name__=='__main__':main()
