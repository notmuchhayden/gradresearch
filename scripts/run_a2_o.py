#!/usr/bin/env python3
"""Preflight and provenance-gated execution driver for A2-O."""
import argparse, csv, hashlib, json, shutil, sys, time
from pathlib import Path
from functools import lru_cache
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a2_s_common import kfs as _kfs,base_map,digest,dump_json,sha,packed
from rgb_observability import scalar_grid,dct_modes,bilinear_basis,profile_digest,shared_scale_residual

OUT=ROOT/'results/A2_O_rgb_observability/2026-10-27'
CFG=ROOT/'configs/a2_o_rgb_observability_protocol.json'
PLAN=ROOT/'docs/experiments/A2_O_execution_plan.md'

def baseline(scene):
    return ROOT/('results/A0_pointmap_pose_factorial/office2/baseline' if scene=='office2' else 'results/V1_office3_diagnostic/2026-10-26/baseline')

@lru_cache(maxsize=2)
def kfs(scene):
    return _kfs(scene)

def final_snapshot(scene):
    p=baseline(scene)/'audit/snapshots/input000499_final.pt'
    if not p.exists(): raise FileNotFoundError(p)
    import torch
    return torch.load(p,map_location='cpu',weights_only=True)

@lru_cache(maxsize=2)
def events(scene):
    import torch
    root=baseline(scene); final=final_snapshot(scene)
    raw={}
    metadata={int(x['kf_idx']):x for x in final['metadata']}
    assert len(metadata)==len(kfs(scene))
    rows=[]
    for k in kfs(scene):
        m=metadata[k['kf_idx']]
        # Baseline snapshots and raw-pair IDs are subsample indices in both scenes;
        # office3 canonical local source_frame is already original-frame space.
        assert 2*int(m['frame_id'])==k['original_frame']
        event=m.get('candidate_event')
        ep=root/'exports/raw_pairs'/f'{event}.pt' if event else None
        rec=torch.load(ep,map_location='cpu',weights_only=True) if ep is not None and ep.exists() else None
        if rec is not None: raw[event]=rec
        status=m.get('fused',{}).get('status','unknown')
        if rec is None or event is None:
            ancestry=[];reason='UNKNOWN_PROVENANCE'
        elif status not in ('traced','known'):
            ancestry=sorted(set(map(int,rec.get('source_image_ids',[]))))
            reason='UNKNOWN_PROVENANCE'
        else:
            ancestry=sorted(set(map(int,rec.get('source_image_ids',[]))))
            reason=None if ancestry else 'UNKNOWN_PROVENANCE'
        rows.append(dict(kf_idx=k['kf_idx'],original_frame=k['original_frame'],candidate_event=event,
                         candidate_sources=ancestry,lineage_status=status,final_pose_revision=int(final['pose_revision']),
                         final_snapshot=str((baseline(scene)/'audit/snapshots/input000499_final.pt').relative_to(ROOT)),
                         reason=reason))
    return rows,raw

def pairs_for(scene):
    rows,raw=events(scene); bykf={r['kf_idx']:r for r in rows}
    evidence=sorted([r for r in rows if r['original_frame']>=200],key=lambda r:(r['original_frame'],r['kf_idx']))
    result=[]
    for s in evidence:
        if not s['candidate_sources'] or s['reason']:
            result.append(dict(scene=scene,source_kf=s['kf_idx'],source_frame=s['original_frame'],evidence_kf='',
                               status='UNKNOWN_PROVENANCE',reason=s['reason'] or 'unknown_source'))
            continue
        valid=[]
        for e in evidence:
            if e['kf_idx']==s['kf_idx']: continue
            if not e['candidate_sources'] or e['reason']:
                result.append(dict(scene=scene,source_kf=s['kf_idx'],source_frame=s['original_frame'],evidence_kf=e['kf_idx'],
                                   evidence_frame=e['original_frame'],status='UNKNOWN_PROVENANCE',reason=e['reason'] or 'unknown_evidence'))
            elif set(s['candidate_sources']).isdisjoint(e['candidate_sources']):
                valid.append(e)
            else:
                result.append(dict(scene=scene,source_kf=s['kf_idx'],source_frame=s['original_frame'],evidence_kf=e['kf_idx'],
                                   evidence_frame=e['original_frame'],status='SHARED_SOURCE',reason='candidate_image_ancestry_overlap'))
        valid.sort(key=lambda x:(x['original_frame'],x['kf_idx']))
        for i,e in enumerate(valid):
            result.append(dict(scene=scene,source_kf=s['kf_idx'],source_frame=s['original_frame'],evidence_kf=e['kf_idx'],
                               evidence_frame=e['original_frame'],pool='rgb_fit' if i%2==0 else 'rgb_audit',
                               source_images=s['candidate_sources'],evidence_images=e['candidate_sources'],
                               source_event=s['candidate_event'],evidence_event=e['candidate_event'],
                               final_pose_revision=s['final_pose_revision'],evidence_pose_revision=e['final_pose_revision'],
                               status='PROVENANCE_DISJOINT',reason=''))
    return result

