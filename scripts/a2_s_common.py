"""Read-only adapters for registered office2 and office3 A2-S source inputs."""
from pathlib import Path
import hashlib, json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/A2_S_scalar_spatial/2026-10-27'
U=ROOT/'results/A1_U_scale_reparameterization/2026-10-26/construction/office2'
V=ROOT/'results/V1_office3_diagnostic/2026-10-26'
MASK=np.asarray(json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())['common_mask'])
H,W=288,512

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def digest(path):
    p=Path(path);return {'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),'bytes':p.stat().st_size,'sha256':sha(p)}

def dump_json(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n');tmp.replace(p)

def packed(path,count):
    p=np.memmap(path,dtype=np.float32,mode='r',shape=(count,13));return p

def kfs(scene):
    out=[]
    if scene=='office2':
        m=json.loads((U/'manifest.json').read_text())
        for row in m['keyframes']:
            i=row['kf_idx'];lp=ROOT/row['local_file']['path'];assert sha(lp)==row['local_file']['sha256']
            a=np.load(lp);reg=np.load(ROOT/f'results/A0_pointmap_pose_factorial/office2/oracles/kf{i:04d}_registry.npz')
            pix=a['active_pixel_indices'];assert np.array_equal(np.flatnonzero(reg['native_mask']),pix)
            assert np.array_equal(a['candidate_ids'] if 'candidate_ids' in a else reg['active_candidate_ids'],reg['active_candidate_ids'])
            frame=2*int(row['frame_id']);rv=reg['common_mask'][pix]
            strict=rv & (frame>=200)
            out.append(dict(kf_idx=i,original_frame=frame,H=H,W=W,y=a['y'],covariance_y=a['covariance_y'],Q=a['rigid_Q'],pixel_indices=pix,candidate_ids=reg['active_candidate_ids'],ref_z=reg['gt_depth'][pix].astype(float),ref_xyz=reg['raw_xyz'][pix].astype(float),ref_valid=rv,strict=strict,local_path=lp,registry_path=ROOT/f'results/A0_pointmap_pose_factorial/office2/oracles/kf{i:04d}_registry.npz'))
    else:
        man=json.loads((V/'maps/manifest.json').read_text())
        # Manifest order is source frame order from registered blocks.
        blocks=man.get('blocks')
        if blocks is None: blocks=sorted([int(p.stem[2:]) for p in (V/'maps/local').glob('kf*.npz')])
        for item in blocks:
            i=int(item['kf_idx'] if isinstance(item,dict) else item);p=V/f'maps/local/kf{i:03d}.npz';a=np.load(p)
            frame=int(a['source_frame']);rv=a['reference_replace'].astype(bool);strict=a['strict'].astype(bool)
            assert np.array_equal(strict,rv&(frame>=200))
            out.append(dict(kf_idx=i,original_frame=frame,H=H,W=W,y=a['y'],covariance_y=a['covariance_y'],Q=a['rigid_Q'],pixel_indices=a['active_pixel_indices'],candidate_ids=a['candidate_ids'],ref_z=a['reference'][:,2],ref_xyz=a['reference'],ref_valid=rv,strict=strict,local_path=p,registry_path=None))
    return out

def base_map(scene,gauge):
    if scene=='office2':
        if gauge=='position': p=ROOT/'results/A1_C_canonical_factorial/2026-10-26/oracles/office2_strict/C00.f32'
        else:p=ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/maps/office2_strict_orientation/C00.f32'
        n=1200827
    else:
        p=V/f'maps/{"position_strict" if gauge=="position" else "orientation_strict"}/C00.f32';n=855796
    return p,n

