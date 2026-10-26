#!/usr/bin/env python3
"""Export V1 figures and a reviewable Korean report from completed artifacts."""
from pathlib import Path
import json
import csv
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from v1_common import context,ARMS,CZ,OLD
from prepare_e2b_run import digest,save_json


def table(result,names):
    text = '| 조건 | 후보 수 | 00 | 10 | 01 | 11 | Support 통과 뷰 | 공통/reference |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
    for name in names:
        c = result['cases'][name]
        gate = c['support_gate']
        values = list(c['errors'].values())
        text += f"| {name} | {c['count']:,} | "+' | '.join(f'{v:.6f}' if v is not None else 'NA' for v in values)+f" | {gate['qualifying_views']}/{gate['registered_views']} ({'PASS' if gate['passed'] else 'FAIL'}) | {100*c['mean_common_fraction']:.2f}% |\n"
    return text


def main():
    spec,out = context()
    R = json.loads((out/'analysis/results.json').read_text())
    assert R['decision']['execution']=='COMPLETE'
    figs = ROOT/'docs/figures/V1'
    figs.mkdir(parents=True,exist_ok=True)
    colors = ['#667085','#14836b','#c43c4a','#4169ba']
    x = np.arange(4)
    fig,axes = plt.subplots(1,3,figsize=(13,3.8),constrained_layout=True)
    for ax,(left,right,title) in zip(axes,[('position_strict','orientation_strict','Gauge: SAME eight-arm pixels'),
            ('position_strict','original_strict','Representation: SAME eight-arm pixels'),
            ('position_strict','position_full','Scope: SAME eight-arm pixels')]):
        p = next(p for p in R['pairs'] if p['left']==left and p['right']==right)
        ax.bar(x-.18,list(p['errors_left'].values()),.36,color=colors,alpha=.45,label=left)
        ax.bar(x+.18,list(p['errors_right'].values()),.36,color=colors,label=right)
        ax.set_xticks(x,['00','10','01','11'])
        ax.set_title(title,fontsize=10)
        ax.set_ylabel('Mean per-view depth MAE (m)')
        ax.legend(fontsize=7)
        ax.grid(axis='y',alpha=.2)
        ax.set_axisbelow(True)
    fig.savefig(figs/'paired_comparisons.png',dpi=170)
    plt.close(fig)
    fig,axes = plt.subplots(2,2,figsize=(10,7),constrained_layout=True)
    for col,kind in enumerate(['source_only','target_only']):
        for p,color in [('uniform_hash','#14836b'),('scan_rows','#c43c4a')]:
            for row,a in enumerate(['C00','C10']):
                names = [f'{kind}_{p}_{d:02d}' for d in [1,10]]
                vals = [R['cases'][n]['errors'][a] for n in names]
                axes[row,col].plot([1,10],vals,'o-',color=color,label=p)
                for d,n,v in zip([1,10],names,vals):
                    if not R['cases'][n]['support_gate']['passed']:
                        axes[row,col].scatter([d],[v],s=140,facecolors='none',edgecolors='black')
                axes[row,col].axhline(R['cases']['position_strict']['errors'][a],color='#667085',ls='--')
                axes[row,col].set_title(f'{kind}: {a}; own four-arm mask')
                axes[row,col].set_xscale('log')
                axes[row,col].set_xticks([1,10],['1%','10%'])
                axes[row,col].set_xlabel('Nominal retained density')
                axes[row,col].set_ylabel('Depth MAE (m)')
                axes[row,col].legend(fontsize=8)
                axes[row,col].grid(alpha=.2)
    fig.suptitle('Office3 V1 | black ring = support FAIL; dashed = unchanged dense reference')
    fig.savefig(figs/'source_target_sensitivity.png',dpi=170)
    plt.close(fig)
    group = json.loads((out/'analysis/position_strict_common4.json').read_text())
    fig,axes = plt.subplots(2,1,figsize=(10,6),sharex=True,constrained_layout=True)
    for a,color in zip(ARMS,colors):
        axes[0].plot([r['frame'] for r in group['rows']],[r['errors'][a] for r in group['rows']],color=color,label=a)
    axes[0].set_ylabel('Common depth MAE (m)')
    axes[0].legend(ncol=4)
    axes[1].plot([r['frame'] for r in group['rows']],[100*r['common_fraction'] for r in group['rows']],color='#4169ba')
    axes[1].axhline(50,color='black',ls='--',label='dense fraction threshold; pixel count also required')
    axes[1].set_ylabel('Common/reference (%)')
    axes[1].set_xlabel('Heldout original frame ID')
    for ax in axes: ax.grid(alpha=.2)
    axes[1].legend(fontsize=8)
    fig.savefig(figs/'per_view_metrics.png',dpi=170)
    plt.close(fig)
    for f in spec['saved_views']:
        entries = [np.load(out/'evaluation/position_strict'/a/f'frame{f:04d}.npz') for a in ARMS]
        ref = entries[0]
        fig,axes = plt.subplots(3,5,figsize=(14,6.2),constrained_layout=True)
        axes[0,0].imshow(ref['target'])
        axes[1,0].imshow(np.where(ref['valid'],ref['gt'],np.nan),vmin=.1,vmax=5,cmap='viridis')
        axes[2,0].imshow(ref['valid'],cmap='gray',vmin=0,vmax=1)
        axes[0,0].set_title('Heldout target')
        axes[1,0].set_title('GT camera Z, 0.1..5m')
        axes[2,0].set_title('GT interior mask')
        for col,(a,e) in enumerate(zip(ARMS,entries),start=1):
            axes[0,col].imshow(e['rgb'])
            axes[1,col].imshow(np.where(e['covered'],e['depth'],np.nan),vmin=.1,vmax=5,cmap='viridis')
            err = np.abs(e['depth']-e['gt'])
            axes[2,col].imshow(np.where(e['valid']&e['covered'],err,np.nan),vmin=0,vmax=.3,cmap='magma')
            axes[0,col].set_title(a)
            axes[1,col].set_title('Expected camera Z')
            axes[2,col].set_title('Own-covered |error|, 0..0.3m')
        for ax in axes.ravel(): ax.axis('off')
        fig.suptitle(f'Office3 V1 | fixed heldout view {f} | RGB attributes fixed, refiner off')
        fig.savefig(figs/f'office3_frame{f:04d}.png',dpi=155)
        plt.close(fig)
        for e in entries: e.close()
    baseline = json.loads((out/'baseline/run_manifest.json').read_text())
    qual = json.loads((out/'baseline/qualification.json').read_text())
    construction = json.loads((out/'maps/manifest.json').read_text())
    unit = json.loads((out/'maps/unit_contract.json').read_text())
    alignment = json.loads((out/'maps/alignment.json').read_text())
    primary = R['cases']['position_strict']
    denominator_audit = json.loads((out/'analysis/reference_denominator_audit.json').read_text())
    assert denominator_audit['status']=='PASS'
    ep = primary['effects']
    arm_table = '| Arm | 공통 깊이 MAE (m) | Coverage | Correct coverage | TSDF Chamfer (m) |\n|---|---:|---:|---:|---:|\n'
    for a in ARMS:
        s = primary['summary'][a]
        surface = R['surfaces'][a]
        chamfer = surface.get('chamfer_m',surface.get('chamfer'))
        arm_table += f"| {a} | {s['MAE_m']:.6f} | {s['coverage']*100:.3f}% | {s['correct_coverage']*100:.3f}% | {chamfer:.6f} |\n"
    denominator_table = '| Arm | Interior coverage / correct | All-GT-valid coverage / correct |\n|---|---:|---:|\n'
    for a in ARMS+CZ:
        ds = denominator_audit['arms'][a]['summary']
        denominator_table += f"| {a} | {100*ds['interior']['coverage']:.3f}% / {100*ds['interior']['correct_coverage']:.3f}% | {100*ds['all_valid']['coverage']:.3f}% / {100*ds['all_valid']['correct_coverage']:.3f}% |\n"
    pair_table = '| 비교 (각 행쌍 동일 8군 픽셀) | 00 | 10 | 01 | 11 |\n|---|---:|---:|---:|---:|\n'
    for p in R['pairs']:
        for label,errors in [(p['left'],p['errors_left']),(p['right'],p['errors_right'])]:
            pair_table += '| '+label+' | '+' | '.join(f'{v:.6f}' for v in errors.values())+' |\n'
    ray_table = '| Arm | 같은 C+CZ 6군 MAE (m) |\n|---|---:|\n'
    for a,s in R['ray_control']['summary'].items(): ray_table += f"| {a} | {s['MAE_m']:.6f} |\n"
    effect_table = '| Scope | Δlocal (m) | Δrigid (m) | Interaction (m) | Local gain |\n|---|---:|---:|---:|---:|\n'
    for name,c in R['cases'].items():
        e = c['effects']
        effect_table += f"| {name} | {e['delta_local']:.6f} | {e['delta_placement']:.6f} | {e['interaction']:.6f} | {100*e['local_gain_relative_to_baseline']:.2f}% |\n"
    flips = [p['right'] for p in R['pairs'] if p['right']!='original_strict' and any(p['sign_flip'].values())]
    report = f'''# V1: office3 고정 진단 재현

**실행일: 2026-10-26 (Asia/Seoul). 실행 COMPLETE. 보정 알고리즘 GO 보류.**

새 validation 장면 office3에서 유효 local 참조 치환의 깊이 MAE는 **{primary['errors']['C00']:.6f}→{primary['errors']['C10']:.6f}m ({100*ep['local_gain_relative_to_baseline']:.2f}% 감소)**였다. Rigid pose 단독은 **{primary['errors']['C01']:.6f}m**, joint 참조는 **{primary['errors']['C11']:.6f}m**였다. 이는 참조 개입의 진단이며 RGB-only 보정 성능을 측정한 것이 아니다. 독립 최종 test가 아닌 **고정된 validation 재현**이다.

## 1. 등록·실제 실행 범위

- [기존 frozen recipe](../../configs/v1_office3_diagnostic_protocol.json)는 원문과 hash를 보존했다. 그 파일의 NOT_EXECUTED는 당시 등록 상태이며 현재 완료 여부는 이 보고서와 [실행 요약](../../configs/v1_office3_results_summary.json)을 따른다.
- [실행 설정](../../configs/v1_office3_execution.json), [평가 설정](../../configs/v1_office3_analysis.json), [baseline 등록](../../results/V1_office3_diagnostic/2026-10-26/registration.json), [평가 코드·입력 등록](../../results/V1_office3_diagnostic/2026-10-26/analysis_registration.json). 평가 코드는 RGB-only baseline 실행 중 구현했고 **기준선 추적 자격을 확인한 뒤, gauge fit·Oracle map·heldout metric 확인 전** 봉인했다. Office2/HK의 기존 결과는 알고 있었다.
- 짝수 원본 ID 0..998의 RGB **500개**, seed0/refiner0/고정 weight/native filter. GT depth/trajectory를 mapper에 전달하지 않았다. Post-prefix/heldout GT로 gauge를 맞추지 않았다.
- 새 추론 결과: **{qual['tracked_poses']}/500 pose**, prefix **{qual['matched_calibration_poses']} pose**, **{qual['keyframes']} KF**, post-prefix **{qual['post_prefix_keyframes']} KF**. Tracking qualification PASS. 창·프레임·seed·threshold를 결과에 따라 바꾸거나 재추론하지 않았다.
- Native **{construction['active']:,}후보**, post-prefix native∩GT-interior strict **{construction['strict']:,}후보**. 전체 native mixed에서는 prefix 포함 **{construction['full_reference_replaced']:,}개 ({100*construction['full_reference_fraction']:.3f}%)**에만 local 참조를 대입했고, 나머지 local은 예측값을 보존했다. 모든 후보의 rigid pose는 해당 arm 정책을 따른다. Full mixed는 완전 GT map이 아니다.
- 홀수 원본 ID **201..999의 400뷰 전부**, 주 position gauge와 same-prefix orientation sensitivity. Covariance 대조는 기존 고정 20뷰 201,241,..,961이다. Appearance/refiner 학습은 없다.

## 2. 계약 검증

- Journal **2,030 events·500 raw events**의 재생, KF raw self-branch/pts3d 일치, 최종 pose revision **{construction['pose_revision']}**, source ID·native mask·RGB/opacity 고정 및 GPU native PLY 재현 PASS. Native filter를 개입별로 다시 계산하지 않았다.
- Local point와 covariance에 KF scale을 함께 흡수했다. C 배율 0.8/1/1.25 × KF 단위 재배분 on/off **6개 양성 map이 독립 원본 경로와 SHA-256까지 동일**했다. 역변환·표준편차→covariance·world mean/covariance 검사가 모든 native 후보에서 PASS.
- 고정 5뷰 × 6 positive **30개 렌더 비교 PASS**, RGB/depth/weight와 coverage 일치. 잘못된 mean-only absorption/naive scale removal은 nonunit **{unit['negative_nonunit_KFs']} KF**에서 대수적으로 검출했고 두 fixed view씩 negative render도 기대대로 불변성에 실패했다. [unit 계약](../../results/V1_office3_diagnostic/2026-10-26/maps/unit_contract.json), [렌더 검증](../../results/V1_office3_diagnostic/2026-10-26/unit_render/completion.json).
- C00=A00 지도 및 400뷰 depth/coverage cache가 bitwise 동일. C11/A11은 중심이 동일하고 covariance 계약이 다르다. 각 비교 내 source ID·순서·속성·local covariance를 고정했다. C01은 scale 추가 제거 없이 rigid R/t만 바꾼다.
- 관련 기존 unittest **48개 PASS**. pytest가 설치되지 않아 저장소의 unittest 형식으로 실행했다. Float64 계약, packed float32 및 TF32-off 기존 CUDA renderer를 사용했다.

## 3. Primary strict C4

네 C군 공통 reference-valid interior 픽셀의 **뷰별 MAE를 동일 가중 평균**했다. 주 표의 Coverage/correct coverage는 G/M과 같은 GT interior 분모다. A1-C의 전체-GT coverage 분모도 같은 cache에서 추가 계산해 아래에 병기했다. 분모가 다른 숫자를 직접 빼지 않는다. Correct threshold는 `max(0.05m, 2% GT Z)`다.

{arm_table}

{denominator_table}

[분모 감사](../../results/V1_office3_diagnostic/2026-10-26/analysis/reference_denominator_audit.json)는 캐시의 own-covered metric도 전 400뷰에서 독립 재계산해 기존 값과 정확히 일치하는지 검사했다. Primary common mask·판정값은 바꾸지 않은 보고 보완이다.

Support: **{primary['support_gate']['qualifying_views']}/400뷰 PASS**, 평균 공통 **{primary['mean_common_pixels']:,.2f}픽셀**, reference의 **{100*primary['mean_common_fraction']:.3f}%**. Δlocal=C00−C10 **{ep['delta_local']:+.6f}m**, Δrigid=C00−C01 **{ep['delta_placement']:+.6f}m**, interaction=C11−C10−C01+C00 **{ep['interaction']:+.6f}m**다. 양수 Δ는 개선이다. Local 참조의 효과를 raw network depth의 고유 기여율로 해석하지 않는다.

TSDF는 같은 고정 20뷰의 GT-depth 관측영역 reference, 4cm voxel/12cm truncation/10m 최대 깊이/100k seed0 면적 표본을 사용했다. Gaussian center NN이나 전체 장면 completeness와 구분한다. Primary C/CZ RGB는 전 400뷰에서 PSNR/SSIM을 저장했고 sensitivity RGB는 고정 5뷰만 평가했다.

![Paired metrics](../figures/V1/paired_comparisons.png)
![Per-view metrics](../figures/V1/per_view_metrics.png)

## 4. Gauge·표현·전체지도·Covariance 비교

각 행쌍은 별도의 **같은 8군 target 픽셀**이다. 행쌍 사이에는 분모가 달라 수치를 섞지 않는다. Own C4 표는 아래와 별도로 저장했다. A군은 office3의 같은 fresh baseline에서 새로 생성·평가했으며 과거 office2 cache를 재사용한 것이 아니다.

{pair_table}

두 gauge는 같은 prefix 100 pose만 썼다. 추정 위치 singular-value 비율은 **1/{alignment['observability']['estimated_singular_ratios'][1]:.6f}/{alignment['observability']['estimated_singular_ratios'][2]:.6f}**, 두 gauge 회전 차이는 **{alignment['rotation_difference_deg']:.6f}°**다. Position primary를 유지하고 더 좋은 heldout gauge를 사후 선택하지 않았다.

Covariance 비교는 canonical local covariance를 rigid transport한 네 군과 world covariance를 C00 값에 고정한 네 군의 20뷰 비교다. 단독 factor 부호가 바뀐 비교는 **{', '.join(flips) if flips else '없음'}**이며 support·10% 효과 크기를 함께 확인해야 한다. 원 A/C의 차이는 factor와 covariance 정의 변경을 포함한다.

## 5. Source-only와 Target-only 희소화

{table(R,[n for n,c in R['cases'].items() if c['definition']['kind'] in ['source_only','target_only']])}

Source-only는 같은 strict 후보 행을 양 군 모두에서 GT-blind hash/scan-row mask로 1%/10% 남겼다. Scale/opacity/footprint를 부풀리거나 hole을 메우지 않았다. 분모는 원 dense target GT다. Target-only는 **dense 지도와 render cache를 그대로** 두고 target reference만 측정 mask로 제한했다. 위 target-only 후보 수는 unchanged dense 지도 수이고, 공통/reference 비율은 sampled GT가 분모다. Full-GT 대비 실제 측정·공통 비율은 [CSV](../../results/V1_office3_diagnostic/2026-10-26/analysis/V1_four_arms.csv)에 별도 기록했다.

Dense gate는 등록 뷰 ≥80%에서 공통 ≥1,000픽셀 및 reference ≥50%, target-only sparse gate는 ≥1,000픽셀 및 sampled reference ≥20%다. Target 1%는 뷰별 valid 픽셀 수가 작아 count gate에 실패할 수 있다. 실패도 포함해 전 400뷰를 유지했다. 이 희소화는 실제 LiDAR acquisition/noise의 재현이 아니다.

![Source versus target](../figures/V1/source_target_sensitivity.png)

## 6. Predicted-ray Z 대조와 전체 factorial 효과

{ray_table}

Ray 대조는 6군 공통 픽셀로 계산했다. CZ10/CZ11은 predicted ray를 유지한 참조 Z 개입이다. C10/C11과 같은 픽셀에서 비교해 ray 변경과 depth 변경을 구분한다.

{effect_table}

Strict가 아닌 full mixed·source-only 및 target-only는 서로 다른 정보량과 가림을 갖는다. 모든 표는 scene 내 조건부 진단이며 픽셀/400뷰를 독립 반복으로 세지 않는다. 단일 validation 장면으로 scene CI나 보편적 원인 기여율을 만들지 않았다.

## 7. 비용·재현 명령·산출물

- GPU: {baseline['environment']['gpu']}; Torch {baseline['environment']['torch']}; CUDA {baseline['environment']['cuda']}. RGB-only 기준선 {baseline['wall_seconds']:.2f}초. 38개 intervention map·**{R['evaluation']['new_depth_views']:,} unique depth-view**, unit original/positive/negative/repeat 40 depth-view, 실패한 A00 재렌더 400뷰를 별도 비용으로 기록한다. 성공 map의 렌더·저장·표면평가 시간 합은 {R['evaluation']['total_unique_map_render_seconds']:.2f}초, resume 구간은 {R['evaluation']['wall_seconds']:.2f}초다 (입력 로딩·unit 검증·실패 시도 제외). Device-memory CSV와 per-map GPU peak/시간은 각 manifest에 있다.
- Unit map·local npz·candidate hash·source KF/depth/confidence strata·mask·depth/coverage cache·고정 5뷰 RGB/depth·표면 PLY·100k 표본을 `results/V1_office3_diagnostic/2026-10-26/`에 저장했다.
- [요약](../../configs/v1_office3_results_summary.json), [4군 CSV](../../results/V1_office3_diagnostic/2026-10-26/analysis/V1_four_arms.csv), [effect CSV](../../results/V1_office3_diagnostic/2026-10-26/analysis/V1_effects.csv), [상세 결과](../../results/V1_office3_diagnostic/2026-10-26/analysis/results.json).

```bash
.venv/bin/python scripts/run_v1_baseline.py
.venv/bin/python scripts/build_v1.py register
.venv/bin/python scripts/build_v1.py build
.venv/bin/python scripts/evaluate_v1.py
.venv/bin/python scripts/analyze_v1.py
.venv/bin/python scripts/audit_v1_denominators.py
.venv/bin/python scripts/report_v1.py
```

완료 출력은 보존한다. 위 명령은 fresh output용 순서이며 재실행은 별도 amendment/output이 필요하다. Frozen recipe 원문과 기존 A0/A1 결과는 수정하지 않았다. N2 manifest의 zip_crc는 등록 전 hash 비교에서 provenance 부가필드로 구분했고 파일 bytes/SHA-256은 모두 대조했다.

**구현 수정 A1:** Sensitivity는 RGB를 고정 일부 뷰에만 계산하는데 초기 집계가 누락된 `psnr_db` key를 참조해 첫 original A00 평가 말미에 중단됐다. [수정 이력](../../configs/v1_implementation_amendment_A1.json)에 초기/수정 code hash, 당시 결과 접근 범위, 기존 출력 hash를 남겼다. 선택적 RGB 항목을 None으로 채우고 완료 cache를 보존해 resume했다. Partial A00와 실패 log도 `failed_attempt1/`에 보존했으며 **같은 map/400뷰 재렌더의 depth/coverage SHA-256이 실패 시도와 동일**했다. Geometry·split·threshold·mask·renderer·primary 지표 변경이나 baseline 재추론은 없다. 원 코드 스냅샷과 수정 코드를 모두 보관했다.

## 8. 경로 판정

자동 gate: **{R['decision']['interpretation']}**, 두 gauge의 local ≥10% 및 correct coverage 보존: **{R['decision']['local_minimum_effect_both_gauges']}**, direction flip: **{R['decision']['any_gauge_scope_covariance_direction_flip']}**, support 실패 존재: **{R['decision']['any_support_failure']}**.

다음 후보는 **{R['decision']['next']}**다. 이 판정은 Oracle local 개선 여지의 후속 진단 자격이며 Depth-only 우세·RGB 관측 가능성·보정 알고리즘 GO가 아니다. V1 ray/surface·covariance·paired support 및 기존 office2 차이를 함께 검토한 최종 경로는 [A1 경로 판정](A1_route_decision.md)에 기록한다. **Q0-HK 미해결, office4 보류를 유지**한다. 이 요청에서는 다음 단계 실험이나 새 optimizer를 자동 실행하지 않았다.

![Fixed view 601](../figures/V1/office3_frame0601.png)
'''
    (ROOT/'docs/experiments/V1_office3_replication.md').write_text(report)
    artifacts = [ROOT/'docs/experiments/V1_office3_replication.md']+sorted(figs.glob('*.png'))
    matrix = []
    for name,c in R['cases'].items():
        matrix.append(dict(case=name,gauge=c['definition']['gauge'],kind=c['definition']['kind'],candidates=c['count'],
            common_pixels=c['mean_common_pixels'],common_reference_fraction=c['mean_common_fraction'],
            support_pass=c['support_gate']['passed'],**c['effects']))
    with (out/'analysis/V1_gauge_support_matrix.csv').open('w',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)
    save_json(out/'A1_coordinate_reparameterization.json',dict(status='PASS',scene='office3',
        unit_contract=digest(out/'maps/unit_contract.json'),unit_render=digest(out/'unit_render/completion.json'),
        construction=digest(out/'maps/manifest.json'),original_baseline=digest(out/'baseline/run_manifest.json')))
    save_json(out/'report_manifest.json',dict(status='COMPLETE',files=[digest(p) for p in artifacts]))
    print('V1 report and figures exported.',flush=True)


if __name__=='__main__': main()