def cmd_preflight():
    OUT.mkdir(parents=True,exist_ok=True)
    spec=json.loads(CFG.read_text()); report={'status':'PASS_QA','protocol':digest(CFG),'scenes':{},'environment':{}}
    import torch,cv2
    report['environment']={'python':sys.version.split()[0],'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),
                           'opencv':cv2.__version__,'torch_threads':2,'opencv_threads':2}
    for scene in spec['scenes']:
        Ks=kfs(scene); expected=(11,1545979,1200827) if scene=='office2' else (8,1136762,855796)
        n_native=sum(len(k['y']) for k in Ks);n_strict=sum(int(k['strict'].sum()) for k in Ks)
        assert (len(Ks),n_native,n_strict)==expected,(scene,len(Ks),n_native,n_strict)
        assert all((k['H'],k['W'])==(288,512) for k in Ks)
        rows,pairs_raw=events(scene);pair_rows=pairs_for(scene)
        usable={r['source_kf'] for r in pair_rows if r.get('pool')=='rgb_fit'}
        audit={r['source_kf'] for r in pair_rows if r.get('pool')=='rgb_audit'}
        report['scenes'][scene]={'native_keyframes':len(Ks),'native_candidates':n_native,'strict_candidates':n_strict,
             'frames':[k['original_frame'] for k in Ks],'final_pose_revision':rows[0]['final_pose_revision'],
             'final_snapshot':digest(ROOT/rows[0]['final_snapshot']),'source_manifest_rows':len(rows),
             'raw_pair_events':len(pairs_raw),'provenance_fit_sources':len(usable),'provenance_audit_sources':len(audit),
             'pair_rows':len(pair_rows),'local_files':[digest(k['local_path']) for k in Ks],
             'gauge_maps':{g:digest(base_map(scene,g)[0]) for g in ['position','orientation']}}
        out=OUT/scene/'pair_manifest.csv';out.parent.mkdir(parents=True,exist_ok=True)
        fields=list(dict.fromkeys(k for r in pair_rows for k in r))
        with out.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(pair_rows)
    dump_json(OUT/'preflight.json',report)
    print(json.dumps(report,indent=2))

def code_inventory():
    files=[CFG,PLAN,ROOT/'src/rgb_observability.py',ROOT/'scripts/run_a2_o.py',ROOT/'tests/test_rgb_observability.py',
           ROOT/'scripts/a2_s_common.py',ROOT/'src/scalar_spatial_diagnostic.py',ROOT/'src/gauge_support.py',
           ROOT/'src/pointmap_contract.py',ROOT/'configs/n1_coordinate_contract.json',ROOT/'configs/n2_dataset_manifest.json']
    return [digest(p) for p in files]

def cmd_register():
    if (OUT/'registration.json').exists(): raise RuntimeError('registration already exists; preserve it')
    pre=json.loads((OUT/'preflight.json').read_text());assert pre['status']=='PASS_QA'
    manifest=json.loads((ROOT/'configs/n2_dataset_manifest.json').read_text()); used=[]
    for row in manifest['files']:
        if row['path'].startswith(('data/N2/Replica/office2/','data/N2/Replica/office3/')) or row['path']=='data/N2/Replica/cam_params.json':
            p=ROOT/row['path'];assert p.exists() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],row['path'];used.append(row)
    code=code_inventory()
    dump_json(OUT/'registration.json',dict(status='REGISTERED_BEFORE_PROFILE',registered_before_fit=True,known_validation={'office3':True},
       protocol=code[0],code=code,dataset_files=used,preflight=digest(OUT/'preflight.json'),office4_accessed=False,hk_accessed=False,
       limitation='This registration does not authorize profile/evaluation until the provenance and runtime gates pass.'))
    dest=OUT/'registered_code';dest.mkdir(exist_ok=False)
    for item in code:
        src=ROOT/item['path'];target=dest/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
    print('REGISTERED_BEFORE_PROFILE')

