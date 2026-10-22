"""CUDA compact-map RGB/depth, isolated memory, and observed-region TSDF evaluation."""
import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import cv2
import numpy as np
from PIL import Image
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from run_e4 import setup,checked_seal,load_scene
from run_e3 import bake,depth_metrics
from prepare_e2b_run import digest,save_json
from e1_taxonomy import camera_geometry,resize_depth,depth_masks
from e0b_audit import sim3_matrix
from e3b_provisional import metrics,KEEP,REJECT,EXCLUDED
from e4_budget import pack_parameters,image_metrics,sample_mesh,surface_metrics


def open3d_module():
    import open3d
    return open3d


def volume(spec):
    o=open3d_module();g=spec['geometry']
    return o.pipelines.integration.ScalableTSDFVolume(g['voxel_m'],g['trunc_m'],o.pipelines.integration.TSDFVolumeColorType.NoColor)


def integrate(v,depth,pose,K):
    o=open3d_module();h,w=depth.shape
    rgbd=o.geometry.RGBDImage.create_from_color_and_depth(o.geometry.Image(np.zeros((h,w,3),np.uint8)),
        o.geometry.Image(np.ascontiguousarray(depth,np.float32)),depth_scale=1.,depth_trunc=10.,convert_rgb_to_intensity=False)
    intrinsic=o.camera.PinholeCameraIntrinsic(w,h,K[0,0],K[1,1],K[0,2],K[1,2])
    v.integrate(rgbd,intrinsic,np.linalg.inv(pose))


def finish_surface(v,path,spec):
    o=open3d_module();mesh=v.extract_triangle_mesh()
    path.parent.mkdir(parents=True,exist_ok=True);assert o.io.write_triangle_mesh(str(path),mesh)
    return sample_mesh(np.asarray(mesh.vertices),np.asarray(mesh.triangles),spec['geometry']['surface_samples'],spec['geometry']['sample_seed'])


