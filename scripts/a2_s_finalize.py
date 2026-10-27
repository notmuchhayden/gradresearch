#!/usr/bin/env python3
"""Assemble immutable A2-S summaries, paired gauge contrasts and final manifest."""
import csv,json,hashlib,platform,sys
from pathlib import Path
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/A2_S_scalar_spatial/2026-10-27';sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a2_s_common import kfs,digest,dump_json
from e1_taxonomy import resize_depth,depth_masks

def rows(path):
    with open(path,newline='') as f:return list(csv.DictReader(f))
def main():
    summary={'experiment':'A2-S scalar bias vs fixed spatial field diagnostic','status':'COMPLETE_DIAGNOSTIC','date':'2026-10-27','scenes':{},'scope_limits':['GT-fit Sk/SkH/Sf are oracle diagnostics, not RGB-only methods','office3 was previously used validation, not independent test','no office4 or HKairport access','A2-O, correction algorithms, D/P implementation and joint optimizer not run']}
    gauge_pairs=[]
    for scene in ['office2','office3']:
      scalar=rows(OUT/scene/'evaluation/scalar_sufficiency.csv');src=rows(OUT/scene/'analysis/source_spatial_residuals.csv');contr=rows(OUT/scene/'evaluation/target_common4_contrasts.csv');surf=rows(OUT/scene/'evaluation/surface_metrics.csv');rgb=rows(OUT/scene/'evaluation/rgb_metrics.csv')
      fit=json.load(open(OUT/scene/'fits/fit_parameters.json'));scenes={}
      for g in ['position','orientation']:
       scenes[g]={}
       for fold in [0,1]:
        key=f'{g}/fold{fold}';s=next(x for x in scalar if x['gauge']==g and int(x['fold'])==fold);c={x['method']:x for x in contr if x['gauge']==g and int(x['fold'])==fold}
        source={m:float(np.mean([float(x['mae_z_m']) for x in src if x['gauge']==g and int(x['fold'])==fold and x['method']==m and x['supported']=='True'])) for m in ['S0','Sg','Sk','SkH','Sf']}
        scenes[g][str(fold)]={'primary':{k:(None if s[k] in ('',None) else (s[k] if k=='label' else float(s[k]))) for k in ['E0','Ek','Ef','field_gain','scalar_gain','ratio','label','target_support_fraction','interior_coverage_S0','interior_coverage_Sk','interior_coverage_Sf','correct_coverage_S0','correct_coverage_Sk','correct_coverage_Sf']},'common4_equal_view_mae':{m:float(c[m]['common4_equal_view_mae']) for m in ['S0','Sk','SkH','Sf']},'source_opposite_tile_equal_KF_mae_z_m':source,'support':{'postprefix_KFs_supported':int(fit[g][str(fold)]['kf_support_fraction']*sum(r['kf_idx']>=0 for r in src if r['gauge']==g and int(r['fold'])==fold and r['method']=='ALL') if False else sum(1 for x in fit[g][str(fold)]['fits'].values() if x['support'])), 'postprefix_KFs_total':len(fit[g][str(fold)]['fits']),'strict_candidate_fraction':float(fit[g][str(fold)]['candidate_support_fraction']),'prefix_fit_pixels':int(fit[g][str(fold)]['prefix_n'])}}
      # Explicit scene-level rule: both folds in both gauges must pass to claim robust scene scalar sufficiency.
      labels=[scenes[g][str(f)]['primary']['label'] for g in scenes for f in [0,1]]
      summary['scenes'][scene]={'gauge_fold':scenes,'scene_scalar_sufficiency':'SCALAR_SUFFICIENT' if all(x=='SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD' for x in labels) else 'NOT_ESTABLISHED_IN_BOTH_FOLDS_AND_GAUGES','source_support':{'all_supported':all(v['support']['strict_candidate_fraction']>=.8 and v['support']['postprefix_KFs_supported']>=.8*v['support']['postprefix_KFs_total'] for g in scenes.values() for v in g.values())},'surface_position':surf,'rgb_5view_mean':{m:{'psnr_db':float(np.mean([float(x['psnr_db']) for x in rgb if x['method']==m])),'ssim':float(np.mean([float(x['ssim']) for x in rgb if x['method']==m]))} for m in sorted(set(x['method'] for x in rgb))}}
      # Paired six-map comparison with the exact common interior pixels, rendered caches, and equal view weight.
      base=ROOT/'data/N2/Replica'/scene;camera=json.load(open(ROOT/'data/N2/Replica/cam_params.json'))['camera'];contract=json.load(open(ROOT/'configs/n1_coordinate_contract.json'))['common_mask'];frames=list(range(201,1000,2));keys={}
      mm=json.load(open(OUT/scene/'maps/manifest.json'))['maps']
      for x in mm:keys[(x['gauge'],x['fold'],x['method'])]=x['file']['sha256']
      for fold in [0,1]:
       errs={g:{m:[] for m in ['S0','Sk','Sf']} for g in ['position','orientation']}
       for frame in frames:
        raw=cv2.imread(str(base/'results'/f'depth{frame:06d}.png'),cv2.IMREAD_UNCHANGED);gt=resize_depth(raw.astype(np.float32)/camera['scale'],camera);valid,edge=depth_masks(gt,contract);common=valid&~edge;pred={}
        for g in ['position','orientation']:
         for m in ['S0','Sk','Sf']:
          p=OUT/scene/'evaluation/depth'/keys[(g,fold,m)]/f'frame{frame:04d}.npz'
          with np.load(p) as z:
           w=z['weight'];d=z['depth'];y=np.divide(d,w,out=np.zeros_like(d),where=w>1e-9);cov=(w>.001)&(y>0)&np.isfinite(y)
          pred[(g,m)]=(y,cov);common &= cov
        for g in ['position','orientation']:
         for m in ['S0','Sk','Sf']:
          y,cov=pred[(g,m)];errs[g][m].append(float(np.mean(np.abs(y[common]-gt[common]))) if common.any() else None)
       for g in ['position','orientation']:
        vals={m:float(np.mean([x for x in errs[g][m] if x is not None])) if any(x is not None for x in errs[g][m]) else None for m in errs[g]}
        gauge_pairs.append(dict(scene=scene,fold=fold,gauge=g,common6_equal_view_E0=vals['S0'],common6_equal_view_Ek=vals['Sk'],common6_equal_view_Ef=vals['Sf'],common6_views=sum(x is not None for x in errs[g]['S0'])))
    with (OUT/'gauge_pairs.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(gauge_pairs[0]));w.writeheader();w.writerows(gauge_pairs)
    # Final verification extends stage verification to the surface/RGB artifacts.
    for scene in ['office2','office3']:
      assert json.load(open(OUT/scene/'verification.json'))['status']=='PASS'
      for p in [OUT/scene/'evaluation/surface_manifest.json',OUT/scene/'evaluation/rgb_manifest.json']:
        meta=json.load(open(p));assert meta['status']=='PASS'
    assert json.load(open(OUT/'independent_verification.json'))['status']=='PASS'
    dump_json(OUT/'results_summary.json',summary)
    source_code=[digest(ROOT/p) for p in ['configs/a2_s_scalar_spatial_protocol.json','src/scalar_spatial_diagnostic.py','scripts/a2_s_common.py','scripts/run_a2_s.py','scripts/a2_s_surface.py','scripts/a2_s_visualize.py','scripts/a2_s_independent_verify.py','scripts/a2_s_finalize.py','tests/test_scalar_spatial_diagnostic.py','src/gauge_support.py','src/pointmap_contract.py','scripts/evaluate_e4.py','src/e4_budget.py']]
    commands=['.venv/bin/python -m unittest discover -s tests -p test_scalar_spatial_diagnostic.py', '.venv/bin/python scripts/run_a2_s.py preflight --config configs/a2_s_scalar_spatial_protocol.json','.venv/bin/python scripts/run_a2_s.py register --config configs/a2_s_scalar_spatial_protocol.json']
    commands += [f'.venv/bin/python scripts/run_a2_s.py {cmd} --scene office2 --config configs/a2_s_scalar_spatial_protocol.json' for cmd in ['fit','build','evaluate','analyze','verify']]
    commands += ['.venv/bin/python scripts/run_a2_s.py seal --config configs/a2_s_scalar_spatial_protocol.json']
    commands += [f'.venv/bin/python scripts/run_a2_s.py {cmd} --scene office3 --config configs/a2_s_scalar_spatial_protocol.json' for cmd in ['fit','build','evaluate','analyze','verify']]
    commands += ['.venv/bin/python scripts/a2_s_surface.py --scene office2','.venv/bin/python scripts/a2_s_surface.py --scene office3','.venv/bin/python scripts/a2_s_visualize.py --scene office2','.venv/bin/python scripts/a2_s_visualize.py --scene office3','.venv/bin/python scripts/a2_s_independent_verify.py','.venv/bin/python scripts/a2_s_finalize.py']
    artifacts=[digest(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in {'execution_manifest.json'}]
    manifest={'status':'COMPLETE_DIAGNOSTIC','execution_date':'2026-10-27','timezone':'Asia/Seoul','protocol':digest(ROOT/'configs/a2_s_scalar_spatial_protocol.json'),'registered_code':source_code,'registration':digest(OUT/'registration.json'),'development_seal':digest(OUT/'development_seal.json'),'office2_verification':digest(OUT/'office2/verification.json'),'office3_verification':digest(OUT/'office3/verification.json'),'amendments':[digest(p) for p in sorted((OUT/'amendments').glob('AMENDMENT_*.json'))],'documentation':[digest(ROOT/p) for p in ['docs/experiments/A2_S_scalar_spatial_results.md','docs/experiments/A1_route_decision.md','docs/pointmap_pose_error_decomposition_research_plan_v1.md','configs/a2_s_results_summary.json']],'environment':{'gpu':'NVIDIA GeForce RTX 5060, 8GB','torch':'2.13.0+cu132','cuda':'13.2','python':sys.version,'numpy':np.__version__,'open3d':'0.19.0','tf32':False},'commands':commands,'artifacts':artifacts,'unexecuted':['A2-O','D/P algorithms','joint optimizer','office4','HKairport']}
    dump_json(OUT/'execution_manifest.json',manifest);dump_json(ROOT/'configs/a2_s_execution_manifest.json',manifest);dump_json(ROOT/'configs/a2_s_results_summary.json',summary)
if __name__=='__main__':main()
