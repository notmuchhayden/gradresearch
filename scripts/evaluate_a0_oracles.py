#!/usr/bin/env python3
"""CUDA render all registered A0 variants; retain depths for shared-mask errors."""
from datetime import datetime
import gc
import json
from pathlib import Path
import shutil
import sys
import time
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
sys.path.append(str(ROOT/"results/E4_matched_budget/deps"))
from prepare_e2b_run import digest,save_json
from evaluate_e4 import CudaMap,reference_rgb,integrate
from e4_budget import sample_mesh,surface_metrics,image_metrics
from e1_taxonomy import camera_geometry,depth_masks,resize_depth
from a0_metrics import depth_state,mean_rows


def new_volume(spec):
    import open3d as o
    g=spec["evaluation"]["surface"]
    return o.pipelines.integration.ScalableTSDFVolume(g["voxel_m"],g["trunc_m"],o.pipelines.integration.TSDFVolumeColorType.NoColor)


def finish_volume(volume,path,spec):
    import open3d as o
    mesh=volume.extract_triangle_mesh()
    if not len(mesh.triangles):return np.empty((0,3))
    assert o.io.write_triangle_mesh(str(path),mesh)
    g=spec["evaluation"]["surface"]
    return sample_mesh(np.asarray(mesh.vertices),np.asarray(mesh.triangles),g["surface_samples"],g["sample_seed"])


@torch.no_grad()
def smoke(dest,spec):
    K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1.]])
    from e4_budget import pack_parameters
    from render_e1 import render_values
    mu=np.array([[0.,0,1.],[0.,0,2.]],np.float32);cov=np.repeat((np.eye(3)*.0001)[None],2,axis=0).astype(np.float32)
    rgb=np.array([[1.,0,0],[0,0,1]],np.float32);opacity=np.full(2,.5,np.float32)
    packed=pack_parameters(mu,cov,rgb,opacity);g=CudaMap(packed)
    expected=render_values({"means":torch.from_numpy(mu).cuda(),"covariances":torch.from_numpy(cov).cuda(),
                           "opacity":torch.from_numpy(opacity).cuda()},np.eye(4),K,(64,64),torch.from_numpy(rgb).cuda())
    torch.testing.assert_close(g.render(np.eye(4),K,(64,64)),expected,atol=1e-6,rtol=1e-6)
    depth=g.depth(np.eye(4),K,(64,64));assert 1<depth[32,32,0]/depth[32,32,1]<2
    v=new_volume(spec);integrate(v,np.full((64,64),2.,np.float32),np.eye(4),K)
    pts=finish_volume(v,dest/"synthetic_plane_tsdf.ply",spec)
    assert len(pts)==spec["evaluation"]["surface"]["surface_samples"] and np.max(np.abs(pts[:,2]-2))<.02
    save_json(dest/"smoke.json",{"status":"PASS","compact_CUDA_vs_existing_renderer":"PASS","known_depth_compositing":"PASS","TSDF_plane":"PASS"})
    del g,v;gc.collect();torch.cuda.empty_cache()


