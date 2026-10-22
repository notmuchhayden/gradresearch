"""Development-only calibration after immutable E4c geometric extraction."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts')]
from run_e4c_v2 import OUT,COMBOS,checked
from prepare_e2b_run import digest,save_json


def metric(reject,labels,active,finite,anchors):
    S=active&(labels==1);O=active&(labels==2);U=active&(labels==0)
    sr=int((S&reject).sum());o=int((O&reject).sum())
    ratios=lambda numerator,denominator:float(numerator/denominator) if denominator else None
    return dict(active=int(active.sum()),S=int(S.sum()),O=int(O.sum()),U=int(U.sum()),
        rejected=int((active&reject).sum()),S_rejected=sr,O_rejected=o,U_rejected=int((U&reject).sum()),
        S_retention=ratios(int(S.sum())-sr,int(S.sum())),O_recall=ratios(o,int(O.sum())),
        precision=ratios(o,o+sr),finite_S=int((finite&S).sum()),finite_O=int((finite&O).sum()),
        finite_S_retention=ratios(int((finite&S&~reject).sum()),int((finite&S).sum())),
        anchor_S=[dict(anchor=int(a),S=int((S&(anchors==a)).sum()),
            retention=ratios(int((S&(anchors==a)&~reject).sum()),int((S&(anchors==a)).sum())))
            for a in np.unique(anchors[active])])


def replay(scene,key,kind,threshold,active,anchors,dest):
    n=int((OUT/'development'/scene/'history'/'snapshot0000.npz').exists())
    first=np.full(len(active),-1,np.int32);revision=first.copy();state=np.zeros(len(active),np.uint8)
    for index,path in enumerate(sorted((OUT/'development'/scene/'history').glob('*.npz'))):
        with np.load(path) as h:
            a=h[key+'_'+kind].reshape(-1);count=len(a)
            born=active&(anchors<=index);state[born&(state==0)]=1
            current=active[:count]&(state[:count]!=2)&np.isfinite(a)&(a>threshold)
            ids=np.flatnonzero(current);state[ids]=2;first[ids]=h['input_frame'];revision[ids]=h['pose_revision']
    reject=active&(state==2)
    np.savez_compressed(dest/f'{key}_{kind}_decisions.npz',active=active,rejected=reject,
        natural_membership=active&~reject,first_reject=first,reject_revision=revision,state=state)
    return reject


def main():
    spec=checked();target=ROOT/'configs/e4c_v2_development_calibration.json'
    if target.exists():raise RuntimeError('Completed calibration preserved')
    loaded={};inputs=[]
    for scene in spec['development']:
        path=OUT/'development'/scene
        summary=json.loads((path/'geometry_summary.json').read_text())
        for e in summary['artifacts']:assert digest(ROOT/e['path'])==e
        loaded[scene]=(dict(np.load(path/'features.npz')),np.load(path/'audit_labels.npz')['labels'])
        inputs += [digest(path/'geometry_summary.json'),digest(path/'features.npz'),digest(path/'audit_labels.npz')]
    combinations={};any_calibrated=False;any_minimum=False
    for cs,ch in COMBOS:
        key=f'c{cs}_{ch}';thresholds={};groups=[];failures=[]
        for scene,(f,labels) in loaded.items():
            active=f['active'];common=np.isfinite(f[key+'_shadow_s'])&np.isfinite(f[key+'_shadow_d'])
            if int((active&(labels==2)).sum())<100:
                failures.append(f'{scene}: fewer than 100 audit O')
            if int((active&common&(labels==2)).sum())<100:
                failures.append(f'{scene}: fewer than 100 common audit O')
        for kind,shadow in [('s','shadow_s'),('d','shadow_d')]:
            quantiles=[]
            for scene,(f,labels) in loaded.items():
                finite=np.isfinite(f[key+'_'+shadow]);s=f['active']&(labels==1)&finite
                common=np.isfinite(f[key+'_shadow_s'])&np.isfinite(f[key+'_shadow_d'])
                candidates=[('own',s,True),('common',s&common,True)]
                candidates += [(f'anchor_{a}',s&(f['anchor_kf']==a),False) for a in np.unique(f['anchor_kf'])]
                for name,mask,required in candidates:
                    enough=int(mask.sum())>=100
                    q=float(np.quantile(f[key+'_'+shadow][mask],.99,method='higher')) if enough else None
                    groups.append(dict(method=kind,scene=scene,group=name,count=int(mask.sum()),required=required,quantile=q))
                    if enough:quantiles.append(q)
                    elif required:failures.append(f'{kind}/{scene}/{name}: fewer than 100 finite audit S')
            thresholds[kind]=max([1. if kind=='s' else 0.]+quantiles) if quantiles else None
        metrics={}
        if failures:
            status='INCONCLUSIVE_CALIBRATION'
            thresholds={k:None for k in thresholds}
        else:
            any_calibrated=True;passes=[]
            for scene,(f,labels) in loaded.items():
                dest=OUT/'development'/scene/'calibrated';dest.mkdir(exist_ok=True)
                metrics[scene]={}
                for kind in ['s','d']:
                    reject=replay(scene,key,kind,thresholds[kind],f['active'],f['anchor_kf'],dest)
                    expected=f['active']&np.isfinite(f[key+'_'+kind])&(f[key+'_'+kind]>thresholds[kind])
                    np.testing.assert_array_equal(reject,expected)
                    finite=np.isfinite(f[key+'_shadow_'+kind])
                    m=metric(reject,labels,f['active'],finite,f['anchor_kf']);metrics[scene][kind]=m
                m=metrics[scene]['s']
                minimum=m['O_rejected']>=30 and m['O_recall'] is not None and m['O_recall']>=.05
                preservation=m['S_retention'] is not None and m['S_retention']>=.99 and m['finite_S_retention']>=.99
                preservation &= all(g['S']<100 or g['retention']>=.99 for g in m['anchor_S'])
                passes.append(bool(minimum and preservation))
            any_minimum |= all(passes)
            status='MAP_EVALUATION_REQUIRED' if all(passes) else 'REVISE_DEVELOPMENT_MINIMUM_OR_PRESERVATION'
        combinations[key]=dict(status=status,thresholds=thresholds,groups=groups,failures=failures,metrics=metrics)
    result=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
        status='NEXT_STAGE_REQUIRED' if any_minimum else ('REVISE' if any_calibrated else 'INCONCLUSIVE'),
        combinations=combinations,inputs=inputs,code=digest(Path(__file__)),
        external_GT_used_for_thresholds=False,fresh_scenes_opened=False,
        map_metrics_measured=False,legacy_comparisons_measured=False,
        reason='Development audit/calibration gate; no efficacy GO issued')
    save_json(target,result);save_json(OUT/'development_calibration.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
