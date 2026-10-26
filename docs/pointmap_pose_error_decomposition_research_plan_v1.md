# MASt3R-SLAM 기반 3D Gaussian Splatting의 기하 오차 원인 분해 및 조건부 깊이 보정 연구

## 연구 설계·구현·실험 계획서 v1.0 — Surface-guided Gaussian Mapping 종료 이후 신규 연구

- **작성일:** 2026-10-22 (Asia/Seoul)
- **연구 단계:** 새 주제의 타당성·원인 분해를 우선 검증하는 **사전 실험 계획**. 새로운 Depth 보정 알고리즘의 효과나 논문 독창성은 아직 입증되지 않음
- **직전 연구:** `surface_guided_gaussian_mapping_research_plan_v3.md` → `surface_guided_gaussian_mapping_experiment_summary.md` (E0~E4f, 2026-10-15~22 완료·연구 종료)
- **시스템:** MASt3R/MASt3R-SLAM + Splatt3R-SLAM, 단안 RGB 입력, 학습된 모델의 가중치는 기본적으로 고정
- **현재 논문 제목(가안):** **MASt3R-SLAM 기반 3D Gaussian Splatting에서 Pointmap 및 카메라 자세 오차가 3차원 재구성에 미치는 영향 분석**
- **조건부 후속 제목:** **MASt3R-SLAM 기반 3D Gaussian Splatting의 기하 오차 분석 및 선택적 깊이 보정**
- **영문 제목(가안):** *Decomposing Pointmap and Camera Pose Errors in MASt3R-SLAM-Based 3D Gaussian Splatting Reconstruction*
- **연구 운영 원칙:** A0의 원인 분해 결과가 확보되기 전에는 `Depth 보정이 핵심 해결책`이라고 미리 확정하지 않는다.

> **진행 상태 (2026-10-26):** [N0 자산 점검·기준선 재현](experiments/N0_asset_audit_results.md) 및 [N1 좌표계·단위·개입 계약 검증](experiments/N1_coordinate_contract.md) **PASS**. 개발 `office0`에서 공통 후보 258,718개·고정 표본 1,429개를 등록하고 4군 불변 조건을 확인했다. 다음은 **미사용 GT 장면 확보·A0 평가 등록과 실행**이다. A0 기하 효과·원인 우세는 아직 평가하지 않았다. 아래 일정·체크리스트는 계획이며 개별 완료 여부는 실험 보고서를 따른다.

> **문서의 증거 구분**
> - **[기존 실험]**: 2026-10-22 종료 보고서에 기록된 관측 및 수치.
> - **[논문 근거]**: 첨부 MASt3R-SLAM, Splatt3R, 두 GeoGS-SLAM 등의 방법 설명.
> - **[가설/제안]**: 본 문서에서 새로 설계한 통제실험·평가 방법·보정 방식. 실제 효과는 아직 미검증.
> - 이번 계획은 기존 Pruning 프로젝트를 재개하는 지시가 **아니다**. 이전 프로젝트의 저장된 코드·데이터·평가 기반만 재활용한다.

---

# 0. 핵심 결론과 연구 변경 이유

## 0.1 한 문장 연구 문제

> **연속 RGB 영상에서 추정된 3D Gaussian Map의 형상 오류가 (A) 입력 Pointmap의 국소 깊이·형상 오차, (B) Keyframe의 Pose·Scale 배치 오차, (C) Gaussian 표현·렌더링 오류 중 어디서 발생하는지 실험적으로 구분하고, 주된 원인에만 제한적인 보정을 적용해 실제 기하 정확도를 개선할 수 있는가?**

## 0.2 과거 실험으로 이미 확인한 사항

| 관측 | 실험 기록 | 본 연구에서의 함의 |
|---|---|---|
| 검사한 Splatt3R-SLAM raw self-branch 후보에서 `Gaussian mean == source pts3d` | E4e: raw/pre-active 후보 각각 4,472,832개, offset median/p95=0 | 점 중심의 초기 배치 오류가 **새 Gaussian 생성 단계에서 독립적으로 추가되었다**고 가정하지 않음. Pointmap/월드 변환을 먼저 분석 |
| GT-front 오차 후보가 존재하지만 고립 floater의 확정 라벨은 아님 | E1: active 705,772개 중 반복 GT-front proxy 12.81% | 개별 중심 outlier 수만으로 지도 전체의 잘못된 표면을 대표할 수 없음 |
| 틀린 Pointmap도 일관된 국소 평면을 형성함 | E4b: 잘못된 평면이 미제거 bad 31,412개를 지지; 30,777개에서 주변 점의 대다수도 같은 방향 오류 | 같은 모델에서 나온 국소 평면에 projection하는 방법은 공유 편향을 교정하지 못할 수 있음 |
| 기존 plane admission의 추가 성능 이득 미입증 | E4 office1 75% 예산: plane TSDF Chamfer 0.108354m, B6 0.105947m | 후보 제거/보류/중복 판정 연구는 종료. 강한 Depth 대조군보다 나은지 반드시 확인 |
| UAV 실험에서 국소 표면 단차·왜곡을 관찰 | E4e HKairport01: 240입력, 21KF, tracking gate 미통과 | 시각적 현상만으로 원인을 확정할 수 없음. 우선 GT 보유 장면에서 분해 |
| KITTI에서 Depth 오류와 전역 배치 문제가 함께 의심됨 | E4f: 전역 Scale 후에도 거리별 Depth 잔차, OXTS 배치에서 일부 NN 거리 개선 | Pose 및 Scale을 **같이 바꾼 Oracle**로는 어느 요소가 원인인지 인과 분해 불가 |
| 기존 NVS 실험은 full appearance optimization의 대표 성능이 아님 | E0/E4: refinement=0, degree-0 appearance 설정 | 저 PSNR을 곧바로 Depth 오류로 단정하지 않고 refiner-on/off 별도 통제 |

**철회할 가정:** 'Gaussian 생성 자체가 무작위로 엉뚱한 위치를 만드는 것이 주된 문제'라는 포괄적 설명. 검사된 구현 경로에 한해서만 중심과 pointmap의 일치를 확인했으며, **Gaussian의 covariance·opacity·appearance 오차, pose/scale 오차, 모든 시퀀스의 동작까지 배제한 것은 아님**.

## 0.3 기존 프로젝트와의 경계

- `KEEP / REJECT / DEFER` 기반 candidate admission, repeated-plane-support pruning, surface-aware dedup은 **종료된 주제**이다.
- 신규 연구에서는 **같은 Gaussian ID와 속성을 유지한 채** Pointmap 또는 월드 배치의 변화가 지도 품질에 미치는 영향을 우선 검증한다.
- 마스크 기반 하늘/동적 객체 제거, 새로운 Gaussian의 재학습, mesh completion, 대규모 SLAM backend 재작성은 기본 필수 범위에서 제외한다.

---

# 1. 연구 목표, 연구 질문, 가설

## 1.1 필수 목표(MVP)

1. **오류 전달 경로 계측:** raw pair pointmap → local frame → keyframe/global Sim(3) → Gaussian center → rendered depth/3D surface의 변환 및 provenance 확정.
2. **오류의 분리 실험 A0:** 고정된 후보 ID·픽셀·Gaussian 속성을 대상으로 Pointmap과 Pose를 각각 GT로 치환한 2×2 factorial Oracle 실험.
3. **Scale 분리:** 전역 단안 gauge 정렬과 Keyframe별 drift를 분리하고, 회전/이동/scale의 효과가 혼합되지 않도록 통제.
4. **기하 중심 평가:** GT depth와 3D surface, coverage, 거리별/표면별 오류. 렌더링 지표는 별도로 보고.
5. **Go/No-Go:** A0 결과에 따라 Depth 보정, Pose/Scale 보정, Gaussian 표현 연구 또는 '원인 분해 분석 논문'으로 범위를 결정.
6. **재현성:** 동일 후보 풀·동일 공통 마스크·같은 test scenes·run manifest를 보존.

## 1.2 A0가 통과했을 때만 추가하는 목표

