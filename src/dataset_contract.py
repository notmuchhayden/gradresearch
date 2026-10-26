"""Data-only split and GT coordinate checks, independent of model predictions."""
from __future__ import annotations

import numpy as np

from e1_taxonomy import depth_masks
from pointmap_contract import backproject_z, project, transform_points


def triangulate_faces(faces,n_vertices):
    """Validate polygons and fan-triangulate in source face/winding order."""
    faces=np.asarray(faces)
    if len(faces)==0:
        raise ValueError("Empty mesh")
    if faces.ndim==2 and np.issubdtype(faces.dtype,np.integer):
        arity=faces.shape[1]
        if arity<3 or faces.min()<0 or faces.max()>=n_vertices:
            raise ValueError("Invalid polygon indices/arity")
        triangles=np.stack([faces[:,[0,i,i+1]] for i in range(1,arity-1)],axis=1).reshape(-1,3)
        return triangles.astype(np.int32),{str(arity):len(faces)}
    if faces.ndim!=1:
        raise ValueError("Invalid polygon array")
    counts={};triangles=[]
    for face in faces:
        face=np.asarray(face)
        if face.ndim!=1 or not np.issubdtype(face.dtype,np.integer) or len(face)<3 or face.min()<0 or face.max()>=n_vertices:
            raise ValueError("Invalid polygon indices/arity")
        counts[str(len(face))]=counts.get(str(len(face)),0)+1
        triangles.extend([[face[0],face[i],face[i+1]] for i in range(1,len(face)-1)])
    return np.asarray(triangles,dtype=np.int32),counts


def frame_split(stop, prefix_stop):
    if not isinstance(stop,int) or not isinstance(prefix_stop,int) or not 2 <= prefix_stop < stop:
        raise ValueError("Need a nonempty calibration prefix and evaluation tail")
    ids=np.arange(stop,dtype=np.int32)
    mapping=ids%2==0
    return {"original_frame_id":ids,"model_input_rgb":mapping,
            "calibration_pose":mapping & (ids<prefix_stop),
            "primary_eval_view":~mapping & (ids>=prefix_stop),
            "primary_candidate_anchor_eligible":mapping & (ids>=prefix_stop),
            "unused_prefix_odd":~mapping & (ids<prefix_stop)}


def validate_poses(poses, required, atol=1e-5):
    poses=np.asarray(poses,dtype=np.float64)
    if poses.ndim!=3 or poses.shape[1:]!=(4,4) or len(poses)<required or not np.isfinite(poses).all():
        raise ValueError("Missing/invalid row-major GT poses")
    if not np.allclose(poses[:,3,:],[0,0,0,1],atol=atol,rtol=0):
        raise ValueError("Invalid homogeneous pose row")
    rotations=poses[:,:3,:3]
    orth=np.max(np.abs(rotations.transpose(0,2,1)@rotations-np.eye(3)))
    det=np.max(np.abs(np.linalg.det(rotations)-1))
    if orth>atol or det>atol:
        raise ValueError("GT pose contains scale, reflection or non-rotation")
    return {"pose_rows":len(poses),"rotation_orthogonality_max_abs_error":float(orth),
            "rotation_determinant_max_abs_error":float(det)}


def cross_view_gt_depth(source_depth,target_depth,source_c2w,target_c2w,K,qa):
    """Fixed-grid GT-only forward reprojection; report occlusion outliers too."""
    if source_depth.shape!=target_depth.shape:
        raise ValueError("RGB/depth grid shapes differ")
    sv,se=depth_masks(source_depth,qa["edge_mask"])
    tv,te=depth_masks(target_depth,qa["edge_mask"])
    h,w=source_depth.shape
    v,u=np.indices((h,w)); stride=qa["cross_view_sample_grid_stride"]
    keep=sv & ~se & (u%stride==0) & (v%stride==0)
    uv=np.column_stack([u[keep],v[keep]])
    local=backproject_z(uv,source_depth[keep],K)
    target=transform_points(local,np.linalg.inv(target_c2w)@source_c2w)
    front=np.isfinite(target).all(1)&(target[:,2]>0)
    target=target[front]
    target_uv=np.rint(project(target,K)).astype(int)
    inside=(target_uv[:,0]>=0)&(target_uv[:,0]<w)&(target_uv[:,1]>=0)&(target_uv[:,1]<h)
    target,target_uv=target[inside],target_uv[inside]
    x,y=target_uv[:,0],target_uv[:,1]
    good=tv[y,x]&~te[y,x]
    residual=np.abs(target[good,2]-target_depth[y[good],x[good]])
    tolerance=np.maximum(qa["cross_view_consistency_abs_tolerance_m"],
                         qa["cross_view_consistency_relative_tolerance"]*target_depth[y[good],x[good]])
    median=float(np.median(residual)) if len(residual) else None
    fraction=float(np.mean(residual<=tolerance)) if len(residual) else None
    passed=(len(residual)>=qa["cross_view_min_common_samples"] and
            median<=qa["cross_view_median_abs_depth_residual_max_m"] and
            fraction>=qa["cross_view_min_consistent_fraction"])
    return {"status":"PASS" if passed else "FAIL","source_samples":len(uv),"target_common_samples":len(residual),
            "median_abs_z_residual_m":median,"p95_abs_z_residual_m":float(np.percentile(residual,95)) if len(residual) else None,
            "consistent_fraction":fraction,"note":"GT data alignment QA; forward warp retains remaining occlusion outliers; no predicted map involved"}
