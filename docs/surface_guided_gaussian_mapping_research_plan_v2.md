# 연속 드론 영상 기반 3D Gaussian Splatting에서 이상 Gaussian 감소를 위한 교차시점 기하 정합성 기반 매핑

## 연구 설계·구현·실험 계획서 (개정판 v2.0)

- **개정일:** 2026-10-13
- **문서 단계:** 석사학위 논문 초고 작성 전 연구·실험 설계
- **원본:** `surface_guided_gaussian_mapping_research_plan.md`
- **현재 제출 계획서 제목:** **연속 영상 기반 3D Gaussian Splatting에서 이상 Gaussian 감소를 위한 기하 정합성 기반 최적화 연구**
- **영문 제목(현재 유지):** *Geometry-Consistent Optimization for Reducing Outlier Gaussians in Continuous-Video 3D Gaussian Splatting*
- **작업용 연구 명칭:** *Cross-View Surface-Supported Gaussian Admission*

> **문서 사용 원칙.** 아래는 구현 전의 가설 및 실험 계획이다. 새로운 알고리즘의 효과, 실제 재현 가능한 성능 및 논문의 독창성은 **아직 입증되지 않았다**. 공개 저장소의 기능과 본 연구의 제안, 구현 시 확인이 필요한 가정을 구분한다. 석사논문의 최종 제목과 기여도는 실험 결과를 반영해 결정한다.

---

## 0. v1에서 변경한 핵심 사항

| 항목 | v1 설계 | v2 개정 내용 | 우선순위 |
|---|---|---|---|
| Surface 검증 | 주로 Gaussian 대 fused surface 거리 | **후보 생성 Keyframe의 정보를 가능한 한 제외한 cross-view 검증**을 핵심으로 설정 | 필수 |
| 공유 오류 문제 | 위험 요소로만 서술 | 동일 MASt3R 계열 prediction의 상관 오차를 설계·실험에서 직접 통제 | 필수 |
| Local PCA | curvature 중심의 평면 판정 | 선형 분포 배제, 깊이 경계·표면 혼합 방지, 관측/가시성 조건 추가 | 필수 |
| Admission | Keep / Project / Reject | **KEEP / PROJECT / REJECT / DEFER(BYPASS)**로 확장 | 필수 |
| Score | 단일 종합 score 및 score 연동 projection | 후보 적합성·표면 신뢰성 분리; projection 강도 독립 설정 | 필수 |
| Duplicate | 새 기능 자체를 기여로 제시 | 기존 confidence thinning·voxel dedup과 **동일 Gaussian 예산에서 비교**; dedup은 확장 | 필수 비교, 알고리즘 선택 |
| Loop closure | anchor-local 변환 언급 | **Sim(3) scale·covariance 변환·cache invalidation** 명시 | 필수 |
| Memory | active count와 VRAM 중심 | candidate/active/resident count, 메모리 실제 할당, compaction 분리 | 필수 |
| Geometry 평가 | Gaussian center와 GT 표면 거리 중심 | center-based 지표를 보조로 유지하고 GT 깊이/표면 재구성·coverage를 함께 평가 | 필수 |
| 데이터셋 | 드론 영상 수집을 후반에 배치 | **초기 드론 파일럿**을 앞당겨 domain mismatch·trajectory 실패 위험 선제 확인 | 필수 |
| 연구 범위 | projection·dedup까지 최소 구현 | **교차시점 admission 및 matched-budget 검증을 핵심**, projection·dedup 선택 확장 | 필수 |
| 선행연구 | 2025년 이전 중심 | 2026년 유사 연구 확인 및 novelty 재검증 과제 추가 | 필수 |

---

# 1. 연구 문제와 목표

## 1.1 한 문장으로 정의한 문제

> **연속 RGB 영상에서 feed-forward predictor가 반복적으로 생성한 Gaussian을 장기 SLAM Map에 편입할 때, 서로 다른 시점의 기하 관측을 이용하여 잘못된 Gaussian의 편입을 억제하고 정상 표면의 표현과 렌더링 품질을 유지할 수 있는가?**

본 연구는 MASt3R-SLAM이 추정한 pose와 pointmap, Splatt3R가 예측한 Gaussian을 활용한다. 기존 네트워크의 재학습이나 완전한 mesh 재구성을 필수 요구로 두지 않고, **Map Admission(편입 의사결정)**을 독립적인 연구 대상으로 삼는다.

구체적 목표:

1. 후보 Gaussian과 같은 입력을 공유하지 않는 **다른 Keyframe의 3D 관측**에서 국소 표면 지지 근거를 확보한다.
2. 불충분한 표면 정보와 명백한 기하 불일치를 구분하여 정상 Gaussian의 불필요한 삭제를 방지한다.
3. Gaussian 수·실제 메모리·기하 오류·표면 coverage·렌더링 품질 간 trade-off를 정량 평가한다.
4. 단순 confidence filtering, 균일 thinning, voxel deduplication보다 **동일 Gaussian 예산에서 더 나은 결과를 제공하는지** 검증한다.
5. 실험이 성공하면 drone video의 장기 Map에 적용 가능성을 검토한다. 대규모 및 실시간 성능은 측정 후 주장한다.

## 1.2 연구 범위와 제외 범위

**필수 범위(MVP)**

- Splatt3R-SLAM 기본 실험 및 평가 파이프라인 재현
- Pose·Pointmap·confidence·Gaussian의 export와 좌표계 검증
- 서로 다른 Keyframe의 관측을 이용한 surface patch 생성/검증
- KEEP / REJECT / DEFER(BYPASS) 방식의 geometry-guided Gaussian admission
- 단순 거리 필터·confidence filter·uniform thinning·voxel dedup과 matched-budget 비교
- GT 가능한 장면의 geometry 평가 및 held-out novel-view rendering 평가
- 드론 영상 초기 파일럿 및 오류 사례 분석

**검증 후 선택적으로 확장**

- 안전 조건을 만족하는 Gaussian의 제한적 soft projection
- surface-aware keep-best deduplication 및 실제 map compaction
- covariance orientation/thickness correction

**연구 필수 범위에서 제외**

- 새로운 MASt3R/SLAM backbone 학습, SLAM backend 전면 개편
- full semantic segmentation, dynamic-object SLAM 전체 해결
- 보이지 않는 표면의 AI hallucination 또는 surface completion
- 완전한 triangle mesh 추출, photorealistic texture baking
- 전면적인 end-to-end Gaussian parameter 재학습

# 2. 연구 질문과 검증 가설

| ID | 연구 질문 | 직접 대응할 실험 |
|---|---|---|
| **RQ1(핵심)** | 자기 Pointmap 기반 거리 검증보다 **교차시점 기하 검증**이 실제 이상 Gaussian을 더 정확하게 판별하는가? | E1/E2, GT 기준 precision-recall·geometry error |
| **RQ2(핵심)** | 교차시점 기반 admission은 **동일 Gaussian 수/용량**에서 기존 단순 thinning·voxel filtering보다 재구성 품질을 더 잘 보존하는가? | E3, PSNR·SSIM·LPIPS·completeness·Pareto |
| RQ3(확장) | 표면 신뢰도가 높은 일부 Gaussian에 한정한 soft projection이 삭제 정책보다 품질-기하 정확도의 균형을 개선하는가? | E4 |
| RQ4(확장) | 반복 관측 영역에서 surface-aware dedup이 단순 voxel dedup보다 동일 예산에서 유리한가? | E5 |
| RQ5(성능) | 교차시점 판정과 map 유지 비용을 포함하여 장기 시퀀스에서 얼마나 확장 가능한가? | E6 |

검증 가설(증명 이전에는 **기대 효과**로만 기재):

- **H1**: 외부 GT로 판정한 outlier 탐지 성능(예: PR-AUC 또는 고정 inlier recall에서의 outlier precision)이 자기 Pointmap 기반 필터보다 개선된다.
- **H2**: 동일 active Gaussian budget 조건에서 cross-view admission의 rendering/geometry 지표가 단순 thinning 이상이다.
- **H3**: 보수적 DEFER/BYPASS로 표면 정보가 부족한 정상 geometry의 손실을 줄일 수 있다.
- **H4(확장)**: 일정 영역의 재관측이 증가할 때 active/resident Gaussian 증가율을 낮출 수 있다.

> **중요:** Gaussian 수가 적어지거나 내부 surface distance가 작아졌다는 이유만으로 H1·H2가 확인된 것은 아니다. 반드시 독립 GT·held-out view·matched-budget 실험을 함께 사용한다.

# 3. 관련 연구 및 novelty 검증