- **Depth 중심 결과:** RGB-only 정보를 활용하는 *저차원/국소 선택적 Depth 보정*의 성능을 기존 단순 scale·photometric reprojection 방식과 비교.
- **Pose 중심 결과:** full SLAM 개편 대신, pose/scale 재배치 진단과 제한된 외부-학습 없는 정렬 보정을 작은 실험으로 검증.
- **복합 결과:** Pointmap·Pose의 상호작용 분석까지를 연구 기여로 선택할 수 있으나, 두 분야를 동시에 본격 개선하는 것은 필수 목표로 만들지 않음.

## 1.3 연구 질문

| ID | 연구 질문 | 검증 실험 |
|---|---|---|
| **RQ1** | 동일한 Gaussian 후보에서 실제 표면 오류에 더 크게 기여하는 것은 **Pointmap local geometry**인가, **Pose/Scale placement**인가? | A0 factorial Oracle, A1 pose/scale 분해 |
| **RQ2** | Pointmap 오차가 전역 scale 차이인지, 공간적으로 변하는 local depth deformation인지 구분 가능한가? | A2 단일-scale 최적 잔차 vs region residual |
| **RQ3** | 깊이 보정이 효과적인 조건에서는 GT 없이 **RGB-only 제한적 Depth 보정**으로 독립 GT 기하 품질을 높일 수 있는가? | D0~D5, 신규 scene 실험 |
| **RQ4** | Depth 보정이 rendering quality/coverage와 정상 구조를 훼손하지 않는가? | held-out RGB, TSDF/surface, per-region failure |
| **RQ5** | GPU 8GB 환경에서 재현 가능하고 제한된 추가 계산비로 수행할 수 있는가? | VRAM/latency, ablation |

## 1.4 검증 가설 — 결과 전 주장 금지

- **H1:** A0에서 GT Pointmap 또는 GT Pose를 한 가지만 치환해도 지도 GT 오류의 일정 부분이 감소한다. 어느 쪽이 큰지는 미정.
- **H2:** GT를 적용한 2×2 실험에서 두 오류 성분 간 상호작용이 존재할 수 있다. 오차를 단순 합으로 해석하지 않는다.
- **H3(조건부):** 깊이 오차가 주요 원인이라면 공간적으로 제한된 보정이 Keyframe 단일 scale만 사용하는 방법보다 지표 개선을 얻을 수 있다.
- **H4(조건부):** 보정할 증거가 부족한 평면/하늘/occlusion/저시차 영역에서는 보정 강도를 낮추는 선택 정책이 보정 전면 적용보다 구조 손상을 줄일 수 있다.

---

# 2. 선행연구와 독창성 경계

| 연구 | 기존 기여 | 본 연구에서 하지 말아야 할 주장 |
|---|---|---|
| DUSt3R / MASt3R | 두 이미지의 pointmap, confidence, matching descriptor; pose/depth 추정 기반 | Pointmap 자체를 출력한다는 것이 새로움이 아님 |
| MASt3R-SLAM | MASt3R pointmap과 matching, 카메라 추적 및 전역 정렬 | Sim(3) pose update 일반 원리 자체를 새로움으로 주장하지 않음 |
| Splatt3R | MASt3R 기반 per-pixel Gaussian 속성 예측; 원칙적으로 Gaussian 중심과 pointmap이 연계됨 | pointmap을 Gaussian 중심에 쓰는 것을 새로움으로 주장하지 않음 |
| GeoGS-SLAM, Geometry-Only (2026) | depth/normal 및 multi-view photo loss, local-plane PCA, coherent Sim(3) map update | local plane, depth smoothness, multi-view consistency 자체를 신기법이라고 표현 금지 |
| GeoGS-SLAM, Geometric Priors (2026) | VGGT priors, map/pose joint optimization, DoG sampling, photometric+depth objectives | 예측 depth와 RGB를 결합한다는 일반적인 아이디어를 독창성으로 주장하지 않음 |
| 기타 depth/pose refinement 연구 | BA, photometric consistency, smoothness, scale alignment 등 오래된 기법 | 단일 scale 또는 재투영 기반 depth refinement만으로 독창성 주장 금지 |

**잠정 차별화(검증 전):** **동일한 MASt3R-SLAM→Splatt3R 후보 경로에서 Pointmap·Pose·Gaussian 표현의 error source를 분리하는 재현 가능한 평가 계약**, 그 결과로 드러나는 실패 조건, 그리고 *특정 오류 유형에서만* 유효한 제한적 보정의 추가 효과.

**문헌 검토 게이트:** 최종 보정 방법을 확정하기 전, MASt3R/DUSt3R/VGGT 기반 depth refinement, SLAM scale drift, photometric/geometric BA, Gaussian pose/depth joint refinement와 직접 중복되는 연구를 추가 검색. 전체 시스템과 공정 비교할 수 없으면 기법별 비교군으로 구분.

---

# 3. 고정 파이프라인·데이터 계약

## 3.1 검증해야 할 좌표계

기본 표기(코드의 실제 규약과 일치하는지 테스트 후 확정):

> **N1 확인:** 개발 self-branch의 좌표계·xyzw·단위·픽셀 및 native active/PLY 연결은 [N1 계약서](experiments/N1_coordinate_contract.md)에서 검증했다. Raw Pointmap의 ray는 GT pinhole ray와 정확히 일치하지 않으므로, 아래 GT backprojection은 깊이와 ray를 함께 바꾸는 **local geometry** 개입으로 해석한다.

- $I_a, I_b$: Splatt3R/MASt3R 입력 이미지 pair
- $X_{v\leftarrow a}(u)$: 이미지 v의 픽셀 u에 대응하되 기준 이미지 a 좌표계로 표현한 3D pointmap
- $K_v$: 카메라 v의 intrinsics, $r_v(u) = K_v^{-1}[u_x,u_y,1]^T$: 비정규화 카메라 ray
- $D_v(u)$: **카메라 Z-depth**. LiDAR range(유클리드 거리)와 정의가 다를 수 있으므로 항상 기록
- $T_{w\leftarrow a}=(s_a,R_a,t_a)$: anchor a에서 공통 world로 변환하는 Sim(3)
- $G_i=(\mu_i,\Sigma_i,\alpha_i,c_i,\ldots)$: Gaussian의 position, covariance, opacity, color 등
- 원본에서 관찰된 raw self branch에서는 $\mu_{i,a}=X_{a\leftarrow a}(u_i)$였으나 **각 branch와 refiner 경로에서 다시 검증**해야 함.

기본 변환:

$$
\mu_{i,w}=s_a R_a\mu_{i,a}+t_a, \qquad
\Sigma_{i,w}=s_a^2 R_a\Sigma_{i,a}R_a^T.
$$

GT Depth 기반 로컬 점은 v 카메라 좌표계에서:

$$
X^{\mathrm{GT}}_{v\leftarrow v}(u) = D_v^{\mathrm{GT}}(u) K_v^{-1}[u_x,u_y,1]^T.
$$

**v가 anchor a와 다른 경우**, GT 상대 Pose를 이용해 $X^{\mathrm{GT}}_{v\leftarrow a}$로 변환한 후 후보의 원래 anchor 좌표계에 저장한다. `GT pose arm`으로 실험하기 전에 이 좌표 변환만으로 올바른 pointmap 대체가 성립해야 한다. 두 개를 동시에 GT로 교체해 버리는 누설을 금지한다.

### 필수 구현 검증

1. pose 저장 방향(camera-to-world vs world-to-camera), quaternion 순서, 단안 scale 단위 확인.
2. pair 1/2의 pointmap이 **어느 카메라 좌표계에 있는지**, Gaussian 생성 branch별 mean offset 유무 확인.
3. $K$의 왜곡 모델, undistortion, 렌더 해상도와 이미지 resize/crop 변환 확인.
4. `depth_z` vs `range`의 차이를 통합 depth evaluator에서 명시.
5. 변환 왕복 test: mean, covariance, projection residual; GT pose를 두 번 적용하는 버그 탐지.
6. raw 후보와 `active`/PLY 후보의 ID 연결, pruning/native filter, refiner 여부 확인.
7. tracklet/sky/occlusion mask 및 평가 GT 가용성 분리.

## 3.2 필수 logging 데이터 모델

