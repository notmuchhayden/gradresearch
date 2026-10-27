"""Reference-free primitives for the registered A2-O RGB diagnostic."""
from __future__ import annotations

import hashlib
import numpy as np
from dataclasses import asdict, dataclass


def scalar_grid():
    return np.round(np.arange(-0.20, 0.2000001, 0.01), 8)


def bilinear_basis(u, v, height=288, width=512):
    u=np.asarray(u,dtype=np.float64); v=np.asarray(v,dtype=np.float64)
    xs=np.linspace(0,width-1,4); ys=np.linspace(0,height-1,4)
    ix=np.clip(np.searchsorted(xs,u,side='right')-1,0,2)
    iy=np.clip(np.searchsorted(ys,v,side='right')-1,0,2)
    tx=(u-xs[ix])/(xs[ix+1]-xs[ix]); ty=(v-ys[iy])/(ys[iy+1]-ys[iy])
    out=np.zeros((len(u),16),np.float64)
    for dy in range(2):
        for dx in range(2):
            out[np.arange(len(u)),(iy+dy)*4+ix+dx] += (tx if dx else 1-tx)*(ty if dy else 1-ty)
    return out


def dct_modes():
    """15 orthonormal 4x4 DCT-II node modes, DC omitted, deterministic sign."""
    x=np.arange(4,dtype=np.float64)
    one=[]
    for p in range(4):
        a=np.cos(np.pi*(2*x+1)*p/8)
        a *= np.sqrt(1/4) if p==0 else np.sqrt(2/4)
        one.append(a)
    modes=[]
    for p in range(4):
        for q in range(4):
            if p==q==0: continue
            z=np.outer(one[p],one[q]).reshape(-1)
            z-=z.mean(); z/=np.sqrt(np.mean(z*z))
            nz=np.flatnonzero(np.abs(z)>1e-12)
            if z[nz[0]]<0:z=-z
            modes.append(z)
    return np.asarray(modes)


def photo_patch(source_rgb, warped_rgb, eps=1e-12):
    """Compute per-patch 0.85 ZNCC + 0.15 RGB L1 loss."""
    a=np.asarray(source_rgb,dtype=np.float64); b=np.asarray(warped_rgb,dtype=np.float64)
    if a.shape!=b.shape or a.shape[-1]!=3: raise ValueError('patch arrays must match and end in RGB')
    wa=np.array([.299,.587,.114]); x=a@wa; y=b@wa
    x=x.reshape(-1); y=y.reshape(-1); xc=x-x.mean(); yc=y-y.mean()
    den=np.sqrt(np.sum(xc*xc)*np.sum(yc*yc))
    corr=np.sum(xc*yc)/(den+eps); corr=np.clip(corr,-1,1)
    zncc=(1-corr)/2
    l1=float(np.mean(np.abs(a-b)))
    return float(.85*zncc+.15*l1),float(zncc),l1


def tie_argmin(losses, candidates, tie_epsilon=1e-8, keys=None):
    losses=np.asarray(losses,dtype=np.float64); c=list(candidates)
    if len(losses)!=len(c) or not len(c): raise ValueError('empty or mismatched profile')
    if not np.isfinite(losses).all(): raise ValueError('loss must be finite')
    best=float(losses.min()); tied=np.flatnonzero(losses<=best+tie_epsilon)
    if keys is None: keys=[(abs(float(x)),float(x)) for x in c]
    i=min(tied,key=lambda j:keys[j])
    return int(i), best, len(tied)


def profile_digest(mask):
    a=np.ascontiguousarray(mask,dtype=np.uint8)
    return hashlib.sha256(a.tobytes()).hexdigest()


def apply_log_depth(y, d):
    y=np.asarray(y); d=np.asarray(d)
    if d.ndim==0: factor=np.exp(float(d))
    else: factor=np.exp(d)[...,None]
    return y*factor