| 기술/논문 | 기존 기여 및 본 연구와의 관계 | 본 연구에서 주의할 점 |
|---|---|---|
| **3DGS (Kerbl et al.)** | Gaussian 최적화와 adaptive density control | 본 연구는 일반적인 prune/clone 기능 자체를 새롭다고 주장하지 않음 |
| **DUSt3R / MASt3R** | 이미지 쌍 기반 pointmap 및 matching prior | pointmap의 물리적·metric 정확성 및 신뢰도는 보장되지 않음 |
| **MASt3R-SLAM** | tracking, local pointmap fusion, loop closure, Sim(3) 기반 global consistency | 모든 3D geometry가 독립 GT로 교정되는 것은 아님 |
| **Splatt3R** | MASt3R 계열에서 per-pixel Gaussian 예측 | Gaussian과 지원 pointmap이 **같은 예측 편향**을 공유할 수 있음 |
| **Splatt3R-SLAM** | 연속 영상에서 feed-forward Gaussian mapping | 이미 confidence gate, map budget, 선택적 voxel dedup 및 refinement 기능을 제공함 |
| **CCGS** | segmentation association 및 piecewise-plane 제약 | surface constraint 또는 plane fitting 자체는 새로운 기술이 아님 |
| **SuGaR** | Gaussian-surface alignment 및 mesh reconstruction | mesh extraction은 본 연구의 핵심 목표가 아님 |
| **GeoGS-SLAM (2026)** | geometry prior 기반 온라인 monocular Gaussian reconstruction | geometry prior+Gaussian SLAM의 일반적 결합만으로 차별화 불가 |
| **Geometry-Aware Online Mapping for 3DGS SLAM (2026)** | 온라인 mapping의 기하 기반 초기화·밀도 제어 | online density control 자체를 독창적 기여로 내세우지 않음 |

**잠정적 차별화 지점:** 후보 생성에 사용한 관측을 가능한 범위에서 제외하여 다른 Keyframe의 3D 증거로 Gaussian의 *map admission*을 검증하고, 기하 정보가 부족하면 삭제를 유예하며, 이 정책의 효용을 **matched Gaussian count**에서 검증한다.

아래 점검을 논문 제출 전 수행한다.

- [ ] 2026년까지 발표된 surface-constrained Gaussian SLAM, geometry-aware pruning, multi-view Gaussian filtering, online mapping, opacity/confidence thinning 관련 문헌 추가 탐색
- [ ] 비교 논문별 입력, supervision, 실시간성, primitive 생성/유지 정책, multi-view association, 평가 메트릭 비교표 작성
- [ ] 해당 개념과 동일한 방법이 확인되면 novelty 주장을 재조정하고, 자체 데이터·실험 프로토콜·오류 유형 분석의 기여를 별도로 제시
- [ ] GitHub/논문 버전별 세부 구현은 해당 시점의 commit과 설정 파일을 근거로 재확인

# 4. 시스템 개요 및 데이터 계약

```text
Input: Monocular / drone RGB video
              │
              ▼
     MASt3R-SLAM tracking
     ├─ Keyframe pose T_k ∈ Sim(3) [구현 출력 확인]
     ├─ Fused / local pointmap, confidence
     └─ Frame association / loop closure updates
              │
        ┌─────┴─────────────────────┐
        │                           │
        ▼                           ▼
  Splatt3R inference          Observation registry
  Candidate Gaussians         (KFs, ancestry, valid rays,
  + source pair IDs            pointmap samples)
        │                           │
        │                           ▼
        │                   Cross-view Surface Patches
        │                   + reliability / visibility
        └──────────────┬────────────┘
                       ▼
             Gaussian Admission Gate
        KEEP / REJECT / DEFER(BYPASS)
             [PROJECT: 선택 확장]
                       │
                       ▼
         Keyframe-owned Gaussian Map
          + active/resident bookkeeping
          [Surface-aware dedup: 선택 확장]
                       │
                       ▼
     Rendering / GT geometry / memory evaluation
```

## 4.1 입력과 출력의 확정 전 확인 항목

공개 시스템 설명에는 `pts3d`, `conf`, `means`, `scales`, `rotations`, `opacities`, `sh` 등의 출력이 제시된다. 그러나 원하는 형태의 **다른 Keyframe별 독립 pointmap 관측** 또는 정확한 observation count가 런타임에 곧바로 제공된다고 가정해서는 안 된다.

| 데이터 | 필요성 | 우선 확인 작업 |
|---|---|---|
| Keyframe ID, frame timestamp, source pair IDs | 독립 관측 검증 | 어떤 이미지 쌍이 후보와 Pointmap에 참여했는지 trace |
| Pose 및 scale, 변환 방향 | 공통 좌표계 | 실제 Sim(3) 저장 형태와 world/local 방향을 unit test로 검증 |
| Local/fused pointmap 및 confidence | surface | keyframe별 export 가능 여부와 fusion ancestry 확인 |
| Pixel↔3D 대응/카메라 ray 모델 | visibility 및 대응 | calibration이 있으면 projection, 없으면 ray map 또는 기존 pointmap matching 사용 |
| Gaussian mean/covariance/SH/opacity | map 및 rendering | **Gaussian local 좌표계와 anchor frame** 확인 |
| Scene scale/GT pose | 메트릭 평가 | GT 정렬 및 단위 정의 |

실행 중 지원하지 않는 데이터가 있는 경우: (a) 가능한 범위에서 export 코드를 추가하거나, (b) raw keyframe pointmap을 별도로 추정하여 사용하는 비교 실험을 두고, (c) 독립성 부족을 결과에 명시한다.

## 4.2 지켜야 할 실험 통제

- 원본 저장소의 pretrained weight·input resolution·camera 처리·keyframe 선택·GPU 설정을 baseline/proposed에서 동일하게 둔다.
- **Refiner 사용 여부를 혼합하여 비교하지 않는다.** 예를 들어 기존 `--refiner-dedup-voxel`은 refiner에 결합된 기능이므로, 해당 비교에서는 동일 refiner 설정 또는 별도 동일 기능 재구현으로 dedup 효과만 분리한다.
- 사용자 정의 Gaussian admission이 tracking 결과를 바꾸지 않도록 처음에는 **후처리 또는 별도 mapping worker**로 구현한다.
- 실시간성은 별도의 latency 실험이 완료되기 전까지 'online 적용 가능한 구조를 목표로 한다'고 표현한다.

# 5. 핵심 방법 A — 교차시점 관측과 Surface Support

## 5.1 왜 자기 Pointmap만 이용하면 안 되는가

Splatt3R가 pointmap 위치 `x_i`를 바탕으로 `μ_i = x_i + Δμ_i`를 예측하므로, 동일 계열 pointmap으로 surface를 만들면 두 오차가 상관될 수 있다. 예컨대 실제 표면이 `z=0`, 추정 surface가 `z=0.30`, Gaussian이 `z=0.32`이면 자기 추정 surface까지 거리는 0.02지만 실제 오차는 0.32이다.

**자기 표면 거리(self-surface distance)는 디버그/약한 baseline 지표**로 유지하고, 제안 방법의 핵심 근거로 사용하지 않는다.

## 5.2 Observation ancestry와 Leave-Source-Out 규칙

후보 Gaussian `G_i`를 만든 image pair의 ID 집합을 `S_i`라 하고, surface patch 생성에 사용할 Keyframe 관측 집합을 `O_i`라 한다. 가능하면:

\[
O_i \cap S_i = \varnothing.
\]

특히 **fused pointmap이 후보 생성 이미지의 정보를 이미 포함한 경우** 이것을 독립 관측으로 세지 않는다. 기본 설계는 다음과 같다.

1. Gaussian 후보를 생성한 Keyframe과 원본 image pair ID를 기록한다.
2. 해당 pair를 제외한 이전/인접 Keyframe의 *별도 관측*을 수집한다.
3. Pose/scale를 이용해 동일 world frame으로 정렬한다.
4. 시야 중복과 가림(occlusion) 조건을 만족하는 관측만 surface 지지로 사용한다.
5. 2개 이상의 독립 지지 시점이 없으면 `LOW_EVIDENCE`로 기록한다. 데이터가 적다는 이유만으로 `REJECT`하지 않는다.

원천적으로 관측 독립성을 확보하기 어렵다면 'cross-view but shared-model'로 별도 표기한다. 다른 프레임 역시 공통 네트워크 bias를 가질 수 있으므로 이것만으로 실제 정확성을 입증할 수 없다.

## 5.3 가시성(visibility)과 correspondence

3차원에서 가장 가까운 surface patch가 항상 같은 물리적 표면은 아니다(벽 뒤쪽, 이중 벽, 유리, 바닥과 벽 경계 등). 따라서 단순 nearest-neighbor만 사용하지 않는다.

- 관측 Keyframe의 시야 영역 안에 있는지 검사한다.
- 대응하는 픽셀/레이가 유효하고 깊이 불연속을 넘지 않는지 확인한다.
- 가능한 경우 pointmap matching 또는 projection으로 ray 방향·depth ordering을 검증한다.
- 가려진 표면/미관측 영역은 **부정적 증거**로 세지 않는다.
- 같은 표면인지 불확실하면 `DEFER` 또는 `BYPASS` 처리한다.