| 항목 | 기록 |
|---|---|
| Scene/Run | scene ID, file hash, upstream commit, modified commit, checkpoint hash, seed, GPU/driver/CUDA/PyTorch |
| Image | frame timestamp, pair IDs, source branch, resolution, crop, K, distortion model |
| Candidate | `candidate_id`, `pixel_uv`, `anchor_kf_id`, source pair IDs, raw xyz, offset, confidence |
| Map | local/world mean, scale, quaternion/covariance, opacity, SH/color, native active mask, refiner state |
| Pose | estimated local/global Sim(3), GT pose, source convention, alignment Sim(3), pose revision |
| GT | raw GT units/source, valid depth masks, GT metric scale, mesh/LiDAR coverage, dynamic masks |
| Eval | registered candidate set hash, common valid mask hash, gaussian attributes hash, renderer options |

> **실행 비용 통제:** 처음에는 전체 수백만 후보 대신 **동일 후보 ID의 고정된 stratified subset**으로 A0 구현을 검증하고, pipeline이 정확한 것으로 확인된 뒤 scene 전체 결과를 산출한다. Subset 선택 기준은 GT outlier 여부가 아니라 픽셀/거리/깊이 strata와 고정 seed로 정의한다.

---

# 4. 가장 중요한 실험 A0 — Pointmap × Pose 2×2 Oracle 오류 분해

## 4.1 목표

**동일 장면의 동일 관측 픽셀과 Gaussian 후보를 유지한 상태에서** local pointmap과 world placement를 각각 치환했을 때 독립 GT geometry가 얼마나 좋아지는지 측정한다. GT는 실험 안에서만 허용되는 Oracle이므로, 이 결과는 배포 가능한 RGB-only 알고리즘 성능이 아니다.

## 4.2 공통 유효영역·동일 후보 계약

- 각 source 픽셀에 GT depth가 존재하고, static/occlusion·FOV 조건이 일치하는 공통 집합 $\Omega_{\mathrm{common}}$을 먼저 고정한다.
- 네 실험군에서 **동일한 source pair, candidate ID, 픽셀 위치, candidate 수, active mask, 타임스탬프**를 사용한다.
- Gaussian의 `opacity, color/SH, rotation, covariance(local)`는 **기본 A0**에서 고정. 중심·월드 변환만 바꾼다.
- GT depth가 없는 후보를 한 군에서만 제거하지 않는다. ① 공통 후보만을 대상으로 하는 strict geometry analysis와 ② 미보유 후보를 변경하지 않는 full-map sensitivity를 분리한다.
- 후보 selection이나 native filter를 재실행하여 군마다 후보 수가 바뀌는 경우 별도 'end-to-end' 실험으로 간주하고 **A0 핵심 표에 혼합 금지**.
- 네 군 모두 **한 번 정해진 공통 metric gauge 및 정렬 규칙**을 적용한다. 군별로 매 프레임 GT에 맞춰 최적 정렬하는 것을 금지한다.
- 색상·opacity·covariance를 고정한 채 중심만 이동하면 렌더링이 오히려 악화될 수 있다. 이때 원인분해의 주 지표는 **기하 정확도**이고, renderer/appearance는 별도 효과로 해석한다.

## 4.3 2×2 비교군

| Arm | Local geometry (L) | Placement (P) | 질문 | 해석 |
|---|---|---|---|---|
| **A00** | 추정 Pointmap | 추정 Pose/Scale | 현재 원본의 기하 오차 | baseline |
| **A10** | **GT Depth를 동일 pixel·anchor에 backproject** | 추정 Pose/Scale | local depth 오류를 제거하면? | local geometry oracle |
| **A01** | 추정 Pointmap | **GT Pose(공통 gauge 정렬)** | world placement 오류를 제거하면? | placement oracle |
| **A11** | **GT local geometry** | **GT Pose** | 두 오류를 제거해도 남는 오차는? | oracle upper reference (완벽 재구성 보장 아님) |

**매우 중요한 주의:** source branch가 다른 카메라 b의 픽셀이라면 `GT depth_b → camera-b 좌표 → anchor-a 좌표`의 상대 Pose가 필요하다. 이 변환에서 GT 상대 Pose를 사용하면 A10에도 일부 pose 정보가 들어갈 수 있다. 그러므로 다음처럼 설계를 이원화한다.

1. **Primary strict A0:** raw *self-branch* 또는 **anchor-local native depth**로 대체 가능한 후보만 사용하여 local geometry와 global pose의 독립적인 개입을 보장한다.
2. **Secondary pair A0:** 다른 source view 후보까지 포함한다. `predicted relative pair transform`/`GT relative pair transform`을 분리한 보조 요인 또는 oracle로 명시하고, primary strict A0와 같은 인과 효과라고 주장하지 않는다.

**N1에서 확인한 해석 조건:** GT depth를 GT ray로 backproject하는 A10은 순수 Z-depth 교체가 아니다. Local oracle 효과를 Depth 보정으로 이어서 해석하려면, predicted ray를 유지하는 depth-only 보조 실험 또는 ray 오차의 별도 분석이 필요하다.

## 4.4 단안 Scale 정렬의 주의점

- MASt3R-SLAM의 native 단위는 meter가 아닐 수 있다. per-scene **단일 고정 Sim(3) alignment**를 사용하여 GT reference 좌표계와 맞춘다.
- Scale은 **GT trajectory의 정해진 calibration prefix** 또는 별도 validation 구간에서 한 번만 고정하고, test 구간은 같은 정렬값을 사용한다. 평가 중 각 keyframe에 별도의 최적 scale을 허용하지 않는다.
- 기하 오류 진단 시 두 보고를 병행한다: (i) metric-aligned depth error, (ii) *alignment-insensitive* 상대 깊이/형상(예: depth ratio/locally centered residual).
- A01에서 GT pose를 넣는다는 것이 frame-wise independently aligned depth를 의미하지 않는다.
- 이전 E4f처럼 estimated arm의 keyframe Sim(3) scale과 oracle arm의 `GT SE(3) + trajectory scale`을 동시에 바꾸는 설계를 반복하지 않는다. 엄격 비교가 불가능하면 **미분리 변수**를 명시하고 해당 결과를 primary causal claim에서 제외한다.

### 공통 단위의 명시적 정의(구현 필수)

`GT Depth`의 단위가 미터이고 MASt3R raw local pointmap의 단위가 임의일 수 있으므로, **Oracle 값을 raw local 텐서에 숫자 그대로 대입하지 않는다.** 다음은 코딩 시 검증할 *개념적 공통화 예*이며 실제 pose composition과 저장 규약에 맞춰 부호·방향을 확인한다.

- 한 번 결정한 로컬 단위 환산 계수 $C > 0$(m / raw-local-unit)을 모든 KF에 고정한다. $\hat{X}_k^m = C\hat{X}_k^{\mathrm{raw}}$.
- 전역 게이지 정렬을 포함한 추정 Sim(3)를 $\hat{T}_k^m(X) = \hat{s}_k\hat{R}_k X + \hat{t}_k$로 다시 정의한다. 기존 raw 좌표를 world-metric으로 옮긴 결과가 보존되도록 $\hat{s}_k$를 변환하되, 원래 KF별 상대 scale 변화는 남겨 둔다.
- GT local geometry는 같은 카메라 축에서 $X_k^{\mathrm{GT},m} = D_k^{\mathrm{GT}}(u) K_k^{-1}\tilde{u}$로 만든다.
- $\mathrm{A00}: \hat{T}_k^m(\hat{X}_k^m)$, $\mathrm{A10}: \hat{T}_k^m(X_k^{\mathrm{GT},m})$, $\mathrm{A01}: T_k^{\mathrm{GT},\mathrm{SE3}}(\hat{X}_k^m)$, $\mathrm{A11}: T_k^{\mathrm{GT},\mathrm{SE3}}(X_k^{\mathrm{GT},m})$로 계산한다.
- GT Pose가 metric SE(3)이므로 **GT pose arm의 scale은 1**이며, 추정 pose arm의 $\hat{s}_k$ 변동은 placement factor에 포함한다. 최초 KF/보정용 prefix에서 원점을 고정하고 모든 test frame에는 동일한 $C$와 전역 gauge를 적용한다.