def huber(x, delta=.05):
    x=np.asarray(x,dtype=np.float64); a=np.abs(x)
    return np.where(a<=delta,.5*x*x,delta*(a-.5*delta))


def shared_scale_residual(z_source, z_evidence):
    """Shows predicted-depth agreement under a common multiplicative bias."""
    a=np.asarray(z_source,dtype=np.float64); b=np.asarray(z_evidence,dtype=np.float64)
    if a.shape!=b.shape or np.any(a<=0) or np.any(b<=0): raise ValueError('positive matching depths required')
    return np.log(a/b)


def support_status(pair_counts, min_pairs=2):
    counts=list(map(int,pair_counts))
    return {'supported':sum(c>0 for c in counts)>=min_pairs,'pair_count':sum(c>0 for c in counts),
            'counts':counts,'reason':None if sum(c>0 for c in counts)>=min_pairs else 'FEWER_THAN_TWO_SUPPORTED_PAIRS'}


@dataclass(frozen=True)
class Candidate:
    """One registered correction in the scalar or one-mode field search."""
    kind: str
    a: float
    mode: int | None = None
    b: float = 0.0

    def correction(self, basis, modes):
        basis=np.asarray(basis,dtype=np.float64)
        if self.kind=='scalar':
            return np.full(basis.shape[0],self.a,dtype=np.float64)
        if self.kind!='field' or self.mode is None or not 0<=self.mode<len(modes):
            raise ValueError('invalid candidate')
        return self.a+self.b*(basis@np.asarray(modes)[self.mode])


def scalar_candidates():
    return [Candidate('scalar',float(a)) for a in scalar_grid()]


def field_candidates(seed):
    amps=np.round(np.arange(-.10,.1000001,.01),8)
    return [Candidate('field',float(seed),m,float(b))
            for m in range(15) for b in amps]


def _candidate_key(c, modes_order=True):
    if c.kind=='scalar': return (0,abs(c.a),c.a)
    return (1,abs(c.b),int(c.mode),c.b)


def aggregate_pair_losses(pair_losses):
    """Equal weight per evidence pair, then equal weight per source patch.

    `pair_losses` is a sequence of (candidate,patch) finite arrays. Missing
    pairs must be omitted and separately reported, never replaced with zero.
    """
    arrays=[np.asarray(x,dtype=np.float64) for x in pair_losses]
    if not arrays or any(x.ndim!=2 or not x.shape[1] for x in arrays):
        raise ValueError('each pair must have candidate-by-patch losses')
    n=arrays[0].shape[0]
    if any(x.shape[0]!=n or not np.isfinite(x).all() for x in arrays):
        raise ValueError('pair profile dimensions/nonfinite losses differ')
    return np.mean(np.stack([x.mean(axis=1) for x in arrays]),axis=0)


def select_profile(candidates, losses, tie_epsilon=1e-8, scalar_priority=True):
    """Frozen deterministic tie and boundary selection rules."""
    candidates=list(candidates); losses=np.asarray(losses,dtype=np.float64)
    if len(candidates)!=len(losses) or not len(candidates) or not np.isfinite(losses).all():
        raise ValueError('invalid candidate profile')
    best=float(losses.min()); tied=np.flatnonzero(losses<=best+tie_epsilon)
    def key(i):
        c=candidates[i]
        return ((0 if c.kind=='scalar' else 1) if scalar_priority else 0,*_candidate_key(c)[1:])
    ix=int(min(tied,key=key));c=candidates[ix]
    if c.kind=='scalar': boundary=(abs(c.a)>=.20-1e-9)
    else: boundary=(abs(c.b)>=.10-1e-9)
    selected=asdict(c);selected['mode_id']='DC' if c.kind=='scalar' else int(c.mode)+1
    return {'index':ix,'candidate':selected,'loss':float(losses[ix]),
            'minimum_loss':best,'tie_count':int(len(tied)),
            'boundary':bool(boundary),'status':'SEARCH_BOUNDARY' if boundary else 'SELECTED'}


