"""Tracked E3b report and figures; fresh evaluation remains an explicit gate."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts')]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'results/E3b_provisional_admission/.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from prepare_e2b_run import digest,save_json
from e3b_fresh import status


def main():
    spec=json.loads((ROOT/'configs/e3b_provisional.json').read_text());out=ROOT/spec['output']
    seal=json.loads((out/'seal.json').read_text())
    results={s:json.loads((out/'evaluation'/s/'metrics.json').read_text()) for s in ['office0','room0']}
    r=results['room0'];dev=results['office0'];fresh=status(spec)
    validation=json.loads((out/'validation.json').read_text())
    go=False
    if fresh['evaluated']:
        results['room1']=json.loads((out/'evaluation/room1/metrics.json').read_text())
        go=validation['fresh_evaluation_complete'] and validation['status']=='PASS' and results['room1']['go_for_e4'] and results['room1']['assessment'][spec['primary']]['passed']
        fresh['reason']='Fresh scene evaluated; E4 decision uses sealed metrics and verified provenance'
        fresh['go_for_e4']=go
        save_json(out/'fresh_status.json',fresh);save_json(ROOT/'configs/e3b_fresh_status.json',fresh)
    summary=dict(status=('GO_FOR_E4' if go else 'REGRESSION_REVISE_FRESH_PENDING' if r['status']=='REVISE' and not fresh['evaluated']
        else 'REGRESSION_PASS_FRESH_PENDING' if not fresh['evaluated'] else 'REVISE'),
        regression_status=r['status'],fresh=fresh,go_for_e4=go,research_wide_go=False,
        completed=['office0 calibration and code seal','office0 and room0 label-free provisional replay',
                   'office0 and room0 actual compact-map GT rendering','candidate and artifact verification'],
        pending=[] if fresh['evaluated'] else ['registered fresh room1 CUDA baseline, features, replay and GT evaluation'],
        scene_metrics={s:digest(out/'evaluation'/s/'metrics.json') for s in results},seal=digest(out/'seal.json'))
    summary['next_step']='E3c: compare B6 and plane scores with identical causal observation eligibility and risk calibration before E4' if not go else 'E4 matched-budget and rendering evaluation; no overall efficacy claim yet'
    save_json(out/'metrics.json',summary);save_json(ROOT/'configs/e3b_results_summary.json',summary)
    figdir=ROOT/'docs/figures/E3b';figdir.mkdir(parents=True,exist_ok=True)
    names=['B6_legacy','B6_safe','B7_safe','B8_safe','P_legacy','P_safe','P_persist']
    x=np.arange(len(names));fig,axs=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
    axs[0].bar(x,[100*r['methods'][p]['decision']['creation']['finite_normal_retention'] for p in names])
    axs[1].bar(x,[100*r['methods'][p]['common']['normal_active_retention'] for p in names])
    for ax in axs[:2]:
        ax.axhline(99,color='r',ls='--',lw=1);ax.set(xticks=x,xticklabels=names,ylim=(90,100.2));ax.tick_params(axis='x',rotation=55)
    axs[0].set_ylabel('Finite-normal retention (%)');axs[1].set_ylabel('Common-normal active retention (%)')
    for p in names:
        m=r['methods'][p]['decision']['creation']
        axs[2].scatter(100*m['bad_recall'],100*m['precision'])
        offset=(3,-12) if p=='P_persist' else (3,5)
        axs[2].annotate(p,(100*m['bad_recall'],100*m['precision']),fontsize=8,xytext=offset,textcoords='offset points')
    axs[2].set(xlabel='GT front-error recall (%)',ylabel='Rejection precision (%)')
    axs[2].margins(x=.18,y=.13)
    fig.suptitle('E3b room0 regression: sealed office0 thresholds; fresh room1 pending' if not fresh['evaluated'] else 'E3b room0 regression')
    fig.savefig(figdir/'risk_tradeoff.png',dpi=170);plt.close(fig)
    old=json.loads((ROOT/'configs/e3_room0_results_summary.json').read_text())
    names2=['B1','B6_safe','P_legacy','P_safe','P_persist'];fig,axs=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for p in names2:
        rows=r['methods'][p]['temporal_frames']
        axs[0].plot([a['frame'] for a in rows],[100*a['coverage'] for a in rows],marker='o',label=p)
    axs[0].plot([a['frame'] for a in old['policies']['P2']['temporal_frames']],
        [100*a['coverage'] for a in old['policies']['P2']['temporal_frames']],ls='--',label='E3 hard DEFER')
    axs[0].set(xlabel='Next held-out odd frame',ylabel='GT depth coverage (%)');axs[0].legend(fontsize=8);axs[0].grid(alpha=.2)
    for p in names2:
        a=r['methods'][p]['final_render'];axs[1].scatter(100*a['coverage'],a['depth_l1_m']*1000)
        offset=(-8,-15) if p=='P_legacy' else (-8,6) if p=='P_persist' else (3,4) if p=='B6_safe' else (-8,6)
        axs[1].annotate(p,(100*a['coverage'],a['depth_l1_m']*1000),fontsize=8,xytext=offset,
            textcoords='offset points',ha='left' if p=='B6_safe' else 'right')
    axs[1].set(xlabel='Final GT depth coverage (%)',ylabel='Covered-pixel depth L1 (mm)')
    fig.savefig(figdir/'coverage_preservation.png',dpi=170);plt.close(fig)
    fig,axs=plt.subplots(1,4,figsize=(14,3),layout='constrained')
    for ax,p in zip(axs,['B1','B6_safe','P_safe','P_persist']):
        data=np.load(out/f'evaluation/room0/render/{p}/frame000701.npz')
        error=np.abs(data['pred']-data['gt']);error[(data['weight']<=.001)|~data['valid']]=np.nan
        cmap=plt.get_cmap('magma').copy();cmap.set_bad('#79bce8')
        im=ax.imshow(error,vmin=0,vmax=.3,cmap=cmap);ax.set_title(p);ax.axis('off')
    fig.colorbar(im,ax=axs.tolist(),label='Depth error (m), blue = uncovered / invalid',shrink=.8)
    fig.savefig(figdir/'depth_error.png',dpi=170);plt.close(fig)
    if fresh['evaluated']:
        fr=results['room1'];fnames=['B6_safe','B7_safe','B8_safe','P_legacy','P_safe','P_persist'];fx=np.arange(len(fnames))
        fig,fa=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
        fa[0].bar(fx,[100*(1-fr['methods'][p]['decision']['creation']['finite_normal_retention'])
                      if fr['methods'][p]['decision']['creation']['finite_normal_retention'] is not None else np.nan for p in fnames])
        fa[1].bar(fx,[100*(1-fr['methods'][p]['common']['normal_active_retention'])
                      if fr['methods'][p]['common']['normal_active_retention'] is not None else np.nan for p in fnames])
        for ax in fa[:2]:
            ax.axhline(1,color='r',ls='--',lw=1);ax.set(xticks=fx,xticklabels=fnames);ax.tick_params(axis='x',rotation=55)
        fa[0].set_ylabel('Finite-normal loss (%)');fa[1].set_ylabel('Common-normal loss (%)')
        for p in fnames:
            m0=fr['methods'][p]['decision']['creation']
            if m0['precision'] is not None:
                fa[2].scatter(100*m0['bad_recall'],100*m0['precision'])
                offset=(-65,-12) if p=='P_persist' else (3,4)
                fa[2].annotate(p,(100*m0['bad_recall'],100*m0['precision']),fontsize=8,
                    xytext=offset,textcoords='offset points')
        fa[2].set(xlabel='GT front-error recall (%)',ylabel='Rejection precision (%)');fa[2].margins(x=.2,y=.15)
        fig.suptitle('E3b fresh room1: same sealed office0 thresholds')
        fig.savefig(figdir/'fresh_room1.png',dpi=170);plt.close(fig)
    pct=lambda v:'—' if v is None else f'{100*v:.4f}%'
    rows=[];geometry=[];development=[]
    for name in spec['methods']:
        a=r['methods'][name];m=a['decision']['creation'];c=a['common'];g=a['final_render']
        rows.append(f"| {name} | {m['bad_rejected']:,} / {m['normal_rejected']:,} / {m['unknown_rejected']:,} | {pct(m['precision'])} | {pct(m['bad_recall'])} | {pct(m['normal_active_retention'])} | {pct(m['finite_normal_retention'])} | {pct(c['normal_active_retention'])} |")
        geometry.append(f"| {name} | {g['depth_l1_m']:.6f} | {pct(g['coverage'])} | {pct(g['correct_coverage'])} | {pct(g['boundary_correct_coverage'])} | {pct(a['temporal_mean']['coverage'])} |")
    for name in ['B6_safe','B7_safe','B8_safe','P_safe','P_persist']:
        a=dev['methods'][name];m=a['decision']['creation'];c=a['common']
        development.append(f"| {name} | {seal['thresholds'][name]:.10f} | {m['bad_rejected']:,} / {m['normal_rejected']:,} | {pct(m['finite_normal_retention'])} | {pct(c['normal_active_retention'])} | {pct(m['bad_recall'])} |")
    checkrows=[]
    for p,v in r['assessment'].items():
        for k,b in v['checks'].items():checkrows.append(f"| {p} | {k} | {'PASS' if b else 'FAIL'} |")
    m=r['methods']['P_safe']['decision']['creation'];c=r['methods']['P_safe']['common']
    persistent=r['methods']['P_persist']['decision']['creation'];base=r['methods']['B1']['final_render'];g=r['methods']['P_safe']['final_render']
    fresh_note='**새 장면 검증은 미완료다.** 샌드박스에서는 NVIDIA 장치가 보이지 않는다. 샌드박스 밖 GPU 접근 여부와 새 후보 생성을 확인해 같은 봉인으로 재개해야 한다. room0는 E2b/E3에서 확인한 회귀 장면이며 새 독립 test가 아니다.'
    fresh_section='## 새 room1 평가\n\n아직 실행하지 않았다. 기존 장면 회귀 결과만으로 E4 GO를 기록하지 않는다.\n'
    fresh_execution='새 arm의 runner·동일 E2b 점수 추출식·GT 평가 코드는 준비하고 문법 검사했다. GPU 경로의 실제 동작·새 데이터 다운로드·새 결과는 아직 검증하지 않았다.'
    if fresh['evaluated']:
        fr=results['room1'];fm=fr['methods']['P_safe']['decision']['creation'];fc=fr['methods']['P_safe']['common']
        fg=fr['methods']['P_safe']['final_render'];fb=fr['methods']['B1']['final_render']
        fresh_note=f"**새 room1 평가를 완료했다.** 처음에는 샌드박스에서 GPU가 보이지 않았으나, 샌드박스 밖 읽기 전용 확인에서 RTX 5060 8GB와 PyTorch CUDA 접근을 확인했다. 같은 봉인으로 공식 Replica room1 원본 1,000프레임·짝수 500입력 기준선을 생성했다. GT pose·다른 predictor·임의 KF로 대체하지 않았다. office0/room0와 RGB 입력 hash가 겹치지 않고 동일 backbone·weights인지는 무결성 검증에서 확인했다."
        fresh_note+=f" 주 정책은 bad {fm['bad_rejected']:,}개 / normal {fm['normal_rejected']:,}개를 제거하며 정상 보존과 coverage 기준을 통과했다. 다만 공통 후보에서 B6_safe 대비 정밀도 증가를 보이지 못해 **추가 우위 미확인·E4 보류**다."
        table=[]
        for name,a in fr['methods'].items():
            a0=a['decision']['creation'];g0=a['final_render'];c0=a['common']
            table.append(f"| {name} | {a0['bad_rejected']:,} / {a0['normal_rejected']:,} / {a0['unknown_rejected']:,} | {pct(a0['precision'])} | {pct(a0['bad_recall'])} | {pct(a0['finite_normal_retention'])} | {pct(c0['normal_active_retention'])} | {g0['depth_l1_m']:.6f} | {pct(g0['coverage'])} |")
        fresh_checks=[]
        for name,assessment in fr['assessment'].items():
            fresh_checks += [f"| {name} | {key} | {'PASS' if passed else 'FAIL'} |" for key,passed in assessment['checks'].items()]
        sensitivity='; '.join(f"{mode}: bad {value['bad_rejected']:,}개 / normal {value['normal_rejected']:,}개"
            for mode,value in fr['methods']['P_safe']['decision'].items())
        fresh_section=f'''## 새 room1 평가

원본 active 후보 **{fr['methods']['B1']['decision']['creation']['candidates']:,}개**, 실제 KF **{len(fr['methods']['B1']['temporal_frames'])}개**를 동일 frozen 후보·pose 조건에서 비교했다. office0 봉인 임계값을 그대로 썼으며 room0/room1 결과에 따른 재보정은 없다. 주 정책은 bad **{fm['bad_rejected']:,}개**, normal **{fm['normal_rejected']:,}개**를 제거했고 정밀도 **{pct(fm['precision'])}**, 전체 bad recall **{pct(fm['bad_recall'])}**, 유한 normal 보존 **{pct(fm['finite_normal_retention'])}**, 공통 normal 보존 **{pct(fc['normal_active_retention'])}**였다. coverage는 원본 **{pct(fb['coverage'])}** 대비 **{pct(fg['coverage'])}**다.

주 정책의 유한 점수 가용 후보는 **{fm['finite_candidates']:,}개({100*fm['finite_candidates']/fm['candidates']:.4f}%)**, 모든 신호 공통 후보는 **{fr['common_candidates']:,}개(GT bad {fc['bad']:,}개 / normal {fc['normal']:,}개)**다. GT normal 전체 **{fm['normal']:,}개**, GT bad 전체 **{fm['bad']:,}개**에 대한 분모와 구별한다. 아직 증거가 없는 후보는 렌더 가능하지만 판정에 성공했다고 세지 않는다.

room1 P_safe의 pose 라벨 민감도는 다음과 같다: {sensitivity}. GT-anchor는 예측 scale을 유지한 진단이며 이것만으로 독립적인 전체 표면 정확도나 엄밀한 floater oracle이 되지는 않는다.

| 방법 | 제거 bad / normal / unknown | 정밀도 | bad recall | 유한 normal 보존 | 공통 normal 보존 | 깊이 L1 (m) | coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

| 방법 | 봉인 기준 | room1 결과 |
|---|---|---|
{chr(10).join(fresh_checks)}

새 장면 판정은 **{fr['status']}**다. 통과한 subset만 선택하거나 미달 장면을 빼지 않았다. 단일 새 장면의 pilot이며 다장면 일반화·통계적 유의성을 입증한 결과로 확대하지 않는다.

**실패 항목의 의미:** 주 정책은 정상 보존·비영 bad recall·coverage 기준을 통과했지만, 공통 후보에서 B6_safe도 정밀도 **{pct(fr['methods']['B6_safe']['common']['precision'])}**였다. 주 정책의 정밀도 **{pct(fc['precision'])}**로는 봉인한 “각 대조군보다 +2pp” 조건을 충족하지 못한다. B6가 이미 100%인 경우 이 조건은 수학적으로 달성할 수 없지만, 결과를 보고 기준을 바꾸어 GO로 기록하지 않았다. 공통 후보의 bad 제거 수는 B6_safe **{fr['methods']['B6_safe']['common']['bad_rejected']:,}개**, P_safe **{fc['bad_rejected']:,}개**로 B6 쪽이 더 많았다. 따라서 단순한 기준의 ceiling 문제만으로 보지 않고 **추가 정책의 순이익이 아직 입증되지 않았다**고 판정한다.

다음 보완은 **E3c: 같은 실제 시점의 관측 자격·support veto·위험 보정을 B6에도 적용한 뒤 plane 점수의 추가 가치를 비교**하는 것이다. 높은 정밀도가 score 자체의 정보인지, 좁은 관측 가능 후보만 골랐기 때문인지 분리해야 한다. E4 진행과 알고리즘 우위 주장은 그 결과와 별도 새 평가 계획을 보고 결정한다. room1을 다시 조정용 test로 써서 이번 E3b를 성공으로 소급하지 않는다.

![새 room1 부분집합 위험과 제거량](../figures/E3b/fresh_room1.png)
'''
        fresh_execution='공식 Replica room1 다운로드·원본 GPU 기준선·동일 raw 점수 추출·GT 없는 replay·그 뒤의 GT 라벨링·실제 맵 렌더링을 모두 실행했다. 임계값·관측 자격·후보 생성·pose·refiner 설정을 바꾸지 않았다. 다운로드는 기존 파일을 CRC 재사용하고 중복 HTTP range를 공유 캐시하는 별도 transport를 사용했으며 원본 ZIP 크기·CRC·SHA256 검증은 유지했다.'
    report=f'''# E3b — 임시 편입 후 재검사 및 부분집합 정상 보존 보완

- 실행일: 2026-10-21 (Asia/Seoul)
- 상태: **개발 보정·기존 장면 회귀 실험 실행 완료. room0 판정 {r['status']}. 새 room1 평가는 {fresh['status']}.**
- 전체 판정: **{summary['status']}**. 새 장면이 있으면 그 평가를 우선하며 room0 통과로 대체하지 않는다.
- **E4 진행 승인: {'GO' if go else '아직 아님'}.** 기존 장면 결과만으로 진행을 확정하지 않는다.
- 이전 실험: [E3](E3_admission_decision.md)
- 설정: [e3b_provisional.json](../../configs/e3b_provisional.json), [봉인](../../configs/e3b_preregistration.json), [통합 결과](../../configs/e3b_results_summary.json), [검증](../../configs/e3b_validation.json)

## 현재 확인한 결과

증거가 없는 후보를 렌더링에서 제외하던 hard DEFER를 없애고, **즉시 렌더 가능한 PROVISIONAL 편입 → 실제 KF 도착 시 재검사 → 확인된 충돌만 제거**하도록 바꿨다. 모든 방법의 queue는 0개다. 새 관측·정규화·모델·pose·후보 생성·refiner는 바꾸지 않았다.

office0에서만 보정한 주 정책 P_safe의 room0 결과는 **GT bad {m['bad_rejected']:,}개 / normal {m['normal_rejected']:,}개 제거**, 정밀도 **{pct(m['precision'])}**, 전체 bad recall **{pct(m['bad_recall'])}**다. normal 전체 active 보존 **{pct(m['normal_active_retention'])}**, 유한 점수 normal 보존 **{pct(m['finite_normal_retention'])}**, 모든 신호 공통 후보 normal 보존 **{pct(c['normal_active_retention'])}**를 구별한다. 최종 깊이 coverage는 **{pct(g['coverage'])}**로 원본 **{pct(base['coverage'])}**와 비교했다.

두 연속 KF에서 충돌이 지속될 때 제거하는 P_persist는 bad **{persistent['bad_rejected']:,}개**, normal **{persistent['normal_rejected']:,}개**를 제거했다. 유한 점수 normal 보존은 **{pct(persistent['finite_normal_retention'])}**다. P_persist는 개발에서 별도로 보정해 임계값도 달라졌으므로 그 차이를 시간 지속성 하나의 효과로 해석하지 않는다. 이 결과를 보고 두 정책 중 유리한 것을 새 주 정책으로 선택하거나 임계값을 다시 조정하지 않았다.

{fresh_note}

## office0 개발 보정과 봉인

후보는 원본 active 필터를 통과한 office0 1,547,680개 / room0 1,008,252개다. 공통 점수 cohort는 B2 confidence, B6 depth, B7 RGB NCC, B8 DoG, 반복 plane이 각각 인과적 snapshot 중 유한 점수를 가진 후보의 교집합이다. 개발 공통 후보는 **{seal['development_common_candidates']:,}개**, room0 공통 후보는 **{r['common_candidates']:,}개**다. 공통 후보라는 사실이 증거 도착 시점까지 같다는 뜻은 아니다.

E3b 임계값은 후보별 **시간 누적 최대 점수**를 이용해 개발 normal의 99% higher quantile을 계산했다. (1) 자체 유한 점수 normal, (2) 모든 신호 공통의 유한 normal, (3) 유한 normal ≥100개인 각 anchor KF에서 계산한 임계값 중 최댓값을 택했다. 필수 (1)/(2)에 normal이 100개 미만이면 미보정으로 기록하고 성공 판정을 금지한다. 작은 anchor group은 별도 기록하며 보호를 보장하지 않는다. strict `>`만 제거하고 동률·미관측은 유지한다. 이는 개발 집합의 경험적 오거부 제약이며, 새 장면 위험의 통계적 보장은 아니다.

P_persist의 개발 점수는 두 **인접 실제 KF snapshot** 점수의 최솟값을 시간에 따라 최대 집계한 값이다. 중간 snapshot에서 점수가 NaN이면 연속성을 끊는다. 각 snapshot의 plane 점수 자체는 이미 source-disjoint 2+ 관측과 support veto를 요구한다. **같은 raw 관측의 시간적 지속성은 새 독립 관측 두 개를 뜻하지 않는다.**

| 방법 | 고정 임계값 | office0 bad / normal 제거 | 유한 normal 보존 | 공통 normal 보존 | bad recall |
|---|---:|---:|---:|---:|---:|
{chr(10).join(development)}

B6/B7에도 같은 부분집합 보정 규칙을 적용했다. B8은 개발 원본 pre-map에서 보정하되, 실제 replay는 매번 **자기 정책의 직전 맵**에서 다시 DoG를 계산한다. 경로 의존성 때문에 실제 개발·평가 normal 보존이 보정 진단과 다르면 그대로 보고하며 재튜닝하지 않는다. legacy control은 E3의 office0 전용 임계값 그대로다. 이 통제군들의 후보별 첫 제거 시점이 E3와 정확히 일치하는지 검증한다.

## room0 회귀: 후보별 실제 결정

bad/normal은 고정된 생성 snapshot pose에 대한 GT geometry proxy다. unknown GT는 정밀도·recall 분모에서 제외하고 제거 수를 별도로 기록한다. 이는 엄밀한 Gaussian별 물리적 floater oracle이 아니다.

| 방법 | 제거 bad / normal / unknown | 정밀도 | 전체 bad recall | 정상 active 보존 | 유한 normal 보존 | 공통 normal 보존 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

![부분집합 보호와 제거량](../figures/E3b/risk_tradeoff.png)

각 방법의 전체·자체 유한 점수·공통 후보·anchor별 결과와 최종 추정 pose / GT-anchor / consensus 라벨 민감도를 `configs/e3b_room0_results_summary.json`에 기록했다. 일부 subset에서만 유리한 값을 골라 전체 우위로 주장하지 않는다. B8은 중복 억제 proxy이므로 GT-valid 중복을 줄일 수 있지만 정상 구조 coverage와의 차이를 함께 본다. B6/B7/B8은 GeoGS-inspired proxy이며 원 논문 전체 시스템 재현이 아니다.

## 실제 맵 coverage·깊이

각 정책의 membership으로 compact Gaussian map을 만들고 같은 E3 CPU 렌더러로 평가했다. 최종 추정 pose·trajectory Sim3 정렬·512×288 camera·검정 배경·alpha cutoff·GT depth mask·오차 허용범위는 E3와 같다. 최종 맵은 홀수 원본 프레임 {', '.join(map(str,spec['render_frames']))}의 11시점, 임시 맵은 각 실제 KF 직후의 다음 홀수 프레임에서 렌더했다. 평가 GT pose와 depth는 admission·임계값·evidence에 쓰지 않았다.

| 방법 | 깊이 L1 (m) | 최종 coverage | correct coverage | boundary correct | 임시 맵 coverage 평균 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(geometry)}

L1은 covered 픽셀에서 계산하므로 coverage와 같이 해석한다. correct coverage는 전체 유효 GT 픽셀에서 `max(0.05m, 0.02×GT depth)` 이내의 비율이다. 자연 작동점의 결과이며 matched-budget E4·TSDF·RGB NVS 결과가 아니다.

![E3 hard DEFER와 가용성 비교](../figures/E3b/coverage_preservation.png)
![동일 시점의 실제 깊이 오차](../figures/E3b/depth_error.png)

PROVISIONAL은 증거 부족의 의미를 유지하며 정상으로 인증한 KEEP과 구별한다. 실제 snapshot의 렌더 membership은 `도착한 원본 active 후보 − 그때까지 REJECT된 후보`와 정확히 같아야 한다. queue·보류로 생긴 미표현 후보는 0개다. confidence/observation cache와 frozen pool은 CPU에 그대로 있으므로 GPU memory·총 RSS 절감을 주장하지 않는다. 기록된 CPU replay 시간은 저장된 score 읽기와 정책 계산이며 새 feature 계산을 포함한 online latency가 아니다.

이 방식은 **검증 전 렌더링 차단보다 임시 편입 후 사후 제거에 가깝다.** 불량 후보가 충분한 증거를 얻을 때까지 노출되는 것을 막지는 않는다. 그 노출 기간의 렌더링 손실·실제 처리 지연·비용은 E6의 별도 검증 대상이다.

## 판정과 다음 행동

봉인한 기준은 전체/유한/공통/충분한 anchor normal 보존 ≥99%, bad recall ≥1%, bad 제거 ≥30개, 원본 대비 coverage 손실 ≤0.5pp, 깊이 L1 증가 ≤0.005m, B6_safe/B7_safe/B8_safe 각각보다 전체 및 공통 후보 정밀도 +2pp다. 이미 확인한 장면이므로 다음 표는 회귀 진단이다.

| 방법 | 기준 | room0 결과 |
|---|---|---|
{chr(10).join(checkrows)}

{fresh_section}

E3b 전체 상태는 **{summary['status']}**다. 회귀 결과가 기준을 충족하더라도 room1 fresh 평가와 무결성 검증을 통과하기 전에는 E4 GO가 아니다. 기준 미달이면 실패한 항목을 새 개발 iteration에서 다루되 평가 결과에 맞춰 임계값을 이동시켜 이번 실행의 성공으로 기록하지 않는다. 대조군 대비 부분집합 보호·불량 제거·coverage의 유용한 trade-off가 없으면 정책 개선 주장을 축소한다.

## 재현·실행 범위

개발·회귀 실행과 검증:

```bash
bash scripts/run_e3b.sh test
bash scripts/run_e3b.sh prepare
bash scripts/run_e3b.sh replay office0
bash scripts/run_e3b.sh replay room0
bash scripts/run_e3b.sh evaluate office0
bash scripts/run_e3b.sh evaluate room0
bash scripts/run_e3b.sh verify
bash scripts/run_e3b.sh report
```

GPU가 보이는 실행 환경에서 **같은 봉인**으로 새 room1 1,000원본프레임/500입력 평가를 실행한다:

```bash
bash scripts/run_e3b.sh fresh-status
bash scripts/run_e3b.sh fresh-download
bash scripts/run_e3b.sh fresh-baseline
bash scripts/run_e3b.sh fresh-score
bash scripts/run_e3b.sh replay room1
bash scripts/run_e3b.sh fresh-labels
bash scripts/run_e3b.sh evaluate room1
bash scripts/run_e3b.sh verify
bash scripts/run_e3b.sh report
```

{fresh_execution} 기존 후보·점수·E3 코드와 산출물은 수정하지 않았다. 완료된 봉인·replay·evaluation은 덮어쓰지 않는다.

**테스트 56개 PASS**(기존 45개 + E3b 11개). 부분집합/anchor 위험 집중, 시간 누적 임계값, 중간 NaN의 연속성 단절, 미관측 즉시 렌더, 미래 후보 차단, 거부 후 복구 금지, 미보정 정책의 비거부, GT 읽기 차단을 검사했다. 무결성 검증은 개발 임계값 재계산·모든 snapshot의 즉시편입 membership·첫 제거 시점/revision·legacy control 일치·B8 자기 prefix·compact map/hash를 확인했다. code·환경·봉인·결과는 `configs/e3b_*`, 원본 출력은 `results/E3b_provisional_admission/`에 보관했다. 커밋은 생성하지 않았다.
'''
    path=ROOT/'docs/experiments/E3b_provisional_admission.md';path.write_text(report)
    save_json(out/'figure_manifest.json',dict(figures=[digest(p) for p in sorted(figdir.glob('*.png'))],
        report=digest(path),code=digest(Path(__file__))))
    extra=['scripts/check_e3b.py','scripts/report_e3b.py','scripts/download_e3b_replica.py']
    save_json(ROOT/'configs/e3b_code_manifest.json',dict(sealed_code=seal['code'],
        reporting_code=[digest(ROOT/p) for p in extra],figures=digest(out/'figure_manifest.json'),
        summary=digest(out/'metrics.json'),validation=digest(out/'validation.json')))
    print('Wrote E3b report, figures and suite status; go_for_e4 =',go)


if __name__=='__main__':main()
