"""GT-free resource selection and evaluation-only image/surface metrics."""
import numpy as np
from scipy.spatial import cKDTree

PARAMETER_WIDTH = 13


def random_priority(n, seed=0):
    order=np.random.default_rng(seed).permutation(n)
    rank=np.empty(n,np.int64);rank[order]=np.arange(n)
    return rank


def select_budget(active, natural, score, keep, arm, seed=0):
    """Exact quota or explicit unreachable; never turn missing evidence into a score."""
    active=np.asarray(active,bool);natural=np.asarray(natural,bool)
    if np.any(natural&~active):raise ValueError('Natural map must be a subset of original active')
    k=int(np.floor(active.sum()*keep));priority=random_priority(len(active),seed)
    selected=np.zeros(len(active),bool);finite=active&np.isfinite(score)
    if arm=='policy_fallback':
        if natural.sum()<k:return None,dict(reason='natural_survivors_below_quota',target=k)
        ids=np.flatnonzero(natural);ids=ids[np.argsort(priority[ids],kind='stable')[:k]];selected[ids]=True
    elif arm=='rank_only':
        remove=int(active.sum())-k
        if finite.sum()<remove:return None,dict(reason='insufficient_finite_evidence',target=k,finite=int(finite.sum()))
        ids=np.flatnonzero(finite);order=np.lexsort((priority[ids],-np.asarray(score)[ids]))
        selected[:]=active;selected[ids[order[:remove]]]=False
    elif arm=='random':
        ids=np.flatnonzero(active);selected[ids[np.argsort(priority[ids],kind='stable')[:k]]]=True
    else:raise ValueError(arm)
    return selected,dict(target=k,selected=int(selected.sum()),natural_rejections=int((active&~natural).sum()),
        fallback_rejections=int((natural&~selected).sum()) if arm=='policy_fallback' else 0,
        score_only=arm=='rank_only',unknown_removed=int((active&~selected&~np.isfinite(score)).sum()))


def voxel_birth_score(older, birth, side):
    """Stable first representative per cell, with older original-premap occupancy."""
    if not np.isfinite(side) or side<=0:raise ValueError('Positive voxel side required')
    old=np.floor(np.asarray(older)/side).astype(np.int64)
    new=np.floor(np.asarray(birth)/side).astype(np.int64)
    combined=np.concatenate([old,new]);_,first=np.unique(combined,axis=0,return_index=True)
    unique=np.zeros(len(combined),bool);unique[first]=True
    return (~unique[len(old):]).astype(np.float32)


def pack_parameters(means,cov,rgb,opacity):
    row,col=np.triu_indices(3)
    return np.ascontiguousarray(np.concatenate([means,cov[:,row,col],rgb,opacity[:,None]],axis=1),np.float32)


def unpack_parameters(packed):
    p=np.asarray(packed)
    if p.ndim!=2 or p.shape[1]!=PARAMETER_WIDTH:raise ValueError('Expected 13 float32 parameters per Gaussian')
    cov=np.zeros((len(p),3,3),np.float32);row,col=np.triu_indices(3)
    cov[:,row,col]=p[:,3:9];cov[:,col,row]=p[:,3:9]
    return p[:,:3],cov,p[:,9:12],p[:,12]


def image_metrics(pred,reference):
    from skimage.metrics import structural_similarity
    pred=np.clip(pred,0,1);reference=np.asarray(reference)
    mse=float(np.mean((pred-reference)**2))
    return dict(psnr_db=float(-10*np.log10(max(mse,1e-12))),
        ssim=float(structural_similarity(reference,pred,data_range=1,channel_axis=2)))


def sample_mesh(vertices,triangles,count,seed=0):
    """Area-weighted reproducible surface samples, independent of mesh tessellation."""
    v=np.asarray(vertices);t=np.asarray(triangles,dtype=int)
    if not len(t):return np.empty((0,3))
    tri=v[t];area=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)*.5
    if not np.isfinite(area).all() or area.sum()<=0:return np.empty((0,3))
    rng=np.random.default_rng(seed);chosen=rng.choice(len(t),count,p=area/area.sum());q=tri[chosen]
    u=np.sqrt(rng.random(count));b=rng.random(count)
    return (1-u[:,None])*q[:,0]+(u*(1-b))[:,None]*q[:,1]+(u*b)[:,None]*q[:,2]


def surface_metrics(pred,reference,tolerance=.05):
    if not len(pred) or not len(reference):
        return dict(valid=False,accuracy_m=None,completion_m=None,chamfer_m=None,precision_5cm=None,completion_ratio_5cm=None,f1_5cm=None)
    a=cKDTree(reference).query(pred,workers=2)[0];c=cKDTree(pred).query(reference,workers=2)[0]
    p=float(np.mean(a<=tolerance));r=float(np.mean(c<=tolerance))
    return dict(valid=True,accuracy_m=float(a.mean()),completion_m=float(c.mean()),
        chamfer_m=float((a.mean()+c.mean())*.5),precision_5cm=p,completion_ratio_5cm=r,
        f1_5cm=2*p*r/(p+r) if p+r else 0.)
