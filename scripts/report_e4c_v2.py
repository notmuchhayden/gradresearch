"""Verify and report E4c's development feasibility gate without efficacy claims."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts')]
from run_e4c_v2 import OUT,checked,COMBOS
from prepare_e2b_run import digest,save_json


def main():
    spec=checked();cal=json.loads((OUT/'development_calibration.json').read_text())
    if cal['status']=='NEXT_STAGE_REQUIRED':raise RuntimeError('Map evaluation is required before a stopping report')
    if (ROOT/'configs/e4c_v2_validation.json').exists():raise RuntimeError('Completed validation preserved')
    inputs=json.loads((OUT/'input_manifest.json').read_text())['inputs']
    for e in inputs:assert digest(ROOT/e['path'])==e,e['path']
    for e in cal['inputs']:assert digest(ROOT/e['path'])==e
    assert digest(ROOT/cal['code']['path'])==cal['code']
    registration=json.loads((OUT/'protocol_registration.json').read_text())
    archived=digest(OUT/'sealed_code'/'docs/experiments/E4c_surface_consistency_pruning.md')
    assert archived['sha256']==registration['protocol']['sha256']
    old_inputs=json.loads((ROOT/'results/E4b_reference_plane_audit/input_manifest.json').read_text())['inputs']
    old_labels={e['path']:e for e in old_inputs if e['path'].endswith('/labels.npz')}
    rng=np.random.default_rng(0);results={};examples={};checks=[]
    for scene in spec['development']+spec['regression']:
        dest=OUT/'development'/scene;s=json.loads((dest/'geometry_summary.json').read_text())
        for e in s['artifacts']:assert digest(ROOT/e['path'])==e
        f=dict(np.load(dest/'features.npz'));y=np.load(dest/'audit_labels.npz')['labels'];active=f['active']
        assert set(np.unique(y)) <= {0,1,2}
        assert all((np.isfinite(f[f'c{cs}_{ch}_shadow_s'])==np.isfinite(f[f'c{cs}_{ch}_shadow_d'])).all() for cs,ch in COMBOS)
        # Prior labels are evaluation-only and first opened here, after calibration.
        lp=ROOT/spec['scene_sources'][scene]['labels']/'labels.npz';gt=np.load(lp)['creation']
        assert digest(lp)==old_labels[str(lp.relative_to(ROOT))]
        assert len(gt)==len(active)==len(y)
        matrix={str(a):{str(b):int((active&(y==a)&np.isin(gt,b)).sum())
                for b in [0,1,2,3]} for a in [0,1,2]}
        count=s['combinations']['c3_1'];assert count['S']==int((active&(y==1)).sum())
        assert count['O']==int((active&(y==2)).sum())
        audit_fraction=(count['S']+count['O'])/count['active']
        subsets={}
        for label,name in [(0,'U'),(1,'S'),(2,'O')]:
            ids=np.flatnonzero(active&(y==label));selected=np.sort(rng.choice(ids,min(8,len(ids)),replace=False))
            subsets[name]=selected.tolist()
        ids=np.flatnonzero(active&(y==1)&(gt==3));subsets['S_GT_bad']=np.sort(rng.choice(ids,min(8,len(ids)),replace=False)).tolist()
        examples[scene]=dict(selection_before_figures=True,array_indices=subsets,
          stable_id_rule='lineage[anchor_kf].event_id:self:pixel_index',
          stable_ids={k:[f"{json.loads((ROOT/spec['scene_sources'][scene]['scores']/'score_metadata.json').read_text())['lineage'][int(f['anchor_kf'][v])]['event_id']}:self:{int(f['pixel_index'][v])}" for v in values] for k,values in subsets.items()},
          limitation='No KEEP/REJECT sample strata: policy thresholds could not be calibrated')
        pairs=json.loads((dest/'audit_summary.json').read_text())
        meta=json.loads((ROOT/spec['scene_sources'][scene]['scores']/'score_metadata.json').read_text())
        all_pool_sources={v for j in s['policy'] for v in meta['lineage'][j]['source_images']}
        audit_sources={v for j in s['audit'] for v in meta['lineage'][j]['source_images']}
        assert not all_pool_sources.intersection(audit_sources)
        assert len(s['snapshots'])==meta['keyframes']
        previous=-1
        for index,row in enumerate(s['snapshots']):
            assert row['snapshot']==index and row['input_frame']>=previous;previous=row['input_frame']
            with np.load(dest/'history'/f'snapshot{index:04d}.npz') as h:
                assert h['input_frame']==row['input_frame'] and h['pose_revision']==row['revision']
        locals_by_combo={k:dict(local_protected_S=int((active&(y==1)&f[k+'_local']).sum()),
                               local_protected_O=int((active&(y==2)&f[k+'_local']).sum()))
                         for k in s['combinations']}
        results[scene]=dict(**s,audit_fraction=audit_fraction,GT_cross_matrix=matrix,
            protected_local_by_combo=locals_by_combo,GT_labels=digest(lp),
            feasibility=dict(audit_S_min100=count['S']>=100,audit_O_min100=count['O']>=100,
                audit_fraction_min1percent=audit_fraction>=.01,common_S_min100=count['common_S']>=100,
                common_O_min100=count['common_O']>=100))
        checks.append(dict(scene=scene,status='PASS',source_disjoint_pools=True,paired_finite_equal=True,
            audit_partition=True,snapshot_revisions=True,counts_verified=True,artifact_hashes_verified=True))
    save_json(OUT/'example_ids.json',examples)
    verification=dict(status='PASS',scope='Implemented development gate; not full E4c efficacy validation',
       inputs_rehashed=len(inputs),tests=11,scenes=checks,
       report_code=digest(Path(__file__)),seal=digest(OUT/'seal.json'),calibration=digest(OUT/'development_calibration.json'),
       fresh_data_opened=False,source_results_modified=False)
    save_json(ROOT/'configs/e4c_v2_validation.json',verification)
    overall=dict(status=cal['status'],scope='Development gate completed; fresh efficacy phase not entered',
        scenes=results,calibration=cal,validation=verification,
        omitted=dict(new_baselines=True,legacy_policy_comparison=True,ablation_calibration=True,
                     RGB_depth_TSDF=True,matched_count=True,CUDA_compaction=True),
        reason='Insufficient independently audited supported candidates with repeated policy observations',
        E4_decision='REVISE unchanged',E5_E6='hold unchanged')
    save_json(ROOT/'configs/e4c_results_summary.json',overall);save_json(OUT/'results_summary.json',overall)
    # Samples are fixed above before producing any figures.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    scenes=list(results);fig,axs=plt.subplots(1,2,figsize=(11,4))
    x=np.arange(len(scenes));sv=[results[s]['combinations']['c3_1']['S'] for s in scenes]
    ov=[results[s]['combinations']['c3_1']['O'] for s in scenes]
    axs[0].bar(x-.17,sv,.34,label='Audit surface support');axs[0].bar(x+.17,ov,.34,label='Audit outlier')
    axs[0].set_yscale('symlog',linthresh=1);axs[0].set_title('Audit labels (original active)');axs[0].legend(fontsize=8)
    cs=[results[s]['combinations']['c3_1']['common_S'] for s in scenes]
    co=[results[s]['combinations']['c3_1']['common_O'] for s in scenes]
    axs[1].bar(x-.17,cs,.34,label='Audit S + repeated policy');axs[1].bar(x+.17,co,.34,label='Audit O + repeated policy')
    axs[1].axhline(100,color='r',linestyle='--',label='Required 100');axs[1].set_title('Common observation feasibility');axs[1].legend(fontsize=8)
    for ax in axs:ax.set_xticks(x,scenes);ax.set_ylabel('Candidates')
    fig.tight_layout();figdir=ROOT/'docs/figures/E4c';figdir.mkdir(parents=True,exist_ok=True)
    fig.savefig(figdir/'development_feasibility.png',dpi=160);plt.close(fig)
    lines=['# E4c 결과: 표면 일관성 pruning의 개발 성립 검사','',
      f'**실행일: 2026-10-22. 판정: {cal["status"]}. 개발 성립 단계 완료, 새 장면 효능 검증 미진입.**','',
      '[계획](E4c_surface_consistency_pruning.md)과 [A1 분할 변경](E4c_execution_amendment.md) 및 [A2 구현 수정](E4c_v2_execution_amendment.md)에 따라 실제 원본 점군·decision-time pose에서 기하 feature와 분리 관측의 audit 분류를 계산했다. 후보 제외 robust patch와 명시적인 support/conflict/unknown은 구현했지만, 임계값 보정에 필요한 공통 표본을 확보하지 못했다. **이 결과는 pruning 효능 성공이나 표면 일관성 가설의 반증이 아니다.**','',
      '## 실행한 범위','',
      '- 원래 raw-event 분할 실패를 5장면에서 확인하고, 좌표·GT 결과를 보기 전에 A1을 등록했다. 매 3번째 raw event를 audit로 잡으면 각 장면의 500개 raw 중 audit 166개와 source가 겹치지 않는 policy event가 0개였다.',
      '- A1은 pose가 저장된 KF raw만 사용하며 KF 2·3을 audit로 고정했다. source-image 분리·가시성·시선 다양성·후보 제외 조건을 유지했다.',
      '- A1 첫 기하 실행에서 support용 수선점 hull 조건을 충돌에도 적용한 구현 문제를 확인했다. 고정 fixture를 추가하고 A2를 등록한 V2에서 ray–plane 교점의 hull로 공통 자격을 수정했다. A1 배열·코드·보정 실패는 원래 경로에 보존했으며 이 보고서의 수치는 수정한 V2만 사용한다.',
      '- office0/office1 개발 및 room0/room1/room2 회귀의 모든 original-active 후보와 모든 actual KF snapshot에서 네 표면 두께 조합을 계산했다. audit는 별도의 7×7 RANSAC 표면과 최종 revision을 쓰는 사후 평가다.',
      '- 개발 audit 라벨만으로 임계값 보정을 시도했다. GT 라벨은 보정 이후 이 보고서의 교차 집계에만 열었다. 새 office2/office3의 데이터·RGB·GT·baseline은 열지 않았다.','',
      '## 장면별 관측·표본','',
      '| 장면 | original active | audit S | audit O | audit 분류 비율 | 공통 S | 공통 O | policy 반복 가능 | 보호 후 반복 충돌 가능 | local 표면 지지 |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for scene,s in results.items():
        c=s['combinations']['c3_1'];lines.append(f'| {scene} | {c["active"]:,} | {c["S"]:,} | {c["O"]:,} | {s["audit_fraction"]:.3%} | {c["common_S"]:,} | {c["common_O"]:,} | {c["common_active"]:,} | {c["unprotected_ever_finite"]:,} | {c["local_support"]:,} |')
    lines += ['',
      'S는 audit의 반복 표면 지지, O는 반복 앞쪽 충돌, U는 그 외다. policy 반복 가능은 표면 보호 전 paired score가 한 번 이상 유한한 active 후보이며, 공통 S/O는 그 집합과 audit 분류의 교집합이다. 보호 후 반복 충돌 가능은 local/cross support 보호와 앞쪽 확인을 적용한 뒤 유한한 paired plane 점수가 한 번 이상 있었던 수이며 실제 제거 수가 아니다. 위 local 지지는 `(c_s,c_h)=(3,1)`의 후보 제외 자기 출처 검사다. local 지지 수를 검증된 정상 수나 실제 보존율로 해석하지 않는다.','',
      '![개발 관측 성립 검사](../figures/E4c/development_feasibility.png)','',
      '## 임계값 보정과 중단 이유','',
      '| 두께 조합 | 보정 상태 | S_surface 임계값 | D_surface 임계값 |',
      '|---|---|---:|---:|']
    for key,c in cal['combinations'].items():
        lines.append(f'| {key} | {c["status"]} | {c["thresholds"]["s"]} | {c["thresholds"]["d"]} |')
    lines += ['',
      '계획은 개발 장면별 own/common finite audit S를 각각 최소 100개 요구하고, 평가 성립에는 audit O와 common O도 각각 100개를 요구한다. 필요한 표본을 확보하지 못해 임계값을 정하지 않았다. 보정 불가는 제거 0개의 성공 정책과 다르므로 **자연 membership·제거율·정밀도·정상 보존율을 만들어 보고하지 않았다.** 새로운 장면을 평가하거나 GT 라벨로 부족한 audit S를 대체하지 않았다.','',
      '실제 기하/시차/가림 자격을 통과하는 policy 관측과 별도 audit 관측의 공간적 중첩이 부족했다. ancestry만으로 반복 가능했던 후보가 곧 실제 공통 표면 평가 후보가 되는 것은 아니었다. 특히 audit O가 0인 장면을 실제 이상점이 없는 장면으로 해석하지 않는다.','',
      '## 제거 목표와 audit O의 차이','',
      f'office1의 audit O {results["office1"]["combinations"]["c3_1"]["O"]:,}개 중 {results["office1"]["protected_local_by_combo"]["c3_1"]["local_protected_O"]:,}개는 자기 출처에서 중심점을 제외한 국소 표면 지지를 가졌다. 이는 실제 REJECT 이후의 보존율이 아니라 임계값과 무관한 보존 조건의 관측이다.', '',
      '**다른 두 관측과 앞쪽 충돌한다는 audit O 정의만으로, 국소 표면 밖의 고립점이라고 확정할 수 없다.** 이런 후보를 모두 제거 정답으로 삼으면 일관된 추정 표면을 보존한다는 목적과 다시 충돌할 수 있다. 후속 평가기는 audit 충돌과 별도로 후보 주변의 표면 소속을 독립적으로 확인해, 일관된 표면과 실제 표면 이탈을 구별해야 한다. 현재 O recall 기준을 효능 검증에 곧바로 쓰기에는 이 한계도 남는다.','',
      '## GT 라벨과의 교차 확인','',
      '| 장면 | audit S ∩ GT bad | audit O ∩ GT bad | audit U ∩ GT bad |',
      '|---|---:|---:|---:|']
    for scene,s in results.items():
        m=s['GT_cross_matrix'];lines.append(f'| {scene} | {m["1"]["3"]:,} | {m["2"]["3"]:,} | {m["0"]["3"]:,} |')
    lines += ['',
      'GT bad는 기존 repeated-front-error proxy다. audit S와 겹치는 후보가 있어도 라벨을 바꾸지 않는다. 표면 일관성과 GT 위치 정확도를 분리한다는 원래 목적을 유지했으며, 이번 실행으로 해당 후보의 pruning 후 보존이나 지도 품질 개선을 검증한 것은 아니다.','',
      '## 검증·산출물','',
      f'11개 기전 테스트 PASS. {len(inputs)}개 입력을 재해시했고, 5장면의 snapshot/revision·paired finite mask·audit 분류 집계·policy/audit source 분리·결과 배열 해시를 검사했다. 고정 사례 ID는 그림 생성 전에 seed 0으로 저장했다. 정책이 미보정이므로 KEEP/REJECT 사례 그림과 정상 보존 검증은 수행하지 않았다.','',
      '- [실행 설정](../../configs/e4c_v2_surface_consistency_pruning.json), [등록](../../configs/e4c_v2_protocol_registration.json), [개발 봉인](../../configs/e4c_v2_preregistration.json)',
      '- [보정 결과](../../configs/e4c_v2_development_calibration.json), [전체 집계](../../configs/e4c_results_summary.json), [검증](../../configs/e4c_v2_validation.json)',
      '- 원본 배열·기하 이력·audit 관측 집계·분할·환경·봉인 코드·고정 사례: `results/E4c_surface_consistency_pruning/v2/`','',
      '재현 순서(완료 경로는 덮어쓰기 guard로 보존하며, 재실행에는 별도 출력 경로와 새 등록이 필요):','',
      '```bash',
      'OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python -m unittest discover -s tests -p test_e4c_v2.py -v',
      '.venv/bin/python scripts/run_e4c_v2.py initialize',
      'for scene in office0 office1 room0 room1 room2; do',
      '  OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python scripts/run_e4c_v2.py geometry "$scene"',
      'done',
      '.venv/bin/python scripts/calibrate_e4c_v2.py',
      'MPLCONFIGDIR=/tmp/e4c-mpl .venv/bin/python scripts/report_e4c_v2.py',
      '```','',
      '## 미수행 범위와 다음 판단','',
      '기존 legacy 정책의 새 policy-pool 비교·ablation 보정·새 장면 baseline·natural pruning 효능·RGB/depth/TSDF·동일 수량·GPU compact buffer 평가는 진행하지 않았다. 이들 항목을 통과했다고 처리하지 않는다. E4 REVISE 및 E5/E6 효능 검증 보류를 유지한다.','',
      '다음 개발에서는 같은 표면을 관측하면서 source를 공유하지 않는 policy/audit 관측을 확보할 수 있는지부터 점검해야 한다. 관측 분할을 다시 바꾸려면 이번에 본 장면만 개발에 사용해 별도 amendment와 평가 coverage 검사를 등록해야 한다. 이번 결과에 맞춰 source 조건이나 표본 기준을 사후 완화해 성공으로 바꾸지 않는다.','']
    (ROOT/'docs/experiments/E4c_surface_consistency_pruning_results.md').write_text('\n'.join(lines))
    archive=OUT/'sealed_analysis_code';archive.mkdir(exist_ok=True)
    import shutil
    for path in [ROOT/'scripts/calibrate_e4c_v2.py',Path(__file__)]:shutil.copy2(path,archive/path.name)
    final_paths=[ROOT/'configs/e4c_results_summary.json',ROOT/'configs/e4c_v2_validation.json',
                 ROOT/'docs/experiments/E4c_surface_consistency_pruning_results.md',
                 ROOT/'docs/figures/E4c/development_feasibility.png',OUT/'example_ids.json',
                 ROOT/'scripts/calibrate_e4c_v2.py',Path(__file__)]
    save_json(OUT/'report_manifest.json',dict(reported_at_utc=datetime.now(timezone.utc).isoformat(),
        artifacts=[digest(p) for p in final_paths],analysis_code_created_after_feature_extraction=True))
    print(f'E4c {cal["status"]}: development gate report and validation saved')


if __name__=='__main__':main()
