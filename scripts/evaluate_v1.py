#!/usr/bin/env python3
"""V1 unit rendering, heldout CUDA depth/RGB, and fixed-view surface controls."""
from pathlib import Path
import gc
import json
import sys
import time
import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
sys.path.append(str(ROOT/'results/E4_matched_budget/deps'))
from v1_common import checked, views, definitions, ARMS, CZ
from prepare_e2b_run import digest,save_json
from evaluate_e4 import CudaMap,integrate
from e4_budget import pack_parameters,sample_mesh,surface_metrics,image_metrics
from a0_metrics import depth_state,mean_rows
from run_a1_unit_invariance import render_difference


def new_volume():
    import open3d as o
    return o.pipelines.integration.ScalableTSDFVolume(.04,.12,o.pipelines.integration.TSDFVolumeColorType.NoColor)


def finish_volume(volume,folder):
    import open3d as o
    mesh = volume.extract_triangle_mesh()
    assert len(mesh.triangles)>0
    assert o.io.write_triangle_mesh(str(folder/'depth_tsdf.ply'),mesh)
    pts = sample_mesh(np.asarray(mesh.vertices),np.asarray(mesh.triangles),100000,0)
    np.save(folder/'surface_samples.npy',pts)
    return pts


def cuda_map(row):
    assert digest(ROOT/row['file']['path'])==row['file']
    return CudaMap(np.array(np.memmap(ROOT/row['file']['path'],dtype=np.float32,mode='r',shape=(row['count'],13)),copy=True))


def raw_render(g,a):
    raw = g.depth(a['pose'],a['K'],a['hw'])
    return dict(rgb=g.render(a['pose'],a['K'],a['hw']).permute(1,2,0).cpu().numpy(),numerator=raw[:,:,0],weight=raw[:,:,1])


def unit_render(spec,out,cameras):
    uc = json.loads((out/'maps/unit_contract.json').read_text())
    assert uc['status']=='PASS'
    folder = out/'unit_render'
    if (folder/'completion.json').exists():
        done = json.loads((folder/'completion.json').read_text())
        assert done['status']=='PASS' and done['positive_failures']==0
        print('Preserved completed unit render checks.',flush=True)
        return
    folder.mkdir(exist_ok=False)
    tolerance = json.loads((ROOT/spec['unit_spec']).read_text())['thresholds']['render']
    original = uc['maps'][0]
    g = cuda_map(original)
    saved = {f:raw_render(g,cameras[f]) for f in spec['saved_views']}
    first = spec['saved_views'][0]
    repeat = render_difference(raw_render(g,cameras[first]),saved[first],tolerance)
    assert repeat['status']=='PASS'
    for f,a in saved.items(): np.savez_compressed(folder/f'original_{f:04d}.npz',**a)
    del g
    gc.collect()
    torch.cuda.empty_cache()
    rows = []
    for m in uc['maps'][1:]:
        g = cuda_map(m)
        ids = [201,601] if m['negative'] else spec['saved_views']
        for f in ids:
            a = raw_render(g,cameras[f])
            result = render_difference(a,saved[f],tolerance)
            rows.append(dict(variant=m['id'],frame=f,negative=m['negative'],**result))
            if not m['negative']: assert result['status']=='PASS', rows[-1]
            if m['negative']: np.savez_compressed(folder/f"{m['id']}_{f:04d}.npz",**a)
        if m['negative']: assert any(r['status']=='FAIL' for r in rows if r['variant']==m['id'])
        del g
        gc.collect()
        torch.cuda.empty_cache()
        print('V1 unit render',m['id'],'complete',flush=True)
    save_json(folder/'completion.json',dict(status='PASS',baseline_determinism=repeat,rows=rows,
        positive_cases=sum(not r['negative'] for r in rows),negative_cases=sum(r['negative'] for r in rows),
        positive_failures=sum(not r['negative'] and r['status']!='PASS' for r in rows)))


