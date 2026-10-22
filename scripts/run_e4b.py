"""Frozen-input E4b reproduction and evaluation-only diagnostic replay."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/E4b_reference_plane_audit'
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'scripts'),str(OUT/'deps'),
               str(ROOT/'thirdparty/Splatt3R-SLAM/splatt3r_core')]
import cv2
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from prepare_e2b_run import digest, save_json
from e0b_audit import sim3_matrix, transform
from e1_taxonomy import camera_geometry, resize_depth
from e2_signals import causal_pair, prepare_observation, image_rgb
from e2b_transfer import repeat_score
from e3c_matched import geometry_pair, matched_scores
from e3b_provisional import ProvisionalAdmission, REJECT
from e4b_audit import (COHORTS,FUNNELS,cohort_codes,funnel,aggregate_oracles,prepare_gt,
    reference_quality,pair_details,oracle_pair,gt_front,change_metrics)
from run_e3 import feature_guard
from utils.geometry import build_covariance

CFG = ROOT/'configs/e4b_reference_plane_audit.json'
REG = ROOT/'configs/e4b_protocol_registration.json'
METHOD_KEYS = dict(B6_depth='D_native',D_maskmedian='D_maskmedian',D_shared='D_shared',P2_plane='P_shared')
ARMS = ['factual_common','GT_plane_fixed_veto','GT_plane_recomputed_veto']
CODE = ['scripts/run_e4b.py','scripts/report_e4b.py','src/e4b_audit.py','tests/test_e4b.py',
        'src/e3c_matched.py','src/e2_signals.py','src/e2b_transfer.py','src/e3b_provisional.py',
        'src/e1_taxonomy.py','src/e0b_audit.py','scripts/prepare_e2b_run.py','scripts/run_e3.py',
        'thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py']


def config():
    spec=json.loads(CFG.read_text());reg=json.loads(REG.read_text())
    assert spec==reg['specification'] and digest(CFG)['sha256']==reg['spec_sha256']
    return spec,reg


def verify(entry):
    assert digest(ROOT/entry['path'])==entry,entry['path']


def find_digests(value):
    if isinstance(value,dict):
        if {'path','bytes','sha256'}<=value.keys():yield {k:value[k] for k in ['path','bytes','sha256']}
        else:
            for v in value.values():yield from find_digests(v)
    elif isinstance(value,list):
        for v in value:yield from find_digests(v)


def initialize():
    spec,reg=config();OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'execution_seal.json').exists():raise RuntimeError('Existing execution seal preserved')
    verify(reg['protocol'])
    inputs={}
    def add(path):
        entry=digest(path);inputs[entry['path']]=entry
    for entry in reg['source_manifest_anchors']:
        verify(entry);add(ROOT/entry['path'])
        if Path(entry['path']).suffix=='.json':
            for nested in find_digests(json.loads((ROOT/entry['path']).read_text())):
                verify(nested);inputs[nested['path']]=nested
    for scene,paths in reg['scene_sources'].items():
        meta=json.loads((ROOT/paths['scores']/'score_metadata.json').read_text())
        for path in [ROOT/paths['baseline']/'map'/f'{scene}_kfgauss.pt',
                     ROOT/paths['baseline']/'audit/events.jsonl',
                     ROOT/paths['scores']/'features.npz',ROOT/paths['scores']/'score_metadata.json',
                     ROOT/paths['labels']/'labels.npz',ROOT/paths['dataset']/'traj.txt',
                     ROOT/paths['dataset']/'../cam_params.json']:
            add(path)
        for row in meta['lineage']:
            add(ROOT/paths['baseline']/'exports/raw_pairs'/f"{row['event_id']}.pt")
            add(ROOT/paths['baseline']/'audit'/row['decision_file'])
            add(ROOT/paths['dataset']/'results'/f"depth{row['original_frame']:06d}.png")
        for method in spec['methods']:add(ROOT/paths['replay']/method/'decisions.npz')
    add(CFG);add(REG)
    save_json(OUT/'input_manifest.json',dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
        inputs=list(inputs.values()),source_read_only=True))
    env=dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,torch=torch.__version__,
        pyarrow=pa.__version__,cv2=cv2.__version__,threads=2,device='CPU',
        dependency_policy='pyarrow 19.0.1 installed without deps under E4b/deps; existing venv unchanged')
    save_json(OUT/'environment.json',env)
    entries=[digest(ROOT/p) for p in CODE]
    for p in CODE:
        dest=OUT/'sealed_code'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dest)
    seal=dict(sealed_at_utc=datetime.now(timezone.utc).isoformat(),base_git_commit=subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),code=entries,configuration=digest(CFG),
        registration=digest(REG),input_manifest=digest(OUT/'input_manifest.json'),environment=digest(OUT/'environment.json'),
        analysis_executed_before_seal=False,tests=digest(OUT/'logs/tests.log'))
    save_json(OUT/'execution_seal.json',seal)
    save_json(ROOT/'configs/e4b_execution_seal.json',seal)
    print(f'Initialized: {len(inputs)} hashed inputs; source results preserved',flush=True)


def checked():
    spec,reg=config();seal=json.loads((OUT/'execution_seal.json').read_text())
    for entry in seal['code']+[seal['configuration'],seal['registration'],seal['input_manifest']]:verify(entry)
    return spec,reg


def load_geometry(scene,reg):
    paths=reg['scene_sources'][scene];run=ROOT/paths['baseline'];score=ROOT/paths['scores']
    meta=json.loads((score/'score_metadata.json').read_text())
    f=dict(np.load(score/'features.npz'));active=f['active'];n=meta['raw_per_kf'];nk=meta['keyframes']
    dump=torch.load(run/'map'/f'{scene}_kfgauss.pt',map_location='cpu',weights_only=True)
    base=json.loads((ROOT/'configs/e2_discriminability.json').read_text())
    obs=[];local=[];snapshots=[]
    for i,kf in enumerate(dump['keyframes']):
        path=run/'exports/raw_pairs'/f"{meta['lineage'][i]['event_id']}.pt"
        raw=torch.load(path,map_location='cpu',weights_only=True)
        assert raw['source_image_ids']==meta['lineage'][i]['source_images']
        assert torch.equal(raw['outputs'][0]['means'].reshape(-1,3),kf['means'])
        ob=prepare_observation(raw['outputs'][0],image_rgb(kf),base);obs.append(ob)
        q=kf['rotations']/kf['rotations'].norm(dim=-1,keepdim=True).clamp_min(1e-6)
        local.append(dict(means=kf['means'].numpy().astype(float),cov=build_covariance(kf['scales'],q).numpy()))
        snap=torch.load(run/'audit'/meta['lineage'][i]['decision_file'],map_location='cpu',weights_only=True)
        assert snap['pose_revision']==meta['lineage'][i]['pose_revision']
        for j,m in enumerate(snap['metadata']):
            assert m['candidate_event']==meta['lineage'][j]['event_id']
            assert m['candidate_sources']==meta['lineage'][j]['source_images']
        snapshots.append(dict(frame=snap['input_frame'],revision=snap['pose_revision'],
            sequence=meta['lineage'][i]['decision_sequence'],poses=[sim3_matrix(p.numpy()) for p in snap['poses']]))
        del raw
    del dump
    assert len(local)==nk and len(active)==nk*n
    return paths,meta,f,base,local,obs,snapshots


def eligible(meta,i,j,snap):
    if i==j:return False
    a,b=meta['lineage'][i],meta['lineage'][j]
    assert max(b['source_images'])<=snap['frame']
    return causal_pair(a['source_images'],b['source_images'],snap['sequence'],b['raw_sequence'])


def policies(active,n,thresholds,names):
    anchors=np.repeat(np.arange(len(active)//n),n)
    return {m:ProvisionalAdmission(dict(kind='review'),active,anchors,thresholds[m]) for m in names}


def reproduce(scene):
    started=time.monotonic();spec,reg=checked();dest=OUT/'reproduction'/scene
    if (dest/'check.json').exists():raise RuntimeError('Completed reproduction preserved')
    dest.mkdir(parents=True,exist_ok=True)
    thresholds=json.loads((ROOT/spec['source_seal']).read_text())['thresholds']
    rows=[]
    with feature_guard():
        paths,meta,f,base,local,obs,snaps=load_geometry(scene,reg)
        n=meta['raw_per_kf'];nk=meta['keyframes'];ps=policies(f['active'],n,thresholds,spec['methods'])
        for s,snap in enumerate(snaps):
            vals={m:np.full((s+1,n),np.nan,np.float32) for m in METHOD_KEYS}
            for i in range(s+1):
                ds=[];planes=[]
                for j in range(s+1):
                    if not eligible(meta,i,j,snap):continue
                    d,p,_=geometry_pair(local[i]['means'],local[i]['cov'],obs[i],obs[j],snap['poses'][i],snap['poses'][j],base)
                    ds.append(d);planes.append(p)
                scores,_,_,_=matched_scores(ds,planes,n)
                for m,key in METHOD_KEYS.items():vals[m][i]=scores[key]
            old=np.load(ROOT/paths['scores']/'history'/f'snapshot{s:04d}.npz')
            for m,key in METHOD_KEYS.items():
                np.testing.assert_array_equal(vals[m],old[key],err_msg=f'{scene}/{s}/{m} scores')
                ps[m].advance(s,snap['frame'],snap['revision'],vals[m].reshape(-1))
            np.savez_compressed(dest/f'snapshot{s:04d}.npz',**vals)
            rows.append(dict(snapshot=s,input_frame=snap['frame'],pose_revision=snap['revision'],exact_scores=True))
            print(f'{scene}: reproduce {s+1}/{nk} exact',flush=True)
        for m,p in ps.items():
            old=np.load(ROOT/paths['replay']/m/'decisions.npz')
            for key,array in p.arrays().items():np.testing.assert_array_equal(array,old[key],err_msg=f'{scene}/{m}/{key}')
            np.testing.assert_array_equal(f['active']&(p.state!=REJECT),old['natural_membership'])
    save_json(dest/'check.json',dict(status='PASS',scene=scene,snapshots=rows,natural_membership_exact=True,
        all_policy_fields_exact=True,gt_read_during_reproduction=False,cpu_seconds=time.monotonic()-started,
        artifacts=[digest(p) for p in sorted(dest.glob('snapshot*.npz'))]))


class TableWriter:
    def __init__(self,path):self.path=path;self.writer=None;self.rows=0
    def write(self,columns):
        if not columns or not len(next(iter(columns.values()))):return
        columns={k:np.ascontiguousarray(v) for k,v in columns.items()}
        table=pa.table(columns)
        if self.writer is None:self.writer=pq.ParquetWriter(self.path,table.schema,compression='zstd',compression_level=3)
        self.writer.write_table(table,row_group_size=65536);self.rows+=len(table)
    def close(self):
        if self.writer:self.writer.close()


def distribution(values):
    a=np.asarray(values);a=a[np.isfinite(a)]
    return dict(n=len(a),median=float(np.median(a)) if len(a) else None,
        p05=float(np.percentile(a,5)) if len(a) else None,p95=float(np.percentile(a,95)) if len(a) else None)


def examples(scene,active,labels,codes,meta,dest):
    rng=np.random.default_rng(0);rows=[]
    for code,name in enumerate(COHORTS):
        ids=np.flatnonzero(active&(labels==3)&(codes==code))
        chosen=np.sort(rng.choice(ids,min(8,len(ids)),replace=False))
        rows += [dict(candidate_id=int(k),cohort=name,label=3) for k in chosen]
    ids=np.flatnonzero(active&np.isin(labels,[1,2]))
    chosen=np.sort(rng.choice(ids,min(8,len(ids)),replace=False))
    rows += [dict(candidate_id=int(k),cohort='normal',label=int(labels[k])) for k in chosen]
    n=meta['raw_per_kf']
    for row in rows:
        i,pixel=divmod(row['candidate_id'],n)
        row.update(scene=scene,anchor_kf=i,pixel=pixel,event_id=meta['lineage'][i]['event_id'],branch=0)
    save_json(dest/'example_ids.json',rows)
    return rows


def audit(scene):
    started=time.monotonic();spec,reg=checked()
    for name in [spec['primary_scene'],*spec['secondary_scenes']]:
        assert json.loads((OUT/'reproduction'/name/'check.json').read_text())['status']=='PASS'
    dest=OUT/scene;dest.mkdir(parents=True,exist_ok=True)
    if (dest/'summary.json').exists():raise RuntimeError('Completed diagnostic preserved')
    paths,meta,f,base,local,obs,snaps=load_geometry(scene,reg)
    n=meta['raw_per_kf'];nk=meta['keyframes'];N=n*nk;active=f['active'];anchors=f['anchor_kf']
    labels=dict(np.load(ROOT/paths['labels']/'labels.npz'));y=labels['creation']
    decisions={m:dict(np.load(ROOT/paths['replay']/m/'decisions.npz')) for m in spec['methods']}
    b6=decisions['B6_depth']['state']==REJECT;p2=decisions['P2_plane']['state']==REJECT
    codes=cohort_codes(b6,p2);primary=active&(y==3)&(codes==1)
    birth=np.array([meta['lineage'][int(i)]['input_frame'] for i in anchors],np.int32)
    a=decisions['B6_depth']['first_reject'];b=decisions['P2_plane']['first_reject']
    anchor_frame=np.minimum(np.where(a<0,2**30,a),np.where(b<0,2**30,b))
    anchor_frame=np.where(anchor_frame==2**30,np.where(f['first_repeat']>=0,f['first_repeat'],birth),anchor_frame)
    np.savez_compressed(dest/'cohorts.npz',active=active,labels=y,cohort=codes,anchor_frame=anchor_frame)
    selected=examples(scene,active,y,codes,meta,dest)
    selected_ids=np.array([r['candidate_id'] for r in selected],np.int64)
    example_dir=dest/'examples';example_dir.mkdir(exist_ok=True)
    timelines={int(k):[] for k in selected_ids};payloads={};ranks={}
    lm=json.loads((ROOT/paths['labels']/'label_manifest.json').read_text());global_scale=lm['global_scale']
    dataset=ROOT/paths['dataset'];camera=json.loads((dataset.parent/'cam_params.json').read_text())['camera']
    K=camera_geometry(camera)[0];gtposes=np.loadtxt(dataset/'traj.txt').reshape(-1,4,4)
    lspec=json.loads((ROOT/'configs/e1_taxonomy.json').read_text());gt=[]
    for j in range(nk):
        path=dataset/'results'/f"depth{meta['lineage'][j]['original_frame']:06d}.png"
        depth=resize_depth(cv2.imread(str(path),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera['scale'],camera)
        gt.append(prepare_gt(obs[j],depth,K,lspec,base))
    thresholds=json.loads((ROOT/spec['source_seal']).read_text())['thresholds']
    factual=policies(active,n,thresholds,spec['methods'])
    op=policies(active,n,{name:thresholds['P2_plane'] for name in ARMS},ARMS)
    cp=TableWriter(dest/'candidate_audit.parquet');vp=TableWriter(dest/'view_audit.parquet');pp=TableWriter(dest/'patch_audit.parquet')
    # Aggregate over candidates without treating repeated records as independent candidates.
    ever={key:np.zeros(N,bool) for key in ['GT_auditable','reference_wrong','coherent_wrong','shared_wrong_support','shared_wrong_coherent','pose_front_changed']}
    first_error=np.full(N,2**30,np.int32);anchor_funnel=np.full(N,255,np.uint8)
    classcode=np.where(y==3,2,np.where(np.isin(y,[1,2]),1,0));groups=classcode*4+codes
    pair_counts={k:np.zeros(12,np.int64) for k in ['depth_eligible','shared_eligible','GT_auditable','reference_wrong','coherent_wrong','shared_wrong_support','correspondence_ambiguous','GT_anchor_front_changed']}
    unique_counts={k:0 for k in ['referenced','shared_referenced','GT_auditable','reference_wrong','coherent_wrong','all_points_wrong']}
    patch_group_counts={k:np.zeros(12,np.int64) for k in ['shared_referenced','GT_auditable','reference_wrong','coherent_wrong']}
    anchor_score={m:np.full(N,np.nan,np.float32) for m in spec['methods']}
    patch_sens={f'{a}_{b}':0 for a in [2,5,10] for b in [5,10,20]}
    reference_status=np.zeros(5,np.int64);pair_rows=[];snapshot_rows=[]
    for s,snap in enumerate(snaps):
        count=s+1;end=count*n
        scales=[global_scale*np.cbrt(np.linalg.det(p[:3,:3])) for p in snap['poses']]
        qualities=[reference_quality(obs[j],gt[j],scales[j],base) for j in range(count)]
        hits=[np.zeros(n,np.int32) for _ in range(count)]
        shits=[np.zeros(n,np.int32) for _ in range(count)]
        bits=[np.zeros(n,np.uint16) for _ in range(count)]
        vals={m:np.full((count,n),np.nan,np.float32) for m in spec['methods']}
        orvals={m:np.full((count,n),np.nan,np.float32) for m in ARMS}
        candrows=[]
        for i in range(count):
            ids_all=np.arange(i*n,(i+1)*n);act=active[ids_all]
            ds=[];planes=[];gplanes=[];causal_count=0
            native_count=np.zeros(n,np.uint16)
            for j in range(count):
                ok=eligible(meta,i,j,snap)
                pair_rows.append(dict(snapshot=s,candidate_kf=i,evidence_kf=j,causal_eligible=ok,
                    shared_source_images=sorted(set(meta['lineage'][i]['source_images'])&set(meta['lineage'][j]['source_images']))))
                if not ok:continue
                causal_count+=1
                details,p,cov=pair_details(local[i]['means'],local[i]['cov'],obs[i],obs[j],snap['poses'][i],snap['poses'][j],base)
                ids=details['evidence_pixel'];d=details['depth_score'];plane=details['plane_score']
                ds.append(d);planes.append(plane);native_count+=np.isfinite(d)
                changed,use=oracle_pair(p,cov,d,plane,ids,obs[j],gt[j],scales[j]);gplanes.append(changed)
                q=qualities[j];shared=np.isfinite(d)&np.isfinite(plane);auditable=shared&gt[j]['reliable'][ids]
                wrong=auditable&q['wrong_5_10'][ids]
                coherent=auditable&(q['coherent_front'][ids]|q['coherent_behind'][ids])
                front,correspondence=gt_front(p,cov,gt[j],scales[j],ids)
                gi=gtposes[meta['lineage'][i]['original_frame']].copy();gj=gtposes[meta['lineage'][j]['original_frame']].copy()
                gi[:3,:3]*=scales[i];gj[:3,:3]*=scales[j]
                gp=transform(local[i]['means'],np.linalg.inv(gj)@gi)
                gc=(np.linalg.inv(gj)@gi)[:3,:3]@local[i]['cov']@(np.linalg.inv(gj)@gi)[:3,:3].T
                front_anchor,correspondence_anchor=gt_front(gp,gc,gt[j],scales[j],ids)
                pose_changed=shared&correspondence&correspondence_anchor&(front!=front_anchor)
                strict=wrong&(plane==0)&front&(y[ids_all]==3)&~p2[ids_all]
                for key,mask in [('GT_auditable',auditable),('reference_wrong',wrong),('coherent_wrong',coherent),
                    ('shared_wrong_support',strict),('shared_wrong_coherent',strict&coherent),('pose_front_changed',pose_changed)]:
                    ever[key][ids_all]|=act&mask
                update=act&wrong;first_error[ids_all[update]]=np.minimum(first_error[ids_all[update]],snap['frame'])
                masks=dict(depth_eligible=np.isfinite(d),shared_eligible=shared,GT_auditable=auditable,
                    reference_wrong=wrong,coherent_wrong=coherent,shared_wrong_support=strict,
                    correspondence_ambiguous=shared&~correspondence,GT_anchor_front_changed=pose_changed)
                for key,mask in masks.items():pair_counts[key]+=np.bincount(groups[ids_all[act&mask]],minlength=12)
                rayact=act&details['ray_match']
                hits[j]+=np.bincount(ids[rayact],minlength=n).astype(np.int32)
                sa=act&shared;shits[j]+=np.bincount(ids[sa],minlength=n).astype(np.int32)
                np.bitwise_or.at(bits[j],ids[sa],np.left_shift(np.uint16(1),groups[ids_all[sa]].astype(np.uint16)))
                cols=dict(candidate_id=ids_all[act].astype(np.int32),snapshot=np.full(act.sum(),s,np.int16),
                    input_frame=np.full(act.sum(),snap['frame'],np.int32),pose_revision=np.full(act.sum(),snap['revision'],np.int32),
                    candidate_kf=np.full(act.sum(),i,np.int16),evidence_kf=np.full(act.sum(),j,np.int16),
                    label=y[ids_all[act]],cohort=codes[ids_all[act]],causal_sources=np.ones(act.sum(),bool))
                cols.update({key:value[act] for key,value in details.items()})
                cols.update(GT_status=gt[j]['status'][ids[act]],GT_auditable=auditable[act],reference_wrong=wrong[act],
                    coherent_wrong=coherent[act],shared_wrong_support=strict[act],GT_front=front[act],
                    GT_correspondence=correspondence[act],GT_anchor_front=front_anchor[act],
                    GT_anchor_correspondence=correspondence_anchor[act],pose_front_changed=pose_changed[act],
                    oracle_plane_score=changed[act],oracle_replaced=use[act],
                    plane_offset_m=q['plane_offset_m'][ids[act]],plane_angle_degrees=q['plane_angle_degrees'][ids[act]])
                vp.write(cols)
                for cid in selected_ids[(selected_ids//n==i)&(anchor_frame[selected_ids]==snap['frame'])]:
                    k=int(cid%n);rank=(0 if shared[k] else 1 if np.isfinite(d[k]) else 2 if details['ray_match'][k] else 3,j)
                    if int(cid) in ranks and ranks[int(cid)]<=rank:continue
                    ranks[int(cid)]=rank
                    pixel=int(ids[k]);h,w=obs[j]['hw'];yy,xx=divmod(pixel,w)
                    y0,y1=max(0,yy-2),min(h,yy+3);x0,x1=max(0,xx-2),min(w,xx+3)
                    payloads[int(cid)]=dict(source_rgb=obs[i]['image'],evidence_rgb=obs[j]['image'],
                        predicted_depth=obs[j]['points'][:,2].reshape(h,w)*scales[j],GT_depth=gt[j]['depth'],
                        evidence_kf=j,evidence_pixel=pixel,source_pixel=k,anchor_frame=snap['frame'],snapshot=s,
                        candidate_m=p[k]*scales[j],predicted_mean_m=obs[j]['mean'][pixel]*scales[j],
                        predicted_normal=obs[j]['normal'][pixel],GT_mean_m=gt[j]['mean'][pixel],GT_normal=gt[j]['normal'][pixel],
                        predicted_patch_m=obs[j]['points'].reshape(h,w,3)[y0:y1,x0:x1]*scales[j],
                        GT_patch_m=gt[j]['xyz'][y0:y1,x0:x1],GT_reliable=gt[j]['reliable'][pixel],
                        plane_score=plane[k],depth_score=d[k],shared_wrong_support=strict[k],
                        plane_offset_m=q['plane_offset_m'][pixel],plane_angle_degrees=q['plane_angle_degrees'][pixel])
            values,shared_count,support,_=matched_scores(ds,planes,n)
            for m,key in METHOD_KEYS.items():vals[m][i]=values[key]
            oracle_values=aggregate_oracles(ds,planes,gplanes,n)
            for m,v in zip(ARMS,oracle_values):orvals[m][i]=v
            np.testing.assert_array_equal(orvals['factual_common'][i],vals['P2_plane'][i])
            fu=funnel(native_count,shared_count,support,vals['P2_plane'][i],thresholds['P2_plane'],causal_count)
            at=act&(anchor_frame[ids_all]==snap['frame']);anchor_funnel[ids_all[at]]=fu[at]
            for m in spec['methods']:anchor_score[m][ids_all[at]]=vals[m][i][at]
            shared_median=np.full(n,np.nan,np.float32);shared_second=shared_median.copy();plane_second=shared_median.copy()
            if ds:
                mask=np.isfinite(ds)&np.isfinite(planes)
                with np.errstate(invalid='ignore'):
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore',RuntimeWarning)
                        shared_median=np.nanmedian(np.where(mask,ds,np.nan),axis=0).astype(np.float32)
                shared_second=repeat_score(list(np.where(mask,ds,np.nan)),n,veto=False)[0]
                plane_second=repeat_score(list(np.where(mask,planes,np.nan)),n,veto=False)[0]
            rows=dict(candidate_id=ids_all[act].astype(np.int32),snapshot=np.full(act.sum(),s,np.int16),
                input_frame=np.full(act.sum(),snap['frame'],np.int32),pose_revision=np.full(act.sum(),snap['revision'],np.int32),
                label=y[ids_all[act]],gt_anchor_label=labels['gt_anchor'][ids_all[act]],
                consensus_label=labels['cross_pose_consensus'][ids_all[act]],cohort=codes[ids_all[act]],
                at_anchor=at[act],funnel=fu[act],causal_count=np.full(act.sum(),causal_count,np.uint16),
                native_depth_count=native_count[act],shared_count=shared_count[act],plane_zero_veto=support[act],
                shared_median=shared_median[act],shared_second_largest=shared_second[act],plane_second_largest=plane_second[act])
            for m in spec['methods']:rows[m+'_score']=vals[m][i][act]
            for m in ARMS:rows[m+'_score']=orvals[m][i][act]
            rows['threshold_margin']=vals['P2_plane'][i][act]-thresholds['P2_plane']
            candrows.append(rows)
        # Compare this independent audit pass with exact GT-free reproduction.
        expected=np.load(OUT/'reproduction'/scene/f'snapshot{s:04d}.npz')
        for m in spec['methods']:
            np.testing.assert_array_equal(vals[m],expected[m])
            factual[m].advance(s,snap['frame'],snap['revision'],vals[m].reshape(-1))
        for m in ARMS:op[m].advance(s,snap['frame'],snap['revision'],orvals[m].reshape(-1))
        for rows in candrows:
            cid=rows['candidate_id']
            for m in spec['methods']:
                rows[m+'_state']=factual[m].state[cid];rows[m+'_first_reject']=factual[m].first_reject[cid]
            cp.write(rows)
            exmask=np.isin(cid,selected_ids)
            for pos in np.flatnonzero(exmask):
                k=int(cid[pos]);timelines[k].append({name:value[pos] for name,value in rows.items()})
        for j,q in enumerate(qualities):
            keep=hits[j]>0;shared=shits[j]>0;aud=shared&gt[j]['reliable'];wrong=aud&q['wrong_5_10']
            coh=aud&(q['coherent_front']|q['coherent_behind'])
            unique_counts['referenced']+=int(keep.sum());unique_counts['shared_referenced']+=int(shared.sum())
            unique_counts['GT_auditable']+=int(aud.sum());unique_counts['reference_wrong']+=int(wrong.sum())
            unique_counts['coherent_wrong']+=int(coh.sum());unique_counts['all_points_wrong']+=int((aud&q['all_points_wrong']).sum())
            reference_status+=np.bincount(gt[j]['status'][shared],minlength=5)
            for key,mask in [('shared_referenced',shared),('GT_auditable',aud),('reference_wrong',wrong),('coherent_wrong',coh)]:
                for group in range(12):patch_group_counts[key][group]+=int((mask&((bits[j]&(1<<group))!=0)).sum())
            for key in patch_sens:patch_sens[key]+=int((aud&q['wrong_'+key]).sum())
            cols=dict(snapshot=np.full(keep.sum(),s,np.int16),evidence_kf=np.full(keep.sum(),j,np.int16),
                pixel=np.flatnonzero(keep).astype(np.int32),input_frame=np.full(keep.sum(),snap['frame'],np.int32),
                metric_scale=np.full(keep.sum(),scales[j],np.float64),references=hits[j][keep],
                shared_references=shits[j][keep],cohort_group_bits=bits[j][keep])
            cols.update({k:v[keep] for k,v in q.items()});pp.write(cols)
        snapshot_rows.append(dict(snapshot=s,input_frame=snap['frame'],pose_revision=snap['revision'],
            factual_rejected=int((op['factual_common'].state==REJECT).sum()),
            fixed_veto_rejected=int((op['GT_plane_fixed_veto'].state==REJECT).sum()),
            recomputed_veto_rejected=int((op['GT_plane_recomputed_veto'].state==REJECT).sum())))
        print(f'{scene}: audit {s+1}/{nk}; view rows={vp.rows:,}; oracle rejects={snapshot_rows[-1]["recomputed_veto_rejected"]:,}',flush=True)
    cp.close();vp.close();pp.close()
    assert np.all(anchor_funnel[active]!=255)
    for m in spec['methods']:
        for key,value in factual[m].arrays().items():np.testing.assert_array_equal(value,decisions[m][key])
    np.testing.assert_array_equal(op['factual_common'].state,decisions['P2_plane']['state'])
    oracle={}
    factual_reject=op['factual_common'].state==REJECT
    for m,p in op.items():
        rej=p.state==REJECT
        entry=change_metrics(factual_reject,rej,y,active,primary)
        new_bad=active&(y==3)&~factual_reject&rej
        contribution=new_bad&(first_error<=p.first_reject)
        entry['reference_error_and_same_candidate_transition']=int(contribution.sum())
        entry['shared_wrong_support_and_transition']=int((new_bad&ever['shared_wrong_support']).sum())
        entry['GT_auditable_candidates']=int((active&ever['GT_auditable']).sum())
        entry['GT_candidate_coverage']=float((active&ever['GT_auditable']).sum()/active.sum())
        entry['GT_pair_coverage']=float(pair_counts['GT_auditable'].sum()/pair_counts['shared_eligible'].sum()) if pair_counts['shared_eligible'].sum() else None
        entry['label_sensitivity']={label:change_metrics(factual_reject,rej,labels[label],active,
            active&(labels[label]==3)&(codes==1)) for label in ['gt_anchor','cross_pose_consensus']}
        oracle[m]=entry
        np.savez_compressed(dest/f'{m}_decisions.npz',**p.arrays())
    save_json(dest/'oracle_summary.json',oracle)
    cohort_summary={}
    for cl,clname in [(0,'unknown'),(1,'normal'),(2,'bad')]:
        for co,coname in enumerate(COHORTS):
            mask=active&(classcode==cl)&(codes==co);group=cl*4+co
            entry=dict(candidates=int(mask.sum()),anchor_funnel={name:int((mask&(anchor_funnel==k)).sum()) for k,name in enumerate(FUNNELS)},
                candidate_ever={k:int((mask&v).sum()) for k,v in ever.items()},
                view_records={k:int(v[group]) for k,v in pair_counts.items()},
                unique_snapshot_patches={k:int(v[group]) for k,v in patch_group_counts.items()},
                anchor_method_above_threshold={m:int((mask&np.isfinite(anchor_score[m])&(anchor_score[m]>thresholds[m])).sum()) for m in spec['methods']})
            cohort_summary[clname+'__'+coname]=entry
    for row in selected:
        cid=row['candidate_id'];i,pixel=divmod(cid,n)
        payload=payloads.get(cid,dict(source_rgb=obs[i]['image'],source_pixel=pixel,evidence_kf=-1,
            anchor_frame=int(anchor_frame[cid]),GT_reliable=False))
        np.savez_compressed(example_dir/f'{cid}_geometry.npz',**payload)
        timeline=timelines[cid]
        np.savez_compressed(example_dir/f'{cid}_timeline.npz',**{key:np.array([r[key] for r in timeline]) for key in timeline[0]})
    np.savez_compressed(dest/'candidate_flags.npz',**ever,first_reference_error=first_error,anchor_funnel=anchor_funnel)
    (dest/'pair_audit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in pair_rows))
    result=dict(scene=scene,status='COMPLETE',active=int(active.sum()),bad=int((active&(y==3)).sum()),
        normal=int((active&np.isin(y,[1,2])).sum()),unknown=int((active&(y==0)).sum()),cohorts=cohort_summary,
        unique_snapshot_patches=unique_counts,GT_reference_status_counts=dict(zip(['invalid_GT','GT_edge','too_few_common','nonplanar_or_border','reliable'],reference_status.tolist())),
        reference_error_sensitivity=patch_sens,oracle=oracle,snapshots=snapshot_rows,
        rows=dict(candidate=cp.rows,view=vp.rows,patch=pp.rows),examples=len(selected),cpu_seconds=time.monotonic()-started,
        factual_exact=True,source_results_preserved=True,scope='retrospective diagnostic; no efficacy GO or Chamfer inference')
    save_json(dest/'summary.json',result)
    save_json(dest/'manifest.json',dict(code_seal=digest(OUT/'execution_seal.json'),
        artifacts=[digest(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='manifest.json']))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['initialize','reproduce','audit'])
    parser.add_argument('scene',nargs='?',choices=['office1','office0','room0','room1','room2'])
    args=parser.parse_args();torch.set_num_threads(2);cv2.setNumThreads(2)
    if args.stage=='initialize':initialize()
    elif args.stage=='reproduce':reproduce(args.scene)
    else:audit(args.scene)


if __name__=='__main__':main()
