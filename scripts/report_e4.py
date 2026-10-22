"""E4 prospective decision and tracked report, with all controls retained."""
import json
import os
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts')]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'results/E4_matched_budget/.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from prepare_e2b_run import digest,save_json


def compare(p,b,rule):
    if p is None or b is None or not p['reachable'] or not b['reachable']:
        return dict(passed=False,checks=dict(reachable=False),relative_chamfer_gain=None)
    valid=p['surface']['valid'] and b['surface']['valid']
    gain=(b['surface']['chamfer_m']-p['surface']['chamfer_m'])/b['surface']['chamfer_m'] if valid else None
    checks=dict(same_count=p['count']==b['count'],same_parameter_bytes=p['map']['bytes']==b['map']['bytes'],
        tsdf_valid=valid,chamfer_improvement=gain is not None and gain>=rule['chamfer_relative_improvement_min'],
        psnr=p['render']['psnr_db']>=b['render']['psnr_db']-rule['psnr_loss_max_db'],
        ssim=p['render']['ssim']>=b['render']['ssim']-rule['ssim_loss_max'],
        lpips=p['render']['lpips_alex']<=b['render']['lpips_alex']+rule['lpips_increase_max'],
        coverage=p['render']['coverage']>=b['render']['coverage']-rule['coverage_loss_max'],
        completion=valid and p['surface']['completion_ratio_5cm']>=b['surface']['completion_ratio_5cm']-rule['completion_ratio_loss_max'])
    return dict(passed=all(checks.values()),checks=checks,failed=[k for k,v in checks.items() if not v],relative_chamfer_gain=gain)


