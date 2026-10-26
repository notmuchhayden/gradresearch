#!/usr/bin/env python3
"""Separate A1-G/M reports, paired figures and a frozen V1 diagnostic recipe."""
from pathlib import Path
import json
import shutil
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_gm_common import context,cases,ARMS
from prepare_e2b_run import digest,save_json


def md_rows(result,names):
    text='| Scope | 후보 수 | C00 | C10 | C01 | C11 | Support gate |\n|---|---:|---:|---:|---:|---:|---|\n'
    for name in names:
        v=result['cases'][name];p=v['primary'];es=[p['summary'][a]['MAE_m'] for a in ARMS];gate=p['support_gate']
        text+=f"| {name} | {v['count']:,} | "+' | '.join(f'{x:.6f}' if x is not None else 'N/A' for x in es)+f" | {'PASS' if gate['passed'] else 'FAIL'} ({gate['qualifying_views']}/{gate['registered_views']}) |\n"
    return text


def snapshot(exp,name,arm,frame):
    spec,out,_,_=context(exp);definition=cases(exp)[name]
    p=(ROOT/spec['A1_C']/'evaluation'/definition['base']/arm if definition['reuse'] else out/'evaluation'/name/arm)/f'frame{frame:04d}.npz'
    with np.load(p) as f:return {k:f[k] for k in f.files}


def comparison_image(exp,names,frame,path,title):
    snapshots={(name,a):snapshot(exp,name,a,frame) for name in names for a in ARMS}
    limit=10 if names[0].startswith('office2') else 200
    fig,axes=plt.subplots(len(names)*2,4,figsize=(13,3.3*len(names)),constrained_layout=True)
    for row,name in enumerate(names):
        for col,a in enumerate(ARMS):
            s=snapshots[name,a];axes[row*2,col].imshow(s['rgb']);axes[row*2,col].set_title(f'{name} | {a}',fontsize=8)
            im=axes[row*2+1,col].imshow(np.ma.masked_where(~s['covered'],s['depth']),vmin=0,vmax=limit,cmap='viridis')
    for ax in axes.ravel():ax.axis('off')
    fig.colorbar(im,ax=axes.ravel().tolist(),shrink=.6,label='Expected camera Z (m)');fig.suptitle(title)
    fig.savefig(path,dpi=160);plt.close(fig)