def main():
    if not torch.cuda.is_available():raise RuntimeError("A0 requires CUDA")
    torch.set_num_threads(2);cv2.setNumThreads(2);torch.backends.cuda.matmul.allow_tf32=False
    cfg=ROOT/"configs/a0_office2_factorial.json";spec=json.loads(cfg.read_text());out=ROOT/spec["output"];dest=out/"evaluation"
    manifest=json.loads((out/"oracles/manifest.json").read_text());assert manifest["registered_spec"]==digest(cfg)
    for row in manifest["inputs"]:assert digest(ROOT/row["path"])==row,row["path"]
    source=[cfg,Path(__file__),ROOT/"src/a0_metrics.py",ROOT/"scripts/evaluate_e4.py",ROOT/"src/e4_budget.py",
            ROOT/"src/e1_taxonomy.py",ROOT/"tests/test_a0_metrics.py"]
    if dest.exists():
        frozen=json.loads((dest/"source_manifest.json").read_text())
        assert frozen==[digest(p) for p in source],"Evaluation code changed; use explicit amendment/output"
    else:
        dest.mkdir()
        for p in source:
            q=dest/"source"/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        save_json(dest/"source_manifest.json",[digest(p) for p in source])
    smoke(dest,spec)
    dataset=ROOT/spec["dataset"];camera=json.loads((dataset.parent/"cam_params.json").read_text())["camera"]
    poses=np.loadtxt(dataset/"traj.txt").reshape(-1,4,4);K,_,crop=camera_geometry(camera);hw=tuple(crop[2:])
    frames=list(range(201,1000,2));fusion=spec["evaluation"]["surface_fusion_original_frame_ids"]
    n1=json.loads((ROOT/spec["n1_contract"]).read_text());mask_spec=n1["common_mask"]
    input_lookup={r["path"]:r for r in json.loads((ROOT/spec["n2_manifest"]).read_text())["files"]}
    first=dataset/"results/frame000000.jpg";first_mean=(cv2.cvtColor(cv2.imread(str(first)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.).reshape(-1,3).mean(0)
    views={};targets={};input_rows=[]
    print("Loading fixed 400 heldout views",flush=True)
    for frame in frames:
        dp=dataset/"results"/f"depth{frame:06d}.png";rp=dataset/"results"/f"frame{frame:06d}.jpg"
        for p in (dp,rp):
            row=digest(p);assert row["sha256"]==input_lookup[row["path"]]["sha256"];input_rows.append(row)
        d=resize_depth(cv2.imread(str(dp),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera["scale"],camera)
        valid,edge=depth_masks(d,mask_spec)
        views[frame]={"gt":d,"valid":valid,"edge":edge,"pose":poses[frame]}
        targets[frame]=(reference_rgb(rp,first_mean)*255).round().astype(np.uint8)
    save_json(dest/"input_manifest.json",input_rows+[digest(first),digest(dataset/"traj.txt")])
    reference=dest/"reference_surface_samples.npy"
    if not reference.exists():
        v=new_volume(spec)
        for frame in fusion:
            a=views[frame];integrate(v,np.where(a["valid"]&~a["edge"],a["gt"],0),a["pose"],K)
        points=finish_volume(v,dest/"reference_gt_depth_tsdf.ply",spec);assert len(points)==100000
        np.save(reference,points);del v
    rp=np.load(reference)
    import open3d
    save_json(dest/"environment.json",{"torch":torch.__version__,"cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0),
        "open3d":open3d.__version__,"tf32":False,"SH_degree":0,"refinement":0,"renderer":"existing E4 compact CUDA",
        "surface_reference":"20-view GT-depth TSDF observed region; not full scene mesh completion"})
    # All map geometries and source masks already exist before any outcome.
    for variant in manifest["variants"]:
        folder=dest/variant["id"]
        if (folder/"metrics.json").exists():
            previous=json.loads((folder/"metrics.json").read_text());assert previous["map_hash"]==variant["map_hash"]
            print("Preserved completed",variant["id"],flush=True);continue
        folder.mkdir(exist_ok=True)
        assert digest(ROOT/variant["map_file"])==variant["map_hash"]
        full=variant["C_multiplier"]==1.;view_ids=frames if full else fusion
        packed=np.memmap(ROOT/variant["map_file"],dtype=np.float32,mode="r",shape=(variant["count"],13))
        gc.collect();torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
        g=CudaMap(packed);del packed
        depth_cache=np.lib.format.open_memmap(folder/"depth.npy",mode="w+",dtype=np.float32,shape=(len(view_ids),*hw))
        cover_cache=np.lib.format.open_memmap(folder/"covered.npy",mode="w+",dtype=bool,shape=(len(view_ids),*hw))
        volume=new_volume(spec) if full else None
        rows=[];started=time.monotonic()
        for j,frame in enumerate(view_ids):
            a=views[frame];raw=g.depth(a["pose"],K,hw)
            pred,covered,correct,stat=depth_state(raw[:,:,0],raw[:,:,1],a["gt"],a["valid"],
                spec["evaluation"]["coverage_weight_min"],spec["evaluation"]["correct_depth_abs_tolerance_m"],spec["evaluation"]["correct_depth_relative_tolerance"])
            depth_cache[j]=pred;cover_cache[j]=covered
            _,_,_,interior=depth_state(raw[:,:,0],raw[:,:,1],a["gt"],a["valid"]&~a["edge"])
            row={"frame":frame,**stat,**{"interior_"+k:v for k,v in interior.items()}}
            row["boundary_correct_coverage"]=float(correct[a["valid"]&a["edge"]].mean()) if (a["valid"]&a["edge"]).any() else None
            row["depth_bins"]={}
            for lo,hi in zip(spec["evaluation"]["depth_bins_m"][:-1],spec["evaluation"]["depth_bins_m"][1:]):
                m=a["valid"]&~a["edge"]&(a["gt"]>=lo)&(a["gt"]<hi)
                good=m&covered
                row["depth_bins"][f"{lo}-{hi}"]={"gt_pixels":int(m.sum()),"mae_m":float(np.abs(pred[good]-a["gt"][good]).mean()) if good.any() else None,
                    "correct_coverage":float(correct[m].mean()) if m.any() else None}
            if full:
                rgb_tensor=g.render(a["pose"],K,hw).clamp(0,1)
                image=rgb_tensor.permute(1,2,0).cpu().numpy();row.update(image_metrics(image,targets[frame].astype(np.float32)/255.))
                if frame in fusion:integrate(volume,np.where(a["valid"]&~a["edge"]&covered,pred,0),a["pose"],K)
                if frame in spec["evaluation"]["saved_frames"]:
                    np.savez_compressed(folder/f"frame{frame:04d}.npz",depth=pred,gt=a["gt"],covered=covered,weight=raw[:,:,1],rgb=image,target=targets[frame],valid=a["valid"],edge=a["edge"])
            rows.append(row)
            if j%50==0:
                print(f"{variant['id']}: {j+1}/{len(view_ids)} views",flush=True)
                save_json(folder/"progress.json",{"completed_views":j+1,"total_views":len(view_ids)})
        depth_cache.flush();cover_cache.flush();del depth_cache,cover_cache
        surface=None
        if full:
            pts=finish_volume(volume,folder/"rendered_depth_tsdf.ply",spec);np.save(folder/"surface_samples.npy",pts)
            surface=surface_metrics(pts,rp,spec["evaluation"]["surface"]["distance_threshold_m"])
        keys=["mae_m","absrel","coverage","correct_coverage","interior_mae_m","interior_absrel","interior_coverage","interior_correct_coverage","boundary_correct_coverage"]
        if full:keys += ["psnr_db","ssim"]
        row={"variant":variant,"map_hash":variant["map_hash"],"frames":rows,"frame_ids":view_ids,
             "summary":mean_rows(rows,keys),"surface":surface,"count":variant["count"],"parameter_bytes":variant["count"]*52,
             "GPU_metric_peak_allocated_bytes":torch.cuda.max_memory_allocated(),"wall_seconds":time.monotonic()-started,
             "LPIPS":None,"LPIPS_note":"optional secondary image metric not evaluated",
             "GT_depth_TSDF_reference":digest(dest/"reference_gt_depth_tsdf.ply")}
        save_json(folder/"metrics.json",row)
        print(variant["id"],json.dumps(row["summary"]),flush=True)
        del g,volume;gc.collect();torch.cuda.empty_cache()
    save_json(dest/"completion.json",{"status":"COMPLETE","variant_count":len(manifest["variants"]),
        "metric_files":[digest(dest/v["id"]/"metrics.json") for v in manifest["variants"]],"finished_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat()})


if __name__=="__main__":main()
