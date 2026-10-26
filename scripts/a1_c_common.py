"""Read-only adapters for existing A0/A0b/A1-U contracts."""
from pathlib import Path
import json
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from prepare_e2b_run import digest,save_json
from a0b_geometry import camera_model,load_calibrations,resize_contract,processed_rgb
from e1_taxonomy import camera_geometry,resize_depth,depth_masks
from evaluate_e4 import reference_rgb
from pointmap_contract import sim3_from_xyzw

SPEC=ROOT/'configs/a1_c_canonical_factorial.json'
ARMS=['C00','C10','C01','C11'];ALL_ARMS=ARMS+['CZ10','CZ11'];OLD_ARMS=['A00','A10','A01','A11']


def context():
    s=json.loads(SPEC.read_text());u=json.loads((ROOT/s['A1_U_spec']).read_text())
    return s,ROOT/s['output'],u


def frames(case):return list(range(201,1000,2)) if case['scene']=='office2' else list(range(104,300,5))


def prior(case,arm):
    spec,_,_=context();name=case['prior_ids'][arm]
    if case['scene']=='office2':
        root=ROOT/spec['prior_office'];m=json.loads((root/'oracles/manifest.json').read_text());v=next(v for v in m['variants'] if v['id']==name)
        return dict(map=ROOT/v['map_file'],map_hash=v['map_hash'],folder=root/'evaluation'/name,count=v['count'])
    root=ROOT/spec['prior_HK']
    if case['scope']=='sequence_camera_support':
        m=json.loads((root/'support_control/map_manifest.json').read_text())
        return dict(map=root/'support_control'/(name+'.f32'),map_hash=m['maps'][arm],folder=root/'support_control'/name,count=m['count'])
    m=json.loads((root/'oracles/manifest.json').read_text());v=next(v for v in m['variants'] if v['id']==name)
    return dict(map=ROOT/v['map_file'],map_hash=v['hash'],folder=root/'evaluation'/name,count=v['count'])


def prior_group_path(case):
    spec,_,_=context()
    if case['scene']=='office2':return ROOT/spec['prior_office']/'analysis/strict_common4.json'
    if case['scope']=='camera_common':return ROOT/spec['prior_HK']/'analysis/strict_common4.json'
    return ROOT/spec['prior_HK']/'support_control/results.json'


def source_camera(scene):
    if scene=='office2':
        camera=json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera'];return camera_geometry(camera)[0],None
    m=camera_model(load_calibrations(ROOT/'data/E4e/calibration_results.py'),'HKairport_released')
    return resize_contract()[0]@m['K'],m


def load_views(case):
    spec,_,_=context();views={};inputs=[];ids=frames(case)
    if case['scene']=='office2':
        data=ROOT/'data/N2/Replica/office2';cp=data.parent/'cam_params.json';camera=json.loads(cp.read_text())['camera'];K,_,crop=camera_geometry(camera)
        p=data/'traj.txt';poses=np.loadtxt(p).reshape(-1,4,4);inputs.extend([p,cp])
        first=data/'results/frame000000.jpg';first_mean=(cv2.cvtColor(cv2.imread(str(first)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.).reshape(-1,3).mean(0);inputs.append(first)
        mask=json.loads((ROOT/spec['native_filter_contract']).read_text())['common_mask']
        for f in ids:
            dp=data/'results'/f'depth{f:06d}.png';rp=data/'results'/f'frame{f:06d}.jpg';inputs.extend([dp,rp])
            depth=resize_depth(cv2.imread(str(dp),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera['scale'],camera)
            valid,edge=depth_masks(depth,mask)
            views[f]=dict(gt=depth,valid=valid&~edge,all_valid=valid,pose=poses[f],K=K,hw=tuple(crop[2:]),
                target=(reference_rgb(rp,first_mean)*255).round().astype(np.uint8).astype(np.float32)/255.)
    else:
        root=ROOT/spec['prior_HK'];pre=root/'preflight';p=ROOT/'data/E4e/evaluation_only/HKairport01/sampleinfos_interpolated.json'
        records={r['OriginalImageName']:r for r in json.loads(p.read_text())};sp=ROOT/'configs/e4e_input_split.json';split=json.loads(sp.read_text())['scene_splits']['HKairport01']['frames']
        cal=ROOT/'data/E4e/calibration_results.py';model=camera_model(load_calibrations(cal),'HKairport_released');A,hw,_,_=resize_contract();K=A@model['K']
        first=ROOT/'data/E4e/eth3d/HKairport01/images'/Path(split[0]['rgb_member']).name
        first_mean=(cv2.cvtColor(cv2.imread(str(first)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.).reshape(-1,3).mean(0);inputs.extend([p,sp,cal,first])
        for f in ids:
            rp=pre/'heldout_rgb'/Path(split[f]['rgb_member']).name;dp=pre/'references'/f'HKairport_released_target_{f:03d}.npz';inputs.extend([rp,dp]);d=np.load(dp)
            rgb=cv2.cvtColor(cv2.imread(str(rp)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.;gain=np.clip((first_mean+.001)/(rgb.reshape(-1,3).mean(0)+.001),.4,2.5)
            target=processed_rgb((np.clip(rgb*gain,0,1)*255).astype(np.uint8),model).astype(np.float32)/255.
            views[f]=dict(gt=d['depth'],valid=d['valid'],all_valid=d['valid'],pose=np.array(records[Path(split[f]['rgb_member']).name]['T4x4']),K=K,hw=hw,target=target)
    return views,inputs


def reference_poses(scene):
    if scene=='office2':
        gt=np.loadtxt(ROOT/'data/N2/Replica/office2/groundtruth.txt')
        return np.array([sim3_from_xyzw([*r[1:8],1.]) for r in gt]),None
    records={r['OriginalImageName']:r for r in json.loads((ROOT/'data/E4e/evaluation_only/HKairport01/sampleinfos_interpolated.json').read_text())}
    split=json.loads((ROOT/'configs/e4e_input_split.json').read_text())['scene_splits']['HKairport01']['frames'];mapping=[f for f in split if f['role']=='mapping']
    return {f['grid_index']:np.array(records[Path(f['rgb_member']).name]['T4x4']) for f in split},mapping


def stats(values):
    x=np.asarray(values);x=x[np.isfinite(x)]
    return dict(n=len(x),mean=float(x.mean()),median=float(np.median(x)),p95=float(np.percentile(x,95)),max=float(x.max()),min=float(x.min())) if len(x) else dict(n=0,mean=None,median=None,p95=None,max=None,min=None)