이 방식 역시 *게이지 정의에 조건부인 요인 분해*다. $C$를 변경하거나 GT/추정 내부 카메라 모델이 다르면 local-vs-placement contrast가 달라질 수 있으므로, **게이지 민감도 분석(개발 세트)**을 수행하고 `GT가 존재하므로 수학적으로 유일한 오차 기여를 얻었다`고 주장하지 않는다. 실제 자료에서 $\hat{s}_k$가 이미 local scale 보정을 포함하는 방식이 다르다면 위 공통화 식을 먼저 재정의하고 단위시험으로 검사한다.

## 4.5 수학적 평가: 2×2 factorial과 interaction

공통 GT geometry error metric을 $E_{00}, E_{10}, E_{01}, E_{11}$라 정의한다(낮을수록 좋음).

$$
\Delta_{L\mid P=\mathrm{est}}=E_{00}-E_{10},\quad
\Delta_{P\mid L=\mathrm{est}}=E_{00}-E_{01}.
$$

두 효과가 단순히 더해지는지 보려면 interaction을 계산한다.

$$
\mathcal I = E_{11}-E_{10}-E_{01}+E_{00}.
$$

- $\Delta_L$ 또는 $\Delta_P$가 양수여도 다른 요인 조건에서 효과가 바뀔 수 있으므로 **순수하고 보편적인 기여율(%)**로 해석하지 않는다.
- 평가 지표마다 같은 contrast를 계산하되, 각 장면을 독립 단위로 취급하고 frame/point를 독립 표본으로 과장하지 않는다.
- A11의 residual은 occupancy·Gaussian extent/opacity·sensor GT mask·occlusion·TSDF sampling 및 rendering limits 때문에 0일 필요가 없다.
- 추가로 $E_{00} - E_{11}$은 두 Oracle을 함께 사용했을 때의 개선 범위이지, local과 pose 개선을 정확히 합친 값은 아니다.

## 4.6 A0 세부 절차

1. 실행 manifest 고정: Scene, frames, weights, version, camera model, pose revision, native active mask.
2. **GT 픽셀 유효 집합**과 class별/거리별 strata, sky/dynamic/occlusion mask 확정.
3. self-branch local points의 camera projection을 검증하고, raw mean/pointmap equality를 새로운 장면에서 재현.
4. frame-level Sim(3) transform을 검증하고 **단일 metric gauge**로 4개의 arm을 생성.
5. 각 arm을 **후보 ID·Gaussian 속성 고정**하여 저장. 원본 map 전체를 덮어쓰지 않음.
6. 공통 mask에 대해 point-level residual, rendered depth, surface sampling, completeness/coverage를 계산.
7. Pose ATE/RPE와 per-Keyframe scale drift는 원인 추적 보조로 평가.
8. **공통 셋**의 4-arm 대조와 GT 미보유 영역을 유지한 full-map sensitivity를 구분해 저장.
9. Scene별 effect/interaction의 분산과 대표 실패 사례를 시각화.
10. A0 보고서를 봉인한 다음 **Go/Revise/No-Go 결정**을 내린다.

## 4.7 A0 필수 출력

- `A0_candidate_manifest.parquet` 또는 csv: source ID, pixel, depth GT valid, class, branch, anchor.
- `A0_alignment_manifest.json`: gauge estimate, metric scale, pose direction, calibration prefix, mask definition.
- `A0_four_arms.csv`: metric per scene/per arm; rendered-depth errors; sample Chamfer/accuracy/completion.
- `A0_effects.csv`: $\Delta_L$, $\Delta_P$, interaction, paired confidence intervals 또는 scene 분포.
- 단일 프레임/작은 구간 3D viewer: A00 vs A10 vs A01 vs A11, world/frame axes 함께 표시.
- GT geometry 기반 거리 구간·평면·깊이 경계·유리/하늘/동적 영역별 failure table.
- 이미지 비교: RGB test view, rendered depth/validity, local depth residual, placement residual.

---

# 5. 보조 실험 A1 — Pose, Scale, Local Geometry의 재분리

**시작 조건:** A0에서 placement의 효과가 유의미하거나 A0 엄격 독립성에 추가 검증이 필요할 때.

## 5.1 분해 수준

| Arm | 변경 요인 | 목적 |
|---|---|---|
| A1-0 | native per-KF Sim(3) | 기준 |
| A1-R | rotation만 reference로 치환; translation/scale은 고정 규약으로 재배치 | orientation 오류 기여 |
| A1-t | translation만 reference로 치환; rotation/scale은 유지 | translation 오류 기여 |
| A1-s | scale만 reference/consensus로 치환; rotation/translation 고정 | scale drift 기여 |
| A1-SE3 | 회전+이동 reference, scale은 동일 한 값 | pure SE(3) placement reference |
| A1-Sim3 | 전체 pose+scale reference | 종합 placement upper diagnostic |

이 실험은 naive한 $t$/$s$ 숫자 대체만으로 올바르게 정의되지 않을 수 있다. 회전 중심, anchor, scale gauge, 단위가 일치하도록 transformation composition을 먼저 정의하고, **동일 월드 기준으로 차이가 한 변수에서만 발생하도록 synthetic tests를 통과한 arm만 시행**한다.

## 5.2 Local Depth 오류 유형

- **Global multiplicative scale:** 모든 픽셀에 거의 일정 비율로 틀린 깊이.
- **Frame-specific scale:** Keyframe마다 서로 다른 비율로 틀린 깊이.
- **Spatial deformation:** 프레임 내 영역별 깊이 ratio가 다름.
- **Depth discontinuity:** 물체 경계·occlusion에서 앞뒤 표면이 혼합됨.
- **Low-texture/reflection:** GT 관측이 충분하더라도 photometric signal이 약해 geometry가 흔들림.
- **Dynamic/sky/invalid:** 정적 3D 표면이 불명확한 픽셀. depth 오류로 일괄 해석하지 않음.

**진단 통계:** `relative depth error`, log-depth ratio의 median/IQR, 거리별 MAE/p95, rigid patch 내부 분산, keyframe별 scale time series, RGB parallax/reprojection support.

---

# 6. 보조 실험 A2 — Depth 수정 가능성의 상한과 공유 편향

## 6.1 질문

`Depth가 틀렸음`은 `GT 없이 깊이를 고칠 수 있음`과 다르다. Pointmap이 여러 프레임에서 같은 방향으로 틀리는 경우, cross-view geometry self-consistency만으로 실제 표면을 복원할 근거가 없을 수 있다.

## 6.2 비교

1. 단일 global scale/Keyframe scale만으로 raw depth를 정렬한 Oracle 및 RGB-only version.
2. 이미지를 기준으로 좁은 도메인의 local depth residual을 분석(plane/wall/roof/road vs thin vegetation).
3. source-disjoint cross-view geometry 비교. 공통 MASt3R model bias가 있으면 '독립 GT'가 아님을 표시.
4. raw RGB reprojection을 확인하되, 공통의 잘못된 평면에서도 저시차/무텍스처에서는 오차가 작을 수 있음을 실험.
5. GT를 사용하는 **Oracle local deformation**으로 개선 가능한 상한을 측정하되, RGB-only 알고리즘의 성능으로 보고 금지.
6. synthetic controls: (i) depth uniform scale, (ii) piecewise depth scale, (iii) depth bias, (iv) common-mode bias across views, (v) pose rotation/scale perturbations, (vi) occlusion/dynamic masks.

**Go 조건:** 실측 오류가 단일 scale로 설명되지 않는 동시에, RGB-only 관측에서 부분적으로라도 보정에 필요한 구분 가능한 정보가 관측되어야 D 시리즈를 진행한다.

---

# 7. 조건부 연구 경로 D — RGB-only 선택적 깊이 보정

> **D 경로는 A0/A2 통과 시에만 실행한다.** 아래 공식은 알고리즘 가설이며 선행연구에서 그대로 사용한 기술일 수도 있다. 추가 검색·대조 실험 없이 originality를 주장하지 않는다.

## 7.1 연구 목표

- MASt3R/SLAM network weights와 Pose를 기본적으로 고정한 상태에서, 출력 Pointmap의 depth 성분만 선택적으로 수정.
- 별도 입력 depth sensor 없이 RGB 원본 및 기존 추정 geometry만 이용.
- 적은 수의 조정 변수와 강한 regularization으로 기존 Pointmap의 신뢰 가능한 형상을 유지.
- 보정 후 3D Map을 **동일 후보 수·동일 appearance 조건으로 재투영**하여 독립 GT 기준 geometry error 개선 확인.