def two_stage_selection(evaluate_common_fit, *, tie_epsilon=1e-8,
                        flat_epsilon=1e-4, gain_epsilon=1e-4):
    """Run the registered scalar-seed then common 356-candidate selection.

    The callback receives only the candidate list and the stage name and must
    return a finite candidate loss vector plus a mask digest/support summary.
    It is deliberately passed no reference/GT object and no audit inputs.
    """
    scalar=scalar_candidates()
    first=evaluate_common_fit(scalar,'scalar_seed')
    seed_losses=np.asarray(first['losses'],dtype=np.float64)
    if seed_losses.shape!=(41,): raise ValueError('scalar seed profile must contain 41 values')
    seed_choice=select_profile(scalar,seed_losses,tie_epsilon,scalar_priority=False)
    seed=float(seed_choice['candidate']['a'])
    candidates=scalar+field_candidates(seed)
    final=evaluate_common_fit(candidates,'final_common')
    losses=np.asarray(final['losses'],dtype=np.float64)
    if losses.shape!=(356,): raise ValueError('final profile must contain 356 values')
    scalar_choice=select_profile(scalar,losses[:41],tie_epsilon,scalar_priority=False)
    all_choice=select_profile(candidates,losses,tie_epsilon,scalar_priority=True)
    if all_choice['candidate']['kind']=='field' and abs(all_choice['candidate']['b'])<1e-12:
        # b=0 fields duplicate the scalar seed exactly. They are one correction,
        # and scalar is selected on a loss tie.
        all_choice=select_profile(scalar,losses[:41],tie_epsilon,scalar_priority=False)
    span=float(losses.max()-losses.min())
    baseline=float(losses[20])
    improvement=baseline-float(all_choice['loss'])
    scalar_gain=float(scalar_choice['loss']-all_choice['loss'])
    status=[]
    if span<=flat_epsilon: status.append('FLAT_PROFILE')
    if improvement<=gain_epsilon or scalar_gain<=gain_epsilon: status.append('NO_RESOLVED_PHOTO_GAIN')
    if all_choice['boundary']: status.append('SEARCH_BOUNDARY')
    return {'seed':seed,'seed_choice':seed_choice,'seed_mask':first.get('mask_digest'),
            'final_mask':final.get('mask_digest'),'scalar_only_mask':first.get('mask_digest'),
            'final_scalar':scalar_choice,'photo_selected':all_choice,
            'profile_range':span,'gain_vs_zero':improvement,'gain_vs_scalar':scalar_gain,
            'losses':losses.tolist(),'candidate_specs':[asdict(c) for c in candidates],
            'support':final.get('support'),'status':status or ['SELECTED']}


def seal_selection(path, selection, input_hashes, code_hashes, protocol_hash):
    """Atomically serialize immutable RGB-only choices and their provenance."""
    import json
    from pathlib import Path
    payload={'status':'FROZEN_RGB_SELECTION','selection':selection,
             'input_hashes':input_hashes,'code_hashes':code_hashes,
             'protocol_hash':protocol_hash}
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(target.suffix+'.tmp')
    tmp.write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
    tmp.replace(target)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    return {'path':str(target),'sha256':digest,'status':payload['status']}


def _bilinear_sample(image, xy):
    image=np.asarray(image); xy=np.asarray(xy,dtype=np.float64)
    scalar=image.ndim==2
    if scalar: image=image[...,None]
    h,w=image.shape[:2]; x=xy[...,0]; y=xy[...,1]
    inside=np.isfinite(x)&np.isfinite(y)&(x>=0)&(y<h-1)&(x<w-1)
    x0=np.clip(np.floor(np.nan_to_num(x)).astype(np.int64),0,w-2)
    y0=np.clip(np.floor(np.nan_to_num(y)).astype(np.int64),0,h-2)
    dx=(x-x0)[...,None];dy=(y-y0)[...,None]
    out=(image[y0,x0]*(1-dx)*(1-dy)+image[y0,x0+1]*dx*(1-dy)+
         image[y0+1,x0]*(1-dx)*dy+image[y0+1,x0+1]*dx*dy)
    return (out[...,0] if scalar else out),inside,(x0,y0)


