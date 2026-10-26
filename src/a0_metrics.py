"""Mask-explicit oracle contrasts; coverage is never inferred from small error."""
import numpy as np


def depth_state(numerator,weight,gt,valid,weight_min=.001,abs_tol=.05,rel_tol=.02):
    pred=np.divide(numerator,weight,out=np.zeros_like(numerator,dtype=np.float32),where=weight>weight_min)
    covered=(weight>weight_min)&np.isfinite(pred)&(pred>0)
    error=np.abs(pred-gt)
    correct=covered&(error<=np.maximum(abs_tol,rel_tol*gt))
    good=valid&covered
    return pred,covered,correct,{"gt_pixels":int(valid.sum()),"covered_pixels":int(good.sum()),
        "coverage":float(good.sum()/valid.sum()) if valid.any() else None,
        "correct_coverage":float((valid&correct).sum()/valid.sum()) if valid.any() else None,
        "mae_m":float(error[good].mean()) if good.any() else None,
        "absrel":float((error[good]/gt[good]).mean()) if good.any() else None}


def common_covered_metrics(predictions,coverages,gt,valid):
    if set(predictions)!=set(coverages):raise ValueError("Arm sets differ")
    mask=valid.copy()
    for key in predictions:
        if predictions[key].shape!=gt.shape or coverages[key].shape!=gt.shape:raise ValueError("Shape differs")
        mask &= coverages[key]&np.isfinite(predictions[key])
    return mask,{key:{"common_pixels":int(mask.sum()),
        "mae_m":float(np.abs(predictions[key][mask]-gt[mask]).mean()) if mask.any() else None,
        "absrel":float((np.abs(predictions[key][mask]-gt[mask])/gt[mask]).mean()) if mask.any() else None}
        for key in predictions}


def factorial(errors):
    if set(errors)!={"A00","A10","A01","A11"}:raise ValueError("Four error values required")
    if any(v is None or not np.isfinite(v) for v in errors.values()):raise ValueError("Finite errors required")
    base,local,pose,both=[errors[k] for k in ("A00","A10","A01","A11")]
    return {"delta_local":base-local,"delta_placement":base-pose,
            "interaction":both-local-pose+base,"joint_improvement":base-both,
            "local_gain_relative_to_baseline":(base-local)/base if base else None,
            "placement_gain_relative_to_baseline":(base-pose)/base if base else None}


def mean_rows(rows,keys):
    return {key:float(np.mean([r[key] for r in rows if r[key] is not None]))
            if any(r[key] is not None for r in rows) else None for key in keys}
