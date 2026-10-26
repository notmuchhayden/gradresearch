#!/usr/bin/env python3
"""Register and audit HKairport01 references without changing the saved mapper."""
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
import json
import shutil
import sys
import csv
import io
import cv2
import numpy as np
import torch
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from prepare_e2b_run import digest,save_json
from a0b_geometry import load_calibrations,camera_model,resize_contract,processed_rgb,lidar_depth,sampson_pixels,source_rays
from pointmap_contract import fit_prefix_gauge,sim3_from_xyzw,sim3_parts,transform_points,array_hash

SPEC=ROOT/'configs/a0b_hkairport01_factorial.json'


def stats(x):
    x=np.asarray(x);x=x[np.isfinite(x)]
    return dict(n=len(x),mean=float(x.mean()),median=float(np.median(x)),p95=float(np.percentile(x,95)),max=float(x.max())) if len(x) else dict(n=0,mean=None,median=None,p95=None,max=None)


def load_context():
    spec=json.loads(SPEC.read_text());out=ROOT/spec['output'];run=ROOT/spec['baseline']
    frames=json.loads((ROOT/spec['split']).read_text())['scene_splits']['HKairport01']['frames']
    mapping=[f for f in frames if f['role']=='mapping']
    info=json.loads((ROOT/spec['reference']/'sampleinfos_interpolated.json').read_text())
    lookup={x['OriginalImageName']:x for x in info}
    poses={f['grid_index']:np.array(lookup[Path(f['rgb_member']).name]['T4x4'],float) for f in frames}
    return spec,out,run,frames,mapping,lookup,poses