def reference_rgb(path,first_mean):
    raw=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
    gain=np.clip((first_mean+.001)/(raw.reshape(-1,3).mean(0)+.001),.4,2.5)
    im=Image.fromarray(np.uint8(np.clip(raw*gain,0,1)*255));w,h=im.size
    nw,nh=round(w*512/max(w,h)),round(h*512/max(w,h))
    im=im.resize((nw,nh),Image.Resampling.LANCZOS if max(w,h)>512 else Image.Resampling.BICUBIC)
    hw,hh=(nw//16)*8,(nh//16)*8
    if nw==nh:hh=3*hw//4
    return np.asarray(im.crop((nw//2-hw,nh//2-hh,nw//2+hw,nh//2+hh))).astype(np.float32)/255.


class CudaMap:
    def __init__(self,packed):
        self.p=torch.from_numpy(np.ascontiguousarray(packed)).cuda()
        self.means=self.p[:,:3].contiguous();self.cov=self.p[:,3:9].contiguous()
        self.rgb=self.p[:,9:12].contiguous();self.opacity=self.p[:,12:13].contiguous()
        del self.p

    @torch.no_grad()
    def render(self,pose,K,hw,values=None):
        from diff_gaussian_rasterization import GaussianRasterizationSettings,GaussianRasterizer
        h,w=hw;ext=torch.as_tensor(pose,dtype=torch.float32,device='cuda').clone();ext[:3,3]*=10
        view=torch.linalg.inv(ext).T.contiguous();near,far=1.,10000.
        proj=torch.zeros((4,4),dtype=torch.float32,device='cuda')
        proj[0,0],proj[1,1]=2*K[0,0]/w,2*K[1,1]/h
        proj[0,2],proj[1,2]=(2*K[0,2]+1)/w-1,(2*K[1,2]+1)/h-1
        proj[2,2],proj[2,3]=far/(far-near),-far*near/(far-near);proj[3,2]=1
        settings=GaussianRasterizationSettings(image_height=h,image_width=w,tanfovx=w/(2*K[0,0]),tanfovy=h/(2*K[1,1]),
            bg=torch.zeros(3,device='cuda'),scale_modifier=1.,viewmatrix=view,projmatrix=view@proj.T,sh_degree=0,
            campos=ext[:3,3],prefiltered=False,debug=False)
        out,_=GaussianRasterizer(settings)(means3D=self.means*10,means2D=torch.zeros_like(self.means),shs=None,
            colors_precomp=self.rgb if values is None else values.contiguous(),opacities=self.opacity,cov3D_precomp=self.cov*100)
        return out.reshape(3,h,w)

    @torch.no_grad()
    def depth(self,pose,K,hw,bad=None):
        center=torch.as_tensor(pose[:3,3],dtype=torch.float32,device='cuda');axis=torch.as_tensor(pose[:3,2],dtype=torch.float32,device='cuda')
        z=(self.means-center)@axis
        v=torch.stack([z,torch.ones_like(z),torch.zeros_like(z) if bad is None else bad],1)
        return self.render(pose,K,hw,v).permute(1,2,0).cpu().numpy()


@torch.no_grad()
def smoke():
    from render_e1 import smoke as raster_smoke,render_values
    raster_smoke()
    spec,_=setup();K=np.array([[50.,0,31.5],[0,50,31.5],[0,0,1.]])
    mu=np.array([[0,0,1.],[0,0,2.]],np.float32);cov=np.tile(np.eye(3,dtype=np.float32)*.0001,(2,1,1))
    rgb=np.array([[1.,0,0],[0,0,1]],np.float32);opacity=np.full(2,.5,np.float32)
    g=CudaMap(pack_parameters(mu,cov,rgb,opacity));a=g.render(np.eye(4),K,(64,64)).cpu().numpy()
    b=render_values(dict(means=torch.from_numpy(mu).cuda(),covariances=torch.from_numpy(cov).cuda(),opacity=torch.from_numpy(opacity).cuda()),np.eye(4),K,(64,64),torch.from_numpy(rgb).cuda()).cpu().numpy()
    np.testing.assert_allclose(a,b,atol=1e-6,rtol=1e-6)
    v=volume(spec);integrate(v,np.ones((64,64),np.float32)*2,np.eye(4),K)
    mesh=v.extract_triangle_mesh();assert len(mesh.vertices)>0
    assert np.max(np.abs(np.asarray(mesh.vertices)[:,2]-2))<.02
    print('E4 compact CUDA parity and TSDF planar-depth smoke PASS',flush=True)


@torch.no_grad()
def evaluate(scene):
    spec,out=setup();seal=checked_seal(spec,out)
    if not torch.cuda.is_available():raise RuntimeError('E4 rendering requires CUDA')
    torch.backends.cuda.matmul.allow_tf32=False;cv2.setNumThreads(2)
    dest=out/'evaluation'/scene;dest.mkdir(parents=True,exist_ok=True)
    if (dest/'metrics.json').exists():raise RuntimeError('Completed evaluation preserved')
    replay=out/'replay'/scene;manifest=json.loads((replay/'manifest.json').read_text())
    for e in manifest['artifacts']:assert digest(ROOT/e['path'])==e
    score,broad,run,meta,f,local=load_scene(spec,scene);n,nk=meta['raw_per_kf'],meta['keyframes']
    labelroot=out/'evaluation'/scene if scene==spec['fresh_scene'] else ROOT/spec['prior']/'evaluation'/scene
    lp=labelroot/'labels.npz';labels=dict(np.load(lp));lm=json.loads((labelroot/'label_manifest.json').read_text())
    alignment=np.asarray(lm['alignment']);dataset=ROOT/spec['datasets'][scene]
    camera=json.loads((dataset/'cam_params.json').read_text())['camera'];poses=np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    K=camera_geometry(camera)[0];lspec=json.loads((ROOT/spec['label_base_config']).read_text())
    dump=torch.load(run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)
    assert all(k['sh'].shape[-1]==1 for k in dump['keyframes']), 'E4 requires unchanged degree-zero appearance'
    final=[alignment@sim3_matrix(k['T_WC'].numpy()) for k in dump['keyframes']];del dump
    mu,cov,rgb,opacity=bake(local,final,np.ones((nk,n),bool));del local
    full=pack_parameters(mu,cov,rgb,opacity);del mu,cov,rgb,opacity
    inputs=[digest(lp),digest(labelroot/'label_manifest.json'),digest(dataset/'cam_params.json'),digest(dataset/scene/'traj.txt')]
    views={}
    for frame in sorted(set(spec['fusion_frames']+spec['rgb_frames'])):
        path=dataset/scene/'results'/f'depth{frame:06d}.png';raw=cv2.imread(str(path),cv2.IMREAD_UNCHANGED);assert raw is not None
        gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,lspec)
        views[frame]=dict(gt=gt,valid=valid,edge=edge,pose=poses[frame]);inputs.append(digest(path))
    first=dataset/scene/'results/frame000000.jpg';first_rgb=cv2.cvtColor(cv2.imread(str(first)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    first_mean=first_rgb.reshape(-1,3).mean(0);inputs.append(digest(first))
    targets={}
    for frame in spec['rgb_frames']:
        path=dataset/scene/'results'/f'frame{frame:06d}.jpg';targets[frame]=reference_rgb(path,first_mean);inputs.append(digest(path))
        assert targets[frame].shape[:2]==views[frame]['gt'].shape
    reference=dest/'reference_samples.npy'
    if not reference.exists():
        v=volume(spec)
        for frame in spec['fusion_frames']:
            view=views[frame];integrate(v,np.where(view['valid']&~view['edge'],view['gt'],0),view['pose'],K)
        rp=finish_surface(v,dest/'reference_tsdf.ply',spec);np.save(reference,rp);del v
    rp=np.load(reference);assert len(rp)==spec['geometry']['surface_samples']
    import lpips
    perceptual=lpips.LPIPS(net='alex').cuda().eval()
    environment=dict(gpu=torch.cuda.get_device_name(0),torch=torch.__version__,cuda=torch.version.cuda,numpy=np.__version__,
        open3d=open3d_module().__version__,python=sys.version,platform=platform.platform(),
        lpips_version=importlib.metadata.version('lpips'),sh_degree=0,parameter_bytes_per_gaussian=52,
        dependencies=[dict(name=d.metadata['Name'],version=d.version) for d in importlib.metadata.distributions(path=[str(out/'deps')])])
    save_json(dest/'environment.json',environment);save_json(ROOT/'configs/e4_environment.json',environment)
    index=json.loads((out/'selection'/scene/'index.json').read_text());results=[];cache={}
    canonical=dest/'maps';canonical.mkdir(exist_ok=True);rowdir=dest/'rows';rowdir.mkdir(exist_ok=True)
    for j,entry in enumerate(index):
        if not entry['reachable']:results.append(entry);continue
        rowpath=rowdir/(entry['id']+'.json')
        if rowpath.exists():
            previous=json.loads(rowpath.read_text());assert previous['seal']==digest(out/'seal.json');results.append(previous);cache[previous['membership_sha256']]=previous;continue
        start=time.monotonic();selection=out/'selection'/scene/(entry['id']+'.npz');s=np.load(selection)
        mask=np.unpackbits(s['mask'])[:int(s['size'])].astype(bool);assert mask.sum()==entry['count']
        key=hashlib.sha256(mask.tobytes()).hexdigest();row=dict(entry,seal=digest(out/'seal.json'),membership=digest(selection),membership_sha256=key)
        state=np.where(f['active'],KEEP,EXCLUDED).astype(np.uint8);state[f['active']&~mask]=REJECT
        d=dict(state=state,ever_finite=np.isfinite(np.load(replay/entry['method']/'decisions.npz')['score']))
        row['all_label_modes']={mode:metrics(d,y,f['active']) for mode,y in labels.items()};row['natural_classification']=row['all_label_modes']['creation']
        # Identical membership implies byte-identical maps and metrics; avoid duplicate work.
        if key in cache:
            previous=cache[key]
            for field in ['render','frames','tsdf','surface','memory','timing','map']:
                row[field]=previous[field]
            row['reused_identical_membership']=previous['id'];row['wall_seconds']=time.monotonic()-start
            save_json(rowpath,row);results.append(row);continue
        packed=np.ascontiguousarray(full[mask]);mapfile=canonical/(key+'.f32');packed.tofile(mapfile)
        assert mapfile.stat().st_size==entry['count']*52
        gc.collect();torch.cuda.empty_cache();torch.cuda.synchronize()
        memory_before=torch.cuda.memory_allocated();g=CudaMap(packed);del packed;torch.cuda.synchronize()
        map_bytes=torch.cuda.memory_allocated()-memory_before
        assert sum(t.numel()*t.element_size() for t in [g.means,g.cov,g.rgb,g.opacity])==entry['count']*52
        torch.cuda.reset_peak_memory_stats();v=volume(spec);frames=[]
        render_wall=0.;lpips_wall=0.;fusion_wall=0.
        bad=torch.from_numpy((labels['final_estimated'][mask]==3).astype(np.float32)).cuda()
        for frame in sorted(views):
            view=views[frame];pose=view['pose'];hw=view['gt'].shape
            tick=time.perf_counter();rendered=g.depth(pose,K,hw,bad);render_wall+=time.perf_counter()-tick
            stat,pred,weight=depth_metrics(rendered,view['gt'],view['valid'],view['edge'],lspec)
            if frame in spec['fusion_frames']:
                use=view['valid']&~view['edge']&(weight>spec['geometry']['coverage_weight_min'])&np.isfinite(pred)&(pred>0)
                tick=time.perf_counter();integrate(v,np.where(use,pred,0),pose,K);fusion_wall+=time.perf_counter()-tick
            if frame in targets:
                tick=time.perf_counter();rgb_tensor=g.render(pose,K,hw).clamp(0,1);pred_rgb=rgb_tensor.permute(1,2,0).cpu().numpy();render_wall+=time.perf_counter()-tick
                target=torch.from_numpy(targets[frame]).permute(2,0,1).unsqueeze(0).cuda()
                image=image_metrics(pred_rgb,targets[frame]);tick=time.perf_counter();image['lpips_alex']=float(perceptual(rgb_tensor[None],target,normalize=True).mean());lpips_wall+=time.perf_counter()-tick
                frames.append(dict(frame=frame,**stat,**image));del rgb_tensor,target
                if frame==501 and entry['arm']=='natural' and entry['method'] in ['B1','D_maskmedian','D_shared','P2_plane']:
                    np.savez_compressed(dest/(entry['id']+'_frame501.npz'),rgb=pred_rgb,target=targets[frame],depth=pred,gt=view['gt'],weight=weight)
        tick=time.perf_counter();surfacefile=canonical/(key+'_tsdf.ply');points=finish_surface(v,surfacefile,spec);del v;fusion_wall+=time.perf_counter()-tick
        row['surface']=surface_metrics(points,rp,spec['geometry']['distance_threshold_m']);row['tsdf']=digest(surfacefile)
        metric_peak=torch.cuda.max_memory_allocated();del bad;torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
        frame=501;view=views[frame];timings=[]
        for repeat in range(7):
            torch.cuda.synchronize();tick=time.perf_counter();tmp=g.render(view['pose'],K,view['gt'].shape);torch.cuda.synchronize()
            if repeat>=2:timings.append((time.perf_counter()-tick)*1000)
            del tmp
        row['timing']=dict(render_median_ms=float(np.median(timings)),render_p95_ms=float(np.percentile(timings,95)),samples_ms=timings)
        row['timing'].update(all_view_render_wall_s=render_wall,lpips_wall_s=lpips_wall,tsdf_cpu_wall_s=fusion_wall)
        row['memory']=dict(actual_n_resident=len(g.means),parameter_tensor_bytes=entry['count']*52,
            allocated_map_increment_bytes=map_bytes,render_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            render_peak_reserved_bytes=torch.cuda.max_memory_reserved(),baseline_allocated_bytes=memory_before,
            metric_pipeline_peak_allocated_bytes=metric_peak,physical_compaction=True)
        row['frames']=frames;row['render']={k:float(np.mean([a[k] for a in frames if a[k] is not None])) for k in frames[0] if k!='frame'}
        row['map']=digest(mapfile);row['wall_seconds']=time.monotonic()-start
        del g;torch.cuda.empty_cache();save_json(rowpath,row);cache[key]=row;results.append(row)
        print(f'{scene}: {j+1}/{len(index)} {entry["id"]} N={entry["count"]} PSNR={row["render"]["psnr_db"]:.3f} Chamfer={row["surface"]["chamfer_m"]}',flush=True)
    result=dict(scene=scene,fresh=scene==spec['fresh_scene'],seal=digest(out/'seal.json'),rows=results,
        reference=digest(reference),reference_mesh=digest(dest/'reference_tsdf.ply'),inputs=inputs,
        rendered_arms=sum(r['reachable'] for r in results),unreachable_arms=sum(not r['reachable'] for r in results),
        evaluation_only=True,off_axis_metrics=None,reference_scope='same-view GT-depth TSDF, observed region only')
    save_json(dest/'metrics.json',result);save_json(ROOT/f'configs/e4_{scene}_results_summary.json',result)
    save_json(dest/'manifest.json',dict(metrics=digest(dest/'metrics.json'),inputs=inputs,seal=digest(out/'seal.json'),
        replay=digest(replay/'manifest.json'),row_files=[digest(p) for p in sorted(rowdir.glob('*.json'))]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('scene',nargs='?',default='office0');p.add_argument('--smoke',action='store_true');a=p.parse_args()
    if a.smoke:smoke()
    else:evaluate(a.scene)
