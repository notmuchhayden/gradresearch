#!/usr/bin/env python3
"""Render registered A0b variants against sparse heldout LiDAR observations."""
from pathlib import Path
import gc
import json
import shutil
import sys
import time
import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from prepare_a0b import load_context,SPEC,stats
from prepare_e2b_run import digest,save_json
from a0b_geometry import camera_model,load_calibrations,resize_contract,processed_rgb
from a0_metrics import depth_state,mean_rows
from e4_budget import pack_parameters,image_metrics
from pointmap_contract import transform_points
from evaluate_e4 import CudaMap


@torch.no_grad()
def main():
    assert torch.cuda.is_available(),'Host CUDA execution required'
    torch.set_num_threads(2);cv2.setNumThreads(2);torch.backends.cuda.matmul.allow_tf32=False
    spec,out,run,frames,mapping,lookup,poses=load_context();dest=out/'evaluation'
    manifest=json.loads((out/'oracles/manifest.json').read_text());assert manifest['spec']==digest(SPEC)
    assert manifest['amendment']==digest(ROOT/'configs/a0b_amendment_A1.json')
    pre=json.loads((out/'preflight/manifest.json').read_text());assert manifest['preflight']==digest(out/'preflight/manifest.json')
    dest.mkdir(exist_ok=False)
    sources=[SPEC,Path(__file__),ROOT/'src/a0b_geometry.py',ROOT/'src/a0_metrics.py',ROOT/'scripts/evaluate_e4.py',ROOT/'src/e4_budget.py']
    for p in sources:
        q=dest/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(dest/'source_manifest.json',[digest(p) for p in sources])
    # Depth compositing at actual UAV distance; an upper color clamp would fail this.
    Ksmoke=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
    smoke=CudaMap(pack_parameters(np.array([[0.,0,70.],[0,0,90.]]),np.repeat((np.eye(3)*.5)[None],2,axis=0),
        np.array([[1.,0,0],[0,0,1.]]),np.array([.5,.5])))
    raw=smoke.depth(np.eye(4),Ksmoke,(64,64));z=float(raw[32,32,0]/raw[32,32,1]);assert 70<z<90
    save_json(dest/'renderer_smoke.json',dict(status='PASS',expected_Z_between_m=[70,90],rendered_Z_m=z))
    del smoke;gc.collect();torch.cuda.empty_cache()
    cal=load_calibrations(ROOT/spec['calibration_file']);models={n:camera_model(cal,n) for n in spec['camera_models']}
    A,hw,_,_=resize_contract();eval_ids=pre['evaluation_grid_ids'];diagnostic=spec['diagnostic_view_ids']
    first_path=ROOT/'data/E4e/eth3d/HKairport01/images'/Path(mapping[0]['rgb_member']).name
    first=cv2.cvtColor(cv2.imread(str(first_path)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
    first_mean=first.reshape(-1,3).mean(0)
    targets={};references={};input_files=[first_path]
    reference_cloud=[];reference_colors=[]
    for name,m in models.items():
        for grid in eval_ids:
            p=out/'preflight/references'/f'{name}_target_{grid:03d}.npz'
            # Every reference cache was hashed before building any factorial map.
            expected=next(r for r in pre['reference_rows'] if r['grid_index']==grid)['models'][name+'_target']['file']
            assert digest(p)==expected
            with np.load(p) as f:references[name,grid]={k:f[k] for k in ['depth','valid','edge']}
            input_files.append(p)
            path=out/'preflight/heldout_rgb'/Path(frames[grid]['rgb_member']).name
            image=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
            gain=np.clip((first_mean+.001)/(image.reshape(-1,3).mean(0)+.001),.4,2.5)
            normalized=(np.clip(image*gain,0,1)*255).astype(np.uint8)
            targets[name,grid]=processed_rgb(normalized,m).astype(np.float32)/255.
            input_files.append(path)
            if name=='HKairport_released':
                a=references[name,grid];yy,xx=np.where(a['valid']);pix=np.column_stack([xx,yy,np.ones(len(xx))]);K=A@m['K']
                local=(pix@np.linalg.inv(K).T)*a['depth'][yy,xx,None]
                # Fixed spatial sampling, independent of predicted errors.
                chosen=np.arange(0,len(local),max(1,len(local)//1500))
                reference_cloud.append(transform_points(local[chosen],poses[grid]))
                reference_colors.append(targets[name,grid][yy[chosen],xx[chosen]])
    np.savez_compressed(dest/'heldout_lidar_center_reference.npz',xyz=np.concatenate(reference_cloud),rgb=np.concatenate(reference_colors))
    save_json(dest/'input_manifest.json',[digest(p) for p in sorted(set(input_files))])
    save_json(dest/'environment.json',dict(torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0),
        tf32=False,renderer='existing E4 compact CUDA',SH_degree=0,refinement=0,reference='sparse LiDAR camera Z; no dense surface GT'))
    allrows=[]
    for variant in manifest['variants']:
        assert digest(ROOT/variant['map_file'])==variant['hash']
        folder=dest/variant['id'];folder.mkdir()
        name=variant['model'];m=models[name];K=A@m['K']
        full=variant['C_multiplier']==1 and name=='HKairport_released' and variant['gauge']=='position'
        grids=eval_ids if full else diagnostic
        packed=np.memmap(ROOT/variant['map_file'],dtype=np.float32,mode='r',shape=(variant['count'],13))
        gc.collect();torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats();g=CudaMap(packed);del packed
        depth=np.lib.format.open_memmap(folder/'depth.npy',mode='w+',dtype=np.float32,shape=(len(grids),*hw))
        cover=np.lib.format.open_memmap(folder/'covered.npy',mode='w+',dtype=bool,shape=(len(grids),*hw))
        rows=[];started=time.monotonic()
        for j,grid in enumerate(grids):
            ref=references[name,grid];raw=g.depth(poses[grid],K,hw);es=spec['evaluation']
            pred,covered,correct,s=depth_state(raw[:,:,0],raw[:,:,1],ref['depth'],ref['valid'],
                es['coverage_weight_min'],es['correct_depth_absolute_m'],es['correct_depth_relative'])
            depth[j]=pred;cover[j]=covered;error=np.abs(pred-ref['depth']);good=covered&ref['valid']
            row=dict(grid_index=grid,**s,error_distribution_m=stats(error[good]),depth_bins={})
            for lo,hi in zip(es['depth_bins_m'][:-1],es['depth_bins_m'][1:]):
                mask=ref['valid']&(ref['depth']>=lo)&(ref['depth']<hi);ok=mask&covered
                row['depth_bins'][f'{lo}-{hi}']=dict(reference_pixels=int(mask.sum()),covered_pixels=int(ok.sum()),
                    mae_m=float(error[ok].mean()) if ok.any() else None,correct_coverage=float(correct[mask].mean()) if mask.any() else None)
            image=g.render(poses[grid],K,hw).clamp(0,1).permute(1,2,0).cpu().numpy()
            row.update(image_metrics(image,targets[name,grid]))
            if grid in diagnostic:
                np.savez_compressed(folder/f'grid{grid:03d}.npz',depth=pred,gt=ref['depth'],valid=ref['valid'],covered=covered,
                    weight=raw[:,:,1],rgb=image,target=targets[name,grid])
            rows.append(row)
        depth.flush();cover.flush();del depth,cover
        summary=mean_rows(rows,['mae_m','absrel','coverage','correct_coverage','psnr_db','ssim'])
        metrics=dict(variant=variant,frame_ids=grids,frames=rows,summary=summary,wall_seconds=time.monotonic()-started,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),depth_cache=digest(folder/'depth.npy'),covered_cache=digest(folder/'covered.npy'))
        save_json(folder/'metrics.json',metrics);allrows.append(digest(folder/'metrics.json'))
        print(variant['id'],json.dumps(summary),flush=True)
        del g;gc.collect();torch.cuda.empty_cache()
    save_json(dest/'completion.json',dict(status='COMPLETE',variants=len(allrows),metrics=allrows,
        source_manifest=digest(dest/'source_manifest.json'),input_manifest=digest(dest/'input_manifest.json')))


if __name__=='__main__':main()
