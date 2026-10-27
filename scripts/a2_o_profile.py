"""GT-isolated RGB profile construction and frozen coefficient selection."""
import csv, json, hashlib
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

from a2_s_common import ROOT, kfs, digest, dump_json
from run_a2_o import OUT, CFG, baseline, events, pairs_for
from run_a2_s import local_gauge
from e1_taxonomy import camera_geometry
from rgb_observability import (scalar_candidates, field_candidates, dct_modes,
    native_patch_samples, rasterize_predicted_depth, evaluate_pair_candidates,
    two_stage_selection, bilinear_basis, profile_digest, select_profile,
    aggregate_pair_losses, huber, seal_selection)

H,W=288,512
CAMERA=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera']
K=camera_geometry(CAMERA)[0]
_RGB={}
PROFILE_ROOT=OUT/'profile_selection_v2'


def rgb_for(scene, frame):
    key=(scene,int(frame))
    if key in _RGB: return _RGB[key]
    p=ROOT/'data/N2/Replica'/scene/'results'/f'frame{frame:06d}.jpg'
    bgr=cv2.imread(str(p),cv2.IMREAD_COLOR)
    if bgr is None: raise FileNotFoundError(p)
    raw=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB); im=Image.fromarray(raw)
    rw,rh=im.size; scale=512/max(rw,rh); nw,nh=round(rw*scale),round(rh*scale)
    filt=Image.Resampling.LANCZOS if max(rw,rh)>512 else Image.Resampling.BICUBIC
    im=im.resize((nw,nh),filt); cx,cy=nw//2,nh//2
    hw=((2*cx)//16)*8; hh=((2*cy)//16)*8
    if nw==nh: hh=3*hw//4
    im=im.crop((cx-hw,cy-hh,cx+hw,cy+hh))
    arr=np.asarray(im,dtype=np.float32)/255.
    if arr.shape!=(H,W,3): raise ValueError(f'RGB resize/crop mismatch {arr.shape}: {p}')
    _RGB[key]=arr
    return arr


def _pred_only(k):
    # Explicit allow-list prevents reference fields carried by the shared A2-S
    # adapter from entering any RGB profile function.
    return {key:k[key] for key in ('kf_idx','original_frame','H','W','y',
             'covariance_y','Q','pixel_indices','local_path')}


def _gauge_pred(k, gauge):
    pred=_pred_only(k)
    y,_,Q=local_gauge(pred,gauge)
    return y,np.asarray(Q,dtype=np.float64)


def _pair_bundle(scene, src, ev, raw, gauge, fold):
    # Model-input IDs and anchor IDs are subsample indices. Local frame IDs are
    # already original-frame IDs, so conversion is applied only at this edge.
    rs=raw[src['candidate_event']]; re=raw[ev['candidate_event']]
    sf=2*int(rs['anchor_frame_id']); ef=2*int(re['anchor_frame_id'])
    if sf!=src['original_frame'] or ef!=ev['original_frame']:
        raise ValueError('anchor image/local frame mismatch')
    ys,Qs=_gauge_pred(src,gauge); ye,Qe=_gauge_pred(ev,gauge)
    rgb_s=rgb_for(scene,sf); rgb_e=rgb_for(scene,ef)
    patches=native_patch_samples(ys,src['pixel_indices'],rgb_s,fold=fold,
                                 height=H,width=W,stride=4,guard=2,texture_min=.02)
    # Keep only source rays whose native point projects back to its registered
    # RGB pixel within the fixed 1px gate.
    lut=np.full(H*W,-1,np.int32);lut[src['pixel_indices']]=np.arange(len(src['pixel_indices']),dtype=np.int32)
    if len(patches['centers']):
      center_rows=lut[patches['centers']];yc=ys[center_rows];zc=np.maximum(yc[:,2],1e-12)
      pu=K[0,0]*yc[:,0]/zc+K[0,2];pv=K[1,1]*yc[:,1]/zc+K[1,2]
      ray_error=np.hypot(pu-patches['centers']%W,pv-patches['centers']//W)
      patches['ray_error']=ray_error;patches['ray_grid_match']=ray_error<=1.0
      # Predicted parallax angle between the fixed source/evidence camera rays.
      world=yc@Qs[:3,:3].T+Qs[:3,3]
      rs=Qs[:3,3]-world;re=Qe[:3,3]-world
      den=np.linalg.norm(rs,axis=1)*np.linalg.norm(re,axis=1)
      cosine=np.sum(rs*re,axis=1)/np.maximum(den,1e-12)
      patches['parallax_deg']=np.degrees(np.arccos(np.clip(cosine,-1,1)))
      patches['primary_parallax']=patches['parallax_deg']>=1.0
      patches['texture'] &= patches['ray_grid_match']
    else:
      patches['ray_error']=np.empty(0);patches['ray_grid_match']=np.empty(0,bool)
      patches['parallax_deg']=np.empty(0);patches['primary_parallax']=np.empty(0,bool)
    baseline=float(np.linalg.norm(Qs[:3,3]-Qe[:3,3]))
    source_rows=lut[patches['centers']] if len(patches['centers']) else np.empty(0,np.int32)
    depth_med=float(np.median(ys[source_rows,2])) if len(source_rows) else None
    pbins=np.histogram(patches['parallax_deg'],bins=[0,.25,1,3,np.inf])[0].astype(int).tolist()
    z,valid,_=rasterize_predicted_depth(ye,ev['pixel_indices'],K,height=H,width=W,
                                        edge_relative=.05,edge_dilation=2)
    return {'patches':patches,'source_Q':Qs,'evidence_Q':Qe,'K':K,
            'evidence_rgb':rgb_e,'evidence_z':z,'evidence_valid':valid,
            'scene':scene,'source_kf':src['kf_idx'],'evidence_kf':ev['kf_idx'],
            'source_frame':sf,'evidence_frame':ef,'gauge':gauge,'fold':fold,
            'ray_grid_mismatch_count':int(np.sum(~patches['ray_grid_match'])),
            'ray_grid_sampled_count':int(len(patches['ray_grid_match'])),
            'camera_baseline':baseline,'baseline_over_median_source_depth':None if not depth_med else baseline/depth_med,
            'parallax_bin_counts_deg':pbins}


def _pair_design_ok(profile, pair, minimum=16, eigen_min=1e-8):
    m=profile['mask']; P=pair['patches']
    if not m.any(): return False,[],0.
    centers=P['centers'][m];u=centers%W;v=centers//W
    counts=[]
    for r in range(4):
        for c in range(4):
            counts.append(int(np.sum((u>=c*W/4)&(u<(c+1)*W/4)&(v>=r*H/4)&(v<(r+1)*H/4))))
    B=bilinear_basis(u,v); eig=np.linalg.eigvalsh(B.T@B/max(1,len(B)))
    ratio=float(eig[0]/eig[-1]) if eig[-1]>0 else 0.
    return min(counts,default=0)>=minimum and ratio>=eigen_min,counts,ratio


def _eval_pool(bundles, candidates, modes, *, require_field=False):
    results=[]
    for pair in bundles:
        p=evaluate_pair_candidates(pair,candidates,modes)
        p['pair']=pair;results.append(p)
    supported=[p for p in results if p['support']]
    if len(supported)<2:
        return {'losses':None,'mask_digest':None,'support':{'supported':False,
            'supported_pairs':len(supported),'attempted_pairs':len(results),
            'reasons':[{'evidence_kf':p['pair']['evidence_kf'],'retained':p.get('retained',0),
                        'eligible':p.get('eligible',0),'support':p['support']} for p in results]}}
    losses=aggregate_pair_losses([p['losses'][None,:] for p in supported])[0]
    geometry=aggregate_pair_losses([p['geometry_losses'][None,:] for p in supported])[0]
    zncc=aggregate_pair_losses([p['zncc_losses'][None,:] for p in supported])[0]
    l1=aggregate_pair_losses([p['l1_losses'][None,:] for p in supported])[0]
    field_support={'supported':True}
    if require_field:
        centers=np.concatenate([p['pair']['patches']['centers'][p['mask']] for p in supported])
        u=centers%W;v=centers//W;region_counts=[]
        for r in range(4):
            for c in range(4):
                region_counts.append(int(np.sum((u>=c*W/4)&(u<(c+1)*W/4)&(v>=r*H/4)&(v<(r+1)*H/4))))
        Bc=bilinear_basis(u,v);eig=np.linalg.eigvalsh(Bc.T@Bc/max(1,len(Bc)))
        ratio=float(eig[0]/eig[-1]) if eig[-1]>0 else 0.
        field_support={'supported':len(centers)>=1024 and min(region_counts,default=0)>=16 and ratio>=1e-8,
            'combined_centers':int(len(centers)),'region_counts':region_counts,'design_eigen_ratio':ratio,
            'reason':None if len(centers)>=1024 and min(region_counts,default=0)>=16 and ratio>=1e-8 else 'FIELD_DESIGN_SUPPORT_FAILED'}
        if not field_support['supported']:
            all_mask=np.concatenate([p['mask'] for p in supported])
            return {'losses':losses,'geometry_losses':geometry,'zncc_losses':zncc,'l1_losses':l1,
                    'mask_digest':profile_digest(all_mask),'support':field_support,
                    'pair_results':results}
    all_mask=np.concatenate([p['mask'] for p in supported])
    return {'losses':losses,'geometry_losses':geometry,'zncc_losses':zncc,'l1_losses':l1,
        'mask_digest':profile_digest(all_mask),
        'support':{'supported':True,'supported_pairs':len(supported),'attempted_pairs':len(results),
                   'patch_counts':[p['retained'] for p in supported],
                   'eligible_counts':[p['eligible'] for p in supported],
                   'retention':[p['retention'] for p in supported],
                   'pair_geometry':[{'evidence_kf':p['pair']['evidence_kf'],
                       'baseline':p['pair']['camera_baseline'],
                       'baseline_over_depth':p['pair']['baseline_over_median_source_depth'],
                       'parallax_bins_deg':p['pair']['parallax_bin_counts_deg'],
                       'ray_grid_mismatch_count':p['pair']['ray_grid_mismatch_count'],
                       'ray_grid_sampled_count':p['pair']['ray_grid_sampled_count']} for p in supported],
                   'field_design':field_support},
        'pair_results':results}


def profile_scene(scene):
    """Compute fit-only scalar seed, final shared-mask profiles and selections."""
    root=PROFILE_ROOT/scene;root.mkdir(parents=True,exist_ok=True)
    pair_rows=pairs_for(scene)
    pair_path=root/'pair_manifest.csv'
    pair_fields=list(dict.fromkeys(key for row in pair_rows for key in row))
    with pair_path.open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=pair_fields);w.writeheader();w.writerows(pair_rows)
    rows,raw=events(scene); event_by_kf={int(r['kf_idx']):r['candidate_event'] for r in rows}
    kmap={int(k['kf_idx']):_pred_only(k) for k in kfs(scene)}
    for i,k in kmap.items(): k['candidate_event']=event_by_kf[i]
    valid_pairs=[p for p in pair_rows if p.get('status')=='PROVENANCE_DISJOINT']
    selections={}; profile_rows=[]; mask_rows=[]; kf_scalar_loss={}; npost=sum(k['original_frame']>=200 for k in kmap.values())
    modes=dct_modes()
    for gauge in ('position','orientation'):
      selections[gauge]={}
      for fold in (0,1):
        selections[gauge][str(fold)]={}
        supported_scalars=[]
        for kf,k in kmap.items():
          if k['original_frame']<200: continue
          fit_ids=[int(p['evidence_kf']) for p in valid_pairs if int(p['source_kf'])==kf and p.get('pool')=='rgb_fit']
          audit_ids=[int(p['evidence_kf']) for p in valid_pairs if int(p['source_kf'])==kf and p.get('pool')=='rgb_audit']
          fit_bundles=[_pair_bundle(scene,k,kmap[e],raw,gauge,fold) for e in fit_ids]
          if len(fit_bundles)<2:
            selections[gauge][str(fold)][str(kf)]={'support':False,'reason':'FEWER_THAN_TWO_FIT_PAIRS'};continue
          stage_cache={}
          def evaluate_fit(candidates,stage):
            result=_eval_pool(fit_bundles,candidates,modes,require_field=(stage=='final_common'))
            stage_cache[stage]=result
            return result
          # Field-stage support can fail while scalar still passes. Keep this
          # explicitly unsupported rather than fabricating zero losses.
          def callback(candidates,stage):
            return evaluate_fit(candidates,stage)
          try:
            selection=two_stage_selection(callback)
          except ValueError as exc:
            failure=stage_cache.get('final_common') or stage_cache.get('scalar_seed') or {}
            stage_name='FINAL_FIELD_SUPPORT_FAILED' if 'final_common' in stage_cache else 'SCALAR_FIT_SUPPORT_FAILED'
            selections[gauge][str(fold)][str(kf)]={'support':False,'reason':str(exc),
                'stage':stage_name,'fit_support':failure.get('support')};continue
          final=stage_cache['final_common']
          if not final['support']['supported']:
            # Preserve scalar-only diagnostic separately; do not include it in
            # the primary common scalar/field denominator.
            scalar_set=scalar_candidates()
            ok=select_profile(scalar_set,final['losses'][:41],scalar_priority=False)
            gk=select_profile(scalar_set,final['geometry_losses'][:41],scalar_priority=False)
            selections[gauge][str(fold)][str(kf)]={'support':False,'scalar_only_support':True,
                'reason':'FIELD_COMMON_SUPPORT_FAILED','fit_support':final['support'],
                'scalar_seed':selection['seed'],'Ok':ok,'Gk':gk,
                'Of1':None,'scalar_only_mask':final['mask_digest']}
            for candidate,loss,gloss in zip(scalar_set,final['losses'][:41],final['geometry_losses'][:41]):
              profile_rows.append({'scene':scene,'gauge':gauge,'fold':fold,'kf_idx':kf,
                  'stage':'scalar_only_final_common_fit','candidate_kind':'scalar','a':candidate.a,
                  'mode':None,'b':0.0,'photo_loss':float(loss),'geometry_loss':float(gloss),
                  'zncc_loss':float(final['zncc_losses'][scalar_set.index(candidate)]),
                  'l1_loss':float(final['l1_losses'][scalar_set.index(candidate)]),
                  'support_pairs':final['support'].get('supported_pairs',0),
                  'mask_sha256':final['mask_digest']})
            mask_root=root/'masks';mask_root.mkdir(parents=True,exist_ok=True)
            for pair_result in final.get('pair_results',[]):
              if not pair_result.get('support'): continue
              pair=pair_result['pair'];centers=pair['patches']['centers'][pair_result['mask']]
              mask_name=f'{gauge}_fold{fold}_kf{kf:03d}_evidence{pair["evidence_kf"]:03d}_scalar_only_final.npz'
              mask_path=mask_root/mask_name;np.savez_compressed(mask_path,source_patch_centers=centers.astype(np.int32))
              mask_rows.append({'scene':scene,'gauge':gauge,'fold':fold,'kf_idx':kf,
                  'evidence_kf':pair['evidence_kf'],'pool':'rgb_fit','stage':'scalar_only_final',
                  'eligible_centers':pair_result['eligible'],'retained_centers':pair_result['retained'],
                  'retention':pair_result['retention'],'mask_sha256':pair_result['mask_digest'],
                  'index_file':str(mask_path.relative_to(root)),'index_file_sha256':digest(mask_path)['sha256']})
            continue
          selection.pop('losses',None);selection.pop('candidate_specs',None)
          mask_root=root/'masks';mask_root.mkdir(parents=True,exist_ok=True)
          for stage_name,stage_result in (('scalar_seed',stage_cache['scalar_seed']),('final_common',final)):
            for pair_result in stage_result.get('pair_results',[]):
              if not pair_result.get('support'): continue
              pair=pair_result['pair'];centers=pair['patches']['centers'][pair_result['mask']]
              mask_name=f'{gauge}_fold{fold}_kf{kf:03d}_evidence{pair["evidence_kf"]:03d}_{stage_name}.npz'
              mask_path=mask_root/mask_name
              np.savez_compressed(mask_path,source_patch_centers=centers.astype(np.int32))
              mask_rows.append({'scene':scene,'gauge':gauge,'fold':fold,'kf_idx':kf,
                  'evidence_kf':pair['evidence_kf'],'pool':'rgb_fit','stage':stage_name,
                  'eligible_centers':pair_result['eligible'],'retained_centers':pair_result['retained'],
                  'retention':pair_result['retention'],'mask_sha256':pair_result['mask_digest'],
                  'index_file':str(mask_path.relative_to(root)),'index_file_sha256':digest(mask_path)['sha256']})
          selections[gauge][str(fold)][str(kf)]={'support':True,'selection':selection,
              'fit_support':final['support'],'audit_evidence_kfs':audit_ids}
          supported_scalars.append((kf,np.asarray(final['losses'][:41])))
          kf_scalar_loss[kf,gauge,fold]=np.asarray(final['losses'][:41])
          candidates=scalar_candidates()+field_candidates(selection['seed'])
          seed_profile=stage_cache['scalar_seed']
          for candidate,loss in zip(scalar_candidates(),seed_profile['losses']):
            profile_rows.append({'scene':scene,'gauge':gauge,'fold':fold,'kf_idx':kf,
                'stage':'scalar_seed_fit','candidate_kind':candidate.kind,'a':candidate.a,
                'mode':None,'b':0.0,'photo_loss':float(loss),
                'geometry_loss':float(seed_profile['geometry_losses'][scalar_candidates().index(candidate)]),
                'zncc_loss':float(seed_profile['zncc_losses'][scalar_candidates().index(candidate)]),
                'l1_loss':float(seed_profile['l1_losses'][scalar_candidates().index(candidate)]),
                'support_pairs':seed_profile['support']['supported_pairs'],
                'patch_count_min':min(seed_profile['support']['patch_counts']),
                'mask_sha256':seed_profile['mask_digest']})
          for j,(candidate,loss) in enumerate(zip(candidates,final['losses'])):
            profile_rows.append({'scene':scene,'gauge':gauge,'fold':fold,'kf_idx':kf,
                'stage':'final_common_fit','candidate_kind':candidate.kind,'a':candidate.a,
                'mode':None if candidate.mode is None else candidate.mode+1,
                'b':candidate.b,'photo_loss':float(loss),
                'geometry_loss':float(final['geometry_losses'][j]),
                'zncc_loss':float(final['zncc_losses'][j]),'l1_loss':float(final['l1_losses'][j]),
                'support_pairs':final['support']['supported_pairs'],
                'patch_count_min':min(final['support']['patch_counts']),
                'mask_sha256':final['mask_digest']})
          # Geometry-only Gk uses the same scalar grid, fixed common mask and
          # evidence pairs. It is a predicted-depth agreement comparator only.
          scalar_geom=final['geometry_losses'][:41]
          geom_choice=select_profile(scalar_candidates(),scalar_geom,scalar_priority=False)
          selections[gauge][str(fold)][str(kf)]['Gk']={'a':geom_choice['candidate']['a'],
              'loss':geom_choice['loss'],'boundary':geom_choice['boundary'],
              'support_pairs':final['support']['supported_pairs'],
              'interpretation':'PREDICTED_GEOMETRY_AGREEMENT_ONLY'}
        if supported_scalars:
          og=np.mean(np.stack([x[1] for x in supported_scalars]),axis=0)
          og_choice=select_profile(scalar_candidates(),og,scalar_priority=False)
          selections[gauge][str(fold)]['Og']={'a':og_choice['candidate']['a'],'loss':og_choice['loss'],
             'profile':og.tolist(),'supported_kf_count':len(supported_scalars),'kf_denominator':npost,
             'status':'SELECTED_FIT_SUPPORTED_KF_EQUAL_WEIGHT'}
        else: selections[gauge][str(fold)]['Og']={'a':None,'status':'UNSUPPORTED'}
    # Profile files contain RGB/prediction quantities only.
    p=root/'profiles.csv';p.parent.mkdir(parents=True,exist_ok=True)
    fields=list(dict.fromkeys(key for row in profile_rows for key in row)) or ['scene','gauge','fold','kf_idx','status']
    with p.open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(profile_rows)
    mp=root/'mask_manifest.csv'
    with mp.open('w',newline='') as f:
      mfields=list(dict.fromkeys(key for row in mask_rows for key in row)) or ['scene','gauge','fold','kf_idx','status']
      w=csv.DictWriter(f,fieldnames=mfields);w.writeheader();w.writerows(mask_rows)
    gate={}
    post_candidates=sum(len(k['pixel_indices']) for k in kmap.values() if k['original_frame']>=200)
    for gauge in ('position','orientation'):
      gate[gauge]={}
      for fold in (0,1):
        records=[v for kf,v in selections[gauge][str(fold)].items() if kf!='Og']
        supported_kfs=sum(bool(v.get('support')) for v in records)
        supported_candidates=sum(len(kmap[int(kf)]['pixel_indices']) for kf,v in selections[gauge][str(fold)].items()
                                 if kf!='Og' and v.get('support'))
        gate[gauge][str(fold)]={'supported_kf_count':supported_kfs,'post_prefix_kf_count':npost,
            'supported_kf_fraction':supported_kfs/max(1,npost),
            'supported_native_candidate_count':supported_candidates,
            'post_prefix_native_candidate_count':post_candidates,
            'supported_native_candidate_fraction':supported_candidates/max(1,post_candidates),
            'scene_support_pass':supported_kfs/max(1,npost)>=.8 and supported_candidates/max(1,post_candidates)>=.8}
    all_rows_complete=all(str(kf) in selections[g][str(f)] for g in selections for f in (0,1)
                          for kf,k in kmap.items() if k['original_frame']>=200)
    dump_json(root/'selected_parameters.json',{'scene':scene,'selection_source':'RGB_fit_only',
        'reference_accessed':False,'post_prefix_kf_denominator':npost,'selections':selections,
        'scene_support':gate,'rgb_scene_support_pass':all(gate[g][str(f)]['scene_support_pass'] for g in gate for f in (0,1)),
        'pair_manifest':digest(pair_path),'profiles':digest(p),'mask_manifest':digest(mp),'mask_count':len(mask_rows),
        'profile_count':len(profile_rows),'candidate_count_per_supported_kf':356,
        'selection_complete':all_rows_complete})
    return json.loads((root/'selected_parameters.json').read_text())


def freeze_scene(scene, code_hashes, protocol_hash):
    root=PROFILE_ROOT/scene;sel=json.loads((root/'selected_parameters.json').read_text())
    if sel.get('selection_source')!='RGB_fit_only': raise RuntimeError('selection provenance mismatch')
    if sel.get('reference_accessed') is not False: raise RuntimeError('reference data entered RGB selection')
    inputs=[digest(root/'profiles.csv'),digest(root/'selected_parameters.json'),
            digest(root/'mask_manifest.csv'),digest(root/'pair_manifest.csv'),
            digest(OUT/'preflight.json'),digest(OUT/'registration.json'),
            digest(PROFILE_ROOT/'registration.json')]
    return seal_selection(root/'selection_seal.json',sel,inputs,code_hashes,protocol_hash)