Known intrinsics가 있는 실험에서는 pinhole reprojection을 사용할 수 있다. MASt3R-SLAM의 일반 camera-model 조건에서는 **기존 ray map 기반 matching**을 사용하거나, 대응 구현이 불가능하면 해당 장면을 지원되지 않는 실험 조건으로 명시한다.

## 5.4 관측 일관성 지표

후보 근처에 도달 가능한 다른 시점의 표면 patch를 `S_{ij}`라 하자. 각 관측의 평면잔차는

\[
d_{ij}=\left|n_j^{\top}(\mu_i-\bar p_j)\right|,
\qquad \tilde d_{ij}=\frac{d_{ij}}{h_j+\epsilon}.
\]

`h_j`는 local spacing이다. 유효한 관측만 모아 다음과 같은 **설명 가능한** 통계를 우선 계산한다.

- `support_count`: 유효한 서로 다른 관측 Keyframe 수
- `median_normalized_residual`: 유효 관측에서의 거리 중앙값
- `residual_dispersion`: 관측 간 잔차 변동(예: MAD)
- `patch_reliability`: 관측 patch의 국소 품질
- `visibility_conflict`: 가시성이 확인된 시점에서의 깊이/표면 불일치 여부

이 집계는 확정된 정답 공식이 아니며, 각각 독립 ablation을 수행한다.

# 6. 핵심 방법 B — 신뢰 가능한 Local Surface Estimation

## 6.1 Neighborhood 추출

처음에는 `KNN + 반경/깊이 게이트`와 가중 PCA를 사용한다. 단, 순수 3D-KNN은 서로 다른 면의 점을 섞을 수 있으므로 다음 검사와 결합한다.

- 원본 Pointmap의 2D 픽셀 인접성 또는 연결된 depth-continuity 기반 후보 생성
- 지리적 3D 근접성, normal 유사도(추정 가능 시), 가림/시야 검사
- 중복점·매우 가까운 점의 제거, 공간 범위 제한
- 충분한 neighbor count와 포인트 분포 확보

국소 간격은

\[
h_i=\operatorname{median}_{p_j\in N_i}\|p_j-p_i\|
\]

로 초기화하되, `h_i`가 0 또는 비정상적으로 작으면 최소 간격/자료 유효성 규칙을 적용한다. 단안 SLAM의 scale drift가 있으면 장면별 정규화 값을 함께 기록한다.

## 6.2 Confidence-weighted PCA

\[
\bar p_i=\frac{\sum_{j\in N_i}w_jp_j}{\sum_{j\in N_i}w_j},\quad
M_i=\frac{\sum_{j\in N_i}w_j(p_j-\bar p_i)(p_j-\bar p_i)^\top}{\sum_{j\in N_i}w_j}.
\]

고유값을 `λ1 ≥ λ2 ≥ λ3 ≥ 0`로 두면 `n_i = e3`가 국소 법선의 후보이다. MASt3R confidence를 `w_j=c_j`로 바로 사용하기 전에 **실제 confidence 분포와 값 범위를 측정**하고, clipping/rank scaling/softmax 또는 단순 uniform 가중치와 비교한다. 이 값은 calibration된 확률이라고 가정하지 않는다.

국소 curvature와 surface spread는

\[
\kappa_i=\frac{\lambda_3}{\lambda_1+\lambda_2+\lambda_3+\epsilon},\qquad
r_{\mathrm{spread},i}=\frac{\lambda_2}{\lambda_1+\epsilon}.
\]

`κ_i`가 작기만 하면 직선에 놓인 점들도 통과하므로 `r_spread`에 대한 최소 조건을 함께 둔다. 추가로 fitting residual, neighborhood size, confidence, cross-view support를 검사한다.

## 6.3 SurfacePatch 상태

각 patch는 다음 정보를 보유한다.

`center`, `normal`, `spacing`, `curvature`, `spread_ratio`, `fit_residual`, `confidence_raw`, `confidence_normalized`, `source_keyframes`, `support_count`, `visibility_status`, `validity_reason`, `pose_revision`.

- **RELIABLE:** 충분한 점 분포·신뢰도·교차 관측·가시성 확보
- **UNCERTAIN:** 표면 존재는 가능하나 판단 근거 부족(선형·식생·경계·미관측 등)
- **CONFLICTED:** 충분한 유효한 다중 관측 간 기하 불일치 발견

표면을 구성할 수 없다는 것과 실제 표면이 없다는 것은 별개다.

# 7. 핵심 방법 C — Gaussian Admission 정책

## 7.1 두 종류의 신뢰도를 분리

- **Surface reliability** `R_s`: reference patch가 실제 표면을 제대로 대표할 근거(점 분포, confidence, fitting, 시점 독립성, 관측 합의)
- **Candidate consistency** `C_g`: candidate Gaussian이 해당 검증 표면과 기하적으로 얼마나 일치하는지(거리, 관측별 합의, depth conflict 등)

v1의 곱셈형 단일 score는 **비교 baseline**으로 남기고, 핵심 구현에서는 두 값을 분리한 rule-based gate를 먼저 검증한다.

예시 검사용 점수:

\[
C_g=\exp\!\left(-\frac{\operatorname{median}_j(\tilde d_{ij})^2}{2\sigma_d^2}\right),
\]

단, `support_count`, `R_s`, `visibility_conflict`는 별도 hard condition으로 관리한다. 숫자와 식은 최초 가설이며 validation을 통해 결정한다.

## 7.2 네 가지 결정

| 결정 | 조건의 성격 | 처리 |
|---|---|---|
| **KEEP** | 충분한 외부 시점 지지 + 잔차 작음 | map에 삽입 또는 유지 |
| **PROJECT** | 신뢰도 높은 표면에 아주 가까운 위치 보정 가능 | **선택 확장**에서만 적용 |
| **REJECT** | 복수의 유효 관측이 명백하게 잘못된 위치임을 지지 | map 편입 거부/비활성화 |
| **DEFER / BYPASS** | 표면·시점·depth 증거 부족, 식생/얇은 구조 등 | 후속 Keyframe까지 보류 또는 그대로 유지(대조군) |

초기 필수 실험은 `KEEP/REJECT/DEFER`이며, `DEFER`는 새 관측이 들어오면 재평가하는 큐 상태, `BYPASS`는 근거가 없을 때 원본 Gaussian을 유지하는 안전 baseline 정책으로 구현을 구분한다.

**금지 규칙:** `NO_SURFACE ⇒ REJECT`는 사용하지 않는다. 단일 confidence, opacity, curvature만으로 Gaussian을 확정적으로 제거하지 않는다.

## 7.3 REJECT에 필요한 엄격한 조건

Reject는 다음 중 하나 이상의 근거를 요구하도록 정책을 설계한다.

- 여러 **유효하고 시야가 확인된 독립 관측**에서 수용 범위를 넘는 명확한 거리/깊이 불일치
- 물리적으로 일관된 가까운 표면과 후보가 반복적으로 충돌하며, 자기 관측 이외의 증거가 충분함
- baseline 품질 보존 실험에서 재현성 있게 invalid라고 확인된 정책 조건

가려져서 보이지 않는 점, 멀리 있어서 재구성되지 않은 점을 reject 근거로 삼지 않는다. 매우 엄격한 reject 정책에서 outlier가 적게 제거되더라도 정상 표현을 보존하는지 함께 평가한다.

# 8. 선택 확장 A — Soft Surface Projection

표면 신뢰도가 충분하고 이동 거리가 제한적인 경우에만 투영한다.

\[
\mu_i'=\mu_i-\eta\,n_jn_j^\top(\mu_i-\bar p_j),
\qquad 0\le\eta\le1.
\]

- `η`는 일단 validation에서 선택하는 **독립 하이퍼파라미터**로 둔다. `η = clamp(S_i,0,1)` 형태로 후보 적합성 점수를 직접 재사용하지 않는다.
- 최대 이동 거리: `||μ_i'-μ_i|| ≤ τ_move·h_j` 등의 명시적 제한을 둔다.
- Depth edge, 높은 curvature, 낮은 `R_s`, 서로 다른 surface가 가까운 영역에서는 금지한다.
- 기존 pointmap의 systematic bias가 그대로 표면에 있으면 projection이 GT error를 더 키울 수 있으므로 projection 전/후의 **외부 GT 오차**를 별도로 비교한다.
- Hard projection은 **ablation baseline**이며 필수 경로가 아니다.

시간이 허용되면 covariance의 최소 eigenvector를 normal 방향에 정렬하거나 두께를 제한할 수 있으나 논문 핵심 기여로 사전 약속하지 않는다.

# 9. 선택 확장 B — Surface-aware Duplicate Suppression

기존 Splatt3R-SLAM에는 map budget, confidence gate, 선택적 voxel dedup이 존재한다. 따라서 **'중복 제거 기능의 추가' 자체를 연구 novelty로 주장하지 않는다.**

동일 영역에 반복 관측이 생길 때 `position proximity + normal compatibility + appearance difference + source-view coverage + surface reliability`를 사용한 **keep-best policy**를 시험한다.