@torch.no_grad()
def main():
    spec,out = checked()
    assert torch.cuda.is_available()
    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    torch.backends.cuda.matmul.allow_tf32=False
    maps = json.loads((out/'maps/manifest.json').read_text())
    assert maps['status']=='PASS'
    ap = out/'implementation_amendment_A1.json'
    if ap.exists():
        for row in json.loads(ap.read_text())['preserved_outputs']:
            assert digest(ROOT/row['path'])==row, row['path']
    for row in maps['inputs']: assert digest(ROOT/row['path'])==row
    cameras = views()
    unit_render(spec,out,cameras)
    folder = out/'evaluation'
    folder.mkdir(exist_ok=True)
    if (folder/'completion.json').exists(): raise RuntimeError('Completed V1 evaluation preserved')
    if not (folder/'environment.json').exists():
        save_json(folder/'environment.json',dict(torch=torch.__version__,CUDA=torch.version.cuda,GPU=torch.cuda.get_device_name(0),
            TF32=False,renderer='existing E4 compact CUDA expected camera Z',SH_degree=0,refiner=0))
    K = np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
    smoke = CudaMap(pack_parameters(np.array([[0.,0,70.],[0,0,90.]]),np.repeat((np.eye(3)*.5)[None],2,axis=0),np.array([[1.,0,0],[0,0,1.]]),np.array([.5,.5])))
    d = smoke.depth(np.eye(4),K,(64,64))
    z = float(d[32,32,0]/d[32,32,1])
    assert 70<z<90
    if not (folder/'smoke.json').exists(): save_json(folder/'smoke.json',dict(status='PASS',synthetic_Z_m=z))
    del smoke
    ref_folder = folder/'reference'
    if (ref_folder/'surface_samples.npy').exists():
        reference = np.load(ref_folder/'surface_samples.npy')
    else:
        ref_folder.mkdir()
        volume = new_volume()
        for f in spec['covariance_views']:
            a = cameras[f]
            integrate(volume,np.where(a['valid'],a['gt'],0),a['pose'],a['K'])
        reference = finish_volume(volume,ref_folder)
        del volume
    defs = definitions()
    records = []
    started = time.monotonic()
    # Run primary C/CZ first; source-only and covariance follow as separate groups.
    for m in maps['maps']:
        case,arm = m['case'],m['arm']
        definition = defs[case]
        vf = folder/case/arm
        if (vf/'metrics.json').exists():
            metric = json.loads((vf/'metrics.json').read_text())
            assert metric['map']==m
            for key in ['depth_cache','coverage_cache']:
                assert digest(ROOT/metric[key]['path'])==metric[key]
            records.append(digest(vf/'metrics.json'))
            print('Preserved completed',case,arm,flush=True)
            continue
        vf.mkdir(parents=True,exist_ok=False)
        ids = spec['covariance_views'] if definition['kind']=='fixed_world' else list(cameras)
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        g = cuda_map(m)
        hw = cameras[ids[0]]['hw']
        depth = np.lib.format.open_memmap(vf/'depth.npy',mode='w+',dtype=np.float32,shape=(len(ids),*hw))
        cover = np.lib.format.open_memmap(vf/'covered.npy',mode='w+',dtype=bool,shape=(len(ids),*hw))
        volume = new_volume() if case=='position_strict' else None
        rows = []
        start = time.monotonic()
        for j,f in enumerate(ids):
            a = cameras[f]
            raw = g.depth(a['pose'],a['K'],hw)
            pred,cov,correct,s = depth_state(raw[:,:,0],raw[:,:,1],a['gt'],a['valid'],.001,.05,.02)
            depth[j],cover[j] = pred,cov
            row = dict(frame=f,**s,depth_bins={},psnr_db=None,ssim=None)
            err = np.abs(pred-a['gt'])
            for lo,hi in zip([.1,1,2,4],[1,2,4,10]):
                mask = a['valid']&(a['gt']>=lo)&(a['gt']<hi)
                good = mask&cov
                row['depth_bins'][f'{lo}-{hi}'] = dict(reference_pixels=int(mask.sum()),covered_pixels=int(good.sum()),
                    mae_m=float(err[good].mean()) if good.any() else None,
                    correct_coverage=float(correct[mask].mean()) if mask.any() else None)
            if case=='position_strict' or f in spec['saved_views']:
                rgb = g.render(a['pose'],a['K'],hw).clamp(0,1).permute(1,2,0).cpu().numpy()
                row.update(image_metrics(rgb,a['target']))
                if f in spec['saved_views']:
                    np.savez_compressed(vf/f'frame{f:04d}.npz',depth=pred,covered=cov,weight=raw[:,:,1],rgb=rgb,gt=a['gt'],valid=a['valid'],target=a['target'])
            if volume is not None and f in spec['covariance_views']:
                integrate(volume,np.where(a['valid']&cov,pred,0),a['pose'],a['K'])
            rows.append(row)
            if j%100==0: print('V1 render',case,arm,j+1,'/',len(ids),flush=True)
        depth.flush()
        cover.flush()
        del depth,cover
        surface = surface_metrics(finish_volume(volume,vf),reference,.05) if volume is not None else None
        metric = dict(case=case,arm=arm,map=m,frame_ids=ids,frames=rows,
            summary=mean_rows(rows,['mae_m','absrel','coverage','correct_coverage','psnr_db','ssim']),surface=surface,
            depth_cache=digest(vf/'depth.npy'),coverage_cache=digest(vf/'covered.npy'),wall_seconds=time.monotonic()-start,
            GPU_peak_allocated_bytes=torch.cuda.max_memory_allocated(),RGB_views=sum(r['psnr_db'] is not None for r in rows))
        save_json(vf/'metrics.json',metric)
        records.append(digest(vf/'metrics.json'))
        print('V1 completed',case,arm,flush=True)
        del g,volume
        gc.collect()
        torch.cuda.empty_cache()
    # Byte-identical baseline geometries must also reproduce all 400 cached depths.
    for a,b in [('position_strict/C00','original_strict/A00')]:
        for name in ['depth.npy','covered.npy']:
            assert digest(folder/a/name)['sha256']==digest(folder/b/name)['sha256']
    partial = out/'failed_attempt1/original_strict/A00'
    if partial.exists():
        for name in ['depth.npy','covered.npy']:
            assert digest(partial/name)['sha256']==digest(folder/'original_strict/A00'/name)['sha256']
    save_json(folder/'completion.json',dict(status='COMPLETE',metrics=records,
        new_depth_views=sum(len(json.loads((ROOT/r['path']).read_text())['frame_ids']) for r in records),
        wall_seconds=time.monotonic()-started,baseline_C00_A00_cache_bitwise_equal=True,
        resumed_after_implementation_amendment=ap.exists(),failed_attempt_rerender_bitwise_equal=partial.exists(),
        total_unique_map_render_seconds=sum(json.loads((ROOT/r['path']).read_text())['wall_seconds'] for r in records)))
    print('V1 evaluation COMPLETE',flush=True)


if __name__=='__main__': main()