def main():
    gs,go,_,_=context('G');ms,mo,_,_=context('M')
    G=json.loads((go/'analysis/results.json').read_text());M=json.loads((mo/'analysis/results.json').read_text())
    gf=ROOT/'docs/figures/A1G';mf=ROOT/'docs/figures/A1M';gf.mkdir(parents=True,exist_ok=True);mf.mkdir(parents=True,exist_ok=True)
    colors=['#667085','#d97706','#c43c4a','#14836b'];xx=np.arange(4)
    fig,axes=plt.subplots(1,3,figsize=(13,4),constrained_layout=True)
    for ax,pair in zip(axes,G['pairs']):
        ax.bar(xx-.18,[pair['errors_left'][a] for a in ARMS],.36,color=colors,alpha=.4,label='Position prefix gauge')
        ax.bar(xx+.18,[pair['errors_right'][a] for a in ARMS],.36,color=colors,label='Orientation prefix gauge')
        ax.set_xticks(xx,ARMS);ax.set_title(pair['left'].replace('_position','')+(' | support FAIL' if not pair['group']['support_gate']['passed'] else ''),fontsize=9)
        ax.set_ylabel('MAE on SAME 8-arm target pixels (m)');ax.legend(fontsize=8);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('A1-G | same prefix and source IDs | no best heldout gauge selection')
    fig.savefig(gf/'paired_gauge_metrics.png',dpi=180);plt.close(fig)
    gaugedata={s:json.loads((go/'gauges'/(s+'.json')).read_text()) for s in ['office2','HKairport01']}
    fig,axes=plt.subplots(1,2,figsize=(10,3.6),constrained_layout=True)
    for ax,(scene,meta) in zip(axes,gaugedata.items()):
        ax.bar(['SV1','SV2','SV3'],meta['prefix']['estimated_singular_ratios'],color='#667085');ax.set_yscale('log');ax.set_ylim(.01,1.5)
        ax.set_title(f"{scene}: gauge rotation difference {meta['relative_rotation_deg']:.2f} deg");ax.set_ylabel('Prefix centered-position singular value / SV1');ax.grid(axis='y',alpha=.2)
    fig.suptitle('Prefix trajectory observability; lower minor singular values imply limited positional excitation')
    fig.savefig(gf/'prefix_observability.png',dpi=180);plt.close(fig)
    comparison_image('G',['HKairport01_wide_position','HKairport01_wide_orientation'],204,gf/'HKairport_gauge_view204.png','HK wide | fixed view 204 | RGB and expected depth; conditional reference')
    fig,axes=plt.subplots(1,3,figsize=(13,4),constrained_layout=True)
    groups=[['office2_strict','office2_full'],['HKairport01_common','HKairport01_full_common'],['HKairport01_wide','HKairport01_full_wide']]
    for ax,names in zip(axes,groups):
        for off,name,alpha in [(-.18,names[0],.4),(.18,names[1],1.)]:
            p=M['cases'][name]['primary'];ax.bar(xx+off,[p['summary'][a]['MAE_m'] for a in ARMS],.36,color=colors,alpha=alpha,label=name)
        ax.set_xticks(xx,ARMS);ax.set_ylabel('Own C4-mask MAE (m); masks differ');ax.set_title(names[1],fontsize=9);ax.legend(fontsize=7);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('A1-M scope comparison | full mixed arms retain source-unobserved predictions, not full GT')
    fig.savefig(mf/'scope_metrics.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
    for col,mode in enumerate(['source','target']):
        for pattern,color in [('uniform_hash','#14836b'),('scan_rows','#c43c4a')]:
            nodes=[(d,M['cases'][f'office2_{mode}_{pattern}_{int(d*100):02d}pct']) for d in [.01,.1]]
            for row,a in enumerate(['C00','C10']):
                axes[row,col].plot([d*100 for d,_ in nodes],[v['primary']['summary'][a]['MAE_m'] for _,v in nodes],'o-',color=color,label=pattern)
                dense=M['cases']['office2_strict']['primary']['summary'][a]['MAE_m'];axes[row,col].axhline(dense,color='#667085',ls='--')
                for d,v in nodes:
                    if not v['primary']['support_gate']['passed']:axes[row,col].scatter([d*100],[v['primary']['summary'][a]['MAE_m']],s=150,facecolors='none',edgecolors='black',linewidths=1.5)
        for row,a in enumerate(['C00','C10']):
            axes[row,col].set_xscale('log');axes[row,col].set_xticks([1,10],['1%','10%']);axes[row,col].set_title(f'{mode}-only | {a} | own C4 mask');axes[row,col].set_ylabel('Depth MAE (m)');axes[row,col].set_xlabel('Nominal retained pixel density');axes[row,col].grid(alpha=.2);axes[row,col].legend(fontsize=8)
    fig.suptitle('Map thinning vs measurement thinning | dashed=dense baseline; black rings=support FAIL')
    fig.savefig(mf/'source_vs_target_sampling.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,6),constrained_layout=True)
    names=list(M['cases']);values=[100*M['cases'][name]['primary']['mean_fraction_of_reference'] for name in names]
    ax.barh(names,values,color=['#14836b' if M['cases'][name]['primary']['support_gate']['passed'] else '#c43c4a' for name in names]);ax.invert_yaxis();ax.set_xlim(0,105)
    ax.set_xlabel('Mean common fraction of case reference (%)');ax.set_title('Support gate: green PASS / red FAIL; target-only denominator is sampled GT');ax.tick_params(axis='y',labelsize=8)
    fig.savefig(mf/'support_coverage.png',dpi=180);plt.close(fig)
    comparison_image('M',['HKairport01_wide','HKairport01_full_wide'],204,mf/'HKairport_scope_view204.png','HK wide subset vs full native mixed map | same view 204, different source support')
    paired='| Scope / gauge | C00 | C10 | C01 | C11 | 8-arm support |\n|---|---:|---:|---:|---:|---|\n'
    for pair in G['pairs']:
        gate=pair['group']['support_gate']
        for name,values in [(pair['left'],pair['errors_left']),(pair['right'],pair['errors_right'])]:
            paired+=f'| {name} | '+' | '.join(f'{values[a]:.6f}' for a in ARMS)+f" | {'PASS' if gate['passed'] else 'FAIL'} |\n"
    greport=f'''# A1-G: Prefix gauge 민감도 결과

**실행일: 2026-10-26. 실행 COMPLETE. 판정: Gauge-dependent rigid-pose effect, 보정 GO 보류.**

같은 prefix·후보·target 픽셀에서도 **HKairport wide의 rigid pose 참조 교체 효과가 정렬에 따라 반전**됐다. Local 참조 개입은 두 정렬 모두에서 개선됐지만, 효과 크기와 pose 해석은 gauge에 조건부다. 절대 오차가 작은 정렬을 사후 정답으로 선택하지 않았다.

## 1. 고정 조건

- [설정](../../configs/a1_g_gauge_sensitivity.json), [등록](../../results/A1_G_gauge_sensitivity/2026-10-26/registration.json). A1-C 결과를 알고 설계한 개발 진단이며, 새 G/M 결과를 보기 전 입력 **1,134개**와 생성·평가 코드, 비교군·분모·support gate를 고정했다.
- Position gauge는 기존 final-revision prefix position Sim(3)이다. 같은 입력으로 fit을 재계산해 저장값과 일치를 확인했다.
- Orientation gauge는 같은 prefix의 `Rref @ Rest.T` SO(3) 평균으로 회전을 정한 뒤, 그 회전에서 **전역 scale 하나와 translation 하나**를 prefix 위치로 fit했다. Office2 원본 `<200`의 100개 pose, HK grid `<100`의 80개 pose만 사용했다. Post-prefix/heldout GT는 fit하지 않았다.
- Office2 strict 1,200,827후보·400뷰, HK common 6,368후보·40뷰, HK wide 242,162후보·40뷰를 유지했다. 최종 pose revision·source ID·color/opacity·camera 모델은 동일하다. 새 모델 추론/학습은 없다.
- 상대 gauge D의 scale을 effective local y와 covariance에 함께 반영하고, rigid rotation·camera origin을 D로 옮겼다. `new C00 world == D(old C00 world)` mean/covariance 검사를 통과했다. 참조 local과 참조 SE(3)는 바꾸지 않았다. 이는 C 단위 재배분 불변성(A1-U)과 다른 **전역 정렬 불확실성** 검사다.

## 2. Prefix 관측 조건

| Scene | Prefix pose | 추정 위치 SV 비율 | 두 gauge 회전 차이 | Global scale 비 |
|---|---:|---|---:|---:|
| office2 | 100 | 1 / 0.376868 / 0.119359 | 1.550503° | 0.999922 |
| HKairport01 | 80 | 1 / 0.082965 / 0.017367 | 9.929346° | 0.997034 |

HK prefix는 거의 직선이어서 위치만으로 회전을 정할 때의 제한된 관측 조건을 보여 준다. 이것만으로 orientation gauge가 더 정확한 물리 GT라는 뜻은 아니다. Terra pose의 물리 카메라 대응도 여전히 미해결이다.

![Prefix observability](../figures/A1G/prefix_observability.png)

## 3. 같은 target 8-arm 공통 픽셀의 결과

단위 m, 낮을수록 좋은 depth MAE다. 각 행쌍은 position/orientation 각 네 조건의 **동일 8-arm mask**를 사용한다. 각 gauge 자체 C4 결과와 별도로 기록해 mask 변경을 개선으로 혼동하지 않는다.

{paired}

HK wide의 pose 효과는 position에서 **20.359776−17.774036=+2.585740m**인 반면 orientation에서는 **12.994454−17.961217=−4.966763m**였다. 40/40뷰의 paired support가 충분한 상태에서 부호와 10% 이상 효과가 바뀌었다. 따라서 **‘이 장면은 pose만 교체하면 개선된다’는 무조건적 결론은 유지할 수 없다.**

반면 local 참조 교체는 HK wide에서 position **20.359776→10.489161m**, orientation **12.994454→3.929995m**로 모두 개선됐다. Office2도 local 개선이 유지됐고 rigid pose 효과는 두 gauge에서 모두 음수였지만, orientation gauge에서는 악화 폭이 작아졌다. HK common의 방향 반전은 좁은 support 때문에 참고 진단으로만 둔다.

![Paired gauge comparison](../figures/A1G/paired_gauge_metrics.png)

## 4. 자체 C4 분모 결과와 한계

다음은 각 gauge의 own four-arm 공통 mask다. **행 사이의 target 분모가 달라 위 paired 표와 숫자를 혼합하지 않는다.**

{md_rows(G,list(G['cases']))}

C11의 GT/reference 중심은 gauge 간 같고 covariance의 global scale만 일관되게 달라진다. 같은 픽셀에서 HK wide C11은 **2.328522/2.327428m**로 유사했다. 자체 C4의 C11 변화에는 서로 다른 C00/C10 가림 영역에 따른 mask 변화가 포함된다.

![Fixed view 204 gauge comparison](../figures/A1G/HKairport_gauge_view204.png)

## 5. 실행·검증·다음 단계

- Orientation 새 map **12개·1,920 depth-view**를 CUDA로 평가했고, position의 같은 수 cache를 hash로 검증해 재사용했다. RGB는 기존 고정 5뷰씩 총 60뷰만 렌더링했다. 전체 새 모델 추론으로 보고하지 않는다.
- Prefix-only fit·가역 world similarity·GT를 인자로 받지 않는 mask 검사 6개와 기존 38개, **총 44검사 통과**. 원본 prefix gauge 재현, 동일 후보 hash 및 HK 과거 orientation gauge와의 수치 일치도 통과했다.
- Mean per-view MAE, depth coverage와 correct coverage, 픽셀/뷰 수를 기록했다. 모든 등록 뷰와 HK 추적 공백 3뷰를 포함했다. Pixels/frames를 독립 실험 반복으로 세지 않는다.
- Q0-HK는 미해결, V1/office4는 미실행이다. Gauge가 더 좋은 heldout 결과를 보인다는 이유로 primary를 교체하지 않았다. **V1에서는 기존 position을 primary, 같은 prefix orientation을 고정 sensitivity로 둘 다 보고한다.**
- [4군 CSV](../../results/A1_G_gauge_sensitivity/2026-10-26/analysis/A1_G_four_arms.csv), [gauge/support matrix](../../results/A1_G_gauge_sensitivity/2026-10-26/analysis/A1_gauge_support_matrix.csv), [상세 결과](../../results/A1_G_gauge_sensitivity/2026-10-26/analysis/results.json), [요약](../../configs/a1_g_results_summary.json).

현재는 **유효 local 참조 개입의 개선 방향은 유지되지만 rigid pose 효과는 gauge-dependent**라는 개발 관측까지다. 다음은 고정된 V1 절차의 다른 장면 재현이며 Depth-only/pose-only 알고리즘 GO는 아니다.
'''
    source_names=[n for n,v in M['cases'].items() if v['definition']['kind']=='source_only'];target_names=[n for n,v in M['cases'].items() if v['definition']['kind']=='target_only']
    fullnames=['office2_strict','office2_full','HKairport01_common','HKairport01_wide','HKairport01_full_common','HKairport01_full_wide']
    mreport=f'''# A1-M: Source support·Target 측정 밀도·전체 지도 범위 대조

**실행일: 2026-10-26. 실행 COMPLETE. 판정: Scope/density에 조건부인 효과; 보정 GO 보류.**

Source 후보를 줄이는 경우와 target 평가 픽셀만 줄이는 경우는 달랐다. **지도·렌더링을 그대로 둔 target-only 대조**에서는 이번 office2의 효과 방향이 유지됐지만, **source-only 대조**에서는 rigid pose 효과의 방향이 바뀌는 경우가 있었다. 전체 native 지도에서는 HK local 참조 교체가 적은 후보에만 적용돼, 좁은 참조 후보에서의 큰 개선이 전체 지도 개선으로 이어지지 않았다.

## 1. 사전 고정과 비교 정의

- [설정](../../configs/a1_m_support_sensitivity.json), [등록](../../results/A1_M_support_sensitivity/2026-10-26/registration.json). G와 별도로 등록·출력·판정했다. 입력 1,134개와 mask seed·밀도·pattern·분모를 새 결과 전에 고정했다.
- Gauge는 기존 position prefix 정렬만 사용했다. **G×모든 density×pattern의 전 조합 실험이 아니다.** G와 M이 동시에 바뀔 때의 효과까지 검증했다고 주장하지 않는다.
- 기존 C의 strict/common/wide를 그대로 재사용하고, full native mixed 3범위 및 office2 source-only 4범위를 새로 렌더링했다. Target-only 4범위는 같은 dense C map/cache를 재사용했다.
- 400 office2 / 40 HK heldout view, 후보 ID·Gaussian 크기/covariance·RGB/opacity를 규약대로 유지했다. Source thinning에서는 선택된 기존 C의 **packed row 자체**를 복사해 생존 후보의 모든 값이 변하지 않게 했다. GT outlier 선택, opacity/footprint inflation, hole interpolation, 재학습은 없다.

## 2. 전체 native map의 mixed reference

| Scope | Native-active 후보 | Local 참조 교체 가능 후보 | 교체 비율 |
|---|---:|---:|---:|
| office2_full | 1,545,979 | 1,314,328 | 85.016% |
| HKairport01_full_common | 3,242,219 | 7,609 | 0.235% |
| HKairport01_full_wide | 3,242,219 | 261,958 | 8.080% |

Prefix KF를 포함한 원본 후보 전체를 보존했다. C10/C11에서는 source 참조가 있는 local 중심만 교체하고, 나머지 local은 effective 예측을 유지한다. Rigid placement 개입은 모든 후보에 적용한다. **완전 GT/Oracle 지도라고 부르면 안 된다.** 두 HK full scope의 C00/C01 map은 SHA-256까지 동일하며, C10/C11만 local 교체 범위가 다르다.

각 scope **자체 C4 target 공통 mask**의 depth MAE(m)다. Scope 간 비교는 source 정보량·후보 수가 달라지므로, 이를 physical error 기여율로 분할하지 않는다.

{md_rows(M,fullnames)}

HK full wide는 local-only **21.836925→21.807298m**로 변화가 작았다. 이것은 local 깊이가 중요하지 않다는 뜻이 아니다. 약 92%의 native source 후보는 참조 local로 교체하지 못했고, 여러 KF의 가림·opacity 합성에 의해 target 표면이 결정된다. **Wide subset의 약 48% 개선을 전체 native 지도 개선율로 확대할 수 없다는 한계**다.

Office2 full mixed에서도 strict보다 잔차가 커졌다. 같은 target common8에서 strict C00/C10/C01/C11은 **0.120241/0.072655/0.140378/0.018412m**, full은 **0.140793/0.112479/0.163155/0.079434m**였다. Source 참조가 없는 후보 및 prefix를 추가하는 실험이며, 특정 후보 유형 하나가 원인이라고 확정하지 않는다.

![Own-mask scope metrics](../figures/A1M/scope_metrics.png)

![HK wide subset vs full mixed map](../figures/A1M/HKairport_scope_view204.png)

## 3. Source-only thinning — 지도 후보 수만 변경

Office2 strict 1,200,827개에서 seed 0의 **uniform pixel hash / row-scan**, nominal **1%/10%**를 사용했다. Hash는 frame ID와 pixel index만 사용한다. Row scan은 주기 100/10에서 frame별 고정 phase의 행을 선택한다. 실제 후보 수는 GT/native validity를 적용한 뒤 기록했고 부족한 칸을 다시 채우지 않았다. Dense target reference는 그대로다.

{md_rows(M,source_names)}

Uniform 10%의 matched dense+source common8에서는 dense pose-only **0.119371→0.139491m**(악화), source-thinned에서는 **0.104586→0.099543m**(소폭 개선)였다. Paired support는 충분했다. 다만 thinned의 개선은 약 4.8%로 사전 최소 효과 10%에 미달하므로 **강한 pose 우세/보정 GO로 세지 않았다.** 방향 자체가 density에 의존할 수 있다는 관측이다.

1% source 두 pattern은 support gate를 통과하지 못했고, 10% row scan도 충족 뷰 297/400(74.25%)로 등록 한도 80%에 미달했다. 이 숫자를 유리한 뷰만 골라 다시 계산하지 않았다. 삭제로 생긴 coverage·가림·compositing 변화는 새 geometry 보정 알고리즘의 성능이 아니다. 이전 pruning 연구를 재개하는 결과로 해석하지 않는다.

## 4. Target-only thinning — 지도·렌더링은 그대로, 측정만 희소화

동일 pattern/density를 target image grid에 적용하되, 모든 source 후보와 stored render는 그대로 두었다. 각 조건의 map hash와 depth/coverage cache hash가 dense C와 같음을 검증했다. **서로 다른 target 측정을 평가하는 민감도**이며, 더 작은 MAE가 나와도 지도가 개선된 것이 아니다.

{md_rows(M,target_names)}

이번 대조에서 local 개선·pose 단독 악화가 대체로 유지됐다. Uniform 1%/10%, row 1%/10% C00 MAE는 **0.120337/0.120167/0.120625/0.120299m**, 원 dense는 **0.120241m**였다. Row 1%는 `≥1,000 common pixel` 조건 등의 gate를 300/400뷰만 만족해 실패했다. Uniform 1%는 359/400으로 통과했다. 이 한 실내 장면의 측정 안정성이 실제 UAV LiDAR의 noise·extrinsic·가림·스캔 pattern을 검증하지는 않는다.

Target-only의 coverage/correct coverage 분모는 **선택된 GT**이고, 전체 dense reference 중 몇 %를 측정했는지도 별도 저장했다. Source-only는 **원 dense reference**를 분모로 유지했다. 두 정의를 같은 full-scene coverage로 비교하지 않는다.

![Source versus target thinning](../figures/A1M/source_vs_target_sampling.png)

![Support gates](../figures/A1M/support_coverage.png)

## 5. 통계·실행 기록

- 각 범위 common4와 dense-vs-각 source/full scope **common8**을 구분했다. 16조건 전역 교집합을 만들지 않았고, 빈/부족 support는 오류 0이나 강건성 통과로 채우지 않았다.
- G/M의 coverage와 correct coverage는 **해당 primary reference-valid 픽셀**(office2 GT interior, HK LiDAR-valid) 기준이다. A1-C 보고서의 office2 전체 GT-valid coverage와 분모가 다르므로 수치를 직접 동일시하지 않는다. Depth MAE와 기존 C4 mask 재현은 동일하다.
- 신규 map **28개·8,320 depth-view**, cache 재사용 **8,320 case-arm-view 참조**. Target-only의 render 재실행은 없다. G까지 합쳐 신규 map 40개·10,240 depth-view, saved RGB 200뷰를 실행했다. 같은 cache의 반복 참조를 독립 표본이나 새 모델 추론으로 세지 않는다.
- 새 6 + 기존 38 = **44검사 통과**. Seeded mask의 determinism/nesting, prefix fit의 heldout 배제, canonical world similarity 및 기존 계약을 검사했다. Source/target용 mask에 GT 오차 인자는 없다.
- HK common의 support 부족, Q0-HK 미해결 및 기존 tracking gate FAIL을 유지했다. Office3/office4 prediction은 미실행이다.
- [4군 CSV](../../results/A1_M_support_sensitivity/2026-10-26/analysis/A1_M_four_arms.csv), [gauge/support matrix](../../results/A1_M_support_sensitivity/2026-10-26/analysis/A1_gauge_support_matrix.csv), [상세 결과](../../results/A1_M_support_sensitivity/2026-10-26/analysis/results.json), [요약](../../configs/a1_m_results_summary.json).

## 5.1 Source KF·거리·confidence별 참조 범위 보충

[분포 CSV](../../results/A1_M_support_sensitivity/2026-10-26/analysis/source_strata.csv)와 [정의·상세 JSON](../../results/A1_M_support_sensitivity/2026-10-26/analysis/source_strata.json)에 14범위의 source KF, 예측 local 거리, native confidence별 후보·참조 가능·참조 불가 수를 306행으로 기록했다. 각 합계가 map manifest와 일치한다. 이는 **결과 이후 추가한 기술 통계**이며 primary metric·mask·gate·판정을 바꾸지 않았다.

거리는 참조가 없는 후보도 포함할 수 있도록 effective 예측 local의 Euclidean range를 사용했다. Confidence는 장면 전체 native-active 후보의 1/3·2/3 분위값으로 나눴고 동률을 분할하지 않았다. 경계는 office2 **9.019469/19.399624**, HK **1.786351/2.211769**다. 서로 다른 장면의 confidence 값을 같은 확률로 해석하지 않는다.

HK full wide에서 예측 거리 30–60m는 62,418개 중 3,675개(5.888%), 60–120m는 3,172,549개 중 258,279개(8.141%), 120m 이상은 7,252개 중 4개(0.055%)만 local 참조로 교체 가능했다. 30m 미만 native 후보는 없었다. **참조 부재는 오류 0이 아니다.** 이 분포는 source 관측 범위이며, 여러 source가 합성된 target 렌더링 오차를 KF/거리/confidence별 인과 기여율로 나눈 결과가 아니다.

## 6. 현재 판정

**Sparse source map과 sparse target measurement를 같은 실험으로 취급할 수 없다.** 이번 target-only 대조는 안정적이었지만 source-only는 지도 footprint·가림·support를 바꿔 pose 효과 방향까지 달라질 수 있었다. Local 참조 개입의 개선 방향은 검사한 범위에서 유지됐으나, 크기는 scope에 크게 의존했다.

따라서 단일 subset/정렬에서 local/pose 지배 원인을 결정하지 않는다. 다음은 사전 고정한 **office3 V1 진단 재현**이다. 실제 RGB-only correction이나 새로운 joint optimizer의 GO는 아직 아니다.
'''
    gp=ROOT/'docs/experiments/A1_G_gauge_sensitivity_results.md';mp=ROOT/'docs/experiments/A1_M_support_sensitivity_results.md';gp.write_text(greport);mp.write_text(mreport)
    recipe=dict(experiment='V1 office3 diagnostic replication',status='FROZEN_RECIPE_NOT_EXECUTED',date='2026-10-26',
        role='Validation replication only; not final test or algorithm efficacy',scene='office3',dataset='data/N2/Replica/office3',
        N2_registration='configs/n2_dataset_registration.json',mapping='500 even original frame IDs in [0,1000)',calibration='even IDs <200; same prefix for both gauges',evaluation='400 odd IDs 201..999',
        baseline='Existing RGB-only baseline configuration, seed0/refiner0, frozen weights/native filter. Fresh office3 inference required later, not performed here.',
        qualification=dict(tracking_fraction_min=.95,matched_prefix_poses_min=80,native_lineage_and_unit_invariance='must pass; do not select a better window after failure'),
        canonical='A1-U invariance then C00/C10/C01/C11 and CZ10/CZ11 on primary position gauge',
        gauges='Position prefix primary retained; same-prefix orientation gauge four C arms mandatory sensitivity; never choose the better heldout gauge',
        support='Strict post-prefix common source and full native mixed separately; preserve unknown local predictions. Office2-style source-only and target-only uniform_hash/scan_rows at 1% and10%, seed0, same mask definition.',
        covariance='Same canonical local covariance, rigid transport; original fixed 20 fusion views for fixed-C00-world covariance sensitivity',
        evaluation_rules='Reuse A1-C/G/M thresholds, same small comparison-group masks, paired common8, reference/full-reference fractions; missing support cannot pass robustness',
        source_specs=[digest(ROOT/'configs/a1_c_canonical_factorial.json'),digest(ROOT/'configs/a1_g_gauge_sensitivity.json'),digest(ROOT/'configs/a1_m_support_sensitivity.json')],
        interpretation='Replicate direction AND magnitude limitations, not simply positive joint oracle gain. No learned correction, no Q0-HK certification, office4 withheld.',
        predictions_run=False)
    recipepath=ROOT/'configs/v1_office3_diagnostic_protocol.json'
    if recipepath.exists():assert json.loads(recipepath.read_text())==recipe,'Existing V1 recipe preserved; explicit amendment required'
    else:save_json(recipepath,recipe)
    decision=ROOT/'docs/experiments/A1_GM_route_decision.md'
    decision.write_text('''# A1-G/M 이후 경로 판정

**실행일: 2026-10-26. A1-G와 A1-M 각각 COMPLETE. 방법/지배 오류 GO 보류.**

- **G:** HK wide에서 충분한 동일 target support를 유지해도 rigid pose 효과가 position/orientation gauge에 따라 반전했다. Local 참조 개입은 두 gauge에서 개선됐다.
- **M:** Source-only thinning은 pose 효과 방향을 바꿀 수 있었지만 target-only 측정 희소화는 이번 office2에서 효과 방향을 유지했다. Full mixed와 strict의 정보량은 달라 subset의 큰 이득을 full map 개선율로 해석할 수 없다.
- **한계:** 알려진 두 개발 장면뿐이며 실제 HK reference는 미해결이다. G×모든 density의 전체 조합은 실행하지 않았고 pixels/frames를 독립 반복으로 세지 않는다.

다음은 **office3 V1 진단 재현**이다. [고정된 절차](../../configs/v1_office3_diagnostic_protocol.json)를 저장했지만 office3 예측·평가를 실행하지 않았다. 기존 position을 primary로 유지하고 orientation을 정해진 sensitivity로 모두 보고하며, source/target 희소화를 분리한다. 이 레시피는 아직 구현/실행 완료를 뜻하지 않는다.

V1에서도 규칙·실패·scope 의존성을 먼저 보고한 뒤 A2-S/O 또는 추가 RT/R-Q 진단 여부를 결정한다. 현재 결과로 D4, pose-only 알고리즘, joint optimizer 또는 office4 최종 평가를 자동 시작하지 않는다. Q0-HK의 미해결 상태도 유지한다.

[A1-G 보고서](A1_G_gauge_sensitivity_results.md) · [A1-M 보고서](A1_M_support_sensitivity_results.md)
''')
    for exp,out,report,figdir,result in [('G',go,gp,gf,G),('M',mo,mp,mf,M)]:
        code=[ROOT/'scripts/analyze_a1_gm.py',Path(__file__)]
        if exp=='M':code.append(ROOT/'scripts/analyze_a1_m_source_strata.py')
        for p in code:
            q=out/'analysis_code'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        artifacts=[report,*sorted(figdir.glob('*.png')),out/'analysis/results.json',out/'analysis/decision.json',out/'analysis/A1_gauge_support_matrix.csv',decision,recipepath]
        if exp=='M':artifacts.extend([out/'analysis/source_strata.json',out/'analysis/source_strata.csv'])
        save_json(ROOT/f'configs/a1_{exp.lower()}_execution_manifest.json',dict(experiment='A1-'+exp,execution='COMPLETE',decision=result['decision'],
            registration=digest(out/'registration.json'),summary=digest(ROOT/f'configs/a1_{exp.lower()}_results_summary.json'),
            analysis_code=[digest(p) for p in code],artifacts=[digest(p) for p in artifacts]))
    print('Saved separate A1-G/M reports, 7 figures, route decision and unexecuted V1 recipe.',flush=True)


if __name__=='__main__':main()