기본 원칙:

1. 기존 map의 공간 index에서 candidate의 이웃을 찾는다.
2. 단순 3D 거리가 아니라 같은 visible surface인지 확인한다.
3. Gaussian 파라미터를 즉시 merge하지 않고 더 나은 지원 근거의 candidate를 유지하는 keep-best를 시험한다.
4. 큰 Gaussian 또는 복잡한 view-dependent appearance의 제거가 rendering에 미치는 영향을 검사한다.
5. 무조건 `active=false`로만 처리하지 않고 실제 compact GPU buffer를 생성한 별도 실험을 둔다.

**비교 우선순위:** voxel dedup을 켠 경우와 같은 **active Gaussian budget**에서 surface-aware dedup이 추가로 이득이 있는지 먼저 확인한다. 효과가 없으면 논문 필수 기여에서 제외한다.

# 10. Loop Closure, Sim(3) 및 Surface Cache

## 10.1 좌표계 정의

MASt3R-SLAM의 pose는 scale이 포함된 `Sim(3)`로 표현될 수 있다. anchor keyframe `k`에서 world로 가는 변환을 `T_{w←k}=(s_k,R_k,t_k)`로 정의하면

\[
\mu_w=s_kR_k\mu_k+t_k,\qquad
\Sigma_w=s_k^2R_k\Sigma_kR_k^\top.
\]

World에서 수행한 projection을 다시 anchor-local에 저장하려면

\[
\mu_k'=\frac{1}{s_k}R_k^\top(\mu_w'-t_k).
\]

스케일은 covariance에도 제곱으로 영향을 준다. `q`, `scale`의 저장 규약과 월드 변환 방향, 라이브러리의 행렬 convention을 코드에서 확인해야 한다. 위 식은 **정의한 방향의 변환**에 대한 수학적 규칙이다.

## 10.2 보관·업데이트 정책

- 영구 Gaussian 파라미터는 기본적으로 **anchor-local**에서 보존한다.
- World 위치, surface patch association, voxel hash는 pose revision과 연결된 **파생 cache**로 관리한다.
- Loop closure 또는 큰 pose/scale update 시 관련 spatial index·visibility correspondence·surface patch가 stale인지 검사해 재계산한다.
- `pose_revision`, `surface_revision`, `anchor_keyframe_id`, `source_pair_ids`를 함께 로그에 남긴다.
- loop closure 이전에 삭제한 Gaussian은 복원이 어려우므로 최초 구현은 candidate provenance 및 reversible decision log를 보관한다.

# 11. 실제 메모리 절감과 Map 운영

Gaussian 수의 정의를 분리한다.

| 지표 | 정확한 의미 |
|---|---|
| `N_candidate` | Splatt3R가 생성한 총 후보 수 |
| `N_active` | 렌더러에 실제 제출되는 Gaussian 수 |
| `N_resident` | 현재 GPU Tensor에 공간을 점유하는 Gaussian 수 |
| `N_rejected` | 편입되지 않은 후보 수 |
| `N_deferred` | 증거 부족으로 임시 보류 중인 후보 수 |
| `M_serialized` | 저장된 PLY/모델 크기 |
| `VRAM_allocated / peak` | 프레임워크 할당 메모리 / peak |
| `VRAM_process` | GPU 상 실제 프로세스 점유량(측정 가능 시) |

**주의:** `active=false`만으로 `N_resident`나 GPU VRAM이 감소하지 않는다. 논문에서는 다음을 구분한다.

- **Logical filtering:** active mask만 적용하여 렌더링 비용 변화 측정
- **Physical compaction:** 실제 GPU buffer를 재구성·축소하여 resident count 및 memory 변화 측정

Memory benchmark에서는 refiner/renderer의 일시 버퍼와 mapping 단계의 peak를 분리한다. CPU에 보류 candidate를 저장하는 경우 CPU RAM과 디스크 사용량도 기록한다.

전체 scene이 커지면 `keyframe ownership + submap + spatial hash`를 도입하되, 초기 프로토타입에서 대규모 새 자료구조를 설계하기보다 공개 코드의 자료구조를 활용한다.

# 12. 구현 구조 및 최소 데이터 모델

## 12.1 권장 코드 구성

기존 Splatt3R-SLAM 저장소의 실행 코드를 유지하고 변경 부분을 가급적 분리한다. 아래 디렉터리는 **제안 구조**이며 원본 저장소의 실제 디렉터리와 다를 수 있다.

```text
research/
├── third_party/                 # 버전/commit 고정 또는 기존 코드 참조
├── gaussian_mapping/
│   ├── observations/
│   │   ├── source_registry.py   # 후보의 출처 image pair / KF 기록
│   │   ├── view_association.py # 대응/가시성 판정
│   │   └── confidence.py       # confidence 분포·정규화
│   ├── surface/
│   │   ├── neighborhood.py     # 2D+3D 후보 영역
│   │   ├── weighted_pca.py
│   │   ├── reliability.py      # spread/curvature/residual
│   │   └── cache.py            # pose revision 관리
│   ├── admission/
│   │   ├── cross_view.py       # leave-source-out 검증
│   │   ├── policy.py           # KEEP/REJECT/DEFER/BYPASS
│   │   ├── projection.py       # optional
│   │   └── log.py
│   ├── dedup/                   # optional
│   │   ├── voxel_baseline.py
│   │   └── surface_keep_best.py
│   ├── map/
│   │   ├── records.py
│   │   ├── sim3.py
│   │   ├── spatial_index.py
│   │   └── compact.py
│   └── evaluation/
│       ├── rendering.py
│       ├── gt_geometry.py
│       ├── classification.py
│       ├── memory.py
│       └── runtime.py
├── experiments/
│   ├── configs/
│   ├── run_export.py
│   ├── run_self_surface.py
│   ├── run_cross_view.py
│   ├── run_matched_budget.py
│   └── run_ablation.py
├── tests/
│   ├── test_sim3.py
│   ├── test_planar.py
│   ├── test_two_surface.py
│   ├── test_visibility.py
│   └── test_map_compaction.py
└── results/
```

## 12.2 클래스·자료형 초안

```python
from dataclasses import dataclass
from enum import Enum, auto

class AdmissionAction(Enum):
    KEEP = auto()
    REJECT = auto()
    DEFER = auto()
    BYPASS = auto()
    PROJECT = auto()  # optional extension

@dataclass
class SurfacePatch:
    center_world: object
    normal_world: object
    spacing: float
    curvature: float
    spread_ratio: float
    fitting_residual: float
    confidence_score: float   # normalized/validated, not raw probability
    support_keyframe_ids: tuple[int, ...]
    pose_revision: int
    reliable: bool
    validity_reason: str

@dataclass
class GaussianCandidate:
    gaussian_id: int
    anchor_keyframe_id: int
    source_pair_ids: tuple[int, ...]
    mean_local: object
    rotation_local: object
    scale_local: object
    sh: object
    opacity: object
    point_confidence_raw: float

@dataclass
class AdmissionDecision:
    gaussian_id: int
    action: AdmissionAction
    reason: str
    support_count: int
    surface_reliability: float
    candidate_consistency: float
    normalized_residual: float | None
    pose_revision: int
```

구체 Tensor 자료형, quaternion convention, 단안 scale의 메트릭 여부, 시스템의 ID 관리 방식은 공개 코드 실행 결과에 맞게 조정한다.

# 13. 알고리즘 명세 및 초기 구현 순서

## 13.1 Algorithm A — Leave-Source-Out Surface Query

```text
Input:
    candidate G, anchor Keyframe k
    source pair IDs S(G)
    registered keyframe observations O
    pose revision r
Output:
    independently supported SurfacePatch candidates

1. eligible ← observations from other keyframes
2. eligible ← observations whose source IDs do not overlap S(G)
   (if fusion ancestry is unavailable, mark as CORRELATED / UNVERIFIED)
3. Convert eligible 3D samples to a common coordinate frame via Sim(3)
4. Retain samples passing visibility, ray/depth, and edge checks
5. Compute local neighborhood with bounded 2D/3D association
6. If data are insufficient: return UNCERTAIN (not NO_SURFACE_REJECT)
7. Run weighted PCA and calculate spread ratio / curvature / residual
8. Estimate reliability and observation support
9. Return patch candidates with source KFs and pose revision
```

**중요:** `source IDs` 제외만으로 기하 오류가 완전히 독립적이 되는 것은 아니다. `CORRELATED / UNVERIFIED` 표시는 실험 집계에서 별도로 사용한다.

## 13.2 Algorithm B — Conservative Gaussian Admission

```text
Input: candidate G, supported patches P, thresholds θ
Output: action and decision record

1. if P is empty or reliable independent support < required minimum:
       return DEFER (or BYPASS in its dedicated baseline experiment)

2. Find geometrically associated patch (not nearest plane alone)
   if association is ambiguous or patch crosses a depth edge:
       return DEFER

3. compute candidate-to-patch residuals for valid observations
4. estimate surface reliability Rs and candidate consistency Cg
5. if visibility-confirmed repeated conflicts exist
      and evidence is sufficient:
       return REJECT

6. if Rs is high and Cg is high:
       return KEEP

7. if projection experiment enabled and
      Rs high and offset within movement bound and no depth conflict:
       return PROJECT

8. return DEFER or BYPASS according to the experimental policy
```