## 7.2 비교 방법(미리 정의)

| ID | 내용 | 목적 |
|---|---|---|
| **D0** | 추정 Pointmap 원본 | Baseline |
| **D1** | 단안 global scale 또는 KF별 단일 scale 보정(평가 구간 GT 사용 금지) | 간단한 scale 보정과 비교 |
| **D2** | 중복 시점 geometry만으로 전체 depth를 smooth/align하는 baseline | 기존 geometry-only 다중 시점 정합 |
| **D3** | Masked RGB photometric reprojection으로 제한된 depth 변수를 보정 | 일반 multi-view photometric baseline |
| **D4** | **선택적 지역 depth correction**: 신뢰 가능한 영역만 D3 성격의 objective 적용 | Proposed candidate(조건부) |
| D5 | D4 + 지역 신뢰도·low parallax·boundary gate | Optional uncertainty ablation |
| **O-D** | GT Depth 기반 local correction | Oracle 참조, 주 성능표와 분리 |

## 7.3 선택적 보정식 초안

각 Keyframe의 카메라 Z-depth에 제한된 correction field를 정의한다.

$$
D'_k(u)=D_k(u)\exp\{\delta_k(u)\},
\qquad
\delta_k(u)=\sum_m b_m(u)\theta_{km}.
$$

- $b_m(u)$는 저해상도 격자 또는 영역 기반 basis 함수. per-pixel 자유 최적화보다는 파라미터 수를 줄인다.
- $\theta_{km}$는 학습시킨 거대 backbone의 새 가중치가 아니라 **장면별 제한된 보정 변수**.
- RGB reprojection loss는 실제로 시점 간 충분한 overlap/parallax와 가시성이 확보된 곳에만 적용한다.
- regularization은 correction magnitude, 인접 영역 smoothness, RGB depth edges 보존.

예시 objective(구체 weight는 validation에서 결정):

$$
\min_{\theta}\; \lambda_{ph} L_{photo}(\theta)
+\lambda_{mv} L_{geom}(\theta)
+\lambda_{reg}\|\theta\|_2^2
+\lambda_{edge}L_{edge}(\theta).
$$

**기존 기술 대비 검증 포인트:** 같은 photometric objective를 *전체 유효영역*에 적용했을 때와 **신뢰 가능한 영역에만 선택 적용**했을 때의 순증분. 또한 D1/D2/D3와 비교하여 추가 정확도가 없다면 D4의 새로운 기여를 주장하지 않는다.

## 7.4 깊이 보정에 사용할 수 없는 증거

- GT Depth/LiDAR/GT pose를 실제 추론 objective의 직접 target으로 사용 금지(Oracle arm 제외).
- 장면 전체를 처리한 미래 프레임을 온라인 버전에서 현재 시점의 correction에 사용 금지(offline refinement arm과 구분).
- 다른 Keyframe이 같은 모델의 동일 systematic bias를 공유하면 단순 cross-view agreement를 정답 근거로 사용하지 않음.
- 하늘/유리/동적 물체/가려진 픽셀의 거짓 photometric match를 채택하지 않음.

## 7.5 Pointmap 보정 → Gaussian Map 반영 방식

1. 원본 Gaussian `candidate_id`와 `color/SH/opacity/rotation/scale`은 1차 실험에서 고정.
2. 보정 후 $X'$를 원래 anchor frame 좌표로 변환하여 Gaussian 중심 $\mu'$에만 적용.
3. 기존 생성 메서드에서 offset이 존재하면 $\mu_i=X_i+\Delta_i$를 유지한 채 $\mu'_i=X'_i+\Delta_i$로 변환; 검사한 self-branch의 offset 0 사실을 모든 경우로 확대하지 않는다.
4. 중심만 바꾼 Arm과, 위치 변경에 맞춰 scale/covariance만 **정해진 규칙으로** 재초기화한 Arm을 별도로 두어 표현의 영향을 분리한다.
5. renderer, color/SH, active candidate count, mask, pose, test viewpoint를 동일하게 유지.
6. 선택 확장으로 모든 비교군에 동일한 횟수의 Gaussian refiner를 적용하며, optimizer-on/off arm을 비교한다.
7. Depth 보정을 계산하는 동안 pose를 같이 학습시키지 않는다. joint optimization은 범위 변경 승인 후 별도 실험으로 제한한다.

---

# 8. 조건부 경로 P — Pose/Scale 배치 오류가 지배적일 때

A0에서 Pose/Scale Oracle의 이득이 Depth Oracle보다 주요한 경우 아래 경로를 검토한다.

- **P0:** 현재 MASt3R-SLAM pose (baseline).
- **P1:** 이미 시스템에 존재하는 Sim(3) global/loop alignment 단계 재점검 및 parameter/coordinate bug 확인.
- **P2:** 관측 시점 간 상대 변환·overlap·RPE/ATE를 기반으로 국소 pose/scale discrepancy를 정량화.
- **P3(선택):** 제한된 scale drift correction 또는 submap alignment를 구현하여 baseline/기존 SLAM optimizer와 비교.
- **O-P:** GT pose oracle; 실제 알고리즘 성능으로 보고 금지.

**경계:** 카메라 Pose와 점군을 동시에 global ICP로 GT reference에 맞추는 것은 평가 정렬일 뿐 RGB-only SLAM 개선이 아니다. 모든 Keyframe을 각자 GT에 정렬해 error를 숨기는 조치를 금지한다. 신뢰할 수 있는 기존 optimizer가 같은 정확도를 달성한다면 새 알고리즘의 기여는 주장하지 않는다.

---

# 9. Gaussian Representation/Rendering 통제 R

A0의 두 Oracle을 함께 적용한 뒤에도 큰 오류가 남거나 실제 RGB 렌더링 품질의 변화가 기하 오류 변화와 무관할 경우에만 수행한다.

| 실험 | 고정/변경 | 해석 |
|---|---|---|
| R0 | center·pose 고정, 현재 renderer | reference |
| R1 | center·pose 고정, opacity/scale만 정해진 규칙으로 변경 | extent/coverage 기여 |
| R2 | center·pose 고정, 공정한 동일-iteration appearance refinement | 저 PSNR이 geometry만의 문제인지 |
| R3 | GT depth/pose 중심 고정 + representation/renderer 변경 | oracle residual의 원인 분리 |

R 경로는 핵심 연구와 무관한 고품질 NVS 개발로 확장하지 않는다. 기존 E0/E4의 refinement=0 결과와 최적화된 offline 3DGS PSNR을 동일 조건인 듯 직접 비교하지 않는다.

---

# 10. 데이터셋, 개발/검증/최종 평가 분할

## 10.1 이미 사용한 자산(개발/회귀 전용)

- Replica `office0`, `room0`, `room1`, `room2`, `office1`: E0~E4에서 이미 관찰. pipeline regression, unit-test, 시각화, tuning용.
- UAVScenes `HKairport01`: E4e 개발 파일럿. 추적 실패/rolling shutter/sky 등의 오류 분류 참고.
- KITTI Raw `2011_09_26_drive_0015_sync`: E4f 개발 진단/GT range 평가 코드 재활용.
- UAVScenes `AMtown01`, `AMvalley01`: 데이터 확보·preflight만 실행. 기본 mapping baseline 평가 완료라고 적지 않음.

## 10.2 새 연구 평가 세트(실행 가능성 확인 후 확정)

| 세트 | 목적 | 요건 | 주의 |
|---|---|---|---|
| **Replica 새 미노출 scene(s)** | 2×2 A0 main geometry, GT mesh/depth | camera GT, dense geometry, static scene | 원본 v3/E4 사용 장면과 구분. test 장면에서 조건 조정 금지 |
| **TUM RGB-D 또는 다른 독립 실내 세트** | 도메인 전이 확인 | RGB 입력, depth/pose는 평가만, valid masks | depth 센서의 FOV/정렬 및 time sync 확인 |
| **KITTI 미사용 drive** | 실외 sparse LiDAR/depth vs pose 성분 확인 | RGB, calibration, OXTS, LiDAR, dynamic/sky masks | LiDAR sparse points로 GT surface 전체 completeness를 주장하지 않음 |
| **UAV 별도 scene/구간** | trajectory 및 domain stress | scale/pose/reference 있으면 정량 | GT 부재 시 절대 기하 정확도 주장 금지 |

