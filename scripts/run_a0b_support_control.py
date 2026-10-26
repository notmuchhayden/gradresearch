#!/usr/bin/env python3
"""A2: more source support under one explicitly conditional camera model."""
from pathlib import Path
import csv
import gc
import json
import shutil
import sys
import time
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1];UP=ROOT/'thirdparty/Splatt3R-SLAM'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(UP),str(UP/'scripts'),str(UP/'splatt3r_core')]
from prepare_a0b import load_context,stats,SPEC
from prepare_e2b_run import digest,save_json
from a0b_geometry import load_calibrations,camera_model,source_rays,resize_contract
from pointmap_contract import build_arms,sim3_from_xyzw,array_hash
from run_n1_contract import native_mask
from splatt3r_slam.splatt3r_utils import prepare_gaussians_local
from utils.geometry import build_covariance
from e4_budget import pack_parameters
from a0_metrics import depth_state,common_covered_metrics,mean_rows,factorial
from evaluate_e4 import CudaMap


@torch.no_grad()
def main():
    assert torch.cuda.is_available();torch.set_num_threads(2);torch.backends.cuda.matmul.allow_tf32=False
    spec,out,run,frames,mapping,lookup,poses=load_context();dest=out/'support_control';dest.mkdir(exist_ok=False)
    amendment=ROOT/'configs/a0b_amendment_A2.json'
    save_json(dest/'registration.json',dict(spec=digest(SPEC),amendment=digest(amendment),
        conditional_secondary_only=True,phase='before support-control arm construction'))
    src=[Path(__file__),amendment,ROOT/'src/a0b_geometry.py',ROOT/'src/pointmap_contract.py']
    for p in src:
        q=dest/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(dest/'source_manifest.json',[digest(p) for p in src])
    pre=out/'preflight';alignment=json.loads((pre/'alignment.json').read_text());G=np.array(alignment['gauge']);C=alignment['C']
    nf=json.loads((ROOT/spec['native_filter_contract']).read_text())['native_filter']
    model=camera_model(load_calibrations(ROOT/spec['calibration_file']),'HKairport_released');A,hw,_,_=resize_contract();K=A@model['K']
    dump=torch.load(run/'map/HKairport01_kfgauss.pt',map_location='cpu',weights_only=True)
    names=['A00','A10','A01','A11'];blocks=[];count=0;proxy={a:[] for a in names};candidate_rows=[]
    for arm in names:(dest/(arm+'.f32')).touch(exist_ok=False)
    yy,xx=np.indices(hw);uv=np.column_stack([xx.ravel(),yy.ravel()])
    for k in dump['keyframes']:
        grid=mapping[k['frame_id']]['grid_index']
        if grid<100:continue
        native=native_mask(k,nf);ref=np.load(pre/'references'/f'HKairport_released_source_{grid:03d}.npz');take=ref['valid'].ravel()[native]
        local={key:k[key] for key in ['means','scales','rotations','sh','opacities','conf']}
        p=prepare_gaussians_local(local,k['img'],*hw,**nf)
        raw=p[0].numpy()[take];cov=build_covariance(p[1],p[2]).numpy()[take];rgb=p[3].numpy()[take];opacity=p[4].numpy()[take]
        pix=uv[native][take];z=ref['depth'].ravel()[native][take];oracle=source_rays(pix,model)*z[:,None]
        lineage=next(r for r in alignment['lineage'] if r['kf_idx']==k['kf_idx'])
        ids=np.array([f"{lineage['event']}:self:{i}" for i in np.flatnonzero(native)[take]])
        arms=build_arms(raw,oracle,sim3_from_xyzw(k['T_WC'].numpy()),poses[grid],G,C,cov,ids,np.ones(len(ids),bool),dict(rgb=rgb,opacity=opacity))
        for arm,a in arms.items():
            packed=pack_parameters(a['world_points_m'],a['world_covariance_m2'],rgb,opacity)
            with (dest/(arm+'.f32')).open('ab') as f:packed.tofile(f)
            proxy[arm].append(a['world_points_m'][::max(1,len(raw)//1500)])
        blocks.append(dict(kf_idx=k['kf_idx'],grid_index=grid,count=len(raw),candidate_id_hash=array_hash(ids),rgb_hash=array_hash(rgb),opacity_hash=array_hash(opacity)))
        candidate_rows.append(dict(kf_idx=k['kf_idx'],grid_index=grid,depth_abs_error_m=stats(np.abs(raw[:,2]*C-z)),
            predicted_over_lidar_depth_ratio=stats(raw[:,2]*C/z),candidates=len(raw)))
        count+=len(raw)
    assert count>1000
    for arm in names:
        assert (dest/(arm+'.f32')).stat().st_size==count*52
        np.save(dest/(arm+'_center_proxy.npy'),np.concatenate(proxy[arm]))
    save_json(dest/'map_manifest.json',dict(count=count,blocks=blocks,source_local=candidate_rows,maps={a:digest(dest/(a+'.f32')) for a in names}))
    grids=json.loads((pre/'manifest.json').read_text())['evaluation_grid_ids'];es=spec['evaluation'];metricfiles=[]
    for arm in names:
        folder=dest/arm;folder.mkdir();packed=np.memmap(dest/(arm+'.f32'),dtype=np.float32,mode='r',shape=(count,13))
        gc.collect();torch.cuda.empty_cache();g=CudaMap(packed);del packed
        d=np.lib.format.open_memmap(folder/'depth.npy',mode='w+',dtype=np.float32,shape=(len(grids),*hw));c=np.lib.format.open_memmap(folder/'covered.npy',mode='w+',dtype=bool,shape=(len(grids),*hw))
        rows=[]
        for j,grid in enumerate(grids):
            ref=np.load(pre/'references'/f'HKairport_released_target_{grid:03d}.npz');raw=g.depth(poses[grid],K,hw)
            pred,cov,correct,s=depth_state(raw[:,:,0],raw[:,:,1],ref['depth'],ref['valid'],es['coverage_weight_min'],es['correct_depth_absolute_m'],es['correct_depth_relative'])
            d[j]=pred;c[j]=cov;rows.append(dict(grid_index=grid,**s))
            if grid in spec['diagnostic_view_ids']:
                rgb=g.render(poses[grid],K,hw).clamp(0,1).permute(1,2,0).cpu().numpy()
                np.savez_compressed(folder/f'grid{grid:03d}.npz',depth=pred,covered=cov,gt=ref['depth'],valid=ref['valid'],rgb=rgb)
        d.flush();c.flush();del d,c,g;gc.collect();torch.cuda.empty_cache()
        save_json(folder/'metrics.json',dict(arm=arm,frames=rows,frame_ids=grids,summary=mean_rows(rows,['mae_m','absrel','coverage','correct_coverage']),
            depth_cache=digest(folder/'depth.npy'),covered_cache=digest(folder/'covered.npy')))
        metricfiles.append(digest(folder/'metrics.json'));print('Support control',arm,flush=True)
    ds={a:np.load(dest/a/'depth.npy',mmap_mode='r') for a in names};cs={a:np.load(dest/a/'covered.npy',mmap_mode='r') for a in names}
    common_rows=[]
    for j,grid in enumerate(grids):
        ref=np.load(pre/'references'/f'HKairport_released_target_{grid:03d}.npz')
        mask,m=common_covered_metrics({a:ds[a][j] for a in names},{a:cs[a][j] for a in names},ref['depth'],ref['valid'])
        common_rows.append(dict(grid_index=grid,common_pixels=int(mask.sum()),reference_pixels=int(ref['valid'].sum()),errors={a:m[a]['mae_m'] for a in names}))
    errors={a:float(np.mean([r['errors'][a] for r in common_rows if r['errors'][a] is not None])) for a in names}
    table=[dict(arm=a,candidates=count,common_MAE_m=errors[a],**json.loads((dest/a/'metrics.json').read_text())['summary']) for a in names]
    save_json(dest/'results.json',dict(table=table,effects=factorial(errors),per_frame=common_rows,common_pixels=stats([r['common_pixels'] for r in common_rows]),
        common_fraction_of_reference=float(np.mean([r['common_pixels']/r['reference_pixels'] for r in common_rows])),
        decision='CONDITIONAL SECONDARY SUPPORT CONTROL; primary A1 and calibration gate unchanged',metrics=metricfiles))
    print(json.dumps(dict(table=table,effects=factorial(errors)),indent=2),flush=True)


if __name__=='__main__':main()
