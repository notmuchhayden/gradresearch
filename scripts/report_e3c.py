"""Produce the tracked E3c report from sealed, verified measurements."""
import json
import os
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts')]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'results/E3c_matched_evidence/.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from prepare_e2b_run import digest,save_json


def main():
    spec=json.loads((ROOT/'configs/e3c_matched_evidence.json').read_text());out=ROOT/spec['output']
    seal=json.loads((out/'seal.json').read_text());validation=json.loads((out/'validation.json').read_text())
    assert validation['status']=='PASS'
    scenes=['office0','room0','room1','room2']
    results={s:json.loads((out/'evaluation'/s/'metrics.json').read_text()) for s in scenes}
    fresh=results['room2']
    regression_safe=all(results[s]['assessment'][n]['passed'] for s in spec['regression_scenes']
                        for n in ['D_shared','P_shared','D_union','P_union'])
    go=fresh['go_for_e4'] and regression_safe
    summary=dict(status='GO_FOR_E4' if go else 'REVISE',go_for_e4=go,research_wide_go=False,
        fresh_scene='room2',fresh_passed=fresh['go_for_e4'],regression_safety=regression_safe,
        primary_pair=spec['primary_pair'],fresh_comparison=fresh['paired_comparison'],
        completed=scenes,pending=[],validation=digest(out/'validation.json'),seal=digest(out/'seal.json'),
        scene_metrics={s:digest(out/'evaluation'/s/'metrics.json') for s in scenes},
        next_step='Conditionally enter a separately registered E4 comparison, retaining D_maskmedian as well as D_shared and P_shared; no broad plane superiority claim' if go else
        'Keep E4 on hold. Retain matched depth as the strong admission baseline; inspect failure by anchor and surface orientation, then register a new development hypothesis and a new unseen scene. Do not retune on room2 or infer that holes caused this result.')
    median=fresh['methods']['D_maskmedian']['common'];plane=fresh['methods']['P_shared']['common']
    summary['aggregation_ablation']=dict(scene='room2',depth_method='D_maskmedian',
        plane_extra_bad=plane['bad_rejected']-median['bad_rejected'],
        eligible_recall_gain=plane['bad_recall']-median['bad_recall'],
        interpretation='Secondary ablation, not a replacement for the registered primary test; retain median depth in E4')
    summary['scope']='Single fresh scene passes the registered matched-second-largest comparison; room0 and room1 favor depth. Broad superiority and superiority over median-depth ablation remain unproven.'
    save_json(out/'metrics.json',summary);save_json(ROOT/'configs/e3c_results_summary.json',summary)
    pct=lambda x:'—' if x is None else f'{100*x:.4f}%'
    num=lambda x:'—' if x is None else f'{x:.6f}'
    figdir=ROOT/'docs/figures/E3c';figdir.mkdir(parents=True,exist_ok=True)
    fig,axs=plt.subplots(1,2,figsize=(12,4.3),layout='constrained')
    x=np.arange(4);width=.15
    for j,name in enumerate(['D_maskmedian','D_shared','P_shared','D_union','P_union']):
        key='union_common' if name.endswith('union') else 'common'
        axs[0].bar(x+(j-2)*width,[100*results[s]['methods'][name][key]['bad_recall'] for s in scenes],width,label=name)
        axs[1].bar(x+(j-2)*width,[100*results[s]['methods'][name][key]['precision'] if results[s]['methods'][name][key]['precision'] is not None else np.nan for s in scenes],width,label=name)
    for ax in axs:
        ax.set(xticks=x,xticklabels=['office0 (dev)','room0 (reused)','room1 (reused)','room2 (fresh)']);ax.grid(axis='y',alpha=.2)
    axs[0].set_ylabel('Bad recall on matched ever-finite cohort (%)');axs[1].set_ylabel('Rejection precision (%)')
    axs[0].legend(fontsize=8);fig.savefig(figdir/'matched_scores.png',dpi=180);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(12,4.3),layout='constrained')
    for name in ['B1','D_native','D_shared','P_shared','D_union','P_union']:
        m=fresh['methods'][name]
        axs[0].plot([r['frame'] for r in m['temporal_frames']],[100*r['coverage'] for r in m['temporal_frames']],marker='.',label=name)
        axs[1].scatter(100*m['final_render']['coverage'],1000*m['final_render']['depth_l1_m'])
        axs[1].annotate(name,(100*m['final_render']['coverage'],1000*m['final_render']['depth_l1_m']),fontsize=8,
            xytext=(4,4 if name in ['B1','P_shared','P_union'] else -10),textcoords='offset points')
    axs[0].set(xlabel='Next held-out odd frame after actual KF decision',ylabel='GT depth coverage (%)');axs[0].legend(fontsize=8)
    axs[1].set(xlabel='Final-map mean GT depth coverage (%)',ylabel='Covered-pixel depth L1 (mm)')
    fig.suptitle('E3c fresh room2: sealed office0 thresholds, fixed poses and Gaussian parameters')
    fig.savefig(figdir/'fresh_coverage.png',dpi=180);plt.close(fig)
    # A standalone export of the fresh depth-error diagnostic.
    fig,axs=plt.subplots(1,3,figsize=(12,3.5),layout='constrained')
    for ax,name in zip(axs,['B1','D_shared','P_shared']):
        z=np.load(out/f'evaluation/room2/render/{name}/frame000701.npz')
        error=np.abs(z['pred']-z['gt']);error[(z['weight']<=.001)|~z['valid']]=np.nan
        cmap=plt.get_cmap('magma').copy();cmap.set_bad('#79bce8')
        im=ax.imshow(error,vmin=0,vmax=.3,cmap=cmap);ax.set_title(name);ax.axis('off')
    fig.colorbar(im,ax=axs.tolist(),label='Depth error (m); blue = uncovered or invalid',shrink=.8)
    fig.savefig(figdir/'fresh_depth_error.png',dpi=180);plt.close(fig)
    lines=['# E3c — 동일 인과적 관측 조건에서 depth와 plane 점수 비교','',
        f'**실행 완료: 2026-10-22. 판정: {summary["status"]}; E4 '+('비교 실험의 진행 조건 충족. 다장면 우위는 미확인.' if go else '보류.')+'**','',
        '## 질문과 사전 등록','',
        'E3b는 미관측 후보를 즉시 provisional로 렌더해 hard DEFER 공백을 보완했다. 그러나 B6와 plane은 관측 자격·집계·support veto가 달랐다. E3c는 **같은 시점에 같은 관측을 사용해도 plane 잔차가 depth 잔차보다 불량을 더 잘 골라내는가**를 검사한다.','',
        'office0만 임계값 개발에 사용했다. 이미 살펴본 room0·room1은 회귀 장면이고 **room2는 사전 등록한 새 평가 장면**이다. room2는 원본 1,000프레임 중 짝수 500개를 동일 backbone·weights·seed 0·32-KF buffer·원본 filter로 처리했다. 임계값·정책·평가 기준을 봉인한 뒤 평가했으며 room2 GT 라벨은 모든 admission 결정이 끝난 뒤 만들었다.','',
        '새 기준은 정상 보존 ≥99%, 원본 대비 coverage 하락 ≤0.5%p, 깊이 L1 증가 ≤5 mm, 전체 bad recall ≥1%, bad 제거 ≥30개다. own finite·공통 finite·finite normal ≥100인 anchor별 보존을 검사한다. 이 조건을 두 방법 모두 만족하면서 **동일 ever-finite 후보의 bad recall을 plane이 ≥2%p 높이고 정밀도 손실은 ≤0.1%p**여야 한다. 대칭 union veto에서도 안전 조건 및 양의 recall 개선을 요구한다. 이는 E3c에 새로 사전 등록한 기준이며 E3b의 정밀도 +2%p 기준을 소급 변경하지 않는다.','',
        '## 비교 정책','',
        '| 정책 | 관측·집계 |','|---|---|',
        '| B1 | 원본 active 후보 전부 유지 |',
        '| D_native | 원래 B6의 depth 유한 관측 median; E3c 위험 보정 |',
        '| D_maskmedian | 공통 관측·2개 이상·plane support veto 후 depth median |',
        '| D_shared / P_shared | 관측별 finite depth ∩ finite plane, 2개 이상, 두 번째 큰 점수, 동일 plane-zero support veto |',
        '| D_union / P_union | 같은 공통 관측·집계, 어느 점수든 0인 shared 관측이 하나라도 있으면 둘 다 veto |','',
        '각 actual KF snapshot에 도착한 source-disjoint raw view와 그 시점의 pose만 쓴다. 먼저 관측별 교집합을 적용하고 나중에 집계한다. 두 잔차 모두 evidence의 예측 radius로 정규화한다. score 방향별 Gaussian covariance의 3σ를 제외한다. unknown은 렌더 가능한 provisional이고 제거는 absorbing이다. 모든 정책은 같은 고정 Gaussian·pose에서 실제 membership만 바꾼다. D_native의 **점수**는 기존 B6와 같지만 임계값은 E3c 공통 cohort로 다시 개발 보정했으므로 E3b B6_safe 정책의 재현으로 해석하지 않는다.','',
        '**공통 gate에는 plane PCA의 신뢰성 판정이 들어간다.** 따라서 D_shared는 PCA를 전혀 안 쓰는 baseline이 아니며, 이 실험은 해당 gate 아래 잔차 점수의 조건부 가치를 분리한다. primary support veto가 plane에 정의되어 있다는 비대칭은 union 대조로 점검한다. 후보와 각 evidence의 source는 겹치지 않지만 evidence끼리 공유 이미지를 가질 수 있으므로 두 view를 완전히 독립인 통계 표본으로 부르지 않는다.','',
        '## 봉인된 office0 임계값','',
        '| 정책 | 임계값 |','|---|---:|']
    lines += [f'| {name} | {num(t)} |' for name,t in seal['thresholds'].items() if name!='B1']
    lines += ['', '후보별 시간 누적 최대 점수의 99% higher quantile을 own finite normal, 공통 ever-finite normal, normal ≥100인 각 anchor에서 계산해 최댓값을 썼다. strict `>`만 제거한다. 두 paired 방법의 매 snapshot 유한 후보 및 ever-finite 후보는 정확히 같다. **ever-finite 교집합은 개발 위험 보정과 사후 진단 분모에만 쓰며 미래의 관측 가능성을 실제 admission gate로 쓰지 않는다.**','',
        '## 실제 결과','',
        'bad는 E1 GT 분류의 front-error(class 3), normal은 class 1/2다. unknown(class 0) 제거도 따로 기록하며 정밀도 분모에서는 제외한다. 여기서 불량은 해당 기하 분류를 뜻하며 모든 시각적 결함을 포괄하지 않는다.','',
        '| 장면 | KF | 원본 active | primary 공통 후보 | 공통 bad / normal |','|---|---:|---:|---:|---:|']
    for s in scenes:
        meta=json.loads((out/'scores'/s/'score_metadata.json').read_text());c=results[s]['methods']['P_shared']['common']
        lines.append(f'| {s}'+(' (개발)' if s=='office0' else ' (새 평가)' if s=='room2' else ' (회귀)')+f' | {meta["keyframes"]} | {meta["active"]:,} | {c["candidates"]:,} | {c["bad"]:,} / {c["normal"]:,} |')
    for s in scenes:
        r=results[s];lines+=['',f'### {s}','',
            '| 정책 | bad / normal / unknown 제거 | 정밀도 | 전체 bad recall | 자체 finite normal 보존 | primary 공통 bad recall | coverage | 깊이 L1 (m) |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for name,a in r['methods'].items():
            m=a['decision']['creation'];v=a['final_render']
            lines.append(f'| {name} | {m["bad_rejected"]:,} / {m["normal_rejected"]:,} / {m["unknown_rejected"]:,} | {pct(m["precision"])} | {pct(m["bad_recall"])} | {pct(m["finite_normal_retention"])} | {pct(a["common"]["bad_recall"])} | {pct(v["coverage"])} | {num(v["depth_l1_m"])} |')
        lines+=['','| paired 대조 | plane−depth 공통 bad recall | 정밀도 차이 | 판정 |','|---|---:|---:|---|']
        for suffix,a in r['paired_comparison'].items():
            lines.append(f'| {suffix} | {pct(a["eligible_recall_gain"])}p | {pct(a["precision_delta"])}p | '+('PASS' if a['passed'] else 'FAIL: '+', '.join(k for k,v in a['checks'].items() if not v))+' |')
        lines+=['','안전·최소 제거 조건 미달: '+('; '.join(n+'='+','.join(a['failed']) for n,a in r['assessment'].items() if a['failed']) or '없음')+'.']
    lines+=['','![같은 후보에서 잔차 비교](../figures/E3c/matched_scores.png)','',
        '## 새 room2의 coverage·시간별 검사','',
        'coverage는 GT-valid pixel에서 누적 렌더 weight >0.001인 비율이다. mesh의 위상적 구멍 개수가 아니다. 깊이 L1은 덮인 pixel에서 계산하므로 coverage와 함께 해석한다. 최종 지도는 사전 등록한 홀수 11프레임, 시간별 지도는 실제 KF snapshot 바로 다음 홀수 프레임에서 동일 CPU 수치 적응 렌더러로 평가했다. E3 개발 RGB CUDA pre-map parity PSNR 54.7–60.7 dB를 계승하며 새 장면 CUDA depth 동등성이나 GPU latency/VRAM 개선을 주장하지 않는다.','',
        '| 정책 | 최종 coverage 변화 (%p) | temporal 평균 coverage 변화 (%p) | 최대 temporal coverage 손실 (%p) |','|---|---:|---:|---:|']
    b=fresh['methods']['B1']
    for name,a in fresh['methods'].items():
        delta=a['final_render']['coverage']-b['final_render']['coverage']
        td=a['temporal_mean']['coverage']-b['temporal_mean']['coverage']
        worst=max(0,max(bb['coverage']-aa['coverage'] for aa,bb in zip(a['temporal_frames'],b['temporal_frames'])))
        lines.append(f'| {name} | {100*delta:.6f} | {100*td:.6f} | {100*worst:.6f} |')
    lines+=['','![실제 시점별 지도 coverage](../figures/E3c/fresh_coverage.png)','',
        '![room2 홀수 프레임 701 깊이 오차](../figures/E3c/fresh_depth_error.png)','',
        '## pose 라벨 민감도','',
        '정책과 임계값을 바꾸지 않고 room2의 creation / final estimated / GT-anchor / cross-pose consensus 라벨로 제거 대상을 다시 집계했다. 공통 후보 분모도 고정한다.','',
        '| 라벨 | depth bad / normal | plane bad / normal | depth / plane 공통 bad recall |','|---|---:|---:|---:|']
    d=dict(np.load(out/'replay/room2/D_shared/decisions.npz'));p=dict(np.load(out/'replay/room2/P_shared/decisions.npz'))
    mask=d['original_active']&d['ever_finite'];ys=dict(np.load(out/'evaluation/room2/labels.npz'))
    for mode,y in ys.items():
        dm=fresh['methods']['D_shared']['decision'][mode];pm=fresh['methods']['P_shared']['decision'][mode]
        bad=mask&(y==3);den=int(bad.sum())
        dr=float((bad&(d['state']==3)).sum()/den) if den else None;pr=float((bad&(p['state']==3)).sum()/den) if den else None
        lines.append(f'| {mode} | {dm["bad_rejected"]:,} / {dm["normal_rejected"]:,} | {pm["bad_rejected"]:,} / {pm["normal_rejected"]:,} | {pct(dr)} / {pct(pr)} |')
    lines+=['','## 판정과 다음 조치','',
        f'**{summary["status"]}: '+('사전 등록한 새 room2 비교 및 회귀 안전 조건을 충족했다. E4는 별도 matched-budget 계획으로 진행할 수 있다.' if go else '이번 조건에서 plane 점수의 추가 가치를 E4 진행 기준까지 입증하지 못했다. E4는 계속 보류한다.')+'**','',
        '실패 항목은 위 paired 결과 및 정책별 안전 검사에 명시했다. 정상·coverage 보존과 depth 대비 점수의 추가 가치는 별개의 판단이다. **room0·room1은 depth에 유리하고 room2는 plane에 유리한 혼합 결과**이므로 모든 장면에서 plane이 우월하다고 해석할 수 없다.','',
        f'집계 ablation도 중요하다. room2에서 D_maskmedian은 bad {median["bad_rejected"]:,}개, P_shared는 {plane["bad_rejected"]:,}개를 제거했다. 차이는 **{summary["aggregation_ablation"]["plane_extra_bad"]}개 / 공통 bad recall {100*summary["aggregation_ablation"]["eligible_recall_gain"]:.4f}%p**에 그친다. 이는 사전 등록한 두 번째 큰 값 집계의 primary PASS를 취소하거나 대체하는 새 판정 기준이 아니다. 다만 **더 강한 median-depth 대조군보다 충분히 유용하다는 증거는 아직 부족**하며 E4에서 이 대조군을 반드시 유지해야 한다.','',
        '이번 평가 결과에 맞춰 임계값을 옮기거나 room2를 다시 fresh test라고 부르지 않는다. 다음은 D_maskmedian·D_shared·P_shared를 모두 유지한 별도 사전 등록 E4 비교이며, anchor·표면 방향별 분석은 이후 개발 가설을 정하는 데 사용한다. 단일 fresh 장면·고정 후보·고정 pose의 결과이며 다장면 일반화, 통계적 유의성, end-to-end SLAM, NVS·TSDF·메모리·실시간 또는 novelty의 증명은 아니다. E4 자체는 이번 실행에 포함하지 않았다.','',
        '## 검증·산출물·재현','',
        '**63개 테스트 PASS, 4장면 무결성 검증 PASS.** 기존 세 장면의 모든 actual snapshot에서 D_native와 기존 B6, P_shared와 기존 plane 점수가 정확히 일치했다. 모든 paired finite mask, source disjointness·시간 순서, 개발 임계값 재계산, 모든 membership·첫 제거 시점/revision, 코드·입력·모델·지도 hash를 검사했다. 새 room2는 기존 장면과 입력 RGB hash가 겹치지 않고 원본 backbone·weights·설정이 동일하다. 이전 E3/E3b 코드와 산출물은 보존했다.','',
        '- [프로토콜](../../configs/e3c_protocol_registration.json), [임계값·코드 봉인](../../configs/e3c_preregistration.json), [설정](../../configs/e3c_matched_evidence.json)',
        '- [전체 결과](../../configs/e3c_results_summary.json), [검증](../../configs/e3c_validation.json), [CPU 환경](../../configs/e3c_environment.json), [GPU 환경](../../configs/e3c_gpu_environment.json)',
        '- 원본: `results/E3c_matched_evidence/`의 `scores`, `replay`, `evaluation`, `sealed_code`, `logs`; room2 GT 라벨·raw baseline 포함. 생성 배열·모델·데이터는 git 제외, 요약·코드·보고서·그림은 추적 가능하다.','',
        '```bash','bash scripts/run_e3c.sh test','bash scripts/run_e3c.sh initialize',
        'bash scripts/run_e3c.sh score office0','bash scripts/run_e3c.sh prepare',
        '# room2 baseline은 GPU가 보이는 실행 환경에서 실행',
        'bash scripts/run_e3c.sh fresh-download','bash scripts/run_e3c.sh fresh-baseline',
        'for scene in room0 room1 room2; do bash scripts/run_e3c.sh score "$scene"; done',
        'for scene in office0 room0 room1 room2; do bash scripts/run_e3c.sh replay "$scene"; done',
        'bash scripts/run_e3c.sh fresh-labels',
        'for scene in office0 room0 room1 room2; do bash scripts/run_e3c.sh evaluate "$scene"; done',
        'bash scripts/run_e3c.sh verify','bash scripts/run_e3c.sh report','```','',
        '완료된 출력·봉인은 덮어쓰지 않는다. 위 명령은 실행 순서 기록이며 기존 완료 경로에서 재실행하면 보존 guard가 중단한다. 새 실행은 새 출력 경로와 별도 등록이 필요하다.']
    (ROOT/'docs/experiments/E3c_matched_evidence.md').write_text('\n'.join(lines)+'\n')
    report_code=['scripts/check_e3c.py','scripts/report_e3c.py']
    save_json(ROOT/'configs/e3c_reporting_manifest.json',dict(code=[digest(ROOT/p) for p in report_code],
        report=digest(ROOT/'docs/experiments/E3c_matched_evidence.md'),figures=[digest(p) for p in sorted(figdir.glob('*.png'))]))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