**분할 규칙:** 장면/drive 단위 Development / Validation / Final Test 분리. 서로 겹치는 공간을 촬영한 인접 프레임은 독립 장면이 아님. 기존에 많이 분석한 scene은 논문 main test에서 제외. 최소 실험 세트의 숫자는 실제 사용 가능한 ground truth와 GPU 리소스를 확인한 후 manifest에 사전 기록.

## 10.3 GT 사용 레벨

1. `GT-depth/mesh/pose`를 **A0/A1 Oracle과 평가**에 사용하는 것은 허용; 이 Arm에는 Oracle 표기.
2. D/P에서 제출할 RGB-only 방법의 optimization/threshold 학습에 **최종 test GT 사용 금지**.
3. KITTI OXTS orientation/translation, GPS, LiDAR 기준 좌표와 이미지 타임싱크를 검증.
4. Unknown GT 부위는 **오류 0·빈 공간·정답 outlier**로 간주하지 않는다.
5. Dynamic tracklet과 sky 영역은 main static geometry mask에서 분리하고 보조 실험으로 표시.

---

# 11. 평가 지표 및 통계 설계

## 11.1 Pointmap의 국소 오류

- **Z-depth MAE / median / p95 (m):** GT와 추정의 metric 정렬 후 $\lvert D_{\mathrm{est}}-D_{\mathrm{GT}}\rvert$.
- **Abs Relative Error:** $\operatorname{mean}\left(\frac{\lvert D_{\mathrm{est}}-D_{\mathrm{GT}}\rvert}{D_{\mathrm{GT}}}\right)$ (GT $> \varepsilon$, 유효 픽셀만).
- **Log-depth ratio median/IQR:** global scale bias와 residual deformation 분리.
- **거리별:** `0–10, 10–20, 20–40, 40–80m`는 KITTI E4f의 과거 구간과 일치시키되 평가 가능 구간만 보고; 실내는 실내 거리 bin 별도.
- **평면/경계/비평면별:** wall/road/roof, depth edge, vegetation, shiny region/occlusion 여부.
- **Overlap/parallax:** 두 시점에서 실제 관측 가능한 영역의 비율과 관측 각도.

## 11.2 Map geometry 지표 — 핵심

- **Rendered depth**와 GT depth의 MAE/AbsRel/유효 픽셀 coverage 및 **correct-depth coverage**.
- GT mesh가 있는 장면: rendering depth로 얻은 3D samples → sampled GT surface의 accuracy, completion, symmetric Chamfer (샘플링·outlier truncation·거리 단위 고정).
- 해당 지표는 **rendered surface**와 **Gaussian-center proxy**를 구분한다. center→GT nearest distance만으로 실제 지도 형상을 결론 내리지 않는다.
- mask 및 coverage가 다른 방법은 **공통 유효 픽셀 지표와 전체 관측 가능 영역 coverage**를 함께 보고한다.
- 지도 오류를 작은 값으로 만드는 대신 표면 자체를 삭제한 방법은 completion/correct coverage에서 드러나게 한다.

## 11.3 Pose/Scale 지표

- ATE/RPE, orientation error, loop closure 이전/이후의 pose revision.
- 단일 global alignment 이후 keyframe scale trajectory 및 relative scale drift.
- camera/world 좌표를 혼합하지 않도록 GT pose convention을 항상 기록.

## 11.4 NVS/효율 — 부차적

- Held-out PSNR↑, SSIM↑, LPIPS↓, 실제 novel viewpoint/angle/overlap metadata.
- `Gaussian count`, serialized bytes, resident/allocated/peak VRAM, mapping/refinement ms/KF, rendering FPS.
- center-only moved vs covariance-reinitialized, no-refiner vs identical refiner steps를 **같은 평가표 안에서 혼합하지 않음**.
- RGB 품질이 개선되지 않아도 geometry 연구로 성립할 수 있지만, 원본 대비 **영상 품질의 현저한 손상과 coverage 감소**는 반드시 보고.

## 11.5 통계 및 효과 기준

- Scene/sequence를 paired comparison의 독립 단위로 사용. 수백만 픽셀을 독립 실험 반복처럼 간주하지 않음.
- Mean/median 외 per-scene effect, paired plots, 분산, 가능한 경우 scene bootstrap CI를 보고.
- 평가 대상·고정 mask·GT align·가중치·정지 조건을 **최종 test 전에 고정**.
- 최초 개발 단계에서 최소 개선폭과 허용 손실폭을 validation에서 정하되, 결과를 보고 임의로 조정하지 않음.
- 어떤 효과가 개선돼도 서로 다른 scene/GT coverage 간 수치를 한 평균으로 합산하지 않는다.

---

# 12. 핵심 Go / Revise / No-Go 기준

## 12.1 최초 Go/No-Go는 A0 완료 직후

| 관찰 결과 | 판정 | 다음 행동 |
|---|---|---|
| `A10` 개선이 뚜렷하고 `A01` 이득이 상대적으로 작음 | **GO-D** | A2 → RGB-only depth correction D1/D3/D4 비교 |
| `A01` 개선이 뚜렷하고 `A10` 이득이 상대적으로 작음 | **GO-P/REVISE** | A1 Pose/Scale 분리 후 기존 optimizer와 겹침 여부 확인 |
| 두 Oracle 각각 개선하고 interaction 작음 | **REVISE** | 더 큰 오류 원인 하나를 택해 범위를 좁힘 |
| 두 Oracle 모두 개선하지만 interaction 큼 | **REVISE** | joint effect 진단을 논문 기여로 검토. 동시에 두 모델을 새로 학습하지 않음 |
| `A11`에서도 여전히 geometry 오류가 큼 | **GO-R 또는 REVISE** | representation/renderer/GT mask 오류의 우선순위 분석 |
| 네 Arm 차이가 매우 작거나 지표가 불안정 | **NO-GO for correction** | 평가 파이프라인 재검증. 충분하면 실패 요인 중심 분석 논문으로 축소 |
| GT 대응/좌표계/정렬을 신뢰할 수 없음 | **BLOCKED** | A0 효과를 주장하지 않고 좌표계/GT debug 우선 |

**중요:** Oracle 이득은 실제 RGB-only 보정 가능성을 **보증하지 않는다**. GO-D는 D 시리즈 실험의 *진행 자격*일 뿐 논문 가설이 입증됐다는 뜻이 아니다.

## 12.2 D 경로 Go/No-Go

| 조건 | 판정 |
|---|---|
| D4가 D1/D2/D3 강한 대조군보다 신규 test에서 geometry를 개선하고 correct coverage를 보존 | 후보 기여를 검토하고 ablation·재현 실험 진행 |
| D4가 GT에서 개선하더라도 RGB/coverage를 크게 훼손 | 불충분; penalty/선택 정책을 재설계하되 결과를 숨기지 않음 |
| D4 vs D3 차이가 없거나 나쁨 | 새로운 선택적 보정의 기여 주장 보류; 가장 단순한 효과 있는 대조군 채택 또는 범위 축소 |
| GT-depth Oracle은 크게 개선하지만 RGB-only가 실패 | **관측 부족/공유 bias의 한계 분석**으로 연구 방향 재설정 |
| D1 단일 scale만으로 대부분의 개선을 달성 | 복잡한 D4 구현 중단; scale/pose calibration 분석으로 피벗 고려 |

---

# 13. 실험 매트릭스와 결과표 서식

## 13.1 우선순위