def cmd_controls():
    out=OUT/'controls';out.mkdir(parents=True,exist_ok=True)
    grid=scalar_grid();modes=dct_modes();B=bilinear_basis(np.array([0.,127.5,511.]),np.array([0.,143.5,287.]))
    tests={'scalar_grid_n':len(grid),'scalar_zero_present':bool(np.any(grid==0)),
      'dct_modes':int(len(modes)),'dct_mean_max_abs':float(np.max(np.abs(modes.mean(1)))),
      'dct_rms_max_abs_error':float(np.max(np.abs(np.mean(modes**2,axis=1)-1))),
      'dct_orthogonality_max_abs_error':float(np.max(np.abs(modes@modes.T/16-np.eye(15)))),
      'bilinear_partition_max_abs_error':float(np.max(np.abs(B.sum(1)-1))),
      'joint_scale_log_residual_spread':float(np.ptp(shared_scale_residual([2,4,6],[2.2,4.4,6.6]))),
      'interpretation':'Common multiplicative depth bias cancels in predicted-depth agreement; absolute scale remains unobservable.'}
    tests['status']='PASS' if tests['scalar_grid_n']==41 and tests['dct_modes']==15 and tests['dct_mean_max_abs']<1e-12 and tests['dct_rms_max_abs_error']<1e-12 and tests['dct_orthogonality_max_abs_error']<1e-12 and tests['bilinear_partition_max_abs_error']<1e-12 and tests['joint_scale_log_residual_spread']<1e-12 else 'FAIL'
    dump_json(out/'specification.json',json.loads(CFG.read_text()));dump_json(out/'results.json',tests);print(json.dumps(tests,indent=2))

def cmd_prepare(scene):
    if not (OUT/'registration.json').exists():raise RuntimeError('register first')
    pf=json.loads((OUT/'preflight.json').read_text());data=pf['scenes'][scene]
    rows=list(csv.DictReader((OUT/scene/'pair_manifest.csv').open()))
    good=[r for r in rows if r.get('status')=='PROVENANCE_DISJOINT']
    counts={}
    for pool in ('rgb_fit','rgb_audit'):
        counts[pool]={}
        for r in good:
            if r.get('pool')==pool:counts[pool][r['source_kf']]=counts[pool].get(r['source_kf'],0)+1
    supported=[kf for kf in counts['rgb_fit'] if counts['rgb_fit'].get(kf,0)>=2 and counts['rgb_audit'].get(kf,0)>=2]
    out={'scene':scene,'status':'PROVENANCE_QA_PASS' if good else 'BLOCKED_UNKNOWN_OR_SHARED_PROVENANCE',
         'raw_pair_rows':len(rows),'provenance_disjoint_pairs':len(good),'fit_pair_counts':counts['rgb_fit'],
         'audit_pair_counts':counts['rgb_audit'],'kf_with_two_pairs_each_pool':len(supported),
         'post_prefix_kf_total':data['native_keyframes']-(1 if scene=='office2' else 1),
         'source_gt_accessed':False,'rgb_profile_computed':False,'cuda_available':pf['environment']['cuda_available']}
    dump_json(OUT/scene/'prepare_status.json',out);print(json.dumps(out,indent=2))

def profile_code_inventory():
    files=[CFG,PLAN,ROOT/'src/rgb_observability.py',ROOT/'scripts/a2_o_profile.py',
           ROOT/'scripts/run_a2_o.py',ROOT/'scripts/a2_s_common.py',ROOT/'scripts/run_a2_s.py',
           ROOT/'src/scalar_spatial_diagnostic.py',ROOT/'src/gauge_support.py',
           ROOT/'src/pointmap_contract.py',ROOT/'src/e1_taxonomy.py',
           ROOT/'configs/n1_coordinate_contract.json',ROOT/'tests/test_rgb_observability.py']
    return [digest(p) for p in files]