def warp_photo_patches(source_points, source_rgb, correction, source_Q,
                       evidence_Q, K, evidence_rgb, evidence_z,
                       evidence_valid, *, abs_z_tol=.05, rel_z_tol=.05):
    """Warp every source 3x3 point into one predicted evidence view.

    Arrays contain only native-active predicted data and RGB. No reference
    depth, pose, mask, or GT-derived support is accepted by this interface.
    Returns per-patch photo losses, validity, and component losses.
    """
    Y=np.asarray(source_points,dtype=np.float64)
    S=np.asarray(source_rgb,dtype=np.float64)
    if Y.ndim!=3 or Y.shape[1:]!=(9,3) or S.shape!=Y.shape:
        raise ValueError('source patches must be N x 9 x 3')
    d=np.asarray(correction,dtype=np.float64)
    if d.ndim==1: d=np.repeat(d[:,None],9,axis=1)
    if d.shape!=(len(Y),9): raise ValueError('correction must be N or N x 9')
    Qs=np.asarray(source_Q,dtype=np.float64);Qe=np.asarray(evidence_Q,dtype=np.float64);K=np.asarray(K,dtype=np.float64)
    rgb=np.asarray(evidence_rgb,dtype=np.float64); zbuf=np.asarray(evidence_z,dtype=np.float64); vm=np.asarray(evidence_valid,dtype=bool)
    world=(Y*np.exp(d)[...,None])@Qs[:3,:3].T+Qs[:3,3]
    pe=(world-Qe[:3,3])@Qe[:3,:3]
    z=pe[...,2]; safe=np.maximum(z,1e-12)
    xy=np.stack([K[0,0]*pe[...,0]/safe+K[0,2],K[1,1]*pe[...,1]/safe+K[1,2]],axis=-1)
    sampled,inside,_=_bilinear_sample(rgb,xy)
    zz,zinside,zgrid=_bilinear_sample(zbuf,xy)
    x0,y0=zgrid
    # All four evidence z samples must be native-valid; no hole filling.
    valid4=(vm[y0,x0]&vm[y0,x0+1]&vm[y0+1,x0]&vm[y0+1,x0+1])
    # Compare against the bilinear predicted evidence z at the same location.
    vis=np.abs(z-zz)<=np.maximum(abs_z_tol,rel_z_tol*np.maximum(zz,0))
    valid=(inside&zinside&valid4&vis&(z>0)&np.isfinite(sampled).all(axis=-1))
    # Texture gate is evaluated at S0 and then held fixed by the caller.
    gray_w=np.array([.299,.587,.114])
    a=S@gray_w;b=sampled@gray_w
    av=a.var(axis=1);bv=b.var(axis=1)
    corr=np.sum((a-a.mean(axis=1,keepdims=True))*(b-b.mean(axis=1,keepdims=True)),axis=1)
    den=np.sqrt(np.sum((a-a.mean(axis=1,keepdims=True))**2,axis=1)*
                np.sum((b-b.mean(axis=1,keepdims=True))**2,axis=1))
    zncc=np.clip(corr/(den+1e-12),-1,1)
    zncc_loss=(1-zncc)/2
    l1=np.mean(np.abs(S-sampled),axis=(1,2))
    loss=.85*zncc_loss+.15*l1
    geom=huber(np.log(np.maximum(z,1e-12)/np.maximum(zz,1e-12)),delta=.05).mean(axis=1)
    return {'loss':loss,'zncc_loss':zncc_loss,'l1':l1,'geometry_loss':geom,
            'projected_z':z,'sampled_evidence_z':zz,'valid':valid.all(axis=1),
            'valid_point_fraction':valid.mean(axis=1),'source_gray_var':av,
            'warped_gray_var':bv,'warped_rgb':sampled}