| ID | 필수 | 목적 | 비교 | 필수 산출물 |
|---|---|---|---|---|
| **N0** | O | 환경/GT/재현성 점검 | 기존 B1, 저장된 E0~E4f | frozen manifest, file/pose checks |
| **N1** | O | 좌표계·자원 계약 점검 | raw vs active, self vs pair, Sim(3) | test log, common candidate IDs |
| **A0** | O | Pointmap × Pose factorial Oracle | A00/A10/A01/A11 | 4-arm table, error effect, interaction |
| **A1** | 조건부 | rotation/translation/scale 요인 분리 | P0/R/t/s/SE3/Sim3 | pose-scale error table |
| **A2** | 조건부 | local vs shared-bias 및 correction feasibility | fixed scale, depth variants, cross-view | residual hist, observability limits |
| **D0–D5** | GO-D 후 | RGB-only 선택적 Depth 보정 | raw, scale, geom, photo, selective | GT geometry/RGB/coverage, ablation |
| **P0–P3** | GO-P 후 | 제한적 Pose/Scale 개선 | original, existing backend, limited fix | metric pose/geometry comparison |
| **R0–R3** | 조건부 | Gaussian representation 통제 | fixed center, scale/cov, appearance | render-vs-geometry sensitivity |
| **F0** | O | 최종 신규 scene 검증 | A0 + 선택된 한 경로 | sealed results, negative cases |
| **F1** | 선택 | UAV/long sequence | original vs selected | domain limitation/runtimes |

## 13.2 A0 표(빈칸은 실험 후 입력)

| Scene | Arm | Common candidates | MAE depth ↓ | Correct coverage ↑ | Surface accuracy ↓ | Surface completion ↑ | Sample Chamfer ↓ | PSNR ↑ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| TBD | A00 estimated/estimated | | | | | | | |
| TBD | A10 GT-local/estimated | | | | | | | |
| TBD | A01 estimated/GT-pose | | | | | | | |
| TBD | A11 GT-local/GT-pose | | | | | | | |

## 13.3 Effect 분해 표

| Scene | Error metric | Δ local oracle | Δ placement oracle | Interaction | Alignment/mask version |
|---|---|---:|---:|---:|---|
| TBD | | | | | |

## 13.4 D 경로 표(조건부)

| Scene | Method | Adjusted pixels % | Mean correction magnitude | Depth MAE ↓ | Chamfer ↓ | Correct coverage ↑ | LPIPS ↓ | Extra ms/KF ↓ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| TBD | D0 raw | | | | | | | |
| TBD | D1 scale | | | | | | | |
| TBD | D3 photo | | | | | | | |
| TBD | D4 selective | | | | | | | |
| TBD | O-D oracle (diagnostic only) | | | | | | | |

---

# 14. 구현 구조 초안

과거 연구 코드에서 `raw candidate export`, `GT evaluation`, `TSDF/Chamfer`, `frozen map renderer`, `run manifest`와 기타 데이터를 재사용하고, 후보 pruning/admission 코드를 중심 경로에서 제외한다.

```text
research/
├── third_party/                         # upstream commit 고정
├── data_contract/
│   ├── pose_convention.py              # SE3/Sim3 저장·변환 규칙
│   ├── camera_geometry.py              # intrinsics, z-depth vs range
│   ├── candidate_registry.py           # frame/pixel/branch/anchor IDs
│   └── gt_alignment.py                 # one-time metric gauge
├── diagnostics/
│   ├── local_pointmap_error.py         # raw depth/pointmap 오류
│   ├── pose_scale_error.py             # trajectory/scale deviation
│   ├── shared_bias.py                  # common depth/pose perturbation
│   └── oracle_factorial.py             # A00/A10/A01/A11
├── correction/                          # A0 이후 조건부
│   ├── depth_global_scale.py
│   ├── depth_lowrank_field.py
│   ├── photometric_reprojection.py
│   ├── correction_gate.py
│   └── map_replacement.py
├── evaluation/
│   ├── depth_metrics.py
│   ├── map_surface_metrics.py
│   ├── rgb_metrics.py
│   ├── common_mask.py
│   ├── statistics.py
│   └── memory_runtime.py
├── experiments/
│   ├── configs/
│   ├── run_N0_N1.py
│   ├── run_A0_factorial.py
│   ├── run_A1_pose_scale.py
│   ├── run_A2_feasibility.py
│   ├── run_D_depth_correction.py       # conditional
│   └── run_final_sealed.py
├── tests/
│   ├── test_zdepth_range.py
│   ├── test_anchor_frames.py
│   ├── test_sim3_roundtrip.py
│   ├── test_pair_branch_gt.py
│   ├── test_oracle_factorial_independence.py
│   ├── test_common_masks.py
│   └── test_candidate_count_and_attributes.py
└── results/
    └── <experiment_id>/<scene>/<run_id>/
```

**주의:** 위 구조는 새 구현 제안이며 현재 저장소의 실제 디렉터리/CLI를 재현한 것이 아니다. 정확한 코드 삽입 지점·GPU patch는 repository 확인 후 확정한다.

---

# 15. 필수 단위시험·합성시험

1. **Known pinhole plane:** GT depth에서 만든 3D 점과 카메라 projection의 z 단위 검증.
2. **Z-depth vs Euclidean range:** 중심 광선 외에서 예상되는 range/z 차이를 계산하여 KITTI LiDAR와 혼동 방지.
3. **Sim(3) roundtrip:** scale≠1, arbitrary R/t; mean/covariance 왕복 및 rendering projection 검사.
4. **Branch reference:** 1번/2번 이미지 pixel의 GT depth가 올바른 anchor 좌표계로 옮겨지는지 확인.
5. **A0 no-leakage:** A10에서 pose 변수 hash가 A00과 동일한지, A01에서 raw local candidate hash가 A00과 동일한지 검증.
6. **Common-candidate invariant:** 네 Oracle arm에서 후보 개수/ID/opacity/SH/covariance hash 같음. mean/world placement만 차이.
7. **Unit gauge:** 단안 estimated world scale 하나를 일관되게 사용하고 frame-wise GT scale fitting이 발생하지 않는지 검사.
8. **Synthetic depth scale:** local depth만 일정 배율 오류일 때 A10만 해당 오류를 줄이는지 확인.
9. **Synthetic pose translation/rotation/scale:** 주어진 오차 하나만 투입한 경우 A01로 제거되는지 확인.
10. **Error interaction:** depth+pose perturbation을 함께 투입해 interaction 계산의 부호/해석 검증.
11. **Invalid GT:** sky/occlusion/mesh 밖/tracklet mask가 모든 비교군에서 동일하게 제외되는지 검사.
12. **Representation isolation:** geometry-fixed refiner-on/off가 A0 중심 오차로 잘못 해석되지 않는지 확인.
13. **No future/test leakage:** RGB-only correction은 결정 시점까지의 프레임만 사용, final-test GT query 없음을 로그 검증.
14. **Determinism/manifest:** 실행 순서, seed, scene hash, model commit의 반복 결과 일치/허용 편차 확인.

---

# 16. 16주 일정(조건부 분기 포함)

| 시기 | 주된 작업 | 완료 산출물 / Gate |
|---|---|---|
| **1–2주** | N0: 환경·코드 freeze, 기존 E0~E4f 재현, GT camera/depth time sync, 새 평가 scene shortlist | 원본 기준선, environment manifest, data split |
| **3–4주** | N1: branch/pose/convention, Sim(3) gauge, candidate hash, 공통 valid mask와 unit test | `N1_coordinate_contract.md`, 2×2 Oracle 시험 준비 |
| **5–6주** | **A0 strict self-branch**: GT local / GT pose factorial, 첫 신규 실내 scene | A0 4-arm table, interaction, 초기 Go/No-Go |
| **7주** | A0 다른 새 scene 반복 및 KITTI diagnostic 재구축(자원 허용 범위) | 장면별 분산·원인 요약, 최종 경로 선택 |
| **8주** | A1 또는 A2: 오류 유형/관측 가능성 조사, 강한 대조군 구현 정의 | correction feasibility note, 논문 제목/기여 방향 잠정 확정 |
| **9–10주** | **GO-D**: D1/D2/D3 구현 후 D4 최소판; **GO-P**: P1/P2 제약/Scale 분석; **R**: 표시/렌더 오류 진단 | 기존 방식 대비 1차 비교, stop 조건 |
| **11–12주** | 한 경로만 심화: 선택 정책/저차원 depth field 또는 제한 Pose/Scale alignment | ablation, held-out geometry/RGB, 비용 |
| **13주** | 봉인된 새 scene에서 재현, mask/gauge/threshold freeze | F0 결과표, success/failure cases |
| **14주** | KITTI/UAV 외부 domain 또는 long-sequence 제한 적용, 런타임 | F1 가능 범위, domain-specific limitations |
| **15주** | 통계·그림·오차 사례, 논문 방법/실험 초고 | final result matrix, reproducibility checklist |
| **16주** | 논문 집필·검토·수정 | 제출 원고(실험 결과에 맞춰 제목·기여 수정) |