def main():
    spec=json.loads((ROOT/'configs/e4_matched_budget.json').read_text());out=ROOT/spec['output']
    seal=json.loads((out/'seal.json').read_text());validation=json.loads((out/'validation.json').read_text());assert validation['status']=='PASS'
    scenes=['office0',*spec['regression_scenes'],spec['fresh_scene']]
    results={s:json.loads((out/'evaluation'/s/'metrics.json').read_text()) for s in scenes}
    indexes={s:{r['id']:r for r in result['rows']} for s,result in results.items()}
    frac=spec['primary_keep_fraction'];suffix=f'__policy_fallback__{frac:g}'
    controls=['D_maskmedian','D_shared','B2_confidence','B4_voxel','B6_depth','B7_rgb','B8_dog','B3_random_s0','B3_random_s1','B3_random_s2']
    comparisons={s:{m:compare(indexes[s].get('P2_plane'+suffix),indexes[s].get(m+suffix),spec['progress']) for m in controls} for s in scenes}
    fresh=spec['fresh_scene'];natural=indexes[fresh]['P2_plane__natural'];normal=natural['natural_classification']['normal_active_retention']
    safe=normal is not None and normal>=spec['progress']['normal_retention_natural_min']
    go=safe and all(v['passed'] for v in comparisons[fresh].values())
    summary=dict(status='GO_FOR_E5_E6_VALIDATION' if go else 'REVISE',research_wide_go=False,go_for_e5_e6=go,
        fresh_scene=fresh,primary_arm='policy_fallback',primary_keep_fraction=frac,natural_normal_retention=normal,
        natural_normal_pass=safe,comparisons=comparisons,scenes=scenes,pending=[],
        scope='Fixed-pool, fixed-pose, no refinement. Shared-fallback results are not pure admission. TSDF reference is the observed GT-depth-derived surface; no full-scene mesh or off-axis NVS claim.',
        seal=digest(out/'seal.json'),validation=digest(out/'validation.json'),
        scene_metrics={s:digest(out/'evaluation'/s/'metrics.json') for s in scenes})
    p=indexes[fresh]['P2_plane'+suffix];d=indexes[fresh]['D_maskmedian'+suffix]
    summary['fresh_primary']={m:indexes[fresh][m+suffix] for m in ['P2_plane','D_maskmedian','D_shared','B3_random_s0']}
    original=indexes[fresh]['B1__natural'];depth=indexes[fresh]['B6_depth'+suffix]
    summary['findings']=dict(plane_vs_median_chamfer_relative_gain=comparisons[fresh]['D_maskmedian']['relative_chamfer_gain'],
        plane_vs_native_depth_chamfer_relative_gain=comparisons[fresh]['B6_depth']['relative_chamfer_gain'],
        plane_natural_bad_recall=natural['natural_classification']['bad_recall'],
        plane_natural_finite_fraction=natural['natural_classification']['finite_candidates']/natural['natural_classification']['candidates'],
        natural_removed=original['count']-natural['count'],shared_fallback_removed=p['fallback_rejections'],
        parameter_buffer_reduction_fraction=1-p['map']['bytes']/original['map']['bytes'])
    summary['timing_and_view_diagnostics']={}
    for s in scenes:
        replay=json.loads((out/'replay'/s/'manifest.json').read_text())
        feature_manifest=json.loads((ROOT/replay['source_features']['path']).read_text())
        metadata=json.loads((ROOT/feature_manifest['metadata']['path']).read_text())
        poses=np.loadtxt(ROOT/spec['datasets'][s]/s/'traj.txt').reshape(-1,4,4)
        translations=[];angles=[]
        for frame in spec['rgb_frames']:
            rel=np.linalg.inv(poses[frame-1])@poses[frame]
            translations.append(float(np.linalg.norm(rel[:3,3])))
            angles.append(float(np.degrees(np.arccos(np.clip((np.trace(rel[:3,:3])-1)/2,-1,1)))))
        summary['timing_and_view_diagnostics'][s]=dict(feature_bundle_wall_s=metadata.get('cpu_seconds'),
            natural_replay_and_quota_selection_cpu_wall_s=replay['wall_seconds'],
            heldout_to_previous_even_translation_m=dict(min=min(translations),median=float(np.median(translations)),max=max(translations)),
            heldout_to_previous_even_rotation_degrees=dict(min=min(angles),median=float(np.median(angles)),max=max(angles)))
    summary['next_step']='Register E5 shared-bias stress and E6 causal online validation, retaining all strong controls' if go else 'Keep E5/E6 efficacy progression on hold. Compare the best depth/photometric controls and inspect geometry-versus-RGB tradeoffs in development; register a new hypothesis and unseen scene before retuning. Do not infer that matching count or masking alone saves online system VRAM.'
    save_json(out/'metrics.json',summary);save_json(ROOT/'configs/e4_results_summary.json',summary)
    figs=ROOT/'docs/figures/E4';figs.mkdir(parents=True,exist_ok=True)
    names=[m for m in spec['methods'] if indexes[fresh][m+suffix]['reachable']]
    x=np.arange(len(names));fig,axs=plt.subplots(1,3,figsize=(17,5),layout='constrained')
    colors=['#c14535' if m=='P2_plane' else '#dd9433' if m=='D_maskmedian' else '#3484ab' for m in names]
    for ax,key,label in [(axs[0],'psnr_db','PSNR (dB)'),(axs[2],'lpips_alex','LPIPS AlexNet')]:
        ax.bar(x,[indexes[fresh][m+suffix]['render'][key] for m in names],color=colors);ax.set_ylabel(label)
    axs[1].bar(x,[1000*indexes[fresh][m+suffix]['surface']['chamfer_m'] for m in names],color=colors);axs[1].set_ylabel('Sampled TSDF Chamfer (mm)')
    for ax in axs:ax.set(xticks=x,xticklabels=names);ax.tick_params(axis='x',rotation=70);ax.grid(axis='y',alpha=.2)
    fig.suptitle(f'E4 fresh {fresh}: exact {100*frac:g}% count / parameter-byte match, shared fallback')
    fig.savefig(figs/'fresh_primary.png',dpi=170);plt.close(fig)
    fig,axs=plt.subplots(1,3,figsize=(15,4.5),layout='constrained')
    plotnames=['D_maskmedian','D_shared','P2_plane','B2_confidence','B6_depth','B7_rgb','B8_dog']
    for m in plotnames:
        data=[indexes[fresh][f'{m}__policy_fallback__{q:g}'] for q in sorted(spec['keep_fractions'])]
        data=[r for r in data if r['reachable']];xs=[r['fraction']*100 for r in data]
        axs[0].plot(xs,[r['render']['psnr_db'] for r in data],marker='o',label=m)
        axs[1].plot(xs,[r['surface']['chamfer_m']*1000 for r in data],marker='o',label=m)
        axs[2].plot(xs,[r['memory']['allocated_map_increment_bytes']/2**20 for r in data],marker='o',label=m)
    for ax in axs:ax.set_xlabel('Original-active Gaussians retained (%)');ax.grid(alpha=.2)
    axs[0].set_ylabel('PSNR (dB)');axs[1].set_ylabel('Sampled TSDF Chamfer (mm)');axs[2].set_ylabel('Actual compact-map CUDA allocation (MiB)')
    axs[0].legend(fontsize=7);fig.savefig(figs/'budget_tradeoff.png',dpi=170);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    gains=[comparisons[s]['D_maskmedian']['relative_chamfer_gain'] for s in scenes]
    axs[0].bar(np.arange(len(scenes)),[100*v if v is not None else np.nan for v in gains]);axs[0].axhline(2,color='r',ls='--',label='registered +2% target')
    axs[0].set(xticks=np.arange(len(scenes)),xticklabels=scenes,ylabel='Plane vs median-depth Chamfer reduction (%)');axs[0].legend(fontsize=8)
    for m in ['D_maskmedian','D_shared','P2_plane','B6_depth','B7_rgb']:
        r=indexes[fresh][m+suffix]
        if r['reachable']:
            axs[1].scatter(r['render']['psnr_db'],r['surface']['chamfer_m']*1000);axs[1].annotate(m,(r['render']['psnr_db'],r['surface']['chamfer_m']*1000),fontsize=8,xytext=(3,4),textcoords='offset points')
    axs[1].set(xlabel='Fresh primary PSNR (dB)',ylabel='Sampled TSDF Chamfer (mm)');fig.savefig(figs/'scene_tradeoff.png',dpi=170);plt.close(fig)
    pct=lambda v:'—' if v is None else f'{100*v:.4f}%'
    val=lambda v:'—' if v is None else f'{v:.6f}'
    lines=['# E4 — 동일 Gaussian 수·파라미터 바이트에서 RGB·기하 품질 비교','',
        f'**실행 완료: 2026-10-22. 판정: {summary["status"]}.**','',
        '## 목적과 봉인','',
        'E3c의 plane 점수 이득이 실제 지도 품질과 메모리 예산에서도 유용한지 검사했다. office0에서만 개발하고 기존 room0·room1·room2는 회귀로 구분했다. **새 office1**은 아직 E4에 쓰지 않은 장면으로 사전 등록했으며 원본 1,000프레임/짝수 500입력·동일 backbone·weights·seed·32-KF buffer·원본 filter로 기준선을 생성했다. 모델·지도·pose refinement는 0 step이다. 새 GT 라벨은 모든 자연 정책 및 예산별 선택이 끝난 뒤 생성했다.','',
        '**주 평가:** office1에서 원본 active의 75%를 유지하는 `policy_fallback` arm. 정상 자연 보존 ≥99%이며, P2가 median-depth·동일 집계 depth·confidence·voxel·원래 B6·RGB·DoG·무작위 3 seeds 각각보다 TSDF sampled Chamfer를 ≥2% 줄여야 한다. 동시에 PSNR 손실 ≤0.2 dB, SSIM 손실 ≤0.005, LPIPS 증가 ≤0.01, coverage 손실 ≤0.5%p, completion ratio 손실 ≤1%p를 요구했다. 필수 대조군이 도달 불가하면 GO로 판정하지 않는다. 90%·99% 및 회귀 장면은 사후 주 조건을 바꾸는 데 사용하지 않는다.','',
        'E3c와 E3b의 완료 결과·코드·판정을 보존했다. E4 평가 전 identical-membership 렌더 캐시의 방법별 finite-score 라벨 메타데이터를 수정해 최초 봉인을 `seal_revisions/v1_before_evaluation/`에 보존하고 다시 봉인했다. 임계값·membership 규칙·예산·평가 기준은 동일하며 office1 기준선/특징 및 E4 held-out 평가 전에 수행했다.','',
        '## 방법과 arm의 구별','',
        '| 방법 | 정의 |','|---|---|',
        '| B1 | 원본 active, 원본 DC appearance |',
        '| B2_confidence | 기존 E3b 개발 임계값의 confidence gate |',
        '| B3_random_s0/s1/s2 | 무작위 count controls, seed 0/1/2; 자연점은 95% 진단용 |',
        '| B4_voxel | 실제 snapshot pose의 원본 pre-map 및 같은 birth 내 voxel duplicate(0/1) 점수 |',
        '| B5_self | 같은 source prediction의 means–pts3d 상대 거리, 자기 일관성 대조군 |',
        '| B6_depth | 원래 source-disjoint depth median + 기존 E3b 임계값 |',
        '| B7_rgb | source-disjoint masked 5×5 RGB NCC 영역 proxy + 기존 E3b 임계값 |',
        '| B8_dog | 각 정책의 실제 과거 보유 지도에서 다시 계산한 insertion DoG proxy |',
        '| D_shared / D_maskmedian | E3c의 동일 관측 gate에서 두 번째 큰 depth / median-depth |',
        '| P1_creation | birth 시점에서만 반복 plane 판정 |',
        '| P2_plane | E3c P_shared 임계값 그대로, 실제 KF마다 재검사 |',
        '| P3_rgb_and | 같은 snapshot의 min(plane/t_plane, RGB/t_RGB), AND 결합; office0 별도 보정 |','',
        'B4의 binary 점수는 개발 normal 보호 후 임계값 1, B5는 원본 means=pts3d라 임계값 0이다. strict `>`이므로 두 자연 정책은 제거 0개가 정상 결과다. 이들의 score ranker는 count 목표에서 별도 진단한다. 모든 B6/B7/B8은 논문의 전체 시스템 재현이 아닌 inspired proxy이며, shared gate에는 PCA/plane support 판정이 들어간다.','',
        '- `natural`: 봉인 임계값만 적용한 정책 자체의 결과. B3의 95% 자연점은 자원 대조군이며 인과적 admission 효과가 아니다.',
        '- `rank_only`: 시간 누적 점수의 큰 값부터 제거하는 **고정 후보 풀의 사후 자원 진단**. 유한 점수가 부족하면 도달 불가. threshold-safe 정책과 구별하며 B8 점수는 natural 정책의 실제 map에서 얻은 값이다.',
        '- `policy_fallback`: natural 제거를 유지하고 남은 후보에 **동일한 seed 0 무작위 우선순위**를 적용해 정확히 K개를 남긴다. 자연 생존 수가 K 미만이면 복구하지 않고 도달 불가다. B1/B3은 직접 count control이다.','',
        '**25% budget pruning 전체를 순수 admission 효과로 주장하지 않는다.** membership 결정에 GT/held-out RGB를 사용하지 않았다. rank/fallback은 causal quota controller의 실행 결과가 아니며 E6 online replay를 대신하지 않는다.','',
        '## 예산·렌더·TSDF 정의','',
        '원본과 같은 degree-0 appearance를 사용했다. 각 선택 지도를 float32 means 3 + 대칭 covariance 상삼각 6 + DC RGB 3 + opacity 1, 즉 **Gaussian당 52 bytes**의 무압축 `.f32`로 저장했다. 따라서 동일 count arm의 파라미터 직렬화 바이트도 정확히 같다. membership index 및 JSON 메타데이터는 별도이며 전체 저장 디렉터리 크기가 같다는 주장은 아니다. 실제 CUDA compact 버퍼에 선택된 Gaussian만 올려 resident count·allocated 증가·render peak를 측정했다. active mask만 줄인 값을 VRAM 절감으로 세지 않았다.','',
        'RGB는 사전 고정한 홀수 11개 view 전체 영상에서 PSNR·SSIM·LPIPS AlexNet을 계산했다. 동일 GT-aligned 고정 estimated pose·카메라·해상도·검은 배경·원본 색상 및 exposure 전처리를 사용했다. gain은 첫 입력 frame000000의 RGB 평균에 고정하고 예측 영상에 맞추지 않았다. 단순 인접 홀수 frame이므로 temporal held-out이며 off-axis NVS reference는 없어 별도 수치를 만들지 않았다.','',
        '기하는 고정된 짝수 20개 view의 expected rendered z-depth를 **Open3D 0.19.0 TSDF**(4 cm voxel, 12 cm truncation)로 융합했다. 같은 view·카메라·GT-valid interior mask의 GT depth도 같은 TSDF로 융합해 관측 영역 reference를 만들었다. 이는 전체 장면 GT mesh 비교가 아니다. 각 mesh에서 triangle area에 비례한 점 100,000개를 seed 0으로 샘플링해 accuracy(pred→reference), completion(reference→pred), 그 평균 Chamfer, 5 cm precision/completion ratio/F1을 계산했다. 점 샘플 근사 오차가 있으며 통계적 유의성이나 논문 mesh 수치와 직접 동등 비교를 주장하지 않는다. 구현은 [Open3D TSDF API](https://www.open3d.org/html/python_api/open3d.pipelines.integration.ScalableTSDFVolume.html) 및 [mesh sampling 문서](https://open3d.org/docs/release/python_api/open3d.geometry.TriangleMesh.html)를 참고했다.','',
        '렌더러·LPIPS·TSDF 비용을 구분했고 render timing은 frame501에서 warmup 2회 후 동기화 5회 median/p95다. peak renderer allocation은 LPIPS 실행 후 reset하여 RGB render만 따로 측정하며 LPIPS 모델의 상주 baseline도 기록했다. 동시 GPU 기준선/평가 없이 실행했다. cost-matched·tracker FPS·온라인 전체 시스템 VRAM 개선은 이 실험의 결론 범위가 아니다.','',
        '## 새 office1 주 조건 결과','',
        '| 방법 | active/resident | parameter MiB | PSNR | SSIM | LPIPS | depth coverage | TSDF accuracy / completion / Chamfer (m) | completion@5cm |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for m in spec['methods']:
        a=indexes[fresh][m+suffix]
        if not a['reachable']:lines.append(f'| {m} | 도달 불가: {a["reason"]} | — | — | — | — | — | — | — |');continue
        r=a['render'];g=a['surface']
        lines.append(f'| {m} | {a["count"]:,} | {a["map"]["bytes"]/2**20:.3f} | {r["psnr_db"]:.4f} | {r["ssim"]:.6f} | {r["lpips_alex"]:.6f} | {pct(r["coverage"])} | {val(g["accuracy_m"])} / {val(g["completion_m"])} / {val(g["chamfer_m"])} | {pct(g["completion_ratio_5cm"])} |')
    lines+=['','![새 장면 동일 예산 주 비교](../figures/E4/fresh_primary.png)','',
        '| P2 vs 대조군 | Chamfer 상대 개선 | 미달 항목 |','|---|---:|---|']
    for m,a in comparisons[fresh].items():lines.append(f'| {m} | {pct(a["relative_chamfer_gain"])} | '+(', '.join(a.get('failed',['unreachable'])) if not a['passed'] else '없음')+' |')
    lines+=['',f'자연 정책 P2의 정상 보존은 **{pct(normal)}**다. 주 비교 판정은 **{summary["status"]}**이며 다장면 연구 전체 GO와 구별한다.','',
        f'plane의 Chamfer는 {p["surface"]["chamfer_m"]:.6f} m, median-depth는 {d["surface"]["chamfer_m"]:.6f} m로 상대 개선은 **{100*comparisons[fresh]["D_maskmedian"]["relative_chamfer_gain"]:.4f}%**다. 기준 2%에 미달한다. 원래 B6 depth는 **{depth["surface"]["chamfer_m"]:.6f} m**, PSNR **{depth["render"]["psnr_db"]:.4f} dB**로 plane({p["render"]["psnr_db"]:.4f} dB)보다 두 지표에서 좋았다. 이번 주 비교의 미달 원인은 coverage/RGB 비열등성보다 **대조군 대비 충분한 기하 추가 개선 부족**이다.','',
        '## 정책 자체의 자연 작동점','',
        '| 장면 | 방법 | active | bad / normal / unknown 제거 | normal 보존 | PSNR | coverage | Chamfer (m) |','|---|---|---:|---:|---:|---:|---:|---:|']
    for s in scenes:
        for m in ['B1','D_maskmedian','D_shared','P2_plane','B6_depth','B7_rgb','B8_dog']:
            a=indexes[s][m+'__natural'];c=a['natural_classification'];r=a['render']
            lines.append(f'| {s} | {m} | {a["count"]:,} | {c["bad_rejected"]:,} / {c["normal_rejected"]:,} / {c["unknown_rejected"]:,} | {pct(c["normal_active_retention"])} | {r["psnr_db"]:.4f} | {pct(r["coverage"])} | {val(a["surface"]["chamfer_m"])} |')
    lines+=['','### 새 장면 pose 라벨 민감도','',
        'P2 자연 정책을 고정한 채 GT 라벨의 pose 기준만 바꾼 진단이다. 주 판정은 creation 라벨을 사용했다.','',
        '| 라벨 | bad / normal / unknown 제거 | normal 보존 |','|---|---:|---:|']
    for mode,c in natural['all_label_modes'].items():
        lines.append(f'| {mode} | {c["bad_rejected"]:,} / {c["normal_rejected"]:,} / {c["unknown_rejected"]:,} | {pct(c["normal_active_retention"])} |')
    lines+=['',f'office1의 자연 P2는 bad {natural["natural_classification"]["bad_rejected"]:,}개·normal {natural["natural_classification"]["normal_rejected"]:,}개·unknown {natural["natural_classification"]["unknown_rejected"]:,}개를 제거했다. 자체 유한 점수 후보는 전체 active의 **{100*summary["findings"]["plane_natural_finite_fraction"]:.4f}%**, 전체 GT bad recall은 **{pct(natural["natural_classification"]["bad_recall"])}**다. 높은 정밀도·정상 보존만으로 지도 전체의 오류를 충분히 줄였다고 볼 수 없다.','',
        f'75% 지도에서 natural 정책이 제거한 후보는 {summary["findings"]["natural_removed"]:,}개이고 **공통 fallback이 추가로 제거한 후보는 {p["fallback_rejections"]:,}개**다. 파라미터 버퍼 약 25% 감소를 plane admission 자체의 메모리 이득으로 귀속하지 않는다.']
    lines+=['','## 예산 도달성과 비용','',
        '| 장면 | 전체 arm | 도달 | 도달 불가 |','|---|---:|---:|---:|']
    for s,r in results.items():lines.append(f'| {s} | {len(r["rows"])} | {r["rendered_arms"]} | {r["unreachable_arms"]} |')
    lines+=['','도달 불가 목록과 이유는 장면별 결과 JSON의 모든 row에 남겼다. score finite 부족과 natural map이 이미 목표보다 작은 경우를 분리한다. B1/B3의 quota arm은 직접 uniform count control이며 unknown을 증거 점수로 승격한 것이 아니다.','',
        '![예산별 품질과 실제 compact allocation](../figures/E4/budget_tradeoff.png)','',
        '| office1 75% 방법 | 실제 map allocated 증가 MiB | RGB render peak allocated MiB | render median / p95 ms | fallback 추가 제거 |','|---|---:|---:|---:|---:|']
    for m in ['B3_random_s0','D_maskmedian','D_shared','P2_plane','B6_depth','B7_rgb','B8_dog']:
        a=indexes[fresh][m+suffix]
        if a['reachable']:lines.append(f'| {m} | {a["memory"]["allocated_map_increment_bytes"]/2**20:.3f} | {a["memory"]["render_peak_allocated_bytes"]/2**20:.3f} | {a["timing"]["render_median_ms"]:.3f} / {a["timing"]["render_p95_ms"]:.3f} | {a.get("fallback_rejections",0):,} |')
    lines+=['','동일 membership의 렌더·TSDF·timing은 한 번 평가 후 재사용하고 `reused_identical_membership`에 원본을 명시했다. 방법별 GT 분류·finite 분모는 별도로 계산했다. map allocation과 peak는 renderer 평가 프로세스의 값이며 tracker 가중치·CPU 원본 export·감사 파일을 포함한 시스템 전체 크기는 아니다.','',
        '| 장면 | feature bundle wall s | natural replay + quota CPU wall s | 홀수→직전 짝수 이동 중앙값 m / 회전 중앙값 deg |','|---|---:|---:|---:|']
    for s,a in summary['timing_and_view_diagnostics'].items():
        lines.append(f'| {s} | {a["feature_bundle_wall_s"]:.3f} | {a["natural_replay_and_quota_selection_cpu_wall_s"]:.3f} | {a["heldout_to_previous_even_translation_m"]["median"]:.6f} / {a["heldout_to_previous_even_rotation_degrees"]["median"]:.6f} |')
    lines+=['','feature bundle은 공통 전처리·기하/RGB 점수를 함께 계산한 시간이며 P2 단독의 알고리즘 비용이 아니다. 기존 세 장면의 feature 시간은 E3c 기하 bundle을 재사용한 값으로, 새 room2·office1의 RGB 포함 bundle과 직접 속도를 비교하지 않는다. pose gap 수치는 temporal held-out의 제한을 정량화한 진단이다.','',
        '## 회귀와 해석','',
        '![장면별 plane 대 median-depth 및 RGB–geometry tradeoff](../figures/E4/scene_tradeoff.png)','',
        '이미 살펴본 room0·room1·room2 결과는 일반화 성공을 승인하는 새 test가 아니다. scene별 결과를 그대로 보고하고 Gaussian·pixel·KF를 독립 반복으로 세어 유의성을 주장하지 않는다. 무작위 3 seeds는 thinning 변동성 대조군이며 새 독립 장면 수를 늘리지 않는다.','',
        '## 판정과 다음 단계','',
        f'**{summary["status"]}.** '+('봉인한 새 장면 주 조건을 통과했다. 다음은 별도 등록 E5 stress 및 E6 causal online 검증이다.' if go else '봉인한 새 장면 주 조건을 충족하지 못했다. E5/E6 효능 검증으로의 자동 진행을 보류한다.'),'',
        '미달 항목은 위 모든 필수 대조군 표에 명시했다. depth/photometric 대조군보다 실용적으로 유용한지, geometry 이득이 RGB 품질 손실을 동반하는지를 함께 판단해야 한다. 현재 결과로 test 임계값·budget·장면을 바꿔 성공으로 재기록하지 않는다. 다음 개발 가설과 새 평가 분할을 별도 등록하며 기존 완료 장면을 다시 fresh test라고 부르지 않는다.','',
        '## 검증·산출물·재현','',
        '**75개 테스트, compact CUDA 대 기존 CUDA 수치 일치, 합성 TSDF 평면 검사, 5장면 무결성 검사 PASS.** 동일 count·52-byte parameter buffer, 실제 resident 수, fallback의 비복구·unknown ranker의 도달성, 모든 원본 filter 범위, E3c 자연 정책 일치, B8 과거 자기 지도, 봉인·모델·입력·지도·mesh hash와 fresh 결정 후 GT 평가를 검사했다.','',
        '- [프로토콜](../../configs/e4_protocol_registration.json), [설정](../../configs/e4_matched_budget.json), [임계값·코드 봉인](../../configs/e4_preregistration.json)',
        '- [전체 판정](../../configs/e4_results_summary.json), [검증](../../configs/e4_validation.json), [GPU 환경](../../configs/e4_gpu_environment.json), [평가 환경](../../configs/e4_environment.json)',
        '- 원본 출력: `results/E4_matched_budget/{scores,replay,selection,evaluation,sealed_code,seal_revisions,logs}`. compact `.f32` 및 TSDF `.ply` 보존. 생성 데이터는 git 제외, 코드·요약·그림·보고서는 추적 가능하다.','',
        '```bash','bash scripts/run_e4.sh test','bash scripts/run_e4.sh initialize','bash scripts/run_e4.sh score room2',
        'bash scripts/run_e4.sh prepare','bash scripts/run_e4.sh fresh-download',
        '# GPU가 보이는 환경에서 실행','bash scripts/run_e4.sh fresh-baseline','bash scripts/run_e4.sh score office1',
        'for scene in office0 room0 room1 room2 office1; do bash scripts/run_e4.sh replay "$scene"; done',
        'bash scripts/run_e4.sh fresh-labels',
        'for scene in office0 room0 room1 room2 office1; do bash scripts/run_e4.sh evaluate "$scene"; done',
        'bash scripts/run_e4.sh verify','bash scripts/run_e4.sh report','```','',
        '새 의존성은 `results/E4_matched_budget/deps`에 설치해 기존 venv 패키지를 바꾸지 않았다. 완료된 replay/evaluation/봉인은 보존 guard로 덮어쓰지 않는다. 위 명령은 실행 순서이며 독립 재실행에는 새 출력 경로와 별도 사전 등록이 필요하다.']
    (ROOT/'docs/experiments/E4_matched_budget.md').write_text('\n'.join(lines)+'\n')
    save_json(ROOT/'configs/e4_reporting_manifest.json',dict(code=[digest(Path(__file__)),digest(ROOT/'scripts/check_e4.py')],
        report=digest(ROOT/'docs/experiments/E4_matched_budget.md'),figures=[digest(p) for p in sorted(figs.glob('*.png'))]))
    print(json.dumps(dict(status=summary['status'],go_for_e5_e6=go,comparisons=comparisons[fresh]),indent=2))


if __name__=='__main__':main()
