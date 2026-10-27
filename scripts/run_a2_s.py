#!/usr/bin/env python3
"""A2-S frozen source cross-fit and heldout render workflow."""
import argparse, hashlib, json, os, shutil, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from a2_s_common import OUT,U,V,ROOT as R,kfs,base_map,packed,digest,dump_json,sha
from scalar_spatial_diagnostic import tile_masks,bilinear_basis,fit_scalar,fit_huber_scalar,fit_field,support_gate
from gauge_support import change_canonical_gauge
from pointmap_contract import transform_points

CFG=ROOT/'configs/a2_s_scalar_spatial_protocol.json'

def src_hashes():
    files=[CFG,ROOT/'docs/experiments/A2_S_execution_plan.md',ROOT/'src/scalar_spatial_diagnostic.py',ROOT/'scripts/a2_s_common.py',ROOT/'scripts/run_a2_s.py',ROOT/'tests/test_scalar_spatial_diagnostic.py',ROOT/'src/gauge_support.py',ROOT/'src/pointmap_contract.py',ROOT/'scripts/evaluate_e4.py',ROOT/'src/e4_budget.py',ROOT/'configs/n1_coordinate_contract.json',ROOT/'configs/n2_dataset_manifest.json']
    return [digest(p) for p in files]

def local_gauge(k,gauge):
    if gauge=='position':return k['y'],k['covariance_y'],k['Q']
    gd=json.loads((ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json').read_text()) if k['local_path'].is_relative_to(U) else json.loads((V/'maps/alignment.json').read_text())
    D=np.asarray(gd['relative'],float)
    return change_canonical_gauge(k['y'],k['covariance_y'],k['Q'],D)

def source_fit(scene,gauge,fold):
    Ks=kfs(scene);rows=[];fits={};prefix_r=[]
    for k in Ks:
        y,cov,Q=local_gauge(k,gauge);rv=k['ref_valid']&np.isfinite(k['ref_z'])&(k['ref_z']>0)&np.isfinite(y[:,2])&(y[:,2]>0)
        if gauge=='orientation':
            gd=json.loads((ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json').read_text()) if scene=='office2' else json.loads((V/'maps/alignment.json').read_text())
            ref=k['ref_z']*float(np.cbrt(np.linalg.det(np.asarray(gd['relative'])[:3,:3])))
        else:ref=k['ref_z']
        fitmask,evalmask=tile_masks(k['pixel_indices'],rv,fold=fold)
        u=k['pixel_indices']%512;v=k['pixel_indices']//512
        if k['original_frame']<200:
            prefix_r.extend(np.log(ref[fitmask|evalmask]/y[fitmask|evalmask,2]).tolist())
            continue
        with np.errstate(divide='ignore',invalid='ignore'):
            r=np.log(ref/y[:,2])
        B=bilinear_basis(u[fitmask],v[fitmask]); counts=[]
        for ry in range(4):
            for cx in range(4):
                x0=cx*512/4;x1=(cx+1)*512/4;y0=ry*288/4;y1=(ry+1)*288/4
                counts.append(int(np.sum(fitmask&(u>=x0)&(u<x1)&(v>=y0)&(v<y1))))
        gram=B.T@B/max(1,len(B)); eig=np.linalg.eigvalsh(gram);rank=int(np.linalg.matrix_rank(gram,tol=1e-12));ratio=float(eig[0]/eig[-1]) if eig[-1]>0 else 0
        ok,reasons=support_gate(int(fitmask.sum()),int(evalmask.sum()),counts,rank,ratio)
        # Save exact index lists and digests so every split is auditable.
        fidx=k['pixel_indices'][fitmask];eidx=k['pixel_indices'][evalmask]
        rec=dict(scene=scene,gauge=gauge,fold=fold,kf_idx=k['kf_idx'],original_frame=k['original_frame'],fit_n=len(fidx),eval_n=len(eidx),support=bool(ok),reason=reasons,
            fit_indices_sha256=hashlib.sha256(fidx.tobytes()).hexdigest(),eval_indices_sha256=hashlib.sha256(eidx.tobytes()).hexdigest(),region_counts=counts,design_rank=rank,eigen_ratio=ratio)
        rows.append(rec)
        if ok:
            rfit=r[fitmask];alpha=fit_scalar(rfit);h=fit_huber_scalar(rfit);field=fit_field(B,rfit,h['alpha'])
            if not h['converged'] or not field['converged']:raise RuntimeError(f"IMPLEMENTATION_FIX solver did not converge {scene}/{gauge}/{fold}/kf{k['kf_idx']}")
            fits[k['kf_idx']]=dict(alpha=alpha,alpha_h=h['alpha'],beta=float(np.exp(alpha)),beta_h=float(np.exp(h['alpha'])),theta=field['theta'].tolist(),field_min=float(field['theta'].min()),field_max=float(field['theta'].max()),iterations=field['iterations'],objective=field['objective'],condition=field['condition'],fit_n=len(fidx),eval_n=len(eidx),support=True)
        else:fits[k['kf_idx']]=dict(support=False,reason=reasons,fit_n=len(fidx),eval_n=len(eidx))
    if len(prefix_r)<2048:raise RuntimeError(f"prefix support below 2048: {len(prefix_r)}")
    alpha_g=float(np.median(prefix_r))
    post=[k for k in Ks if k['strict'].any()]
    return dict(rows=rows,fits=fits,alpha_g=alpha_g,prefix_n=len(prefix_r),kf_support_fraction=sum(x['support'] for x in rows)/max(1,len(rows)),candidate_support_fraction=sum(k['strict'].sum() for k in post if fits[k['kf_idx']]['support'])/sum(k['strict'].sum() for k in post))

def cmd_preflight():
    OUT.mkdir(parents=True,exist_ok=True);spec=json.loads(CFG.read_text());summary={}
    for scene in spec['scenes']:
        Ks=kfs(scene);expected=(11,1545979,1200827) if scene=='office2' else (8,1136762,855796)
        native=sum(len(k['y']) for k in Ks);strict=sum(int(k['strict'].sum()) for k in Ks)
        assert (len(Ks),native,strict)==expected,(scene,len(Ks),native,strict)
        assert all((k['H'],k['W'])==(288,512) for k in Ks)
        summary[scene]=dict(keyframes=len(Ks),native=native,strict=strict,frames=[k['original_frame'] for k in Ks],inputs=[digest(k['local_path']) for k in Ks])
    dump_json(OUT/'preflight.json',dict(status='PASS',summary=summary,code=src_hashes()))

def cmd_register():
    if (OUT/'registration.json').exists():raise RuntimeError('registration exists; preserve it')
    pf=json.loads((OUT/'preflight.json').read_text());assert pf['status']=='PASS'
    # Register N2 dataset members by manifest bytes/hash, without reading office4.
    manifest=json.loads((ROOT/'configs/n2_dataset_manifest.json').read_text());used=[]
    for x in manifest['files']:
        if x['path'].startswith(('data/N2/Replica/office2/','data/N2/Replica/office3/')) or x['path']=='data/N2/Replica/cam_params.json':
            p=ROOT/x['path'];assert p.exists() and p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],x['path'];used.append(x)
    dump_json(OUT/'registration.json',dict(status='REGISTERED',registered_before_fit=True,code=src_hashes(),dataset_files=used,preflight=digest(OUT/'preflight.json'),office3_known_validation=True,office4_accessed=False,hk_accessed=False))
    (OUT/'registered_code').mkdir(exist_ok=False)
    for row in src_hashes():
        p=ROOT/row['path'];dest=OUT/'registered_code'/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)

def cmd_fit(scene):
    if scene=='office3':
        seal=json.loads((OUT/'development_seal.json').read_text());assert seal['code']==src_hashes(), 'office3 frozen code/protocol mismatch'
        dump_json(OUT/'office3/validation_registration.json',dict(status='REGISTERED_AFTER_OFFICE2_SEAL',seal=digest(OUT/'development_seal.json'),code=src_hashes(),known_validation=True))
    dest=OUT/scene/'fits';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'fit_parameters.json').exists():raise RuntimeError('fit already exists; preserve')
    results={};fold_rows=[]
    for gauge in ['position','orientation']:
        results[gauge]={}
        for fold in [0,1]:
            f=source_fit(scene,gauge,fold);results[gauge][str(fold)]=f
            fold_rows.extend(f['rows'])
    import csv
    with (dest/'source_folds.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(fold_rows[0]));w.writeheader();w.writerows(fold_rows)
    dump_json(dest/'fit_parameters.json',results)

def cmd_build(scene):
    fitpath=OUT/scene/'fits/fit_parameters.json';fits=json.loads(fitpath.read_text());dest=OUT/scene/'maps';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'manifest.json').exists():raise RuntimeError('maps already exist; preserve')
    Ks=kfs(scene);manifest=[]
    for gauge in ['position','orientation']:
        _,count=base_map(scene,gauge);base=np.asarray(packed(base_map(scene,gauge)[0],count)).copy();offset=0
        # S0's per-KF ordering is the strict candidate order in source manifest.
        for fold in [0,1]:
            params=fits[gauge][str(fold)];
            for method in ['S0','Sg','Sk','SkH','Sf']:
                out=np.array(base,copy=True);off=0
                for k in Ks:
                    n=int(k['strict'].sum())
                    if n:
                        if method=='S0':apply=False
                        elif method=='Sg':d=params['alpha_g'];apply=True
                        else:
                            ff=params['fits'][str(k['kf_idx'])]
                            apply=bool(ff['support'])
                            if apply:
                                if method=='Sk':d=ff['alpha']
                                elif method=='SkH':d=ff['alpha_h']
                                else:
                                    u=k['pixel_indices'][k['strict']]%512;v=k['pixel_indices'][k['strict']]//512
                                    d=bilinear_basis(u,v)@np.asarray(ff['theta'])
                        if apply:
                            y,_,Q=local_gauge(k,gauge);yc=y[k['strict']]*np.exp(d) if np.isscalar(d) else y[k['strict']]*np.exp(d)[:,None]
                            xyz=transform_points(yc,Q).astype(np.float32)
                            out[off:off+n,:3]=xyz
                    off+=n
                assert off==count and np.array_equal(out[:,3:],base[:,3:])
                name=f'{gauge}_fold{fold}_{method}.f32';out.tofile(dest/name)
                manifest.append(dict(gauge=gauge,fold=fold,method=method,count=count,file=digest(dest/name),base_sha256=sha(base_map(scene,gauge)[0])))
        del base
    dump_json(dest/'manifest.json',dict(status='PASS',maps=manifest))

def source_residuals(scene):
    import csv
    Ks=kfs(scene);fitroot=OUT/scene/'fits';maps=json.loads((fitroot/'fit_parameters.json').read_text());rows=[]
    for gauge in ['position','orientation']:
      for fold in [0,1]:
        pars=maps[gauge][str(fold)]
        for k in Ks:
          ff=pars['fits'].get(str(k['kf_idx']))
          if not k['strict'].any() or not ff or not ff['support']:
            rows.append(dict(scene=scene,gauge=gauge,fold=fold,kf_idx=k['kf_idx'],method='ALL',fit_n=0 if not ff else ff['fit_n'],eval_n=0 if not ff else ff['eval_n'],supported=False,mae_z_m=None,absrel=None,log_median=None,log_mad=None,mean_3d_m=None));continue
          y,_,Q=local_gauge(k,gauge);rv=k['ref_valid']&(k['ref_z']>0)&(y[:,2]>0)&np.isfinite(y[:,2]);_,ev=tile_masks(k['pixel_indices'],rv,fold=fold)
          gd=json.loads((ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json').read_text()) if scene=='office2' else json.loads((V/'maps/alignment.json').read_text())
          scale=(float(np.cbrt(np.linalg.det(np.asarray(gd['relative'])[:3,:3]))) if gauge=='orientation' else 1.)
          ref=k['ref_z']*scale;refxyz=k['ref_xyz']*scale
          B=bilinear_basis(k['pixel_indices']%512,k['pixel_indices']//512);methods={'S0':np.zeros(len(y)),'Sg':np.full(len(y),pars['alpha_g'])}
          methods.update({'Sk':np.full(len(y),ff['alpha']),'SkH':np.full(len(y),ff['alpha_h']),'Sf':B@np.asarray(ff['theta'])})
          for method,d in methods.items():
            sel=ev&rv; yc=y[sel]*np.exp(d[sel,None] if np.ndim(d) else d); z=yc[:,2];rz=ref[sel];le=np.log(z/rz)
            rows.append(dict(scene=scene,gauge=gauge,fold=fold,kf_idx=k['kf_idx'],method=method,fit_n=ff['fit_n'],eval_n=int(sel.sum()),supported=True,mae_z_m=float(np.mean(np.abs(z-rz))),absrel=float(np.mean(np.abs(z-rz)/rz)),log_median=float(np.median(le)),log_mad=float(np.median(np.abs(le-np.median(le)))),mean_3d_m=float(np.linalg.norm(yc-refxyz[sel],axis=1).mean())))
    p=OUT/scene/'analysis';p.mkdir(parents=True,exist_ok=True)
    with (p/'source_spatial_residuals.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def target_evaluate(scene):
    import csv,cv2,torch
    from e1_taxonomy import camera_geometry,resize_depth,depth_masks
    from evaluate_e4 import CudaMap
    if not torch.cuda.is_available():raise RuntimeError('CUDA is required for A2-S target rendering')
    torch.set_num_threads(2);cv2.setNumThreads(2);torch.backends.cuda.matmul.allow_tf32=False
    ddir=OUT/scene/'evaluation';ddir.mkdir(parents=True,exist_ok=True)
    if (ddir/'target_methods.csv').exists():raise RuntimeError('completed evaluation preserved')
    base=ROOT/'data/N2/Replica'/scene;camera=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera'];K,_,crop=camera_geometry(camera);poses=np.loadtxt(base/'traj.txt').reshape(-1,4,4)
    maskspec=json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())['common_mask'];frames=list(range(201,1000,2));viewdata={}
    for frame in frames:
      raw=cv2.imread(str(base/'results'/f'depth{frame:06d}.png'),cv2.IMREAD_UNCHANGED);gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,maskspec);inside=valid&~edge
      # Existing packed maps already include their frozen position/orientation alignment;
      # renderer poses are the raw GT camera-to-world poses, as in the registered E4 evaluator.
      viewdata[frame]=dict(gt=gt,valid=valid,interior=inside,pose=poses[frame])
    manifests=json.loads((OUT/scene/'maps/manifest.json').read_text())['maps'];depthroot=ddir/'depth';depthroot.mkdir(exist_ok=True);byhash={};rows=[]
    for item in manifests:
      key=item['file']['sha256'];cache=byhash.get(key)
      if cache is None:
        cache=depthroot/(key);cache.mkdir(exist_ok=True);packed_map=np.memmap(ROOT/item['file']['path'],dtype=np.float32,mode='r',shape=(item['count'],13));g=CudaMap(packed_map)
        for frame in frames:
          vv=viewdata[frame];rendered=g.depth(vv['pose'],K,vv['gt'].shape)
          np.savez_compressed(cache/f'frame{frame:04d}.npz',depth=rendered[:,:,0],weight=rendered[:,:,1]);
        del g,packed_map;torch.cuda.empty_cache();byhash[key]=cache
      item['cache']=str(cache)
    # Compute per-arm target statistics and retain exactly the same map/view arrays for all contrasts.
    data={}
    for item in manifests:
      key=(item['gauge'],item['fold'],item['method']);arr={}
      cache=Path(item['cache'])
      for frame in frames:
        with np.load(cache/f'frame{frame:04d}.npz') as z: dep=z['depth'];weight=z['weight']
        pred=np.divide(dep,weight,out=np.zeros_like(dep),where=weight>1e-9);covered=(weight>.001)&np.isfinite(pred)&(pred>0);arr[frame]=(pred,covered)
      data[key]=arr
    target_rows=[];scalar_rows=[]
    for gauge in ['position','orientation']:
      for fold in [0,1]:
        ctx={m:data[(gauge,fold,m)] for m in ['S0','Sg','Sk','SkH','Sf']}
        common3=common2=common4=0;errs={m:[] for m in ctx};support_views=0;view_stats=[]
        for frame in frames:
          vd=viewdata[frame];gt=vd['gt'];valid=vd['valid'];inter=vd['interior'];pred={m:ctx[m][frame][0] for m in ctx};cov={m:ctx[m][frame][1] for m in ctx}
          masks={m:inter&cov[m] for m in ctx};c3=inter&cov['S0']&cov['Sk']&cov['Sf'];c4=inter&cov['S0']&cov['Sk']&cov['SkH']&cov['Sf'];c2=inter&cov['S0']&cov['Sg']
          if c3.sum()>=1000 and c3.sum()/max(1,inter.sum())>=.5:support_views+=1
          for m in ctx:
            own=masks[m];errs[m].append(float(np.mean(np.abs(pred[m][own]-gt[own]))) if own.any() else None)
            target_rows.append(dict(scene=scene,gauge=gauge,fold=fold,frame=frame,method=m,own_n=int(own.sum()),interior_n=int(inter.sum()),own_mae=float(np.mean(np.abs(pred[m][own]-gt[own]))) if own.any() else None,own_absrel=float(np.mean(np.abs(pred[m][own]-gt[own])/gt[own])) if own.any() else None,coverage=float(own.sum()/max(1,inter.sum())),correct_coverage=float(np.sum(own&(np.abs(pred[m]-gt)<=np.maximum(.05,.02*gt)))/max(1,inter.sum())),common3_n=int(c3.sum()),common4_n=int(c4.sum()),common2_n=int(c2.sum())))
          common3+=int(c3.sum());common2+=int(c2.sum());common4+=int(c4.sum())
          if c3.any():
            for m in ['S0','Sk','Sf']:view_stats.append(dict(frame=frame,method=m,mae=float(np.mean(np.abs(pred[m][c3]-gt[c3]))),mask=c3))
        # Equal-view mean of per-view common3 MAE; no pooling across views.
        for m in ['S0','Sk','Sf']:
          vals=[x['mae'] for x in view_stats if x['method']==m];
          if not vals: E={**{x['method']:None for x in []}}
        Es={m:(float(np.mean([x['mae'] for x in view_stats if x['method']==m])) if any(x['method']==m for x in view_stats) else None) for m in ['S0','Sk','Sf']}
        covstats={m:float(np.mean([r['coverage'] for r in target_rows if r['gauge']==gauge and r['fold']==fold and r['method']==m])) for m in ['S0','Sk','Sf']}
        corstats={m:float(np.mean([r['correct_coverage'] for r in target_rows if r['gauge']==gauge and r['fold']==fold and r['method']==m])) for m in ['S0','Sk','Sf']}
        eligible=(support_views/400>=.8)
        E0,Ek,Ef=Es['S0'],Es['Sk'],Es['Sf'];gain=None if None in (E0,Ek,Ef) else E0-Ef;ratio=None if not gain or gain<=0 else (E0-Ek)/gain
        if not eligible:label='INSUFFICIENT_SUPPORT';ratio=None
        elif gain is None or gain<=0 or gain/E0<.1:label='FIELD_GAIN_NOT_ESTABLISHED';ratio=None
        elif covstats['Sk']<covstats['S0']-1e-6 or covstats['Sf']<covstats['S0']-1e-6 or corstats['Sk']<corstats['S0']-.01 or corstats['Sf']<corstats['S0']-.01:label='COVERAGE_TRADEOFF'
        else:label='SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD' if ratio>=.9 else 'RESIDUAL_FIELD_OPPORTUNITY'
        scalar_rows.append(dict(scene=scene,gauge=gauge,fold=fold,E0=E0,Ek=Ek,Ef=Ef,field_gain=gain,scalar_gain=None if E0 is None or Ek is None else E0-Ek,ratio=ratio,label=label,target_support_views=support_views,target_support_fraction=support_views/400,common3_pixel_sum=common3,common2_pixel_sum=common2,common4_pixel_sum=common4,interior_coverage_S0=covstats['S0'],interior_coverage_Sk=covstats['Sk'],interior_coverage_Sf=covstats['Sf'],correct_coverage_S0=corstats['S0'],correct_coverage_Sk=corstats['Sk'],correct_coverage_Sf=corstats['Sf']))
    for file,rows in [('target_methods.csv',target_rows),('scalar_sufficiency.csv',scalar_rows)]:
      with (ddir/file).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    dump_json(ddir/'render_manifest.json',dict(status='PASS',fresh_map_view_pairs=sum(len(frames) for _ in byhash),unique_maps=len(byhash),views=len(frames),cuda=torch.cuda.get_device_name(0),tf32=False))

def cmd_analyze(scene):
    source_residuals(scene)
    import csv
    ev=OUT/scene/'evaluation';man=json.loads((OUT/scene/'maps/manifest.json').read_text())['maps'];depthroot=ev/'depth'
    fits=json.loads((OUT/scene/'fits/fit_parameters.json').read_text());base=ROOT/'data/N2/Replica'/scene
    import cv2
    from e1_taxonomy import camera_geometry,resize_depth,depth_masks
    camera=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera'];spec=json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())['common_mask'];frames=list(range(201,1000,2));vdata={}
    for frame in frames:
      raw=cv2.imread(str(base/'results'/f'depth{frame:06d}.png'),cv2.IMREAD_UNCHANGED);gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,spec);vdata[frame]=(gt,valid,valid&~edge)
    caches={}
    for x in man:
      key=(x['gauge'],x['fold'],x['method']);root=depthroot/x['file']['sha256'];arr={}
      for frame in frames:
        with np.load(root/f'frame{frame:04d}.npz') as a:
          w=a['weight'];d=a['depth'];pred=np.divide(d,w,out=np.zeros_like(d),where=w>1e-9);arr[frame]=(pred,(w>.001)&(pred>0)&np.isfinite(pred))
      caches[key]=arr
    rows=[];binrows=[]
    for gauge in ['position','orientation']:
      for fold in [0,1]:
        ctx={m:caches[(gauge,fold,m)] for m in ['S0','Sk','SkH','Sf']};view_mae={m:[] for m in ctx}
        for frame in frames:
          gt,valid,inside=vdata[frame];cover={m:ctx[m][frame][1] for m in ctx};pred={m:ctx[m][frame][0] for m in ctx};common=inside.copy()
          for m in ctx:common &= cover[m]
          for m in ctx:
            if common.any():view_mae[m].append(float(np.mean(np.abs(pred[m][common]-gt[common]))))
          for m in ctx:
            correct=(cover[m]&(np.abs(pred[m]-gt)<=np.maximum(.05,.02*gt)))
            binrows.append(dict(scene=scene,gauge=gauge,fold=fold,frame=frame,method=m,common4_n=int(common.sum()),correct_coverage_all_reference=float(np.sum(correct&valid)/max(1,valid.sum())),correct_coverage_interior=float(np.sum(correct&inside)/max(1,inside.sum()))))
          edges=[.1,1,2,4,10]
          for j,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
            bm=common&(gt>=lo)&(gt<hi)
            for m in ctx:
              binrows.append(dict(scene=scene,gauge=gauge,fold=fold,frame=frame,method=m,depth_bin=f'[{lo},{hi})',common4_n=int(bm.sum()),common4_mae=float(np.mean(np.abs(pred[m][bm]-gt[bm]))) if bm.any() else None))
        for m in ctx:rows.append(dict(scene=scene,gauge=gauge,fold=fold,method=m,common4_equal_view_mae=float(np.mean(view_mae[m])) if view_mae[m] else None,scored_views=len(view_mae[m])))
    for name,content in [('target_common4_contrasts.csv',rows),('target_coverage_bins.csv',binrows)]:
      with (ev/name).open('w',newline='') as f:
        fields=list(dict.fromkeys(key for row in content for key in row));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(content)

def cmd_verify(scene):
    import csv
    maps=json.loads((OUT/scene/'maps/manifest.json').read_text())['maps'];fits=json.loads((OUT/scene/'fits/fit_parameters.json').read_text());Ks=kfs(scene);checks=[]
    for gauge in ['position','orientation']:
      bp,bn=base_map(scene,gauge);base=np.memmap(bp,dtype=np.float32,mode='r',shape=(bn,13));off_by_kf=[];q=0
      for k in Ks:n=int(k['strict'].sum());off_by_kf.append((q,q+n,k));q+=n
      assert q==bn
      for fold in [0,1]:
       for method in ['S0','Sg','Sk','SkH','Sf']:
        e=next(x for x in maps if x['gauge']==gauge and x['fold']==fold and x['method']==method);p=ROOT/e['file']['path'];out=np.memmap(p,dtype=np.float32,mode='r',shape=(bn,13));assert p.stat().st_size==bn*52
        assert np.array_equal(out[:,3:],base[:,3:]),f'attributes changed {gauge}/{fold}/{method}'
        for a,b,k in off_by_kf:
          if not k['strict'].any():continue
          if method in ['Sk','SkH','Sf'] and not fits[gauge][str(fold)]['fits'][str(k['kf_idx'])]['support']:
            assert np.array_equal(out[a:b,:3],base[a:b,:3]),f'unsupported center changed {gauge}/{fold}/{method}/{k["kf_idx"]}'
          elif method!='S0':
            ff=fits[gauge][str(fold)]['fits'].get(str(k['kf_idx']));
            if method=='Sg':apply=True;d=fits[gauge][str(fold)]['alpha_g']
            elif ff and ff.get('support'):
              apply=True;d={'Sk':ff['alpha'],'SkH':ff['alpha_h']}.get(method)
              if method=='Sf':d=bilinear_basis(k['pixel_indices'][k['strict']]%512,k['pixel_indices'][k['strict']]//512)@np.asarray(ff['theta'])
            else:apply=False
            if apply:
              y,_,Q=local_gauge(k,gauge);yc=y[k['strict']]*np.exp(d) if np.isscalar(d) else y[k['strict']]*np.exp(d)[:,None];xyz=transform_points(yc,Q).astype(np.float32)
              np.testing.assert_allclose(xyz,out[a:b,:3],atol=2e-5,rtol=1e-6)
              inv=transform_points(out[a:b,:3].astype(float),np.linalg.inv(Q));np.testing.assert_allclose(inv,yc,atol=2e-5,rtol=1e-6)
        checks.append(dict(gauge=gauge,fold=fold,method=method,map_sha256=e['file']['sha256'],count=bn,attributes_bitwise=True))
    # Independent S0 replay parity against the five original cached views.
    pos=next(x for x in maps if x['gauge']=='position' and x['fold']==0 and x['method']=='S0');cache=OUT/scene/'evaluation/depth'/pos['file']['sha256'];prior=(ROOT/'results/A1_C_canonical_factorial/2026-10-26/evaluation/office2_strict/C00') if scene=='office2' else V/'evaluation/position_strict/C00'
    par=[]
    for frame in [201,401,601,801,999]:
      a=np.load(cache/f'frame{frame:04d}.npz');b=np.load(prior/f'frame{frame:04d}.npz');ca=a['weight']>.001;cb=b['covered'];inter=ca&cb;pred=np.divide(a['depth'],a['weight'],out=np.zeros_like(a['depth']),where=a['weight']>1e-9);maxd=float(np.max(np.abs(pred[inter]-b['depth'][inter]))) if inter.any() else 0.;dis=int(np.count_nonzero(ca!=cb));assert dis==0 and maxd<=.002,(frame,dis,maxd);par.append(dict(frame=frame,mask_disagreements=dis,max_depth_difference_m=maxd))
    # Source support and required heldout target gate.
    for g in ['position','orientation']:
      for f in ['0','1']:
        x=fits[g][f];assert x['kf_support_fraction']>=.8 and x['candidate_support_fraction']>=.8
    with (OUT/scene/'evaluation/scalar_sufficiency.csv').open() as f:scalars=list(csv.DictReader(f))
    assert len(scalars)==4 and all(float(x['target_support_fraction'])>=.8 for x in scalars)
    v=dict(status='PASS',scene=scene,map_checks=checks,s0_parity=par,support_gate='PASS',target_support_gate='PASS',registered_code=src_hashes(),maps_manifest=digest(OUT/scene/'maps/manifest.json'),fits=digest(OUT/scene/'fits/fit_parameters.json'),target_methods=digest(OUT/scene/'evaluation/target_methods.csv'),scalar_sufficiency=digest(OUT/scene/'evaluation/scalar_sufficiency.csv'))
    dump_json(OUT/scene/'verification.json',v)

def cmd_seal():
    assert json.loads((OUT/'office2/verification.json').read_text())['status']=='PASS'
    seal=dict(status='SEALED',scene='office2',protocol=src_hashes()[0],code=src_hashes(),fit=digest(OUT/'office2/fits/fit_parameters.json'),maps=digest(OUT/'office2/maps/manifest.json'),evaluation=digest(OUT/'office2/evaluation/target_methods.csv'),analysis=digest(OUT/'office2/evaluation/scalar_sufficiency.csv'),verification=digest(OUT/'office2/verification.json'),amendments=[digest(p) for p in sorted((OUT/'amendments').glob('AMENDMENT_*.json'))],parameters_unchanged_after_office2=True,office3_fit_allowed=True)
    dump_json(OUT/'development_seal.json',seal)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['preflight','register','fit','build','evaluate','analyze','verify','seal','report']);p.add_argument('--scene',choices=['office2','office3']);p.add_argument('--config',default=str(CFG));a=p.parse_args()
    if Path(a.config).resolve()!=CFG.resolve():raise ValueError('Only frozen A2-S config accepted')
    if a.command=='preflight':cmd_preflight()
    elif a.command=='register':cmd_register()
    elif a.command=='fit':cmd_fit(a.scene)
    elif a.command=='build':cmd_build(a.scene)
    elif a.command=='evaluate':target_evaluate(a.scene)
    elif a.command=='analyze':cmd_analyze(a.scene)
    elif a.command=='verify':cmd_verify(a.scene)
    elif a.command=='seal':cmd_seal()
    elif a.command=='report':raise NotImplementedError('report is being added')
if __name__=='__main__':main()