**일정 중단 조건:** A0에서 통제 실패/GT 불일치가 지속되면 깊이 보정 개발에 착수하지 않는다. A0가 성공해도 RGB-only D/P가 강한 baseline을 넘지 못하면 복잡한 구현을 계속 확대하지 않는다.

---

# 17. 성공 가능성·실패 위험과 대응

| 주요 위험 | 왜 문제가 되는가 | 조치 |
|---|---|---|
| 두 이미지의 pointmap과 pose가 수학적으로 분리되지 않음 | A10 교체 자체에 relative pose oracle이 섞임 | **self-branch strict primary**와 pair secondary를 분리 |
| 단안 scale ambiguity | meter 오차나 Oracle effect가 잘못 계산될 수 있음 | 단일 global gauge, 별도 scale drift 보고 |
| GT calibration/시간동기 오류 | 원인이 없는 geometry error 생성 | 투영 unit test, sensor mask, reprojection sanity |
| GT depth와 estimated coverage 차이 | Oracle만 더 많은 표면을 포함하게 됨 | 공통 valid candidate ID, full map sensitivity 분리 |
| Shared model bias | 서로 다른 프레임에서도 같은 잘못된 평면을 지지 | RGB parallax/GT diagnostic, 보정 가능성 별도 게이트 |
| Pose·Scale·Depth 상호작용 | 한 요소의 오차가 다른 요소를 바꾸면 효과 착시 | factorial interaction, A1 sensitivity |
| Gaussian center 이동 후 covariance 불일치 | 렌더링/coverage 감소의 원인 혼동 | center-only vs covariance reinit 명확히 구분 |
| 기존 refinery 비활성 상태의 낮은 PSNR | geometry 개선을 appearance 문제로 잘못 해석 | no-refiner vs equal refiner-run sensitivity |
| Dynamic/sky/reflective | static depth GT가 잘 정의되지 않음 | mask 분리, 실패 유형 기록 |
| GPU 8GB 제약 | full scenes/4-arm 메모리 초과 | batch/chunk, subset QA→full, disk-backed map |
| 선행연구와 novelty 중복 | Depth/photo loss나 BA 그 자체는 새롭지 않음 | 원인 분해 계약 + 조건부 보정 순효과를 최소 주장 |
| 신규 scene 부족 | 개발 장면에만 유리한 결론 위험 | seal된 미노출 scene 확보 전 논문 효능 주장 금지 |

---

# 18. 논문 기여도와 연구 종료 기준

## 18.1 결과가 허용하는 잠정 기여 후보

1. **오류 원인 분해 프로토콜:** MASt3R-SLAM Pointmap, keyframe Pose/Scale, Gaussian 표현의 오류를 동일 후보 기반으로 비교하는 factorial Oracle 평가 체계.
2. **정량적 실패 조건:** source-shared depth bias, frame-level scale drift, low parallax 및 GT coverage 등의 조건에서 어느 오류가 지배적인지 정량화.
3. **조건부 보정 기법:** A0가 지지한 우세 오류 유형에서 제한된 RGB-only 보정이 강한 단순 대조군보다 실질적으로 낫다는 증거가 있을 때만 주장.
4. **재현 가능한 체계:** 8GB GPU 환경에서 사용 가능한 평가 도구, 데이터 계약, 단위시험과 negative results.

## 18.2 과장해서는 안 되는 주장

- '모든 Gaussian 이상점은 MASt3R Depth 오차 때문이다.'
- 'GT local geometry oracle 향상 = RGB-only Depth refinement 성능 향상.'
- 'Pose oracle 효과의 전부가 camera translation 오차다.'
- 'Gaussian center == GT surface' 또는 'center distance가 rendered geometry 정확도를 증명한다.'
- '단일 Replica/KITTI 개발 구간에서의 개선이 모든 드론 시퀀스로 일반화된다.'
- 'PSNR이 낮으므로 Pointmap이 잘못되었다'(appearance refinement 0의 설정을 무시한 주장).
- '분석만 수행하면 자동으로 새로운 알고리즘 논문으로서 충분하다.' (기존 평가에서 보이지 않은 원인·상호작용·진단법이 실제로 새 지식을 제공해야 함)

## 18.3 가능한 논문 결과 유형

- **Case A:** local Depth가 주원인 + 선택적 보정이 기존 photo/scale보다 성공 → 보정 중심 논문.
- **Case B:** pose/scale drift가 주원인 + 제한적 배치 보정 검증 → pose 중심으로 제목 수정.
- **Case C:** local과 pose의 interaction이 중요하고 실질적인 correction 순효과가 작음 → 엄격한 원인 분해/실패 분석 연구(기여도 추가 점검).
- **Case D:** A0 조차 실험적으로 분리하기 어렵거나 참조 데이터 불충분 → 현재 타당성의 NO-GO, 문제/데이터 재정의.

---

# 19. 지금 당장 할 일: 첫 A0 실험 체크리스트

- [ ] 기존 실험의 원본 체크포인트/환경/코드 버전과 추적 가능한 run manifest 보존.
- [ ] **새로운 GT 실내 scene 1개**를 선정하고 해당 scene의 카메라 내부·외부 파라미터, RGB, Depth, 표면 모델 확인.
- [ ] Splatt3R-SLAM에서 `raw self-branch pixel uv ↔ candidate_id ↔ Gaussian local mean ↔ anchor frame` 매핑 출력.
- [ ] 추정 Sim(3) pose를 읽어 metric aligned world로 내보내는 테스트 작성.
- [ ] `GT depth z`로 pixel unprojection → GT world projection 왕복 오차 확인.
- [ ] 네 A0 Arm 공통 후보 집합과 pose/pointmap 변수 해시 불변 조건 확인.
- [ ] Center-only 4-arm map을 작은 장면에서 생성하고 시각화.
- [ ] GT depth/surface metrics를 계산해 $\Delta_L$, $\Delta_P$, interaction 산출.
- [ ] A0 Go/No-Go 회의록에 '현재 확인된 오차'와 '다음 가설'을 구분해 기록.

---

# 20. 참조 자료 및 기존 산출물

## 20.1 실험 근거(이번 계획의 직접 출발점)

- `surface_guided_gaussian_mapping_experiment_summary.md`, 2026-10-22, §4–§7: E0~E4f 전체 결과·해석·미실행 작업·재사용 가능한 코드/GT 평가 자산.
- `surface_guided_gaussian_mapping_research_plan_v3.md`, 2026-10-14: 동일 후보 풀, source lineage, GT validity, scene-level statistics, 재현성·강한 대조군 원칙. **단, 이전 pruning 가설과 장기 admission 일정은 신규 실행 대상이 아님.**
- 개별 실험 보고서(E0/E1/E2/E3/E4/E4b/E4e/E4f) 및 실행 manifest: 새 실험의 코드·수치 검증에는 이 원자료를 우선 참조.

## 20.2 첨부 논문(기술 배경)

- Wang et al., *DUSt3R: Geometric 3D Vision Made Easy*.
- Leroy et al., *Grounding Image Matching in 3D with MASt3R*.
- Murai et al., *MASt3R-SLAM: Real-Time Dense SLAM with 3D Reconstruction Priors*.
- Smart et al., *Splatt3R: Zero-shot Gaussian Splatting from Uncalibrated Image Pairs*.
- Kerbl et al., *3D Gaussian Splatting for Real-Time Radiance Field Rendering*.
- Zhou et al., *GeoGS-SLAM: Geometry-Only Gaussian Splatting for Dense Monocular SLAM* (2026).
- Gao et al., *GeoGS-SLAM: Online Monocular Reconstruction Using Gaussian Splatting with Geometric Priors* (2026).

**최종 원칙:** A0 원인 분해가 보여 준 **실제 지배 오류**에 따라 연구 주제를 결정한다. `Depth를 수정하면 좋아질 것이다`는 현재 확정 사실이 아니며, `불필요한 Gaussian을 제거한다`는 이전 종료 주제의 가설을 새 계획으로 재도입하지 않는다.
