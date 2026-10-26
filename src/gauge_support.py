"""Prefix-only gauge construction and GT-blind measurement masks."""
import numpy as np
from scipy.spatial.transform import Rotation
from pointmap_contract import sim3_parts,transform_points


def orientation_prefix_gauge(estimated,reference,frame_ids,stop):
    estimated=np.asarray(estimated,float);reference=np.asarray(reference,float);frame_ids=np.asarray(frame_ids)
    if estimated.shape!=reference.shape or estimated.shape!=(len(frame_ids),4,4):raise ValueError('Pose shapes differ')
    if len(np.unique(frame_ids))!=len(frame_ids) or np.any(np.diff(frame_ids)<=0):raise ValueError('Sorted unique frame IDs required')
    mask=frame_ids<stop
    if mask.sum()<3 or mask.all():raise ValueError('Need prefix and separate evaluation region')
    a,b=estimated[mask],reference[mask]
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Invalid prefix poses')
    for p in [*a,*b]:
        if not np.isclose(sim3_parts(p)[0],1.,atol=1e-8,rtol=0):raise ValueError('Input camera poses must be rigid')
    R=Rotation.from_matrix(b[:,:3,:3]@np.swapaxes(a[:,:3,:3],1,2)).mean().as_matrix()
    x,y=a[:,:3,3],b[:,:3,3];xc=x-x.mean(0);yc=y-y.mean(0);den=np.sum(xc**2)
    if den<=1e-15:raise ValueError('No positional baseline in prefix')
    scale=float(np.sum((xc@R.T)*yc)/den)
    if not np.isfinite(scale) or scale<=0:raise ValueError('Nonpositive fitted global scale')
    G=np.eye(4);G[:3,:3]=scale*R;G[:3,3]=y.mean(0)-scale*R@x.mean(0)
    sv=np.linalg.svd(xc,compute_uv=False);svref=np.linalg.svd(yc,compute_uv=False)
    return G,dict(prefix_ids=frame_ids[mask].tolist(),prefix_count=int(mask.sum()),
        estimated_position_singular_values=sv.tolist(),estimated_singular_ratios=(sv/sv[0]).tolist(),
        reference_position_singular_values=svref.tolist(),reference_singular_ratios=(svref/svref[0]).tolist(),
        prefix_position_mean_residual_m=float(np.linalg.norm(transform_points(x,G)-y,axis=1).mean()))


def change_canonical_gauge(points,covariance,Q,relative):
    scale,R,t=sim3_parts(relative);points=np.asarray(points,float);covariance=np.asarray(covariance,float)
    if not np.isclose(sim3_parts(Q)[0],1.,atol=1e-10,rtol=0):raise ValueError('Q must be rigid')
    changed=np.eye(4);changed[:3,:3]=R@Q[:3,:3];changed[:3,3]=transform_points(Q[:3,3][None],relative)[0]
    return points*scale,covariance*scale**2,changed


def splitmix64(value):
    with np.errstate(over='ignore'):
        x=np.asarray(value,dtype=np.uint64)+np.uint64(0x9E3779B97F4A7C15)
        x=(x^(x>>np.uint64(30)))*np.uint64(0xBF58476D1CE4E5B9)
        x=(x^(x>>np.uint64(27)))*np.uint64(0x94D049BB133111EB)
        return x^(x>>np.uint64(31))


def sampling_mask(hw,frame,pattern,density,seed=0):
    h,w=hw
    if h<=0 or w<=0 or not (0<density<=1):raise ValueError('Invalid grid or density')
    salt=splitmix64(np.uint64(int(frame))^np.uint64(int(seed)))
    if pattern=='uniform_hash':
        bits=splitmix64(np.arange(h*w,dtype=np.uint64)^salt)
        values=(bits>>np.uint64(11)).astype(np.float64)/2**53
        return (values<density).reshape(h,w)
    if pattern=='scan_rows':
        period=int(round(1/density))
        if not np.isclose(1/period,density):raise ValueError('Scan density must be reciprocal integer')
        phase=int(salt)%period
        return np.broadcast_to((np.arange(h)%period==phase)[:,None],(h,w)).copy()
    raise ValueError('Unknown sampling pattern')