def native_patch_samples(y, pixel_indices, rgb, *, fold, stride=4,
                         height=288,width=512,guard=2,texture_min=.02):
    """Build fixed, guarded 3x3 samples from native-active prediction pixels."""
    y=np.asarray(y,dtype=np.float64); idx=np.asarray(pixel_indices,dtype=np.int64)
    rgb=np.asarray(rgb,dtype=np.float64)
    if y.shape!=(len(idx),3) or rgb.shape!=(height,width,3): raise ValueError('native input shapes differ')
    lut=np.full(height*width,-1,np.int32);lut[idx]=np.arange(len(idx),dtype=np.int32)
    u=idx%width;v=idx//width
    xe=np.floor(np.arange(9)*width/8).astype(int);ye=np.floor(np.arange(9)*height/8).astype(int)
    tc=np.searchsorted(xe[1:],u,side='right');tr=np.searchsorted(ye[1:],v,side='right')
    parity=(tc+tr)&1
    guarded=(u>=xe[tc]+guard)&(u<xe[tc+1]-guard)&(v>=ye[tr]+guard)&(v<ye[tr+1]-guard)
    centers=np.flatnonzero((u%stride==0)&(v%stride==0)&(parity==fold)&guarded)
    du=np.tile(np.arange(-1,2),3);dv=np.repeat(np.arange(-1,2),3)
    pix=idx[centers,None]+dv[None,:]*width+du[None,:]
    rows=lut[pix];ok=(rows>=0).all(1)
    ok &= (((u[centers,None]+du[None,:])//(width//8))==tc[centers,None]).all(1)
    ok &= (((v[centers,None]+dv[None,:])//(height//8))==tr[centers,None]).all(1)
    centers=centers[ok];rows=rows[ok];pix=pix[ok]
    if not len(centers):
        return {'points':np.empty((0,9,3)),'rgb':np.empty((0,9,3)),
                'centers':idx[:0],'xy':np.empty((0,9,2)),'texture':np.zeros(0,bool)}
    yp=y[rows];z=yp[:,4,2]
    jumps=np.abs(yp[:,[1,3,5,7],2]-z[:,None])/np.maximum(np.abs(z[:,None]),1e-8)
    rgbp=rgb[pix//width,pix%width]
    gray=rgbp@np.array([.299,.587,.114])
    return {'points':yp,'rgb':rgbp,'centers':idx[centers],
            'xy':np.stack([pix%width,pix//width],axis=-1),
            'texture':(gray.std(1)>=texture_min)&~(jumps>.05).any(1)}


def rasterize_predicted_depth(y, pixel_indices, K, *, height=288,width=512,
                              edge_relative=.05,edge_dilation=2):
    """Native-only z-buffer from predicted evidence pointmap; holes stay invalid."""
    import cv2
    y=np.asarray(y,dtype=np.float64);idx=np.asarray(pixel_indices,dtype=np.int64);K=np.asarray(K)
    z=y[:,2];ok=np.isfinite(y).all(1)&(z>0)
    x=np.zeros(len(y));v=np.zeros(len(y))
    x[ok]=K[0,0]*y[ok,0]/z[ok]+K[0,2]
    v[ok]=K[1,1]*y[ok,1]/z[ok]+K[1,2]
    px=np.rint(x).astype(int);py=np.rint(v).astype(int)
    ok &= (px>=0)&(px<width)&(py>=0)&(py<height)
    depth=np.full(height*width,np.inf,np.float32)
    np.minimum.at(depth,py[ok]*width+px[ok],z[ok].astype(np.float32))
    depth=depth.reshape(height,width);valid=np.isfinite(depth);edge=~valid
    for axis in (0,1):
        a=[slice(None),slice(None)];b=[slice(None),slice(None)]
        a[axis]=slice(1,None);b[axis]=slice(None,-1);a=tuple(a);b=tuple(b)
        jump=np.abs(depth[a]-depth[b])>edge_relative*np.minimum(depth[a],depth[b])
        jump |= ~valid[a]|~valid[b];edge[a]|=jump;edge[b]|=jump
    edge=cv2.dilate(edge.astype(np.uint8),np.ones((2*edge_dilation+1,)*2,np.uint8)).astype(bool)
    valid &= ~edge;depth[~valid]=0
    return depth,valid,edge


def evaluate_pair_candidates(pair, candidates, modes, *, texture_min=.02,
                             abs_z_tol=.05, rel_z_tol=.05):
    """Return one RGB profile on a candidate-wide fixed patch intersection."""
    P=pair['patches'];Y=P['points'];S=P['rgb'];coords=P['xy']
    n=len(Y)
    if n==0:
        return {'losses':np.full(len(candidates),np.nan),'mask':np.zeros(0,bool),
                'eligible':0,'support':False,'reason':'NO_NATIVE_PATCHES'}
    B=bilinear_basis(coords[...,0].reshape(-1),coords[...,1].reshape(-1)).reshape(n,9,16)
    zero=warp_photo_patches(Y,S,np.zeros(n),pair['source_Q'],pair['evidence_Q'],pair['K'],
        pair['evidence_rgb'],pair['evidence_z'],pair['evidence_valid'],abs_z_tol=abs_z_tol,rel_z_tol=rel_z_tol)
    primary=P.get('primary_parallax',np.ones(n,bool))
    eligible=P['texture']&primary&zero['valid']&(zero['warped_gray_var']>=texture_min**2)
    common=eligible.copy()
    # Candidate-wide geometry/visibility intersection. Corrections are RGB
    # predictions only; every registered candidate shares the resulting mask.
    for c in candidates:
        d=c.correction(B.reshape(-1,16),modes).reshape(n,9)
        out=warp_photo_patches(Y,S,d,pair['source_Q'],pair['evidence_Q'],pair['K'],
            pair['evidence_rgb'],pair['evidence_z'],pair['evidence_valid'],abs_z_tol=abs_z_tol,rel_z_tol=rel_z_tol)
        common &= out['valid']
    retained=int(common.sum()); base=int(eligible.sum())
    if retained:
        # Re-evaluate each candidate on exactly the same pixels.
        losses=[];geometry=[];znccs=[];l1s=[]
        for c in candidates:
            d=c.correction(B.reshape(-1,16),modes).reshape(n,9)
            out=warp_photo_patches(Y,S,d,pair['source_Q'],pair['evidence_Q'],pair['K'],
                pair['evidence_rgb'],pair['evidence_z'],pair['evidence_valid'],abs_z_tol=abs_z_tol,rel_z_tol=rel_z_tol)
            losses.append(float(out['loss'][common].mean()))
            geometry.append(float(out['geometry_loss'][common].mean()))
            znccs.append(float(out['zncc_loss'][common].mean()))
            l1s.append(float(out['l1'][common].mean()))
        losses=np.asarray(losses)
    else:
        losses=np.full(len(candidates),np.nan);geometry=np.full(len(candidates),np.nan)
        znccs=np.full(len(candidates),np.nan);l1s=np.full(len(candidates),np.nan)
    return {'losses':losses,'geometry_losses':np.asarray(geometry),
            'zncc_losses':np.asarray(znccs),'l1_losses':np.asarray(l1s),
            'mask':common,'eligible':base,'retained':retained,
            'retention':retained/max(1,base),'support':bool(retained>=256 and retained>=.5*base),
            'mask_digest':profile_digest(common),'basis':B,'design_eigen_ratio':None}