def main():
    torch.set_num_threads(2);cv2.setNumThreads(2)
    spec,out,run,frames,mapping,lookup,poses=load_context()
    out.mkdir(parents=True,exist_ok=False)
    save_json(out/'registration.json',dict(spec=digest(SPEC),registered_at=datetime.now().astimezone().isoformat(),
        phase='before reference rasterization, local residuals and factorial outcomes',prior_results_known=['E4e baseline','office2 A0']))
    dest=out/'preflight';dest.mkdir();(dest/'references').mkdir();(dest/'heldout_rgb').mkdir()
    source=[SPEC,Path(__file__),ROOT/'src/a0b_geometry.py',ROOT/'src/pointmap_contract.py',ROOT/'tests/test_a0b_geometry.py']
    for p in source:
        q=dest/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    save_json(dest/'source_manifest.json',[digest(p) for p in source])
    baseline=json.loads((run/'run_manifest.json').read_text());assert baseline['return_code']==0 and not baseline['gt_pose_or_lidar_used_for_mapping']
    # Check every saved mapper input against its original manifest.
    for row in baseline['inputs']:assert digest(ROOT/row['path'])==row,row['path']
    dump=torch.load(run/'map/HKairport01_kfgauss.pt',map_location='cpu',weights_only=True)
    events=[json.loads(r) for r in (run/'audit/events.jsonl').read_text().splitlines()]
    final_event=[e for e in events if e['kind']=='snapshot' and e['stage']=='final'][-1]
    snapshot=torch.load(run/'audit'/final_event['file'],map_location='cpu',weights_only=True)
    lineage=[];inputs=[SPEC,ROOT/spec['split'],ROOT/spec['calibration_file'],ROOT/spec['reference']/'sampleinfos_interpolated.json',
        run/'run_manifest.json',run/'map/HKairport01_kfgauss.pt',run/'map/HKairport01_frames.txt',run/'audit/events.jsonl',run/'audit'/final_event['file']]
    for k in dump['keyframes']:
        match=[i for i,m in enumerate(snapshot['metadata']) if m['frame_id']==k['frame_id'] and m['kf_idx']==k['kf_idx']]
        assert len(match)==1
        i=match[0];meta=snapshot['metadata'][i]
        assert torch.equal(k['T_WC'].reshape(8),snapshot['poses'][i].reshape(8))
        rp=run/'exports/raw_pairs'/(meta['candidate_event']+'.pt');raw=torch.load(rp,map_location='cpu',weights_only=True)
        assert raw['coordinate_frame']=='first_source_camera' and raw['source_pair_ids'][0][0]==k['frame_id']
        for key in ['means','scales','rotations','sh','opacities','conf']:
            assert torch.equal(k[key],raw['outputs'][0][key].reshape_as(k[key])),key
        assert torch.equal(raw['outputs'][0]['means'],raw['outputs'][0]['pts3d'])
        lineage.append(dict(kf_idx=k['kf_idx'],mapping_index=k['frame_id'],grid_index=mapping[k['frame_id']]['grid_index'],
            event=meta['candidate_event'],raw_file=digest(rp),pose_hash=array_hash(k['T_WC'].numpy())))
        inputs.append(rp)
    trajectory=np.loadtxt(run/'map/HKairport01_frames.txt')
    times=np.array([f['rgb_timestamp'] for f in mapping])
    matches=np.argmin(np.abs(trajectory[:,0,None]-times[None,:]),axis=1)
    assert len(np.unique(matches))==len(matches) and np.max(np.abs(trajectory[:,0]-times[matches]))<1e-5
    grid=np.array([mapping[i]['grid_index'] for i in matches]);gt=np.array([poses[g][:3,3] for g in grid])
    gauge,cal_ids=fit_prefix_gauge(trajectory[:,1:4],gt,grid,spec['calibration_prefix_grid_stop_exclusive'])
    assert len(cal_ids)>=spec['gates']['min_prefix_poses']
    C=sim3_parts(gauge)[0]*float(dump['keyframes'][0]['T_WC'].reshape(8)[7])
    errors=np.linalg.norm(transform_points(trajectory[:,1:4],gauge)-gt,axis=1)
    aligned_rot=sim3_parts(gauge)[1]@Rotation.from_quat(trajectory[:,4:8]).as_matrix()
    refrot=np.array([poses[g][:3,:3] for g in grid])
    orientation=np.degrees(Rotation.from_matrix(np.swapaxes(refrot,1,2)@aligned_rot).magnitude())
    missing=sorted(set(range(len(mapping)))-set(matches.tolist()))
    missing_grid=[mapping[i]['grid_index'] for i in missing]
    save_json(dest/'alignment.json',dict(gauge=gauge.tolist(),global_scale=sim3_parts(gauge)[0],C=C,
        prefix_grid_ids=cal_ids.tolist(),prefix_count=len(cal_ids),post_prefix_GT_used_for_fit=False,
        position_error_prefix_m=stats(errors[grid<100]),position_error_post_prefix_m=stats(errors[grid>=100]),
        orientation_error_post_prefix_deg=stats(orientation[grid>=100]),pose_revision=snapshot['pose_revision'],
        mapping_pose_count=len(matches),mapping_input_count=len(mapping),missing_mapping_indices=missing,missing_grid_ids=missing_grid,
        missing_interval_grid=[min(missing_grid),max(missing_grid)+1] if missing_grid else None,
        original_tracking_gate='FAIL: 2.4 second break > previous 2 second gate; unchanged',lineage=lineage))
    cal=load_calibrations(ROOT/spec['calibration_file']);models={n:camera_model(cal,n) for n in spec['camera_models']}
    model_meta={n:{k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in m.items()} for n,m in models.items()}
    A,hw,_,_=resize_contract();assert hw==(416,512)
    # Independent image correspondences on prefix mapping images only.
    sift=cv2.SIFT_create(nfeatures=3000);epipolar=[]
    for ia,ib in [(0,8),(16,24),(32,40),(48,56),(64,72)]:
        pair=[]
        for idx in [ia,ib]:
            path=ROOT/'data/E4e/eth3d/HKairport01/images'/Path(mapping[idx]['rgb_member']).name
            rgb=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
            image=processed_rgb(rgb);kp,des=sift.detectAndCompute(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),None)
            pair.append((np.array([k.pt for k in kp]),des));inputs.append(path)
        match=cv2.BFMatcher().knnMatch(pair[0][1],pair[1][1],k=2)
        good=[m for m,n in match if m.distance<.75*n.distance]
        x=np.array([pair[0][0][m.queryIdx] for m in good]);y=np.array([pair[1][0][m.trainIdx] for m in good])
        assert len(x)>=20
        _,mask=cv2.findFundamentalMat(x,y,cv2.FM_RANSAC,1.,.999)
        take=mask.reshape(-1).astype(bool);x=x[take];y=y[take]
        pa=poses[mapping[ia]['grid_index']];pb=poses[mapping[ib]['grid_index']]
        row=dict(mapping_pair=[ia,ib],grid_pair=[mapping[ia]['grid_index'],mapping[ib]['grid_index']],matches=len(good),image_only_RANSAC_inliers=len(x),models={})
        for name,m in models.items():
            K=A@m['K'];ux=source_rays(x,m)@K.T;uy=source_rays(y,m)@K.T
            row['models'][name]=dict(c2w=stats(sampson_pixels(ux[:,:2],uy[:,:2],pa,pb,K)),
                inverse=stats(sampson_pixels(ux[:,:2],uy[:,:2],np.linalg.inv(pa),np.linalg.inv(pb),K)))
        kp=A@np.array(lookup[Path(mapping[ia]['rgb_member']).name]['P3x3'])
        row['Terra_pinhole_c2w']=stats(sampson_pixels(x,y,pa,pb,kp))
        row['Terra_pinhole_inverse']=stats(sampson_pixels(x,y,np.linalg.inv(pa),np.linalg.inv(pb),kp))
        epipolar.append(row)
    save_json(dest/'epipolar.json',epipolar)
    # RTK shape/scale check independent of predicted SLAM (translation or inverse).
    from e1_taxonomy import fit_sim3
    with ZipFile(ROOT/spec['archive']) as z:
        rtk=list(csv.DictReader(io.StringIO(z.read('interval1_HKairport01/rtk_positions_raw.csv').decode())))
        rt=np.array([float(r['headerstamp']) for r in rtk]);rxy=np.array([[float(r['easting']),float(r['northing'])] for r in rtk])
        prefix=[f for f in mapping if f['grid_index']<100];rs=[]
        for f in prefix:rs.append(rxy[np.argmin(np.abs(rt-f['rgb_timestamp']))])
        rs=np.column_stack([rs,np.zeros(len(rs))]);rtk_checks={}
        for direction in ['c2w','inverse']:
            q=np.array([(poses[f['grid_index']] if direction=='c2w' else np.linalg.inv(poses[f['grid_index']]))[:3,3] for f in prefix])
            g=fit_sim3(q,rs);rtk_checks[direction]=dict(scale=sim3_parts(g)[0],residual_m=stats(np.linalg.norm(transform_points(q,g)-rs,axis=1)))
        # Extract heldout RGB into a new evaluation-only directory; preserve original assets.
        evalframes=[f for f in frames if f['role']=='heldout' and f['grid_index']>=100]
        for f in evalframes:
            target=dest/'heldout_rgb'/Path(f['rgb_member']).name
            target.write_bytes(z.read(f['rgb_member']));inputs.append(target)
    source_frames=sorted({r['grid_index'] for r in lineage}|{mapping[i]['grid_index'] for i in [0,8,16,24,32,40,48,56,64,72]})
    needed=sorted(set(source_frames)|{f['grid_index'] for f in evalframes})
    reference_rows=[]
    for grid_id in needed:
        f=frames[grid_id];path=ROOT/spec['reference']/'lidar'/Path(f['lidar_member']).name
        pts=np.loadtxt(path);assert pts.ndim==2 and pts.shape[1]==3
        inputs.append(path);row=dict(grid_index=grid_id,role=f['role'],lidar_points=len(pts),models={})
        for name,m in models.items():
            for mode,distorted in [('source',True),('target',False)]:
                ref=lidar_depth(pts,m,distorted)
                target=dest/'references'/f'{name}_{mode}_{grid_id:03d}.npz'
                np.savez_compressed(target,depth=ref['depth'],valid=ref['valid'],edge=ref['edge'],count=ref['count'])
                row['models'][name+'_'+mode]=dict(valid_pixels=int(ref['valid'].sum()),observed_pixels=int((ref['count']>0).sum()),
                    valid_fraction=float(ref['valid'].mean()),positive_z_points=ref['positive_z_count'],projected_points=ref['projected_count'],
                    depth_m=stats(ref['depth'][ref['valid']]),file=digest(target))
        reference_rows.append(row)
        if len(reference_rows)%10==0:print('Prepared sparse reference',len(reference_rows),'/',len(needed),flush=True)
    # Model-independent temporal LiDAR consistency under the adopted Terra c2w poses.
    cross=[]
    for row in epipolar:
        ga,gb=row['grid_pair']
        for name,m in models.items():
            a=np.load(dest/'references'/f'{name}_target_{ga:03d}.npz');b=np.load(dest/'references'/f'{name}_target_{gb:03d}.npz')
            yy,xx=np.where(a['valid']);pix=np.column_stack([xx,yy]);K=A@m['K']
            rays=np.column_stack([pix,np.ones(len(pix))])@np.linalg.inv(K).T
            local=rays*a['depth'][yy,xx,None];rel=np.linalg.inv(poses[gb])@poses[ga];p=transform_points(local,rel)
            front=p[:,2]>0;p=p[front];uv=p@K.T;uv=uv[:,:2]/uv[:,2:]
            pr,valid,_,_=__import__('a0b_geometry').rasterize(uv,p[:,2],hw)
            common=valid&b['valid']
            cross.append(dict(model=name,grid_pair=[ga,gb],common_pixels=int(common.sum()),
                camera_Z_difference_m=stats(np.abs(pr[common]-b['depth'][common]))))
    save_json(dest/'reference_crossview.json',cross)
    epi_ok=all(r['models']['HKairport_released']['c2w']['median']<spec['gates']['prefix_epipolar_median_px_max'] for r in epipolar)
    target_counts=[r['models']['HKairport_released_target']['valid_pixels'] for r in reference_rows if r['grid_index'] in [f['grid_index'] for f in evalframes]]
    gate=dict(pipeline_reference_coverage=bool(min(target_counts)>=spec['gates']['min_target_valid_pixels_per_view']),
        prefix_epipolar=bool(epi_ok),published_sequence_extrinsic_rotation=bool(models['HKairport_released']['orthogonality_max']<=spec['gates']['extrinsic_orthogonality_max']),
        author_confirmed_RGB_preprocessing=False,author_confirmed_Terra_physical_camera_equivalence=False,
        interpretation='CONDITIONAL DIAGNOSTIC ONLY; strict GT causal attribution blocked by calibration provenance',
        native_raw_self_provenance='PASS for every final exported KF; popped slot IDs matched by both KF ID and frame ID',
        final_snapshot_slots=len(snapshot['metadata']),native_exported_KFs=dump['n'],
        snapshot_only_slots=[dict(kf_idx=m['kf_idx'],frame_id=m['frame_id']) for m in snapshot['metadata'] if m['kf_idx'] not in {k['kf_idx'] for k in dump['keyframes']}])
    save_json(dest/'manifest.json',dict(registration=digest(out/'registration.json'),models=model_meta,resize_matrix=A.tolist(),hw=list(hw),
        evaluation_grid_ids=[f['grid_index'] for f in evalframes],source_grid_ids=source_frames,reference_rows=reference_rows,
        RTK_checks=rtk_checks,gates=gate,inputs=[digest(p) for p in sorted(set(inputs))],
        camera_metadata_note='Terra P3x3 and physical camera K are distinct; HK_GNSS was used in old input metadata but use_calib=false so not consumed by mapper'))
    print(json.dumps(dict(C=C,prefix_poses=len(cal_ids),reference_targets=len(evalframes),min_target_pixels=min(target_counts),gates=gate),indent=2),flush=True)


if __name__=='__main__':main()