def cmd_register_profile():
    """Versioned code seal; preserve the earlier provenance-only registration."""
    from a2_o_profile import PROFILE_ROOT
    target=PROFILE_ROOT/'registration.json'
    if target.exists(): raise RuntimeError('profile registration exists; preserve it')
    prior=json.loads((OUT/'registration.json').read_text())
    assert prior['registered_before_fit'] is True
    assert json.loads((OUT/'controls/results.json').read_text())['status'].startswith('PASS')
    code=profile_code_inventory()
    dest=PROFILE_ROOT/'registered_code';dest.mkdir(parents=True,exist_ok=False)
    for item in code:
        src=ROOT/item['path'];p=dest/item['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,p)
    dump_json(target,{'status':'REGISTERED_BEFORE_RGB_PROFILE','registered_before_fit':True,
        'prior_provenance_registration':digest(OUT/'registration.json'),
        'preflight':digest(OUT/'preflight.json'),'code':code,'protocol':code[0],
        'office3_known_validation':True,'office4_accessed':False,'hk_accessed':False,
        'registered_after_out_of_sandbox_cuda_verification':digest(OUT/'cuda_verification.json')})
    print('REGISTERED_BEFORE_RGB_PROFILE')

def assert_profile_code(registration, code_root):
    for item in registration['code']:
        if digest(ROOT/item['path'])!=item:
            raise RuntimeError(f"registered profile code changed: {item['path']}")
        archived=digest(code_root/item['path'])
        if archived['bytes']!=item['bytes'] or archived['sha256']!=item['sha256']:
            raise RuntimeError(f"registered profile snapshot mismatch: {item['path']}")

def cmd_profile(scene):
    from a2_o_profile import PROFILE_ROOT,profile_scene
    registration=json.loads((PROFILE_ROOT/'registration.json').read_text())
    assert registration['status']=='REGISTERED_BEFORE_RGB_PROFILE'
    assert_profile_code(registration,PROFILE_ROOT/'registered_code')
    prepare=json.loads((OUT/scene/'prepare_status.json').read_text())
    if prepare['status']!='PROVENANCE_QA_PASS': raise RuntimeError('provenance QA failed')
    dest=PROFILE_ROOT/scene
    if (dest/'profiles.csv').exists() or (dest/'selected_parameters.json').exists():
        raise RuntimeError('profile output exists; preserve and use a new amendment attempt')
    result=profile_scene(scene)
    print(json.dumps({'scene':scene,'profile_count':result['profile_count'],
                      'selection_complete':result['selection_complete'],
                      'output':str((dest/'selected_parameters.json').relative_to(ROOT))},indent=2))

def cmd_freeze_selection(scene):
    from a2_o_profile import PROFILE_ROOT,freeze_scene
    registration=json.loads((PROFILE_ROOT/'registration.json').read_text())
    assert_profile_code(registration,PROFILE_ROOT/'registered_code')
    if (PROFILE_ROOT/scene/'selection_seal.json').exists():
        raise RuntimeError('selection seal exists; preserve it')
    seal=freeze_scene(scene,registration['code'],registration['protocol']['sha256'])
    print(json.dumps(seal,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['preflight','register','register-profile','controls','prepare','profile','freeze-selection','evaluate','verify','seal','report']);ap.add_argument('--scene',choices=['office2','office3']);ap.add_argument('--config',default=str(CFG));a=ap.parse_args()
    if Path(a.config).resolve()!=CFG.resolve():raise RuntimeError('A2-O uses its frozen protocol file')
    if a.command=='preflight':cmd_preflight()
    elif a.command=='register':cmd_register()
    elif a.command=='controls':cmd_controls()
    elif a.command=='register-profile':cmd_register_profile()
    elif a.command=='prepare':
        if not a.scene:ap.error('--scene required')
        cmd_prepare(a.scene)
    elif a.command=='profile':
        if not a.scene:ap.error('--scene required')
        cmd_profile(a.scene)
    elif a.command=='freeze-selection':
        if not a.scene:ap.error('--scene required')
        cmd_freeze_selection(a.scene)
    else:
        raise RuntimeError(f'{a.command} is not enabled: the remaining profile/evaluation implementation must pass provenance, GT-isolation, and runtime gates first')

if __name__=='__main__': main()
