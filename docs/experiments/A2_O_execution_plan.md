# A2-O 실행 계획 — RGB 관측 가능성과 공유 편향 진단

작성: 2026-10-27 (Asia/Seoul).

**상태: PARTIAL_EXECUTION / PROFILE_IMPLEMENTED_NOT_EXECUTED / EVALUATION_NOT_EXECUTED.** 프로토콜·입력 QA·provenance 준비와 제한된 수치 검사는 수행했고 RGB profile/selection 코드도 구현했다. 새 구현을 등록하거나 coefficient profile을 계산하지는 않았다. 보정 지도 생성과 source/target geometry 평가도 수행하지 않았다. 상세 기록은 [부분 실행 보고서](A2_O_rgb_observability_results.md)다. 본 실행은 D/P 보정 알고리즘이나 joint optimizer 실행을 뜻하지 않는다.

직접 근거: [연구 계획 §6.3](../pointmap_pose_error_decomposition_research_plan_v1.md#63-a2-o--rgb-관측-가능성과-공유-편향), [A2-S 결과](A2_S_scalar_spatial_results.md), [A2-S 실행 규약](A2_S_execution_plan.md), [최신 경로 판정](A1_route_decision.md#a2-s-이후-경로-판정).

## 0. 범위와 실행 원칙

실행 순서는 **구현·합성 검사 → 입력 QA·등록 → office2 진단 → 개발 봉인 → office3 고정 검증 → 독립 재계산·보고**다. 이번 부분 실행은 provenance QA 뒤 RGB profile 단계 전에 멈췄다.

- Office2는 개발 장면, office3는 A1/V1/A2-S에서 이미 사용한 validation이다. Office3를 미사용 test 또는 새로운 독립 장면으로 표현하지 않는다.
- Office4는 봉인 상태로 유지한다. HKairport는 reference 미해결이므로 이번 범위에서 제외한다.
- 기존 RGB-only baseline, canonical local, final pose, lineage, gauge, A2-S 결과를 읽기 전용으로 재사용한다. 새 SLAM/네트워크 추론, 모델 학습, 후보 제거, appearance/covariance 최적화는 하지 않는다.
- 조사 대상은 **고정된 작은 변수 집합에서 RGB objective가 올바른 깊이 방향을 선택하는가**이다. 전역적인 관측 가능성 증명이나 새로운 보정 방법의 성능 검증이 아니다.
- 아래 수치·loss·basis·support 기준은 이번 계획에서 제안하는 사전 고정값이며, 검증된 최적값이 아니다. Office2 결과를 본 뒤 유리한 범위·loss·pair만 고르지 않는다.
- 실험 완료, RGB 방향 구별, target geometry 개선, D 경로 자격을 서로 다른 status로 기록한다. 과학적 FAIL/INCONCLUSIVE도 보고서까지 완성한다.

## 1. A2-S가 다음 질문을 바꾸는 이유

| A2-S 관측 | A2-O 설계에 반영할 사항 |
|---|---|
| Office2 fixed field는 target MAE를 줄였지만 scalar 충분성은 4 gauge/fold 중 1개만 통과 | Scalar와 작은 field를 모두 조사하되 field가 필요하다고 먼저 결론 내리지 않는다. |
| Office3에서 scalar는 target MAE를 악화했고 field도 S0 대비 target 이득을 입증하지 못함 | Office3에 개선 가능한 field가 있다고 가정하지 않는다. RGB loss 감소와 source/target geometry를 별도로 검증한다. |
| 두 장면 모두 opposite-tile source field 잔차는 감소 | Source 오차 감소만으로 target 일반화·보정 GO를 판정하지 않는다. |
| Source/target support는 두 장면 모두 통과 | A2-S support 통과를 RGB parallax/texture/lineage support 통과로 대체하지 않는다. |
| 모든 보정 계수는 source GT oracle | Sk/Sf 계수·방향을 RGB 후보 생성, mask, pair 선택, regularization에 넣지 않는다. |

주 질문은 다음 세 가지다.

1. **O1 방향 구별:** 충분한 baseline/parallax·texture·visibility 조건에서 RGB만으로 선택한 scalar/field가, 보지 않은 source tile·RGB 시점과 target geometry에서도 올바른가?
2. **O2 추가 자유도:** 같은 loss·mask·탐색 예산을 명시했을 때 작은 field가 강한 scalar/simple 대조군보다 추가 정보를 얻는가?
3. **O3 거짓 일관성:** 공유 depth bias, scale gauge ambiguity, pose 오류, 가림·동적 영역에서 낮은 RGB/geometry residual이 틀린 깊이를 지지하는가?

## 2. 데이터 계약과 GT 접근 경계

### 2.1 재사용 입력

| 입력 | 경로 / 규칙 |
|---|---|
| Office2 canonical local | `results/A1_U_scale_reparameterization/2026-10-26/construction/office2/manifest.json`의 KF 순서와 `local_file` |
| Office2 baseline / lineage | `results/A0_pointmap_pose_factorial/office2/baseline/`의 `run_manifest.json`, `exports/raw_pairs/`, `audit/events.jsonl`, 대응 final snapshot, KF export |
| Office3 canonical local | `results/V1_office3_diagnostic/2026-10-26/maps/local/`, `maps/manifest.json` |
| Office3 baseline / lineage | 같은 V1 root의 `baseline/` 아래 manifest·raw pair·audit·final snapshot·KF export |
| Gauge·S0 map·render cache | A2-S 입력 manifest와 scene별 map manifest가 가리키는 position/orientation S0. 경로를 새로 추정하지 않는다. |
| A2-S source split·결과 | `results/A2_S_scalar_spatial/2026-10-27/`의 등록 및 최종 채택 artifact. `amendments/attempt*`는 재사용 금지 |
| RGB·camera·평가 reference | `data/N2/Replica/{office2,office3}`, `cam_params.json`, `configs/n2_dataset_manifest.json`, N1 coordinate/mask 규약 |

Office2의 manifest `frame_id`는 subsample index이므로 원본 frame은 `2*frame_id`다. Office3 local의 `source_frame`은 이미 원본 번호이므로 두 배 하지 않는다. Raw pair의 이미지 ID도 baseline 입력 manifest를 통해 원본 frame으로 명시적으로 변환한다. 숫자가 같아 보인다는 이유로 다른 ID 체계를 혼용하지 않는다.

예상 native KF는 office2 11개, office3 8개이며 post-prefix source KF는 각각 10개, 7개다. Strict map 후보 수는 각각 1,200,827개와 855,796개다. H=288, W=512의 실제 모델 입력 RGB와 source pixel grid를 쓴다. 원본 JPG를 단순 resize해 대체하지 말고 baseline dataloader의 resize/crop 및 변환된 K를 재현·검증한다.

### 2.2 RGB 단계가 받을 수 있는 자료

RGB profile/선택 함수에는 RGB, 변환된 camera K, predicted canonical `y`, predicted `Q`, native validity/confidence, candidate ID, lineage만 전달한다. 실측 reference depth/mesh/pose, A2-S oracle 계수, reference-valid mask는 전달하지 않는다. 공용 adapter가 반환하는 `ref_z`, `ref_xyz`, `ref_valid`, `reference_replace`, GT 유래 `strict`를 RGB 함수에 그대로 넘기지 않는다.

RGB source 집합은 **native-active AND original_frame>=200**에서 시작한다. A2-S의 GT-derived strict mask로 RGB fitting pixel을 선택하지 않는다. Prefix KF는 RGB evidence로 사용할 수 있으나 correction source와 primary map에는 포함하지 않는다.

등록·입력 QA와 사후 평가만 reference 접근을 허용한다. RGB 선택 결과·mask·계수·hash를 먼저 봉인한 뒤 reference evaluator가 source GT와 400 target GT를 읽는다. Office3에서는 선택된 후보와 baseline의 geometry만 평가하며, GT로 주석 단 loss basin·gradient·전체 후보 오차 곡선을 만들지 않는다. **GT에 대한 basin/gradient 조사는 office2 및 synthetic에서만 수행**한다.

기존 canonical 단위와 gauge에는 prefix GT alignment가 포함돼 있다. 또한 최종 map 비교는 과거 GT-derived strict 후보를 유지한다. 따라서 이번 결과는 **기존 gauge·평가 support에 조건부인 RGB-only 계수 선택 진단**이다. 전체 파이프라인이 GT-free metric scale을 추론했다고 주장하지 않는다.

## 3. Source-disjoint pair와 두 종류의 holdout

### 3.1 이미지 provenance 검증

각 source KF k에서 실제 `y`의 ancestry를 추적한다. Raw self-branch이면 대응 `candidate_event`의 두 source image 집합을 사용한다. Fused geometry이면 실제 사용한 final revision의 fused image union을 쓴다. Evidence geometry에도 같은 규칙을 적용한다. 후보 event의 ancestry와 fused ancestry를 서로 바꿔 쓰지 않는다.

Pair k→j는 다음 모두를 만족해야 한다.

- 서로 다른 anchor image이며 두 geometry의 image ancestry 집합이 서로소다.
- Candidate event·KF·frame·final pose revision 대응이 검증되고 lineage status가 known/traced다.
- RGB 이미지도 각 geometry의 실제 anchor image와 일치한다.

같은 네트워크를 썼다는 사실은 독립성 근거가 아니다. 이미지 불공유도 통계적 독립이나 참조 정확성을 보장하지 않는다. Lineage 미상은 `UNKNOWN_PROVENANCE`, 불공유 위반은 `SHARED_SOURCE`로 제외하고 수를 공개한다. Pair가 부족하다고 공유 이미지를 허용하거나 새 inference로 채우지 않는다.

이번은 final revision을 쓰는 **offline 진단**이다. Evidence가 source보다 미래여도 쓸 수 있으나 online/causal 방법으로 표현하지 않는다.

### 3.2 Evidence 시점 split

각 source에 대해 source-disjoint인 기존 evidence KF 전부를 `(original_frame,kf_idx)`로 정렬한다. 정렬 위치 짝수는 RGB-fit, 홀수는 RGB-audit로 고정한다. Split은 overlap나 loss를 보기 전에 저장하며, 탈락한 pair를 반대 pool에서 보충하지 않는다. Fit/audit 각각 서로 다른 evidence 2개 이상이 필요하다. Evidence끼리 ancestry가 겹칠 수 있으므로 이 split을 네트워크 예측의 독립 재현으로 부르지 않는다.

이 분리는 source KF별이다. 같은 이미지가 다른 KF의 fit 역할로 사용될 수 있으므로 pooled global scalar Og의 audit를 전체 이미지 불공유 검증이라고 부르지 않는다. 엄격히 분리된 최종 측정은 기존 mapping 입력에 들어가지 않은 400 odd target이다.

GT가 아닌 S0 predicted geometry로 pair overlap·parallax·visibility를 계산한다. Pair 채택·탈락 사유를 전부 저장하며 가장 좋은 pair 몇 개를 사후 선택하지 않는다.

### 3.3 Source spatial split

A2-S의 `8×8` checkerboard 두 fold와 2pixel tile guard 규칙을 재사용하되, 그 위에 씌웠던 GT-valid/strict mask는 RGB 단계에서 제거한다. Fold0는 parity0 fitting / parity1 audit, fold1은 반대다.

**계수 선택:** source fitting tile × RGB-fit evidence만 사용한다. **RGB 일반화:** 반대 source tile × RGB-audit evidence에서 선택 계수를 그대로 평가한다. 같은 tile의 audit-view와 반대 tile의 fit-view도 보조로 저장해 공간 일반화와 시점 일반화를 구분한다. Source GT 평가는 선택 이후 반대 tile의 reference-valid 부분에서만 한다.

원본 odd frame `range(201,1000,2)`의 400 heldout target은 RGB fitting, pair 선택, threshold 조정에 전혀 쓰지 않는다. RGB audit evidence와 이 400 target은 별도의 집합이다.

## 4. 좌표·projection·mask 고정

각 gauge에서 기존 rigid placement Q를 고정하고 source point를 다음처럼 이동한다.

```text
y'_k(u) = exp(d_k(u)) * y_k(u)             # xyz 세 축을 함께 변경
X'_w = Q_k * y'_k(u)
p_j = inverse(Q_j) * X'_w
v_j = project(K_j, p_j)
```

Native KF scale은 다시 풀지 않는다. Position을 주 gauge, same-prefix orientation을 필수 sensitivity로 사용한다. 각 gauge에서 같은 RGB 규칙을 적용하며 유리한 gauge를 선택하지 않는다.

Evidence depth는 그 KF의 **예측 native pointmap**을 K로 z-buffer rasterize해 만든다. Confidence/validity도 함께 저장하며 빈 pixel을 보간해 채우지 않는다. Bilinear sample은 4개 이웃이 모두 valid일 때만 허용한다. Source RGB pixel과 `project(K_k,y_k)`의 오차가 1pixel을 넘으면 해당 source는 `RAY_GRID_MISMATCH`로 제외한다. 이 탈락률을 별도 보고해 calibrated-ray 가정이 범위를 바꾼 정도를 드러낸다.

다음 gate는 GT 없이 S0에서 정하고 저장한다.

| 항목 | 제안 고정값 |
|---|---|
| Confidence | 기존 native 기준 1.5 이상; 기존 active mask를 느슨하게 재생성하지 않음 |
| Source sampling | `(u mod 4==0) AND (v mod 4==0)`인 고정 grid; tile guard와 patch border 모두 적용 |
| Patch | Source 3×3 각 pixel의 자기 predicted 3D를 개별 warp; 중앙 depth를 patch 전체에 복제하지 않음 |
| Texture | Gray `[0,1]`의 3×3 patch std≥0.02, source와 S0-warp evidence 모두 충족 |
| Parallax | S0 world point에서 두 camera center로 향하는 ray의 각도≥1°가 primary |
| Baseline 보고 | gauge 단위 camera 간 거리 및 거리/source predicted depth 비율을 함께 저장 |
| Edge | 예측 인접 Z의 상대 jump>5% 또는 invalid 경계, 2pixel dilation 영역 제외 |
| Visibility | Positive Z, image 안쪽, valid evidence sample, `abs(z_projected-z_evidence)<=max(0.05m,0.05*z_evidence)` |
| Occlusion | Predicted z-buffer로 판정. GT visibility를 primary mask에 쓰지 않음 |

Mask 축소로 loss가 작아지는 것을 막기 위해 **같은 비교군의 모든 등록 후보에서 유효한 source patch 교집합**을 만든다. Scalar/field/simple 대조 비교군은 같은 공통 mask를 쓴다. 후보에 따라 patch가 밖으로 나가거나 가려지면 해당 후보만 분모에서 빼지 않고, 비교군 전체에서 제외한다. 이 mask 생성도 RGB/prediction만 사용하며 hash를 저장한다. §6의 두 단계 규칙으로 scalar seed를 먼저 고정해 candidate/mask 정의의 순환을 피한다. Fit mask는 fit tile×fit evidence만으로, audit mask는 audit tile×audit evidence만으로 각각 만든다. Audit mask나 loss를 보고 fit mask·계수를 다시 만들지 않는다. Pose perturbation 비교는 별도의 paired common mask를 만들어 base pose도 그 mask에서 재평가한다.

이 규칙은 보수적이며 잘못된 S0 visibility가 올바른 correction까지 제외할 수 있다. S0 mask 대비 공통 mask 유지율과 제외 사유를 공개하고, synthetic의 true-visibility **사후 audit**로 이 편향을 계량한다. True visibility로 primary 선택을 재실행하지 않는다.

Parallax `[0,0.25),[0.25,1),[1,3),[3,∞)`도 모두 별도 집계한다. 낮은 parallax·낮은 texture는 관측 한계 대조이지 제거해서 숨길 실패가 아니다.

## 5. RGB objective와 simple 대조 objective

RGB는 실제 `[0,1]` 입력 값을 쓰고 exposure/색상 계수는 fit하지 않는다. Gray 가중치는 `(0.299,0.587,0.114)`다. 각 유효 3×3 patch에서 다음을 계산한다.

```text
l_photo = 0.85 * (1 - ZNCC(gray_source, gray_warp))/2
          + 0.15 * mean(abs(RGB_source - RGB_warp))
```

ZNCC는 `[-1,1]`로 clip하고 분모 epsilon=1e-12를 쓴다. 고정 mask의 source/evidence는 S0 texture gate를 통과해야 한다. Correction 후 분산이 작아졌다고 sample을 제거하지 않는다. 결과가 상수 patch이면 위 epsilon 규칙으로 loss를 계산한다. L1-only와 ZNCC-only 곡선은 office2 보조 진단으로 저장하되 primary objective를 바꾸는 데 쓰지 않는다.

Pair 안에서는 patch 동등 가중, KF 안에서는 evidence pair 동등 가중, scene에서는 source KF 동등 가중이다. Pixel 수가 많은 KF가 결론을 지배하지 않게 한다. Missing loss는 null이며 0으로 채우지 않는다. Photo objective에 predicted-depth agreement, GT, A2-S field 계수, regularization을 섞지 않는다. 제한된 grid 자체가 이번 진단의 correction 범위다.

Geometry-only scalar 대조는 같은 후보·pair·mask에서 `Huber(log(z_projected/z_evidence), delta=0.05)`를 최소화한다. Evidence depth는 예측값이며, 이 residual 감소를 정답의 증거로 취급하지 않는다. RGB-only와 geometry-only 선택 결과를 별도 arm으로 남긴다.

## 6. Scalar 및 고정 작은 field의 loss profile

### 6.1 후보 집합: GT와 무관하게 생성

- **Scalar:** `d(u)=a`, `a = -0.20 + 0.01*n`, n=0..40. 0을 정확히 포함한다.
- **Field:** A2-S와 같은 4×4 bilinear node basis B를 사용한다. Node 위 orthonormal DCT-II의 DC를 제외한 15개 mode를 `(p,q)` 사전순으로 고정한다. 각 mode는 16node mean=0, RMS=1로 정규화하고 부호는 첫 nonzero node가 양수가 되도록 정한다.
- 먼저 41개 scalar의 공통 fit mask에서 RGB seed `a_seed`를 선택한다. 이 단계에는 audit pixel·시점을 쓰지 않는다.
- Seed를 고정하고 `d(u)=a_seed+b*(B(u)@v_m)` 후보를 생성한다. `b=-0.10+0.01*n`, n=0..20, mode m=1..15다. 41개 scalar와 315개 field 후보의 공통 fit mask를 새로 고정한 뒤 **그 mask에서 scalar도 다시 선택**한다. 최종 scalar를 Ok로, 전체 356개 중 photo 최소를 Of1로 둔다. Of1이 scalar를 고르면 mode=DC로 기록한다.
- 최종 Ok가 seed와 달라도 field를 다시 중심 이동시키지 않는다. Seed·scalar-only mask·최종 공통 mask를 모두 저장한다. 따라서 최종 비교는 같은 mask·loss를 사용하며 candidate 생성은 두 단계로 완결된다.
- 동률은 loss 차이≤1e-8로 정의한다. Scalar는 `abs(a)`가 작은 후보, 그다음 수치가 작은 a를 선택한다. Field는 `abs(b)`가 작은 후보, mode 순서, 수치가 작은 b 순으로 선택한다.
- Scalar와 field의 loss가 동률이면 scalar를 우선한다. 같은 node field를 만드는 중복 후보(예: b=0)는 하나의 correction으로 취급하며, 단순 parameter 중복을 다중 최소로 세지 않는다.
- RGB loss가 낮아지는 방향을 GT field 방향으로 정의하지 않는다. GT에 맞춘 mode, amplitude, candidate 추가는 금지한다.

이는 **16-node field의 사전 고정된 1차원 slice들**이다. 16변수 full optimum이나 모든 deformation의 관측 가능성을 평가하지 않는다. Profile boundary에서 최소면 `SEARCH_BOUNDARY`로 표시하며 범위를 사후 확대하지 않는다.

### 6.2 필수 비교 arm

| ID | 선택 자료 / 역할 |
|---|---|
| O0 | S0 그대로; correction=0 |
| Og | RGB-fit만으로 모든 supported KF에 공유할 global scalar. KF 등가중 pooled photo grid 최소 |
| Ok | KF별 RGB scalar grid 최소 |
| Gk | 같은 scalar grid의 geometry-only 최소; 공유 편향을 갖는 simple 대조 |
| Of1 | 고정 seed 주위 15mode×21amplitude와 scalar 후보 중 photo 최소 선택; 최대 한 공간 mode, 추가 반복 없음 |
| Sk, SkH, Sf | 기존 A2-S 최종 oracle map을 사후 참조. RGB 후보·계수·mask를 만드는 데 쓰지 않음 |

주 비교는 `O0/Ok/Of1`, 강한 simple 비교는 `O0/Og/Ok/Gk/Of1`이다. Of1의 후보 평가 횟수가 더 많다는 사실을 보고한다. Of1의 fit loss 감소만으로 추가 정보를 얻었다고 주장하지 않고, 반대 tile·audit 시점·target으로 확인한다.

각 fold·gauge에서 독립적으로 선택한다. Global Og는 최종 공통 **fit support**를 통과한 KF들만 pooling하며 미지원 KF에 전파하지 않는다. Audit support에 따라 pooling·계수를 다시 계산하지 않는다. 지원 KF가 하나도 없으면 Og도 null이다. Scalar는 지원되지만 field가 미지원인 KF의 scalar-only 보조 표를 별도로 남기고 primary 공통 집합에 섞지 않는다.

### 6.3 Development에 한정한 basin·gradient 진단

Office2와 synthetic에서만, 먼저 모든 RGB 선택을 저장한 뒤 각 고정 후보의 opposite-tile reference Z MAE `E(a,b)`를 계산한다. Photo와 reference는 같은 source 위치의 reference-valid 교집합에서 추가로 paired 계산해 비교한다. GT mask로 재계수를 선택하지 않는다.

- 원점 주변 scalar와 각 field mode에서 central difference h=0.01의 photo gradient와 GT-error gradient를 구한다. Field 원점은 RGB seed `a_seed`다.
- `grad_photo * grad_error > 0`이면 해당 축의 negative photo-gradient가 오차 감소와 국소적으로 정렬한다. 음수는 반대, gradient 절댓값≤1e-6은 `FLAT_OR_UNRESOLVED`다.
- 같은 고정 후보에서 RGB 선택의 source MAE와 사후 GT 최선의 차이(regret), 선택 amplitude 부호, boundary 최소, local minima 수를 저장한다. 이 GT 최선은 **등록 grid 안의 사후 참조**이며 보정 arm으로 채택하지 않는다.
- Profile 평탄성은 `max(J)-min(J)<=1e-4`, RGB 선택이 O0/Ok 대비 1e-4 이하 개선이면 `NO_RESOLVED_PHOTO_GAIN`으로 기록한다. 연속적인 basin width는 grid 해상도 0.01 이하로 추정하지 않는다.

Office3는 동일 grid를 **RGB inference 규칙**으로 실행할 수 있지만 GT 후보 곡선·GT gradient·GT 최적 후보를 만들거나 office3에 맞춰 다시 선택하지 않는다.

## 7. Control matrix: 잘못된 정답을 지지하는 경우

### 7.1 Synthetic scene과 정보 분리

외부 asset 없이 고정 seed0의 작은 analytic renderer를 만든다. H=288/W=512, fx=fy=400, cx=255.5/cy=143.5, 깊이 2/4/8m의 정면·경사 평면, 앞쪽 가림 사각형, 비주기 texture/반복 texture/상수 texture를 사용한다. Camera translation baseline은 0/0.001/0.1/0.4m로 고정하고 pure rotation도 포함한다. 실제 pose와 clean depth는 generator 및 사후 evaluator만 보유한다.

각 control의 예상 거동, 부호와 오차 허용 범위를 구현 시 JSON에 먼저 기록하고 synthetic 결과를 보기 전에 등록한다. Synthetic 실패를 실제 scene의 threshold를 바꾸는 근거로 쓰지 않는다. 필수 positive sanity는 textured·static·visible·0.4m baseline에서 ±0.10 scalar 주입의 inverse correction을 0.01 grid 한 칸 이내로 회복하는 것이다. Rasterization 때문에 이를 못 맞추면 real 실행 전에 구현/fixture 원인을 밝힌다.

| Control | 고정 주입 | 확인할 실패 / 해석 |
|---|---|---|
| Clean / no-op | Bias 없음 | 0 부근 최소와 source/evidence projection·loss parity |
| Source-only scale | `D'_k=exp(e)*D_k`, e=±0.05, ±0.10 | Corrective sign과 scalar 회복; 충분한 parallax의 positive control |
| Piecewise scale | 영상 좌/우에 `exp(+0.10)` / `exp(-0.10)` | Scalar 이후 residual, 작은 smooth field의 표현 한계; 경계는 별도 집계 |
| Additive depth bias | `D'=D+b`, b=±0.05/±0.10m | Multiplicative scalar가 모든 depth bin을 설명하지 못하는 상황 |
| Shared depth bias | 모든 source/evidence에 같은 e 또는 additive b, **pose baseline은 고정** | 같은 모델의 depth agreement가 틀릴 수 있는지; RGB가 구별하는지 별도 검사 |
| Joint scale gauge | 모든 depth와 camera translation에 같은 exp(e), e=±0.10 | RGB 재투영 불변, metric depth는 달라짐. 절대 scale 관측 성공으로 처리하면 구현 오류 |
| Rigid pose error | Evidence relative pose에 각 축 translation±0.02m 또는 rotation±1°를 하나씩 주입 | Depth field가 pose 오차를 흡수해 photo만 줄이는지 |
| Occlusion | 앞쪽 사각형으로 뒤 평면을 가림 | Predicted visibility 누락·false correspondence; true-visibility는 사후 audit만 |
| Dynamic region | Evidence RGB의 고정 중앙 20% 폭 영역을 x축 +8pixel 이동, geometry는 유지 | 정적 warp 가정 위반에서 거짓 depth 선택. 사용한 영역 mask는 evaluator만 접근 |
| Low texture / repeated texture | 상수 또는 주기 8pixel texture | 평탄한 objective와 다중 최소를 깊이 정답으로 혼동하는지 |

서로 다른 주입은 우선 one-factor-at-a-time으로 수행한다. 필수 결합은 shared scale+pose scale과 pose error+source scale 두 종류다. Synthetic 주입 amplitude를 현실 장면의 실제 오류 크기로 해석하지 않는다.

### 7.2 실제 데이터의 depth-only / pose nuisance 분리

Real primary는 predicted Q 고정의 depth-only arm이다. 별도 nuisance arm에서 relative transform `T_jk=inv(Q_j)Q_k`에 evidence-camera 좌표의 perturbation을 left-multiply한다. 3 translation축 ±0.02m, 3 rotation축 ±1°의 12개와 identity를 고정한다. Source와 evidence를 함께 움직이는 global gauge 변화와 혼동하지 않는다.

Office2에서는 scalar×13pose의 표를 만들고, baseline pose에서 RGB가 선택한 Of1 mode의 amplitude profile도 같은 13pose에서 조사한다. Mode를 pose마다 다시 탐색하지 않는다. Of1이 scalar를 선택했다면 scalar 표만 만들고 공간 mode는 N/A로 남긴다. Photo 최선 depth가 어떻게 이동하는지와 그때의 reference 오차를 사후 비교한다. 이것은 nuisance sweep이며 pose를 추정하거나 joint optimizer로 채택하지 않는다.

Office3에서는 봉인된 Ok/Of1 계수를 그대로 두고 13pose의 RGB audit 민감도만 평가한다. GT gradient나 perturbation별 GT 최선 depth를 찾지 않는다. 실제 장면의 가림·동적 pixel에 GT label을 새로 붙여 primary mask를 개선하지 않는다.

## 8. Support와 평가 지표

### 8.1 RGB support는 별도로 판정

Grid sampling·공통 mask 이후 각 pair/fold에서 fit/audit 해당 tile의 유효 patch center≥256개 및 S0 eligible center의≥50%를 요구한다. Field 주 비교에는 fit/audit 각각 총 center≥1,024개, 4×4 각 공간 구역 center≥16개, fit design `B.T@B`의 eigenvalue ratio≥1e-8을 추가한다. 각 source는 fit/audit evidence 각각 통과 pair≥2개여야 한다.

Scene-level RGB 판정에는 post-prefix KF의≥80% 및 그 KF에 속한 native post-prefix 후보의≥80%가 지원돼야 한다. 두 분모와 strict-map 후보 지원율도 함께 보고한다. 미지원은 0 gain이 아니라 null/reason이며, partial 결과는 조건부 기술 통계로 남긴다.

미지원 KF의 지도 중심은 O0 그대로 둔다. Primary 공통 대조에서는 모든 arm에 같은 KF apply-mask를 사용한다. 별도의 scalar-only support 표는 이 공통 비교와 분리한다. 완전 지원된 일부 KF만으로 scene 전체 관측 가능성을 선언하지 않는다.

### 8.2 Source와 RGB audit

- Fit photo, 반대 tile×audit-view photo, L1/ZNCC component, pair/patch 수, common-mask 유지율, 선택 a/mode/b, boundary/flat 여부.
- 반대 tile의 공통 reference-valid 위치에서 Z MAE/AbsRel/log-residual median·MAD. Native RGB fit과 GT 평가 분모를 따로 기록한다.
- KF 단위 효과, parallax·texture·baseline/depth·depth bin별 결과, 실패 pair와 lineage 탈락 수. 효과가 좋은 bin만 결론에 사용하지 않는다.
- Office2에서만 gradient alignment·grid regret·pose nuisance 표. Office3에는 선택 후보의 paired 개선 여부만 기록한다.

### 8.3 Heldout target geometry와 지도 보존

선택 계수를 봉인한 뒤, 기존 strict packed S0를 복사하고 지원 KF의 중심 `[:, :3]`만 바꾼다. 후보 ID·순서·수, `[:,3:]`의 covariance/RGB/opacity는 bitwise 동일해야 한다. Q와 covariance를 correction에 맞춰 재fit/재scale하지 않는다.

두 gauge×두 fold×두 scene에서 target 400뷰 전부를 평가한다. Target pose는 **raw GT camera-to-world를 평가에만 사용**한다. 이미 정렬된 지도에 맞춘다고 alignment를 target pose에 다시 적용하지 않는다.

필수 비교군은 다음과 같다. 각 군의 MAE 차이는 같은 view·같은 공통 pixel에서만 계산한다.

1. Primary common3: `O0+Ok+Of1`.
2. Simple common5: `O0+Og+Ok+Gk+Of1`.
3. Oracle context common6: `O0+Ok+Of1+Sk+SkH+Sf`. 기존 A2-S 표와 mask가 다르므로 그대로 숫자를 빼지 않는다.
4. Gauge paired common6: position/orientation 각각의 `O0+Ok+Of1`.

Target 지표·threshold는 A2-S와 동일하다. GT-valid interior, covered `weight>0.001`, correct depth `abs(error)<=max(0.05m,0.02*GT)`, view MAE 동등 가중, reference 분모의 coverage/correct coverage, depth bins `[0.1,1,2,4,10]`을 기록한다. 전체400뷰의≥80%에서 common≥1,000pixel AND interior reference의≥50%를 충족해야 target support PASS다.

Own-covered MAE와 전체 reference correct coverage를 함께 보고한다. Error가 낮아져도 coverage loss로 얻은 결과면 별도로 표시한다. Correct coverage 감소 허용폭은 1%p, interior coverage 비교 허용차는 1e-6이다.

Position gauge의 O0/Og/Ok/Gk/Of1은 고정 20뷰 `range(201,1000,40)`의 관측영역 TSDF도 비교한다. A2-S의 **GT-depth TSDF reference** 및 4cm voxel/12cm truncation/10m max depth/100,000 samples/seed0/5cm tolerance를 재사용한다. Reference hash를 확인하며 rendered S0 surface로 대체하지 않는다. RGB/depth/error 시각화는 `[201,401,601,801,999]`에서 저장한다.

Scene끼리 합친 평균, pixel/view를 독립 시행으로 취급한 p-value, 두 scene만으로 만든 일반화 CI는 제시하지 않는다.

## 9. 사전 고정 판정과 다음 경로

다음은 개발 의사결정 gate이며 통계적 유의성 기준이 아니다. Source/RGB/target support가 먼저 통과해야 한다.

| 상태 | 판정 규칙 / 처리 |
|---|---|
| `INSUFFICIENT_RGB_SUPPORT` | Lineage·pair·texture/parallax·공통 mask·KF 기준 미달. 관측 실패와 구별하고 부족한 조건을 명시 |
| `FLAT_OR_AMBIGUOUS` | 충분한 support에서도 photo 범위≤1e-4, 동률 최소가 여러 방향에 있거나 선택이 boundary. 더 큰 optimizer 근거로 쓰지 않음 |
| `PHOTO_GEOMETRY_MISMATCH` | Photo는>1e-4 감소하지만 opposite-tile source 또는 target MAE가 악화. 작은 RGB loss를 보정 성공으로 보고하지 않음 |
| `POSE_DEPTH_CONFUSION` | Synthetic/office2에서 pose perturbation을 깊이로 흡수해 photo 감소와 GT 개선 방향이 분리됨. 확인된 조건을 함께 보고 |
| `SHARED_BIAS_LIMITATION` | Shared-bias control에서 잘못된 geometry agreement/최소가 유지되거나 joint scale ambiguity가 검출됨. 절대 scale·정확성 주장 제한 |
| `RGB_DIRECTION_SUPPORTED` | KF의≥80%에서 선택 후보가 반대 tile×audit-view photo를>1e-4 줄이고, 같은 반대 tile GT MAE도 감소. Scene source 평균 MAE도 감소. 두 fold 모두 충족해야 scene label 부여 |
| `TARGET_EFFECT_SUPPORTED` | 같은 target common mask의 O0 대비 MAE≥10% 감소, interior coverage 보전 및 correct coverage 감소≤1%p, 양 fold에서 충족. Gauge sensitivity·surface와 효과 방향이 모순되지 않아야 함 |
| `SCALAR_PREFERRED` | Common3에서 field의 O0 대비 gain이 양수·≥10%일 때 `(E0-Ek)/(E0-Ef)>=0.90`이고 양 fold·coverage 조건 충족. Field 추가 개발 근거를 보류 |
| `FIELD_INCREMENT_SUPPORTED` | Of1이 simple common5에서 **각** Og/Ok/Gk보다 MAE≥10% 낮고, O0 대비≥10% 낮음. RGB audit/source GT/target·coverage·surface가 지지하며 두 fold·두 gauge에서 방향 유지 |
| `CONDITIONAL_OR_INCONCLUSIVE` | Fold/gauge/scene 불일치, oracle 기회 미성립, 또는 gate 충돌. 좋은 조건만 선택하지 않음 |

`RGB_DIRECTION_SUPPORTED`의 비율 분모는 전체 등록 post-prefix KF이며 미지원 KF를 성공 분모에서 빼지 않는다. Og/Ok/Of1별로 별도 판정한다. `FIELD_INCREMENT_SUPPORTED`의 10%는 이번 계획의 보수적 추가 자유도 기준이다. 미달이면 field가 무의미하다는 보편적 결론을 내리지 않는다.

Office3에서 기존 Sf의 target 이득이 없었다는 사실을 그대로 유지한다. 새 RGB 후보가 더 좋은 결과를 내더라도 Sf를 공간 보정의 수학적 상한으로 해석하지 않으며, A2-S가 재현됐다고 소급 변경하지 않는다.

**D 경로 검토 자격**은 다음 모두를 필요로 한다: 합성 positive/negative control 정상 작동, 두 scene의 방향 구별·target 효과, scalar 이후 추가 field 이득, gauge/coverage/표면 대조, pose/shared-bias 제한 공개, 연구 계획 §12 및 별도 문헌 중복 검토. 이 실험만으로 D4나 joint optimizer를 자동 실행하지 않는다. 이번 A2-O의 최선 결과도 우선 D1/D3 최소 대조 구현의 검토 자격이다.

Oracle만 좋고 RGB가 실패하면 관측 한계 분석으로 남긴다. Scalar가 대부분 설명하면 단순 scale 경로를 우선 검토하되 P 알고리즘의 GO로 바꾸지 않는다. Office2만 성공하거나 office3 source/target mismatch가 반복되면 scene 조건부 결과로 종료한다.

## 10. 구현 파일·실행 순서

### 10.1 새로 만들 파일

| 파일 | 책임 |
|---|---|
| `configs/a2_o_rgb_observability_protocol.json` | 본 계획의 scene/split/grid/loss/mask/control/gate를 기계 판독 가능하게 고정 |
| `src/rgb_observability.py` | Projection·patch loss·고정 mask·grid 선택·DCT mode·판정. Reference I/O와 분리 |
| `scripts/a2_o_common.py` | Native RGB-only adapter, frame/lineage 검증, 별도의 reference 평가 adapter |
| `scripts/run_a2_o.py` | 단계 CLI와 manifest/봉인/재개 검증 |
| `tests/test_rgb_observability.py` | 누출·좌표·합성·판정 검사 |
| `docs/experiments/A2_O_rgb_observability_results.md` | 실행 상태, 두 scene 전체 결과, 실패와 제한 |
| `configs/a2_o_results_summary.json` | 관측 방향·target 효과·추가 field 효과를 분리한 요약 |

출력은 `results/A2_O_rgb_observability/<실행 시작일>/`이다. Asia/Seoul 기준 시작일을 한 번 고정하고 자정을 넘어도 바꾸지 않는다. 아래 명령은 **미구현 CLI 계약**이다.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_rgb_observability.py'
.venv/bin/python scripts/run_a2_o.py preflight --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py register --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py controls --config configs/a2_o_rgb_observability_protocol.json
```

Preflight는 두 scene의 파일/hash/shape/lineage/frame/입력 grid만 확인한다. RGB profile이나 correction 성능을 계산하지 않는다. 등록 시 md/protocol/code/helpers/tests/seed, camera/resize, native masks, lineage, source/evidence/tile split 규칙, 입력 및 A2-S artifact hash를 copy/hash로 고정한다. Controls의 예상 판정도 포함한다.

다음 단계를 **office2에서 먼저** 모두 수행한다.

```bash
.venv/bin/python scripts/run_a2_o.py prepare --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py profile --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py freeze-selection --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py evaluate --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py verify --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py seal --scene office2 --config configs/a2_o_rgb_observability_protocol.json
```

- `prepare`: GT-free pair·split·S0/scalar mask와 정확한 center index/hash 저장.
- `profile`: fit tile×fit evidence만으로 seed → 최종 candidate 공통 mask → scalar/field/simple 선택. Audit 결과를 계수 선택에 쓰지 않음.
- `freeze-selection`: 모든 arm의 계수·support·입력/code/config hash 봉인. 이후 evaluate에서 재선택 금지.
- `evaluate`: RGB audit → source GT 사후 평가 → map build →400 target·surface 평가. Office2만 추가 GT profile/gradient와 pose nuisance 분석.
- `verify`: 별도 cache 재계산으로 선택 argmin/동률 규칙, common mask, support, geometry/coverage 판정 검증.
- `seal`: code/protocol/controls/office2 결과/amendment를 고정. Office2 결과에 따른 parameter 탐색은 하지 않음.

Office3 시작 시 seal hash 일치와 `validation_registration.json`을 확인한 뒤 같은 `prepare → profile → freeze-selection → evaluate → verify`를 실행한다. Office3 evaluate는 §2.2의 GT 후보 곡선 금지를 강제한다. 마지막에 `report`로 통합 결과·manifest를 작성한다.

RGB profile/selection 구현은 `scripts/a2_o_profile.py`에 있다. 앞선 provenance-only registration과 코드를 섞지 않도록 새 구현을 사용하기 전에 `register-profile`로 별도 code snapshot을 만든다. Profile은 고정된 raw self-branch pair split에서 fit pool만 사용하고 reference/GT 필드를 허용하지 않는다. 결과는 `profile_selection_v2/` 아래 `profiles.csv`, exact fit-mask index와 manifest, `selected_parameters.json`에 저장한다. `freeze-selection`은 선택과 입력/code/protocol hash를 `selection_seal.json`에 봉인한다.

```bash
.venv/bin/python scripts/run_a2_o.py register-profile --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py profile --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py freeze-selection --scene office2 --config configs/a2_o_rgb_observability_protocol.json
```

GT source 평가를 숨기고 400 target만 늦게 여는 것으로 충분하지 않다. **모든 GT 성능 평가보다 RGB 선택 봉인이 먼저**여야 한다. Hash가 같지 않은 partial 결과를 resume하지 않는다.

## 11. 필수 검사와 실패 처리

필수 검사는 구현을 그대로 복제하는 것보다 다음 실제 실패를 검출해야 한다.

1. 두 장면의 frame 번호·candidate event·anchor RGB·final snapshot 대응. Raw/fused ancestry 혼동, 공유 이미지와 unknown lineage 거부.
2. Source/evidence identity warp, 알려진 translation의 pixel 이동 방향, crop/resize K, source ray-grid mismatch 검출.
3. GT depth/pose/validity/Sk/Sf를 바꾸거나 reference loader를 호출 불가로 만들어도 RGB pair·mask·loss·계수 hash 불변.
4. KF별 Ok/Gk/Of1에서 RGB-audit evidence와 opposite-tile source RGB 값을 바꿔도 fitting 선택 불변. Og는 전체 pooled fit 입력을 고정한 상태에서 audit 경로의 변경이 재선택을 유발하지 않음. Target RGB/GT 변경도 선택에 영향 없음. Patch가 tile guard를 넘어 새지 않음.
5. 후보별 image-outside/occlusion/low variance에서 분모가 몰래 달라지지 않음. 공통 mask 축소·null·미지원 이유 정확성.
6. Scalar grid의 0 포함과 동률 선택, 15 DCT mode의 node mean/RMS/상수 직교성, bilinear 행 합=1.
7. Synthetic scalar 회복 positive와 pure rotation/low texture/joint scale ambiguity negative. 가림·동적 영역이 정답 support로 둔갑하지 않음.
8. Pose-only 오류가 photo gain을 내더라도 GT 악화면 성공 판정하지 않음. Field가 scalar와 같거나 미개선일 때 ratio를 오용하지 않음.
9. Correction의 ray 보존, Q 고정, unsupported S0 보존, packed covariance/RGB/opacity·후보 순서 bitwise 불변.
10. S0 고정 5뷰 replay: covered mask 불일치=0, 공통 depth 최대 차이≤0.002m. Alignment 중복 적용 negative 검출.
11. Office3에서 GT profile/gradient API 호출 거부, seal/protocol/hash mismatch 거부, reference TSDF hash 검증.

Python은 `.venv/bin/python`, 검사는 `unittest`를 사용한다. 기존 패키지·GPU renderer를 재사용하며 새 패키지/모델 다운로드를 전제로 하지 않는다. 실제 GPU 접근이 필요하면 환경의 실행 권한 절차를 따른다. Grid·patch 계산은 chunk 처리하고 map은 한 번에 하나만 GPU에 올린다. `torch/cv2` thread=2, renderer TF32=False를 유지한다. Runtime, peak VRAM, 전체 후보 평가 수와 fresh/reused map-view 수를 기록한다.

구현 실패는 원 출력·원 code hash·실패 로그를 보존하고 amendment를 쓴 뒤 수정한다. Mask/loss/grid/threshold/scene scope를 바꾸면 과학적 protocol 변경으로 등록하며 office2부터 영향 범위를 다시 실행한다. Office3를 이미 봤다면 그 사실과 validation 손상을 공개한다. 기존 등록·A2-S 결과를 덮어쓰지 않는다.

## 12. 산출물과 완료 조건

최소 artifact는 다음과 같다.

- `registration.json`, `preflight.json`, `registered_code/`, `controls/{specification,results}.json`.
- Scene별 `pair_manifest.csv`: ancestry, 원본 frame, fit/audit pool, pose revision, pair support와 탈락 이유.
- `masks/`와 `mask_manifest.json`: native/GT 평가 mask 구분, sampled patch index, tile/evidence 분할, 후보 공통 교집합 hash와 유지율.
- `profiles.csv`, `selected_parameters.json`, `selection_seal.json`: RGB/geometry loss, a/mode/b, 동률·boundary·지원 상태. Office3 profiles에는 후보별 GT metric이 없어야 함.
- `rgb_audit.csv`, `source_geometry.csv`, office2 전용 `direction_profiles.csv`, `pose_nuisance.csv`, `synthetic_controls.csv`.
- `maps/manifest.json`, `target_methods.csv`, `target_coverage_bins.csv`, `simple_controls.csv`, `gauge_pairs.csv`, `surface_metrics.csv`, 고정 시각화.
- `development_seal.json`, office3 `validation_registration.json`, `verification.json`, `execution_manifest.json`, 결과 md와 machine-readable summary.

최종 보고서에서는 **실행 상태 → RGB support/선택 → RGB audit와 source geometry → 같은 mask의 target 결과 → scalar/simple/field 비교 → pose/shared-bias/control 실패 → scene별 판정·다음 경로** 순서로 쓴다. RGB loss 단위와 depth MAE(m)를 같은 점수로 합치지 않는다.

- [ ] 등록 전 GT-free adapter·source-disjoint·split·control·수치 규칙 확정.
- [ ] 합성 positive와 negative를 통과하고 office2 완료·개발 seal 뒤 office3 고정 검증.
- [ ] 모든 scene/gauge/fold/arm과 실패·null·지원 분모 공개.
- [ ] Source 개선과 target 일반화를 구분하고 field는 강한 scalar/simple 대조와 비교.
- [ ] A2-S의 source/target mismatch를 보존하고 새로운 결과로 소급 덮어쓰지 않음.
- [ ] Cache에서 독립 재계산한 검증, amendment, 정확한 명령·시간·환경·hash 저장.
- [ ] 실제 실행 완료 후에만 연구 계획·경로 판정에 A2-O 결과 추기.
- [ ] Office4 봉인, HK reference 미해결 유지. D/P 및 joint optimizer 자동 착수 없음.

**완료의 기준은 좋은 RGB minimum을 찾는 것이 아니라, 어떤 조건에서 RGB가 실제 geometry 개선 방향을 구별했고 어떤 조건에서 실패했는지를 재현 가능한 형태로 남기는 것이다.**