## 13.3 Algorithm C — Deferred Re-evaluation

```text
When new keyframes arrive or loop closure changes poses:
    collect candidate decisions affected by new observation / pose revision
    update or rebuild corresponding surface cache
    re-check DEFER candidates
    if support becomes sufficient:
        transition to KEEP or REJECT according to the same policy
    record decision history for reproducibility
```

실제 온라인 구현이 부담되면 `E1~E3`에서는 **고정된 sequence 재생 후 offline으로 동일한 observation history를 순차 처리**하여 mapping policy를 먼저 검증한다. 완전한 streaming 적용은 기본 알고리즘의 유효성이 확인된 후 구현한다.

## 13.4 Algorithm D — Optional Keep-Best Deduplication

```text
Input: admitted candidate G, spatial index H
1. Query nearby active Gaussians
2. Restrict to same visible surface, compatible normal and appearance
3. If no safe duplicate: insert G
4. Else keep candidate or existing record according to reliable support
5. Log prior record and keep reversibility until loop-closure stability verified
6. Periodically compact active GPU buffer and measure actual VRAM change
```

# 14. 실험 설계 원칙과 통제 변수

1. **주요 실험은 예측 네트워크 및 tracker를 고정**하고 Gaussian Map 결정 방식만 변경한다.
2. 동일 입력 영상, 동일 train/validation/test 분할, 동일 camera preprocessing, 동일 pose를 사용한다.
3. Test 이미지는 어떤 형태로도 Gaussian 생성, Map update, projection, refiner 학습, parameter tuning에 사용하지 않는다.
4. 렌더링 품질을 볼 때는 **고정 pose 조건**을 기본으로 삼고, 별도 표에서 estimated pose 성능을 확인한다.
5. 단안 reconstruction에 대한 GT 정렬 절차(Sim(3) 또는 지정된 metric alignment)를 미리 정의하고 모든 방법에 동일하게 적용한다.
6. Threshold와 score weight는 **validation sequence에서만 선택**하고 test에서 다시 조정하지 않는다.
7. Scene 단위 paired comparison을 원칙으로 하고, 개별 frame을 독립 실험 표본으로 간주하여 유의성을 과장하지 않는다.
8. 장면 종류, 관측 수, 표면 유형, 리비짓 여부에 따라 성능을 나누어 보고한다.
9. 실험 이전에 '개선'의 허용 margin과 실패 기준을 **개발 목표**로 사전 지정하되 결과를 보고 임의 변경하지 않는다.

# 15. Baseline 및 Ablation 계획

## 15.1 Baseline 체계

| ID | 방법 | 검증 목적 | 비고 |
|---|---|---|---|
| **B0** | MASt3R-SLAM pose/geometry only | 입력 geometry의 한계 및 trajectory 재현 | Gaussian rendering baseline 아님 |
| **B1** | Splatt3R-SLAM 그대로 | 주된 원본 baseline | 버전과 옵션 고정 |
| **B2** | Confidence filter / confidence-based fade | 학습 모델의 confidence만으로 충분한가 | `--min-confidence`, refiner fade 사용 방식 구분 |
| **B3** | Uniform/random thinning | 단순 개수 감소 효과 | 동일 active count, 여러 random seed |
| **B4** | Spatial voxel dedup | 단순 공간 중복 제거와 비교 | 기존 선택적 refiner 기능과 동등 프로토콜 |
| **B5** | Self-surface distance filtering | 같은 모델의 geometry만 비교하는 순진한 필터 | 상관 오차/오탐 비교 핵심 |
| **P1** | Cross-view admission (거리 및 지원 수) | 핵심 가설 검증 | KEEP/REJECT/DEFER |
| **P2** | P1 + patch reliability/visibility | 다중시점 증거의 기여 | primary proposed 후보 |
| **P3** | P2 + soft projection | 위치 보정 효과 | 선택 확장 |
| **P4** | P2 + surface-aware dedup | 중복 제거 추가 효과 | 선택 확장 |

**주의:** 다른 네트워크 head, refiner budget, optimization step 등이 달라지는 비교는 main table과 분리하고, 동일 설정의 공정 비교가 가능한 경우만 직접 우열을 주장한다.

## 15.2 Admission의 단계별 Ablation

| 기법 | Distance | Independent views | Reliability | Visibility | 상태 |
|---|---:|---:|---:|---:|---|
| A1 | O | X | X | X | 자기 표면 baseline |
| A2 | O | O | X | X | 핵심 cross-view 효과 |
| A3 | O | O | O | X | surface 품질 필터 효과 |
| A4 | O | O | O | O | geometry association 및 occlusion 효과 |
| A5 | O | O | O | O | DEFER vs BYPASS vs aggressive reject 정책 비교 |

추가 민감도 검사: `K`, `τ_curvature`, `τ_spread`, `min_views`, residual threshold, source-exclusion strategy, projection `η`(확장 시).

## 15.3 Matched-budget 핵심 프로토콜

**방법마다 같은 `N_active` 예산을 맞춘 뒤** PSNR/SSIM/LPIPS와 geometry metrics를 비교한다. 예산은 예를 들어 baseline map 크기의 여러 비율로 정의하되 정확한 구간은 validation 계획에 사전 등록한다.

- Budget matching 방식(순위별 threshold, deterministic subsampling 등)을 명시한다.
- 같은 scene/frame 수뿐 아니라 **동일하게 관측된 공간 영역**을 비교한다.
- Random thinning은 여러 seed 결과의 평균 및 분산을 보고한다.
- `PSNR vs active Gaussian count`, `LPIPS vs count`, `GT error vs count`, `VRAM vs count`를 Pareto curve로 작성한다.
- 희소한 구조물/단일 관측 영역에서 coverage 감소가 없는지 별도 분석한다.

# 16. 데이터셋 및 데이터 수집

## 16.1 Stage 0 — 초기 드론 파일럿 (1~4주차)

초기부터 짧은 드론 시퀀스 1~2개를 확보하거나 공개된 단안 비디오를 사용한다. 목적은 최종 성능 발표가 아니라 **pipeline feasibility 판정**이다.

- 장면: 건물 외벽·지붕과 지면, 식생/얇은 구조 포함 영역 각각 가능하면 확보
- 확인: Tracking 실패 비율, pose jump/scale drift, pointmap 밀도, exposure/rolling shutter, sky/background 처리, 영상 프레임 간 시점 중첩, 출력 map 규모
- 기록: 기종, 촬영 해상도/FPS, 고도, 속도, codec, 조명/날씨, 추정된 카메라 calibration, frame extraction stride

이 단계에서 trajectory 또는 pointmap이 심각하게 불안정하면 실험 대상을 benchmark로 축소하거나 camera calibration 및 입력 조건을 조정한다. 드론 적용을 논문의 **기본 성립 조건**으로 두지 않는다.

## 16.2 Stage A — 공개 benchmark

후보: **Replica, 7-Scenes, EuRoC, Splatt3R-SLAM에서 실제 재현 가능한 평가 시퀀스**. 이들 중 어느 데이터셋에 어떤 GT가 존재하는지 확인하고 용도를 구분한다.

| 필요 데이터 | 평가 용도 | 포함 여부 |
|---|---|---|
| Known/reference poses | trajectory 및 고정 pose rendering | 있으면 사용 |
| GT dense depth 또는 mesh | Surface accuracy/completion/outlier truth | **확보 가능한 시퀀스에서만** |
| GT trajectory만 있음 | ATE 등 tracking 확인 | dense geometry GT로 오인하지 않음 |
| Reference RGB held-out | PSNR·SSIM·LPIPS | input/optimization/test 분리 필수 |

데이터셋의 평가 대상이 본 연구 조건(연속 RGB 영상, 충분한 시점 중복)에 맞는지 확인한 후 확정한다.

## 16.3 Stage B — 실사용 드론 영상

- 짧은 단일 건물 → 복수 건물 → 장기 경로 및 revisit 순으로 확장한다.
- 가능하면 별도 수집한 photogrammetry/MVS reconstruction 또는 독립 LiDAR model을 reference로 확보한다. 단, **입력은 RGB만** 사용하고 LiDAR는 평가용 GT로만 분리한다.
- 외부 reference가 없다면 geometry **절대 정확도**를 주장하지 않는다. Held-out novel view, cross-view residual, qualitative surface inspection 중심으로 보고한다.
- `P2`가 실패하면 추가 촬영이나 장기 sequence를 늘리기 전에 실패 원인을 분석한다.

## 16.4 Train/validation/test 분할

