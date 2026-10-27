#!/usr/bin/env python3
"""Independent cache-based recomputation of the primary A2-S common3 contrasts."""
import csv,json,sys
from pathlib import Path
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/A2_S_scalar_spatial/2026-10-27';sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a2_s_common import dump_json,digest
from e1_taxonomy import resize_depth,depth_masks

def read(p):
    with open(p,newline='') as f:return list(csv.DictReader(f))
def main():
  result={}
  for scene in ['office2','office3']:
    camera=json.load(open(ROOT/'data/N2/Replica/cam_params.json'))['camera'];contract=json.load(open(ROOT/'configs/n1_coordinate_contract.json'))['common_mask'];maps=json.load(open(OUT/scene/'maps/manifest.json'))['maps'];by={(x['gauge'],x['fold'],x['method']):OUT/scene/'evaluation/depth'/x['file']['sha256'] for x in maps};fits=json.load(open(OUT/scene/'fits/fit_parameters.json'));stored=read(OUT/scene/'evaluation/scalar_sufficiency.csv');details=[];root=ROOT/'data/N2/Replica'/scene
    for g in ['position','orientation']:
      for fold in [0,1]:
        vals={m:[] for m in ['S0','Sk','Sf']};support=0;covsum={m:[] for m in ['S0','Sk','Sf']};correctsum={m:[] for m in ['S0','Sk','Sf']};common_pixels=0
        for frame in range(201,1000,2):
          raw=cv2.imread(str(root/'results'/f'depth{frame:06d}.png'),cv2.IMREAD_UNCHANGED);gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,contract);inside=valid&~edge;arrays={}
          for m in ['S0','Sk','Sf']:
            with np.load(by[(g,fold,m)]/f'frame{frame:04d}.npz') as x:
              w=x['weight'];d=x['depth'];pred=np.divide(d,w,out=np.zeros_like(d),where=w>1e-9);cover=(w>.001)&(pred>0)&np.isfinite(pred)
            arrays[m]=(pred,cover);own=inside&cover;covsum[m].append(float(own.sum()/max(1,inside.sum())));cor=cover&(np.abs(pred-gt)<=np.maximum(.05,.02*gt));correctsum[m].append(float(np.sum(cor&inside)/max(1,inside.sum())))
          common=inside.copy()
          for m in arrays:common &= arrays[m][1]
          common_pixels+=int(common.sum())
          if common.sum()>=1000 and common.sum()/max(1,inside.sum())>=.5:support+=1
          for m in vals:
            p=arrays[m][0];vals[m].append(float(np.mean(np.abs(p[common]-gt[common]))) if common.any() else None)
        E={m:float(np.mean([x for x in vals[m] if x is not None])) for m in vals}
        source=next(x for x in fits[g][str(fold)]['fits'].values() if x.get('support',False));kf_fraction=fits[g][str(fold)]['kf_support_fraction'];candidate_fraction=fits[g][str(fold)]['candidate_support_fraction'];eligible=kf_fraction>=.8 and candidate_fraction>=.8 and support/400>=.8 and E['S0']>0
        gain=E['S0']-E['Sf'];ratio=(E['S0']-E['Sk'])/gain if eligible and gain>0 and gain/E['S0']>=.1 else None
        if not eligible:label='INSUFFICIENT_SUPPORT';ratio=None
        elif gain<=0 or gain/E['S0']<.1:label='FIELD_GAIN_NOT_ESTABLISHED';ratio=None
        elif np.mean(covsum['Sk'])<np.mean(covsum['S0'])-1e-6 or np.mean(covsum['Sf'])<np.mean(covsum['S0'])-1e-6 or np.mean(correctsum['Sk'])<np.mean(correctsum['S0'])-.01 or np.mean(correctsum['Sf'])<np.mean(correctsum['S0'])-.01:label='COVERAGE_TRADEOFF'
        else:label='SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD' if ratio>=.9 else 'RESIDUAL_FIELD_OPPORTUNITY'
        row=next(x for x in stored if x['gauge']==g and int(x['fold'])==fold)
        for key,m in [('E0','S0'),('Ek','Sk'),('Ef','Sf')]:assert abs(float(row[key])-E[m])<1e-12,(scene,g,fold,key,row[key],E[m])
        assert row['label']==label and support==int(float(row['target_support_fraction'])*400)
        details.append(dict(gauge=g,fold=fold,E=E,label=label,target_support_views=support,common3_pixel_sum=common_pixels,interior_coverage={m:float(np.mean(covsum[m])) for m in covsum},interior_correct_coverage={m:float(np.mean(correctsum[m])) for m in correctsum}))
    result[scene]=dict(status='PASS',primary_independent_recompute=details,target_rows=digest(OUT/scene/'evaluation/target_methods.csv'),source_fits=digest(OUT/scene/'fits/fit_parameters.json'))
  dump_json(OUT/'independent_verification.json',dict(status='PASS',scenes=result,method='reloaded GT depth and renderer caches; recalculated common3, equal-view MAE, target support and registered decision rule'))
if __name__=='__main__':main()