학습을 수행하지 않더라도 parameter validation은 필수다. 동일 scene의 인접 프레임이 map construction과 test에 동시에 포함되면 정보 누설 위험이 있다. 시간적 간격, overlap, keyframe 원천 이미지 포함 여부를 명시한다. 교차시점 검증용 observation과 평가 GT/held-out 이미지를 혼동하지 않는다.

# 17. 평가 지표: 렌더링·기하 정확도·이상점·보존율

## 17.1 Rendering

- **PSNR ↑**, **SSIM ↑**, **LPIPS ↓**를 held-out RGB에서 측정한다.
- 동일한 렌더 해상도·색 공간·노출 처리·pose·image masks를 사용한다.
- Pose estimation error와 map quality의 영향을 구분한다(known/GT-aligned pose rendering 별도 보고).
- 입력 시점 사이의 interpolation뿐 아니라 경로 바깥/상방 시점의 extrapolation을 별도 범주로 평가하되 reference image가 실제로 있는 경우만 정량화한다.

## 17.2 Geometry

GT depth, point cloud, mesh 또는 검증 가능한 reference가 있는 장면에서:

- **Accuracy:** 재구성한 표면 → reference 표면 거리
- **Completion / Completeness:** reference 표면 → 재구성한 표면의 coverage 및 threshold 기반 recall
- **Chamfer Distance:** 양방향 거리(표본화 기준 고정)
- **Depth error:** 동일한 GT camera view에서 렌더링/재구성한 깊이와 GT depth 비교(가능할 때)
- **Normal consistency:** 충분한 GT normal이 있을 때만

`Gaussian center → GT surface` 거리 기반 평가는 **center-based proxy**로 명확히 표기한다. Gaussian은 공간적 부피와 anisotropic covariance를 갖는 primitive이므로 이 값은 실재 표현 표면의 물리적 오차와 동치가 아니다. 가능하면 depth/surface sampling 기반 평가를 병행한다.

## 17.3 Outlier 정의와 정상 Gaussian 보존율

사전에 정의한 GT surface distance threshold `τ_o`에서 **평가용 proxy 라벨**을 만든다.

\[
R_{\mathrm{outlier}}(\tau_o)
= \frac{\#\{i:d(\mu_i,S_{GT})>\tau_o\}}{N_{\mathrm{active}}}.
\]

그러나 이는 제거된 정상 표면의 손실을 나타내지 못한다. 따라서 다음을 함께 평가한다.

- **Inlier retention:** baseline에서 GT 기준 inlier였던 후보 중 proposed가 유지한 비율
- **Outlier rejection precision/recall:** 제거 대상 라벨에 대한 precision/recall, 가능하면 PR-AUC
- **Coverage / completion:** GT 표면의 복원 가능 영역을 얼마나 유지했는지
- **False rejection rate:** 특히 edge, vegetation, fine structure, single-view surface에 대해 측정
- **Threshold curve:** scene scale·거리 threshold에 대한 민감도

`REJECT`만 정답으로 간주하고 `DEFER`를 전부 제거 대상으로 계산하면 평가가 왜곡된다. **보류/유지/삭제/예외** 결과를 각각 기록한다. 외부 GT가 없으면 자기 MASt3R 표면을 정답 라벨로 사용하지 않는다.

## 17.4 Cross-view 지표의 지위

Cross-view consistency residual은 **알고리즘이 사용하는 내부 신호 및 보조 지표**다. 모델과 데이터 소스가 완전히 독립적이지 않을 수 있으므로 실제 geometry 개선을 입증하는 주요 평가 지표로 단독 사용하지 않는다.

# 18. Compactness·Runtime·Long-sequence 평가

## 18.1 Compactness 및 Memory

- `N_candidate`, `N_active`, `N_resident`, `N_deferred`, `N_rejected`
- GPU allocated/peak/process VRAM, CPU memory(선택), PLY 저장 크기
- Rendering FPS와 mapping per-KF time(서로 분리)
- Compaction 전후의 resident memory 변화
- 정상 surface per-unit-area Gaussian density 또는 scene coverage 보정 밀도

다음 곡선을 기본으로 작성한다.

\[
N_{\mathrm{active}},N_{\mathrm{resident}},\mathrm{VRAM}
\quad\text{vs}\quad N_{\mathrm{keyframe}}.
\]

단순 `Gaussian 수 vs Keyframe 수`만으로는 신규 관측 영역과 반복 관측 영역을 구별하기 어렵다. 가능한 경우 **cumulative observed area/volume**, revisit 횟수 또는 동일 patch 재관측 수를 x축으로 추가한다.

## 18.2 Runtime

- Tracking: FPS, median/p95 latency, ATE(가능한 GT에서)
- Splatt3R inference: frame/keyframe당 소요시간
- Surface: 관측 등록, correspondence, PCA, cache refresh
- Admission: 검증 및 decision latency, deferred queue 크기
- Optional: projection, dedup, compaction latency
- Whole pipeline: 처리량, peak VRAM, 병목, GPU 동기화 비용

초기 프로토타입은 PyTorch/CPU 또는 작은 batch로 correctness를 검증한다. CUDA/custom kernel은 확실한 효용이 확인된 후 최적화한다. GPU KNN의 메모리 폭발을 방지하기 위해 작은 scene·chunk·voxel 후보 검색부터 시작한다.

## 18.3 Long-sequence 실험

각 시퀀스 진행률 25%/50%/75%/100%에서 아래를 저장한다.

| Progress | KFs | New area | Revisit ratio | Active #G | Resident #G | VRAM | LPIPS | Completion |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 25% | | | | | | | | |
| 50% | | | | | | | | |
| 75% | | | | | | | | |
| 100% | | | | | | | | |

`new area` 및 `revisit ratio`는 신뢰 가능한 대응 지표가 확보될 때만 계산하고, 정의 및 단위를 기술한다. 새 지역만 계속 관측하면 유효 Gaussian 수가 늘어나는 것이 자연스러우므로 **무조건 낮은 growth slope를 정답으로 해석하지 않는다.**

# 19. 첫 번째 Go / No-Go 실험 (핵심 선행 실험)

## 19.1 실험명: Cross-view Surface Consistency Pilot

**대상:** 공개 benchmark 1개 + 짧은 drone pilot 1개(실행 가능한 경우)

### 절차

1. 원본 Splatt3R-SLAM을 동일 구성으로 실행하고 Keyframe Gaussian/Pointmap/pose/source IDs를 export한다.
2. Candidate `G`의 자기 Pointmap과 외부 관측 Pointmap을 분리할 수 있는지 확인한다.
3. Self-surface distance 및 source-excluded cross-view residual histogram을 만든다.
4. 기하 검증 결과와 GT 기반 outlier proxy/held-out 이미지 residual의 상관을 각각 측정한다.
5. 같은 `N_active`로 **uniform thinning, confidence filter, voxel dedup, self-filter, cross-view filter**를 비교한다.
6. Scene 내부 wall/roof/ground와 thin structure/vegetation 등 실패 영역을 분리해 평가한다.

### 필수 산출물

- Self/cross-view distance histogram (외부 GT error와 함께 산점도 추가)
- Per-Gaussian `source_ids`, `valid_support_count`, `decision_reason` CSV
- 같은 Budget에서 PSNR/LPIPS/GT geometry/Completion 표 및 Pareto curve
- Floater 제거 및 정상 표면 삭제 사례를 나란히 보여 주는 이미지
- Cross-view 독립 관측 확보율, tracking 실패 비율, 추가 처리시간

## 19.2 Go / Revise / No-Go 기준

| 결과 | 판단 및 후속 조치 |
|---|---|
| 독립 관측 확보 가능 + matched-budget에서 유의미한 품질/GT 이득 | **GO:** P2 중심으로 핵심 연구 진행 |
| 독립 관측 가능하나 surface 검증의 추가 효과가 없음 | **REVISE:** 단순 필터의 비용 대비 효용, 관측 association, patch reliability 설계 재검토 |
| Cross-view가 self-surface보다 좋지만 vegetation/경계에서 false reject 증가 | **REVISE:** DEFER/BYPASS 보수화, visibility 강화 |
| 원본 map의 outlier보다 중복이 더 지배적 | **PIVOT 후보:** surface-aware dedup을 핵심으로 전환하되 voxel baseline 대비 이득 재검증 |
| 독립 pointmap 확보가 불가능/가시성 검증 실패 | **NO-GO for original core claim:** '독립 다중시점 검증'이라고 주장하지 않고 입력 파이프라인을 재설계하거나 범위를 조정 |
| Geometry GT 오차가 개선되지 않고 성능만 감소 | **NO-GO 또는 연구 가설 기각:** 실패 메커니즘 분석 후 계획 수정 |

정량 threshold(예: 허용 PSNR 손실 폭, 최소 inlier retention)는 E0 baseline 분포를 본 뒤 **validation 사전등록**으로 정하며, 지금 임의 수치를 성능 보장으로 쓰지 않는다.

# 20. 전체 실험 매트릭스 및 결과 표

| Experiment | 목적 | Baselines | 핵심 결과 |
|---|---|---|---|
| **E0** | Baseline reproducibility | B0, B1 | pose/pointmap 출처, held-out rendering, map size, latency |
| **E1** | Self vs cross-view residual | B5, P1 | GT outlier 분류성, 독립 관측 확보율 |
| **E2** | Reliability/visibility/DEFER 효과 | P1, P2, A1~A5 | false rejection, geometry, coverage |
| **E3** | Matched-budget 필수 비교 | B1~B5, P2 | quality-count Pareto, PR-AUC, completion |
| **E4(선택)** | Soft projection | P2, P3, hard projection | 정상 표면 보존, GT depth, rendering |
| **E5(선택)** | Surface-aware dedup | B4, P4 | 중복 억제의 추가 효용, VRAM 실제 절감 |
| **E6** | Long-sequence / loop closure | B1, P2 (+선택 P4) | per-KF latency, pose revision/re-cache, memory growth |
| **E7** | Drone pilot 및 확장 | B1~B5, P2 | 정성적 3D map, held-out view, 실패 사례 |

### Main Result (빈칸은 실험 후 입력)

| Method | Active #G ↓ | Resident #G ↓ | PSNR ↑ | SSIM ↑ | LPIPS ↓ | GT Accuracy ↓ | GT Completion ↑ | Inlier retention ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B1 Splatt3R-SLAM | | | | | | | | |
| B2 Confidence | | | | | | | | |
| B3 Uniform thinning | | | | | | | | |
| B4 Voxel dedup | | | | | | | | |
| B5 Self-surface | | | | | | | | |
| P1 Cross-view | | | | | | | | |
| P2 Cross-view + reliability | | | | | | | | |

표를 채울 때 **같은 budget** 결과와 **자연스러운 원본 map 크기** 결과를 혼합하지 않는다. 필요하면 별도 표를 사용한다.

### Runtime/Memory Result

| Method | Tracking FPS ↑ | Surface ms/KF ↓ | Admission ms/KF ↓ | End-to-end ms/KF ↓ | Peak VRAM ↓ | GPU Resident #G ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | | — | — | | | |
| Proposed | | | | | | |

# 21. Synthetic / Unit / Regression Test

단순 수치 시험보다 먼저 작성할 **필수 테스트**:

1. **Planar scene:** 약간의 Gaussian offset에서 점-평면 거리 및 법선이 올바르게 계산되는가.
2. **Line-like distribution:** `κ ≈ 0`이어도 `λ₂/λ₁`가 작으면 평면으로 인정하지 않는가.
3. **Two adjacent planes / depth edge:** 서로 다른 두 표면을 동일 neighborhood로 섞지 않는가.
4. **Occluded surface:** 카메라에서 가려진 관측이 `REJECT` 근거가 되지 않는가.
5. **No evidence:** surface/관측이 부족하면 `DEFER` 또는 대조 실험의 `BYPASS`를 반환하는가.
6. **Correlated source:** 후보 생성 pair와 같은 근원의 pointmap을 independent support로 잘못 계산하지 않는가.
7. **Wrong geometry:** 실제 GT와 다르게 동일하게 이동한 Gaussian과 pointmap을 일치로 판정하는 self-filter 오류를 확인하는가.
8. **Sim(3):** 수동으로 알려진 rotation/translation/scale의 mean/covariance 왕복 변환이 일치하는가.
9. **Loop closure:** Pose revision 후 surface/spatial index cache가 무효화되는가.
10. **Compaction:** `N_active`와 `N_resident` 차이가 실제 buffer 재생성 후 사라지며 memory 지표가 정상적으로 측정되는가.
11. **Matched budget:** 모든 비교 방법의 active count 목표가 지정한 허용 오차 안에 들어오는가.
12. **Determinism:** 동일 seed/config/dataset/commit에서 결과가 재현 가능한가(비결정적 GPU 연산은 허용 범위 명시).

# 22. 디버그 시각화 및 연구 노트

## 22.1 먼저 만들어야 하는 Viewer

- **Observation provenance viewer:** 후보 Gaussian의 source pair와 검증 관측 Keyframe 표시
- **Cross-view residual viewer:** self vs independent 관측의 잔차 및 source overlap 표시
- **Surface normal / curvature / spread viewer:** 평면, 선형, 곡면, boundary 구별
- **Admission decision viewer:** KEEP/PROJECT/REJECT/DEFER/BYPASS 별 색상 및 원인 표시
- **GT outlier viewer:** reference surface와 candidate의 거리 기반 분류 결과 확인
- **Coverage/hole viewer:** 위·측면에서 기존 구조물의 삭제 여부와 hole 증가 확인
- **Map budget viewer:** candidate/active/resident Gaussian 및 keyframe progress 표시

## 22.2 실험별 연구 노트

```text
Experiment ID:
Date / Git commit / Dataset split:
Exact configuration / Random seed:
Question to test:
Single change from the control arm:
Reason for change:
Metrics (with matched budget if applicable):
Observations & failure cases:
Next decision (go / revise / no-go):
```

모든 실험 결과는 '무엇을 변경했나, 왜 변경했나, 어떤 지표가 변했나'가 연결되도록 저장한다.

# 23. 16주 개발 일정 (개정)

| 시기 | 목표 | 종료 조건 / 산출물 |
|---|---|---|
| **1~2주** | 공개 저장소·환경 고정, MASt3R-SLAM / Splatt3R-SLAM 재현 | commit·GPU·환경, E0 baseline log, 기본 map export |
| **3~4주** | **드론 초기 파일럿**, source pair ID/pose/pointmap export, GT benchmark 확정 | geometry feasibility 문서, Sim(3) unit test, 독립 관측 확보 가능 여부 |
| **5~6주** | Cross-view observation association + local surface estimator | source exclusion·visibility·PCA unit test, residual viewer |
| **7~8주** | Conservative admission(KEEP/REJECT/DEFER/BYPASS), 첫 E1/E2 | self/cross histogram, GT outlier/coverage 및 first Go/No-Go |
| **9~10주** | Matched-budget B1~B5 vs P1/P2 검증, parameter sensitivity | E3 Pareto curve, 고정된 validation threshold, 핵심 방법 선택 |
| **11~12주** | **결과에 따라** soft projection 또는 surface-aware dedup 중 하나만 우선 구현 | E4 또는 E5 완료, 추가 가치 없으면 확장 중단 |
| **13주** | Long-sequence 및 loop-closure/cache, GPU memory compaction | E6, active/resident/VRAM 분리 그래프 |
| **14주** | 드론 실험 확대, qualitative visualization | E7, 주요 성공/실패 장면 |
| **15주** | Ablation 재실험, scene 단위 통계 및 논문 그림·표 완성 | 최종 result matrix, reproducibility check |
| **16주 이후** | 논문 집필·수정 | 서론/관련 연구/방법/실험/한계 정리 |

상기 일정은 예시다. 8주차에 핵심 가설이 반증되면 9주차 이후 계획은 기존 일정 유지보다 **연구 범위 재결정**을 우선한다.

# 24. 연구의 실패 가능성 및 대응

| 위험 | 영향 | 대응/분석 |
|---|---|---|
| 동일 backbone이 만든 공유 geometric bias | 내부 surface residual은 개선되어도 실제 GT 오차 그대로 | source-exclusion, GT 기준 분석, self/cross 비교 |
| 다른 프레임으로도 실제 independent observation이 부족 | 본 연구의 차별화 약화 | ancestry export, 데이터/시퀀스 조정, 독립성 한계 명시 |
| 기하학적 평면이 얇은 구조·곡면과 충돌 | 정상 Gaussian 삭제, hole 증가 | spread ratio·경계 검사·DEFER/BYPASS |
| MASt3R-SLAM scale drift / pose error | 잘못된 surface projection과 중복 판정 | Sim(3) / cache revision / pose 정렬 검사 |
| GT 데이터 부재 | 실제 이상점 개선을 객관적으로 증명하기 어려움 | 공개 GT dataset 중심 정량 평가, drone은 별도 정성 결과 |
| 기존 voxel/confidence filtering과 성능 차이 없음 | novelty 약화 | 동일 budget에서 통계, 실패 원인 분석, 범위 축소 |
| `active=false`의 VRAM 감소 부재 | compactness 주장 불충분 | physical compaction 별도 구현 및 memory 실측 |
| 필터링 효과보다 coverage 손실이 큼 | PSNR/Completion 악화 | 판단 문턱 완화, false reject 사례 분석, projection 선택 실험 |
| Surface/correspondence 계산이 너무 느림 | online 적용성 부족 | offline correctness 우선, cache/voxel hash 후 GPU 최적화 |
| 신규 2026+ 논문과 novelty 중복 | 기여 주장 축소 | 주기적 literature review, 검증 프로토콜 차이 명확화 |

실험이 일부 실패하더라도 상관 오차의 영향, 어떤 입력 정보가 유효한지, 속도-품질 한계 등 **검증된 부정적 결과**는 연구 분석에 활용한다. 다만 이를 성능 향상이나 독창성 확보로 포장하지 않는다.

# 25. 논문 기여(조건부)와 장 구성

## 25.1 실험 결과가 뒷받침할 때 주장할 기여 후보

1. **교차시점 surface-supported Gaussian admission:** 후보 생성 소스와 검증 소스를 분리하고, 유효한 다중시점 surface support에 따라 Gaussian Map 편입을 판정하는 절차.
2. **불확실성 처리 정책의 정량 분석:** 기하 증거 부족을 outlier와 구분하는 DEFER/BYPASS 방식이 정상 구조 보존·coverage에 미치는 영향.
3. **동일 Gaussian 예산의 재구성 품질 비교:** 기존 confidence/voxel/uniform reduction과 비교한 geometry·rendering·memory trade-off에 대한 재현 가능한 결과.
4. **조건부 확장:** projection 또는 dedup이 별도의 비교에서 추가 이득을 입증할 경우에만 기여로 서술.

기여가 확인되지 않는 경우 해당 항목을 *방법 제안/검증한 가설/실험 관찰*로 표현한다. Pointmap 내부 일치도를 실제 geometry accuracy와 혼동하지 않는다.

## 25.2 예상 학위논문 장 구성

1. **서론:** 3DGS, 연속 영상 및 장기 Map 문제, 연구 질문과 기여
2. **관련 연구:** DUSt3R/MASt3R/MASt3R-SLAM, Splatt3R/Splatt3R-SLAM, 3DGS density control, CCGS·SuGaR, 2026년 관련 연구
3. **제안 방법:** 출처 분리, 가시성·surface 추정, reliability, conservative admission, Sim(3)/cache
4. **구현:** 데이터 pipeline, 주요 자료구조, online/offline 실행과 비용
5. **실험:** benchmark/drone, GT geometry, matched-budget, rendering, memory, ablation
6. **분석 및 한계:** self vs cross view, 경계/식생/재관측 영역, correlated bias, 실시간성
7. **결론 및 향후 연구:** 입증된 효과와 projection/dedup/mesh 관련 후속 방향

# 26. 재현성·최종 산출물

## 26.1 실험 환경 기록

각 experiment를 다음처럼 저장한다.

```text
results/<experiment_id>/
├── config.yaml
├── git_commit.txt
├── environment.txt
├── dataset_split.json
├── metrics.json
├── per_scene.csv
├── per_frame.csv
├── gaussian_decisions.csv
├── observation_sources.csv
├── map_stats.csv
├── timing.csv
├── trajectory.txt
├── render/
├── geometry/
├── figures/
└── logs/
```

필수 환경 및 run 메타데이터:

- GPU/VRAM, CUDA, Python, PyTorch, pretrained weight의 출처·hash, 라이브러리 버전
- git commit, 명령줄 옵션, dataset version/sequence, split, camera preprocessing
- frame resolution, stride, keyframe count, `min-confidence`, `max-gaussians`, refiner flags
- random seed, pose source/scale alignment, GT 사용 여부 및 정렬 프로토콜
- surface support ancestry 규칙, threshold 선정 범위와 validation 선택 근거
- active/resident/serialized Gaussian 정의 및 measurement method

## 26.2 반드시 제출 가능한 artifact

- 실험 재현용 코드 patch 또는 repository
- 구성 파일과 평가 스크립트
- 기본·제안 방법 동일 입력/동일 예산 비교 데이터
- 주요 Plot: PR/ROC, quality-count Pareto, GT coverage, map growth, memory
- Gaussian PLY 및 (가능하면) Keyframe별 map snapshot
- 드론 데이터 촬영 메타데이터 및 정성 시각화
- 성공과 실패 사례의 정확한 재현 절차

# 27. 가장 먼저 실행할 체크리스트

- [ ] 원본 Splatt3R-SLAM commit과 pretrained weights를 고정했다.
- [ ] 실제 사용 옵션(`--min-confidence`, `--max-gaussians`, `--refiner`, `--refiner-dedup-voxel`)과 실행 경로를 기록했다.
- [ ] Keyframe pose·Gaussian anchor frame·Sim(3) scale 적용을 검증했다.
- [ ] 후보 생성 image pair의 ID와 Pointmap ancestry를 추적할 수 있다.
- [ ] 다른 시점에서 독립 관측을 확보할 수 있는지 실측했다.
- [ ] 자기 Pointmap과 cross-view Pointmap을 **별도로** 이용한 distance histogram을 만들었다.
- [ ] 2D pixel neighborhood + 3D distance + depth discontinuity를 반영한 표면 추정을 검사했다.
- [ ] Line-like point cloud에서 평면 오판정이 없도록 확인했다.
- [ ] 외부 GT가 있는 scene과 GT 없는 drone scene을 구분해 평가할 수 있다.
- [ ] Uniform thinning / confidence / voxel / self-filter baseline을 동일 예산에서 비교할 수 있다.
- [ ] REJECT/DEFER 이유와 normal surface 손실을 로그에 남긴다.
- [ ] 실제 GPU buffer count와 VRAM을 측정하는 코드를 마련했다.

# 28. 핵심 참고문헌 및 구현 확인 출처

이 절은 논문 및 공개 저장소에서 확인된 **배경 사실**과 연구 설계에서 별도로 검증할 사항을 구분하기 위한 것이다. 학위논문 최종 원고에는 실제 확인한 출판 정보, 판본, 페이지 및 BibTeX를 사용한다.

1. Kerbl, B. et al. *3D Gaussian Splatting for Real-Time Radiance Field Rendering* (2023). https://arxiv.org/abs/2308.04079
2. Wang, S. et al. *DUSt3R: Geometric 3D Vision Made Easy*. https://arxiv.org/abs/2312.14132
3. Leroy, V. et al. *Grounding Image Matching in 3D with MASt3R* (2024). https://arxiv.org/abs/2406.09756
4. Murai, R., Dexheimer, E. and Davison, A. J. *MASt3R-SLAM: Real-Time Dense SLAM with 3D Reconstruction Priors*. https://arxiv.org/abs/2412.12392
5. Smart, B. et al. *Splatt3R: Zero-shot Gaussian Splatting from Uncalibrated Image Pairs*. https://arxiv.org/abs/2408.13912
6. **Splatt3R-SLAM 공개 구현:** https://github.com/Looong01/Splatt3R-SLAM — 사용 가능한 옵션, `--dump-keyframe-gaussians`, keyframe-local map, refiner, voxel dedup을 **실제 checkout commit 기준으로 다시 검증**할 것.
7. Hu, W. et al. *Pointmap Association and Piecewise-Plane Constraint for Consistent and Compact 3D Gaussian Segmentation Field (CCGS)*. https://arxiv.org/abs/2502.16303
8. Guédon, A. and Lepetit, V. *SuGaR: Surface-Aligned Gaussian Splatting for Efficient 3D Mesh Reconstruction and High-Quality Mesh Rendering*. https://arxiv.org/abs/2311.12775
9. Gao, R., Jin, L. and Zhang, Y. *GeoGS-SLAM: Online Monocular Reconstruction Using Gaussian Splatting with Geometric Priors* (2026). https://arxiv.org/abs/2607.11184
10. Luu, T. et al. *Geometry-Aware Online Mapping for 3D Gaussian Splatting SLAM* (2026). https://arxiv.org/abs/2608.14902

**출처 및 설계 구분:** 1~8은 v1 계획서의 주요 기반이며, 9~10과 공개 저장소 옵션은 이번 개정 검토 과정에서 추가 확인했다. 본 문서의 `source exclusion`, `DEFER`, `matched-budget`, PCA spread gate, Sim(3) cache revision, evaluation protocol은 **연구 설계 제안**이지 위 논문들이 동일하게 제시한 알고리즘이라는 뜻이 아니다. 원고의 CCGS/Splatt3R-SLAM 관련 요약 역시 최종 인용 전에 해당 문헌과 저장소의 원문에 대조할 것.

---

# 29. 최종 연구 방향 요약

```text
Not: MASt3R-SLAM + Splatt3R + CCGS의 기능 단순 결합

Research question:
    Which feed-forward Gaussians deserve admission to a long-term SLAM map?

Proposed hypothesis:
    Candidate-independent cross-view geometry, when reliable and visible,
    can improve Gaussian admission decisions without sacrificing coverage.

Required evidence:
    Independent GT geometry + held-out rendering + matched Gaussian budgets.

MVP:
    Cross-view surface evidence → conservative admission → fair comparison.

Optional after success:
    Bounded soft projection / surface-aware dedup / physical compaction.
```

연구의 성공 여부는 **내부 Pointmap 정합성 수치가 좋아졌는가**보다, 외부 GT와 새로운 카메라 시점에서 이상 Gaussian을 줄이고 정상 표면의 표현을 유지하면서, 기존의 더 단순한 감소 기법보다 좋은 quality-budget trade-off를 제시하는가에 따라 판단한다.
