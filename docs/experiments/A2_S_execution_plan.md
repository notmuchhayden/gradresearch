# A2-S 실행 지침 — Scalar bias와 공간적 depth deformation 분리

작성: 2026-10-26 (Asia/Seoul). 대상: 이 저장소에서 작업을 이어받는 GPT6 Luna.

**문서 상태: 실행 계획만 작성. A2-S 구현·fit·렌더링·결과 판정은 아직 하지 않았다.**

## 0. 인계받는 에이전트가 먼저 읽을 지시

사용자가 이 문서를 따라 실행하라고 요청하면, 아래 순서대로 **구현 → 등록 → office2 → 설정 봉인 → office3 → 검증 → 결과 문서화**까지 수행한다. 계획 설명만 하고 끝내지 않는다. 이 문서를 작성한 현재 턴은 실험 실행 요청이 아니다.

- 작업 디렉터리: `/home/hlee221212/works/gradresearch`.
- Python: `.venv/bin/python`. 패키지를 새로 설치하거나 모델을 다운로드하지 않는다. 테스트는 `unittest`를 사용한다. 이 환경에는 pytest가 없다.
- 기존 baseline, A0/A1/V1 코드·설정·결과를 수정하거나 덮어쓰지 않는다. 새 A2-S 파일만 만든다. 기존 helper는 import해서 사용한다.
- 새 SLAM/MASt3R 추론은 필요 없다. 저장된 canonical local, 후보 지도, gauge, GT 및 렌더러를 재사용한다.
- **office2=개발, office3=이미 사용한 validation, office4=봉인 상태**다. Office4와 HKairport에는 접근하거나 실험하지 않는다.
- 이번 범위는 A2-S 진단이다. A2-O, D/P 보정 알고리즘, joint optimizer, 새로운 pruning은 실행하지 않는다.
- 문서에 없는 과학적 선택을 결과가 좋아지는 방향으로 추가하지 않는다. 아래 고정값으로 실패하면 실패를 보고한다. 구현 버그는 기존 출력 보존·amendment 기록 후 고칠 수 있다.
- 다음 명령은 **새로 구현할 CLI 계약**이다. 현재 A2-S 스크립트가 존재한다고 가정하고 실행하지 않는다.
- 다른 에이전트 호출은 필요 없다. 한 에이전트가 순차 수행한다.

## 1. 질문과 현재 근거

질문: **KF scale을 흡수한 유효 local depth의 오차 중 KF별 scalar로 설명되는 부분과, 그 이후에도 남는 공간적 잔차는 얼마인가?**

V1 office3 strict의 C00/C10/C01/C11 공통 MAE는 0.065526/0.043293/0.062524/0.036682m였다. Local 참조 개입은 33.93% 개선됐지만 pose 효과는 scope에 조건부였다. 이 결과는 RGB-only 보정 가능성이나 depth의 고유한 원인 기여율을 증명하지 않는다.

기준 문서:

1. [A1/V1 경로 판정](A1_route_decision.md).
2. [연구 계획 §6.2, §11.5, §12](../pointmap_pose_error_decomposition_research_plan_v1.md).
3. [V1 보고서](V1_office3_replication.md).

이후의 tile guard/minimum count/field loss/regularization 수치는 **이 인계 문서에서 새로 제안해 고정하는 구현 선택**이다. 이미 검증된 최적값이라고 쓰지 않는다. 아래 기본안은 office2 결과에 맞춘 탐색 없이 사용하며, office3에서는 값을 바꾸지 않는다.

## 2. 만들어야 할 파일과 단계별 책임

| 새 파일 | 역할 |
|---|---|
| `configs/a2_s_scalar_spatial_protocol.json` | 본 문서의 수치·scene·fold·방법·판정 규칙을 기계 판독 가능하게 기록 |
| `src/scalar_spatial_diagnostic.py` | tile mask, bilinear basis, scalar/field fit, correction, 판정 함수. 파일 I/O·렌더링과 분리 |
| `scripts/a2_s_common.py` | office2/3의 서로 다른 저장 형식을 같은 adapter 형식으로 읽기 |
| `scripts/run_a2_s.py` | `preflight/register/fit/build/evaluate/analyze/report/verify/seal` CLI |
| `tests/test_scalar_spatial_diagnostic.py` | §12의 합성·누출·후보 보존 검사 |
| `docs/experiments/A2_S_scalar_spatial_results.md` | 결과 및 실패·미지원·제한 |
| `configs/a2_s_results_summary.json` | scene/gauge/fold별 효과·분모·판정 요약 |
| `configs/a2_s_execution_manifest.json` | 최종 입력/코드/산출물 hash, 실행 명령, environment, amendment |

출력 루트: `results/A2_S_scalar_spatial/<실행 시작일 YYYY-MM-DD>/`.
실행 시작일은 Asia/Seoul로 정하고 설정에 한 번 저장한다. 단계가 자정을 넘어도 루트를 바꾸지 않는다.

출력 구조:

```text
<run>/
  registration.json
  registered_code/
  preflight.json
  office2/{fits,maps,evaluation,analysis,logs}/
  development_seal.json
  office3/validation_registration.json
  office3/{fits,maps,evaluation,analysis,logs}/
  amendments/
  verification.json
  execution_manifest.json
```

성공 marker는 해당 단계의 모든 검사가 통과한 뒤 마지막에 atomic write한다. 로그만 존재하는 것을 완료로 세지 않는다.
`preflight`가 출력 루트를 먼저 만들 수 있으므로 `register`는 루트 디렉터리 존재 자체로 실패하지 않는다. 대신 기존 `registration.json`이나 fit/map 결과가 있으면 덮어쓰기를 거부한다.

## 3. 입력 adapter: 경로와 배열 규약

### 3.1 Office2

- U root: `results/A1_U_scale_reparameterization/2026-10-26/construction/office2/`.
- `manifest.json`의 `keyframes` 순서로 읽는다. KF마다 `local_file.path`의 SHA-256을 확인한다.
- Local npz: `y[N,3]`, `covariance_y[N,3,3]`, `rigid_Q[4,4]`, `active_pixel_indices[N]`, `candidate_event`, `C`.
- Registry: `results/A0_pointmap_pose_factorial/office2/oracles/kf{kf_idx:04d}_registry.npz`.
- Registry 배열 `native_mask[H*W]`, `common_mask[H*W]`, `gt_depth[H*W]`, `active_candidate_ids[N]`, `raw_xyz[H*W,3]`.
- `flatnonzero(native_mask)`와 `active_pixel_indices`는 array-equal이어야 한다.
- **원본 프레임 번호 `original_frame=2*keyframe['frame_id']`**. U manifest의 frame_id는 mapper subsample index다.
- Source reference Z: `gt_depth[active_pixel_indices]`.
- Local reference validity: `common_mask[active_pixel_indices]`.
- Strict: 위 validity AND `original_frame>=200`.
- 원 C00 지도: `results/A1_C_canonical_factorial/2026-10-26/oracles/office2_strict/C00.f32`.
- C map manifest: 같은 디렉터리 `manifest.json`; `variants[].map_file`을 확인한다.
- 원 C00 cache: `results/A1_C_canonical_factorial/2026-10-26/evaluation/office2_strict/C00/`.
- Position gauge는 U local에 이미 반영돼 있다. 재추정하지 않는다.
- Orientation 상대 gauge D: `results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json`의 `relative`.
- Orientation S0 map/cache는 A1-G의 `office2_strict_orientation` manifest를 통해 찾는다. 파일 이름을 추정하지 말고 manifest의 `map_file`/metric cache 기록을 따른다.
- 예상: 11KF, native 1,545,979, strict 1,200,827. Prefix KF는 원본 frame 0 하나이고, post-prefix KF는 10개다.

### 3.2 Office3

- Root: `results/V1_office3_diagnostic/2026-10-26/`.
- `maps/manifest.json`의 `blocks` 순서로 읽는다.
- Local npz: `maps/local/kf{kf_idx:03d}.npz`.
- `y`, `covariance_y`, `rigid_Q`, `active_pixel_indices`, `candidate_ids`, `reference[N,3]`, `reference_replace[N]`, `strict[N]`, `source_frame`.
- **`source_frame`과 manifest block의 `frame`은 이미 원본 frame 번호다. 2를 곱하지 않는다.**
- Source reference Z: `reference[:,2]` 중 `reference_replace=True`만 GT-valid다. False 위치의 reference에는 예측 y가 들어 있다. 이를 GT로 사용하면 안 된다.
- Strict: 저장된 `strict`를 그대로 사용한다. `reference_replace & (source_frame>=200)`와 동일한지 확인한다.
- Position S0 map/cache: `maps/position_strict/C00.f32`, `evaluation/position_strict/C00/`.
- Orientation D: `maps/alignment.json`의 `relative`.
- Orientation S0 map/cache: `maps/orientation_strict/C00.f32`, `evaluation/orientation_strict/C00/`.
- 예상: 8KF, native 1,136,762, strict 855,796. Prefix KF는 frame 0 하나, post-prefix는 7개다.

### 3.3 두 scene 공통 adapter 출력

각 KF를 다음 dict로 정규화한다. 모든 선택은 저장된 native-active 배열의 행 순서를 따른다.

```python
dict(kf_idx=..., original_frame=..., H=288, W=512,
     y=..., covariance_y=..., Q=..., pixel_indices=...,
     candidate_ids=..., ref_z=..., ref_valid=..., strict=...)
```

두 scene 모두 H=288/W=512를 확인한다. 픽셀은 `u=index%W`, `v=index//W`다. 저장된 source image grid와 camera K를 재사용한다.

Packed 지도는 `float32[N,13]`, 열은 `[xyz(3), covariance upper triangle(6), RGB(3), opacity(1)]`다. Byte 수는 `N*52`다.

**지도 생성은 기존 S0 packed 행을 복사하고 `[:, :3]`만 갱신하는 방법을 우선 사용한다. `[:,3:]`는 bitwise 그대로 둔다.** Candidate ID·순서·수·covariance·RGB·opacity는 모든 A2-S arm에서 동일하다.

Source GT가 없는 후보를 새 GT 값으로 채우지 않는다. 과거 native filter도 재실행하지 않는다.

## 4. Dataset, gauge, pose, 평가 scope 고정

| 항목 | 고정값 |
|---|---|
| Dataset | `data/N2/Replica/office2`, `data/N2/Replica/office3` |
| Camera | `data/N2/Replica/cam_params.json` |
| GT/edge mask | `configs/n1_coordinate_contract.json`의 `common_mask` |
| Source mapping 구간 | 원래 짝수 frame 0..998; 기존 KF만 사용 |
| Sg fit source | 기존 prefix KF, 원본 frame `<200`만 |
| Primary map | 기존 post-prefix strict 후보 전체; scene별 후보 수 유지 |
| Heldout target | `list(range(201,1000,2))`, 400뷰 전부 |
| Primary gauge | 기존 position |
| 필수 sensitivity | 기존 same-prefix orientation |
| Rigid placement | 각 gauge의 기존 estimated Q 고정. GT pose arm을 새로 만들지 않음 |
| Render pose | 해당 target의 GT camera-to-world, 평가용으로만 사용 |
| Precision | fit/좌표 계산 float64; packed/render float32; TF32=False |
| Coverage weight | `weight>0.001` |
| Correct depth | `abs(pred-GT)<=max(0.05,0.02*GT)` |

Gauge를 바꿀 때는 `src/gauge_support.py:change_canonical_gauge`를 재사용한다. `y'=s_D*y`, `Sigma_y'=s_D²*Sigma_y`, Q의 rotation과 origin을 D로 옮긴다. Position 자료에 scale을 다시 흡수하지 않는다.

각 gauge에서 Sg/Sk/SkH/Sf를 같은 규칙으로 별도 fit한다. Heldout 결과로 더 나은 gauge를 선택하지 않는다. Gauge 간 효과 비교는 해당 S0/Sk/Sf의 **paired 6군 mask**로 한다.

Full mixed, source thinning, target thinning, refiner 및 appearance 학습은 이번 범위에서 추가하지 않는다.

## 5. Source spatial split: 정확한 규칙

Source image마다 8×8 tile을 만든다.

```python
x_edges = np.floor(np.arange(9)*W/8).astype(int)
y_edges = np.floor(np.arange(9)*H/8).astype(int)
# tile(r,c) = [x_edges[c],x_edges[c+1]) × [y_edges[r],y_edges[r+1])
parity = (r+c) % 2
# fold0: fit parity0, evaluation parity1
# fold1: fit parity1, evaluation parity0
```

- Guard band: **각 tile의 네 변에서 2pixel**을 안쪽으로 제외한다. 외곽 image 경계도 동일하게 처리한다.
- `x0+2<=u<x1-2`, `y0+2<=v<y1-2`인 픽셀만 source fit/evaluation에 사용한다.
- `fit_mask=ref_valid & guard_interior & fit_parity`; `eval_mask=ref_valid & guard_interior & opposite_parity`.
- 두 mask는 서로소여야 한다. Fit/evaluation pixel index와 hash를 KF/gauge/fold별로 저장한다.
- Map 자체에서 guard pixel이나 evaluation tile을 제거하지 않는다. **보정 함수는 strict 전체 후보에 적용**하며, source 오차의 검증만 opposite tile에서 한다.
- Target view는 source spatial fold와 별개인 400개 heldout camera다. Target depth/RGB를 fit 함수에 넘기지 않는다.

## 6. 지원 조건과 unsupported 처리

다음 수치는 source 오차를 확인하기 전에 등록한다.

| 항목 | 조건 |
|---|---|
| KF/fold fit pixel | ≥2,048 |
| KF/fold spatial evaluation pixel | ≥2,048 |
| Field 공간 분포 | source를 4×4 등분한 각 region에 fit pixel ≥64 |
| Bilinear design | `B.T @ B / N` rank=16, 최소/최대 eigenvalue 비 ≥1e-8 |
| Sg prefix | prefix ref-valid guard pixels 합계 ≥2,048 |

Sk/SkH/Sf의 주 비교는 **같은 지원 KF**에서 개입하도록 한다. 위 KF/fold 조건 하나라도 부족하면 그 KF/fold의 세 방법을 모두 `unsupported`로 표시하고, 렌더 지도에는 세 방법 모두 S0 중심을 유지한다. Source error는 그 KF의 fitted method에 대해 `null`이며 0으로 채우지 않는다. Sg는 prefix로 정의되는 별도 대조라 strict 전체에 적용한다.

다음 분모를 전부 기록한다: 지원 post-prefix KF 수/전체 KF 수, 지원 strict 후보 수/전체 strict 후보 수, source fit/eval pixel 수, 미지원 이유. **지원 KF와 지원 strict 후보가 각각 ≥80%**일 때만 scene/fold의 scalar 충분성 판정을 허용한다. 이 80% source gate는 이번 계획의 새 제한이다.

후보 수를 유지하기 위해 미지원 KF를 원 지도에서 삭제하지 않는다. Solver nonconvergence·NaN·누출·배열 정합 오류는 단순 관측 미지원과 구분해 **IMPLEMENTATION_FIX**로 처리한다. 수치 실패를 unsupported로 숨기지 않는다.

## 7. Fit 정의와 지도 변환

모든 잔차의 기준은 canonical `y_z`다. Raw `C*raw_z`와 섞지 않는다. 유효 sample마다:

```python
r = np.log(ref_z / y[:,2])
```

Reference valid 및 positive/finite y 확인 후 사용한다. Confidence나 오차 크기로 fit sample을 추가 선택하지 않는다. Robust loss의 가중치는 모델 fitting의 일부이며 후보 삭제가 아니다.

### 7.1 S0 / Sg / Sk

- **S0:** 기존 C00 지도. 반드시 원 packed 파일과 byte-identical. Source correction d=0.
- **Sg:** 모든 기존 prefix KF의 ref-valid guard pixel을 합쳐 `alpha_g=median(r)` 하나. 두 spatial fold에 같은 값을 사용한다. Post-prefix source/target 자료를 fit에 넣지 않는다. 두 scene 모두 현재 prefix KF가 frame0 하나라는 제한을 보고한다.
- **Sk-oracle:** 지원 KF마다 해당 fold의 fit sample만으로 `alpha_k=median(r)`.
- Correction은 `y_corrected=exp(d)*y`로 **3축을 함께** 곱한다. z만 변경하지 않는다. 그러면 predicted ray가 보존된다.
- Sg/Sk의 d는 해당 scalar alpha다. Beta=exp(alpha), min/median/max를 기록한다. GT fit이므로 Sg도 RGB-only 방법으로 부르지 않는다.

### 7.2 SkH: field와 동일 loss인 scalar 대조

Sk의 median(L1)과 Sf의 Huber loss 차이를 공간 자유도의 이득으로 오해하지 않도록 **SkH를 필수 보조 조건**으로 둔다.

`mean(Huber(alpha-r, delta=0.05))`를 최소화하는 scalar alpha_H를 다음 IRLS로 구한다. 초기값은 median(r). Max iterations=200, absolute parameter-change tolerance=1e-7, epsilon=1e-12.

```python
e = alpha - r
w = np.minimum(1.0, 0.05 / np.maximum(np.abs(e), 1e-12))
alpha_new = np.sum(w*r)/np.sum(w)
```

수렴 기준을 만족한 경우에만 완료한다. SkH는 기본 90% 판정의 Sk를 대체하지 않으며, **공간 field의 추가 이득을 주장할 때 Sk와 SkH 양쪽을 넘어야 한다.**

### 7.3 Sf-oracle: bilinear 4×4 log-depth field

16개 node를 x/y 각각 `linspace(0,W-1,4)`, `linspace(0,H-1,4)`에 둔다. Pixel마다 주변 4node의 bilinear weight를 만들고 `B[N,16]`로 표현한다. 모든 행은 nonnegative이고 행 합=1이다. Node flatten 순서는 row-major다.

`d(u,v)=B(u,v) @ theta`. Fit은 같은 KF/fold fit pixel만 사용한다. L은 4×4 node grid의 가로·세로 인접 차분 24개를 행으로 갖는 `[24,16]` 행렬이다.

고정 목적함수:

```text
J(theta) = mean(Huber(B theta-r, delta=0.05))
           + lambda_s/(2*24) * ||L theta||²
           + lambda_r/(2*16) * ||theta-alpha_H*ones(16)||²
lambda_s = 0.01
lambda_r = 0.0001
```

Regularization은 위 **정규화된 목적함수** 기준이다. Sample 수가 늘었다고 lambda를 임의 조정하지 않는다. Anchor alpha_H는 SkH fit 값이다. 상수 field도 표현 가능하다.

Float64 IRLS: theta 초기값=alpha_H*ones(16), max_iter=200, tolerance=max parameter change ≤1e-7. Huber weight는 SkH와 동일하다.

```python
N = len(r)
w = np.minimum(1.0, 0.05/np.maximum(np.abs(B@theta-r), 1e-12))
A = B.T@(w[:,None]*B)/N + 0.01*(L.T@L)/24 + 0.0001*np.eye(16)/16
b = B.T@(w*r)/N + 0.0001*alpha_H*np.ones(16)/16
theta_new = np.linalg.solve(A,b)
```

Objective, iterations, condition number, node min/max, convergence를 저장한다. Fit 종료 후 opposite source tile에 재fit하지 않는다. 전체 strict 후보의 d를 bilinear 평가해 `exp(d)*y`를 생성한다. Correction clipping이나 depth별 계수 선택을 추가하지 않는다. Nonfinite/비양수가 나오면 구현 실패로 중단한다.

Sf는 **이 고정된 16자유도·loss·regularization의 GT 진단**이다. 모든 공간 보정의 수학적 상한은 아니다. Sf가 개선되지 않아도 “공간 오차가 존재하지 않는다”고 결론 내리지 않는다.

### 7.4 World map

```python
# 각 KF의 strict block에서 계산한다.
# S0: apply_mask 전부 False
# Sg: 전부 True
# Sk/SkH/Sf: 지원 KF이면 전부 True, 미지원이면 전부 False
packed_out = np.array(original_gauge_S0_packed, copy=True)
packed_out[apply_mask, :3] = transform_points(
    y_corrected[apply_mask], Q
).astype(np.float32)
# packed_out[:, 3:]는 original과 array_equal이어야 한다.
```

S0와 미지원 block의 중심은 원 packed 값을 그대로 둔다. 수학적으로 같은 좌표라도 불필요한 재계산으로 bitwise 차이를 만들지 않는다. 여러 KF의 Q를 하나로 합쳐 적용하지 않는다.

**Correction에 맞춰 covariance를 beta²배 하지 않는다.** A1-U의 scale 흡수는 원 지도를 보존하는 재표현이지만, A2-S는 canonical covariance를 고정하고 중심만 개입하는 실험이다. 각 gauge 안에서 Q도 고정한다.

Source 평가용 y는 float64를 유지한다. Packed inverse roundtrip은 `atol=2e-5m, rtol=1e-6`으로 검사한다. Source 수치 양자화와 renderer 오차를 혼동하지 않는다.

## 8. 평가 조건과 비교군

Scene/gauge/fold마다 `S0, Sg, Sk, SkH, Sf`의 5조건이다. Fold는 0/1, gauge는 position/orientation이다. 각 context에서 400 target view를 유지한다.

S0와 Sg는 fold 간 같은 map이므로 hash 검증 후 cache를 공유한다. 기존 S0 cache도 재사용할 수 있지만, 고정 5view를 먼저 재렌더링해 parity를 확인한다. 재사용과 신규 render 수를 따로 보고한다.

필수 target 비교군:

1. **주 판정:** 같은 scene/gauge/fold의 `S0+Sk+Sf` common3.
2. **Global scalar:** `S0+Sg` common2.
3. **Loss 대조:** `S0+Sk+SkH+Sf` common4. 같은 pixel에서 SkH 대비 field 차이를 확인한다.
4. **Gauge sensitivity:** position/orientation 각각의 `S0/Sk/Sf`를 합친 common6.

전체 scene·fold·방법의 거대한 단일 교집합은 만들지 않는다. 비교군마다 view별 pixel count·reference 분모·support gate를 저장한다. Source support와 target coverage는 서로 다른 gate다.

### Source spatial 평가

Fit tile 오차는 적합도로 별도 보고한다. 주 source 진단은 반대 parity의 guard 내부에서 한다.

- 방법별 Z MAE, AbsRel, `log(pred_z/ref_z)`의 median과 MAD, 3D 거리를 구한다.
- 모든 방법에 같은 source 평가 pixel을 쓴다. KF별 값이 기본이며 scene 집계는 supported KF의 등가중 평균이다. Pool 평균은 보조다.
- GT ray와 predicted ray가 다르므로, 주 scale/field 판정은 Z 지표와 target depth로 한다.
- Fit/eval pixel 수, unsupported, beta, field node 값과 범위를 병기한다.

### Target geometry/coverage

- `scripts/evaluate_e4.py:CudaMap`, `src/a0_metrics.py:depth_state`, `common_covered_metrics`를 재사용한다.
- Primary MAE 분모는 GT-valid **interior** AND 비교 모든 arm의 covered pixel이다. 각 view의 MAE를 같은 가중치로 평균한다.
- Own-covered MAE/AbsRel, coverage, correct coverage도 전체 400view에서 저장한다. Interior와 all-GT-valid 분모를 모두 명시한다.
- Target gate: 등록 400view의 ≥80%에서 공통 ≥1,000pixel AND interior reference의 ≥50%. Zero-support는 null이며 gate 분모는 400이다.
- Correct coverage의 분모는 common mask가 아니라 각 view 전체 reference다. 방법 간 같은 interior 분모를 쓴다.
- Depth bins `[0.1,1,2,4,10]`별 오차와 coverage도 저장한다.
- Pixel/400view를 독립 시행으로 간주해 p값이나 scene CI를 만들지 않는다. Scene들을 하나의 평균으로 합치지 않는다.

### 표면과 시각화

- Position gauge의 각 fold·5조건은 고정 20view `range(201,1000,40)`의 GT interior/covered depth를 TSDF로 만든다. 중복 S0/Sg는 재사용한다.
- 각 scene의 기존 20view GT-depth TSDF reference를 hash 검증 후 재사용한다. Office2는 A0 evaluation, office3는 V1 evaluation/reference의 PLY/sample을 사용한다.
- 4cm voxel, 12cm truncation, 10m max depth, 100,000 면적 sample, seed0, 5cm surface tolerance. `scripts/evaluate_e4.py:integrate`와 `src/e4_budget.py`를 재사용한다.
- Gaussian center NN을 TSDF surface라고 부르지 않는다. 전체 scene completeness를 주장하지 않는다.
- Saved target view는 `[201,401,601,801,999]`. 방법별 RGB/depth/error, source fold mask와 field heatmap을 저장한다. RGB는 보조이므로 5view만 계산해도 된다. 누락 RGB metric은 None으로 초기화한다.

## 9. Scalar 충분성: 그대로 구현할 판정

Scene/gauge/fold마다 §8 주 common3의 같은 target pixel에서 E0=E(S0), Ek=E(Sk), Ef=E(Sf)를 계산한다.

```python
field_gain = E0 - Ef
scalar_gain = E0 - Ek
eligible = (
    source_KF_fraction >= 0.8 and source_candidate_fraction >= 0.8
    and target_support_pass and E0 > 0
    and field_gain > 0 and field_gain/E0 >= 0.10
)
ratio = scalar_gain/field_gain if eligible else None
```

Coverage 보전은 이 계획에서 보수적으로 다음 두 조건을 모두 요구한다. 반올림 전 수치로 비교한다.

- Sk/Sf의 interior coverage가 각각 S0 이상. Float 집계 허용차는 1e-6.
- Sk/Sf의 interior correct coverage가 각각 S0−0.01 이상.

위 조건과 ratio≥0.90을 만족하면 해당 fold의 `SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD`다. Ratio>1은 그대로 보고하고 0..1로 자르지 않는다.

| 결과 | 필수 라벨/처리 |
|---|---|
| Source/target gate 실패 | `INSUFFICIENT_SUPPORT`, ratio로 과학적 판정하지 않음 |
| Sf 미개선 또는 개선<10% | `FIELD_GAIN_NOT_ESTABLISHED`, ratio=null. Scalar 충분이라고 쓰지 않음 |
| Ef 개선≥10%, ratio≥0.90, coverage 보전 | 해당 fold의 scalar 충분성 성립 |
| Ef 개선≥10%, ratio<0.90 | `RESIDUAL_FIELD_OPPORTUNITY` 후보. SkH/source/geometry 대조 확인 |
| Coverage 조건 실패 | `COVERAGE_TRADEOFF`, 작은 MAE만으로 충분성/GO를 주지 않음 |
| Source eval만 개선, target 개선 없음 | `SOURCE_TARGET_MISMATCH` 병기. Pose/renderer 등과 미분리 |
| Gauge/fold/scene 결과 불일치 | `CONDITIONAL_OR_INCONCLUSIVE`, 좋은 조건만 선택하지 않음 |

Scene의 scalar 충분성은 **두 fold 모두** 성립할 때만 선언한다. 전체 결론에서는 두 scene·두 gauge의 방향과 gate도 확인한다. Office2만 성립하면 office2에 한정해 보고한다.

Sf의 추가 이득을 “공간적 이득”이라고 쓰려면 주 ratio<0.90 외에도, loss 대조 common4에서 Sf가 Sk와 SkH 모두보다 좋아야 하며, source opposite tile도 개선하고, surface/coverage가 반대 증거를 보이지 않아야 한다. 그렇지 않으면 loss/표현/pose에 조건부인 차이로 보고한다.

A2-S만으로 D/P 구현 GO를 주지 않는다. Scalar가 충분하면 단순 scale 진단을 우선한다. Field 여지가 재현되면 다음 후보는 A2-O RGB 관측 가능성이다. 다음 실험은 자동 실행하지 않는다.

## 10. 실행 순서와 CLI 계약

### Step A: 구현과 read-only preflight

1. `git status --short`와 적용되는 AGENTS를 확인하고 사용자의 변경을 보존한다.
2. §2의 새 파일을 구현한다. 기존 A1/V1 context 중 office2/HK가 고정된 부분을 무비판적으로 복사하지 않는다.
3. `preflight`는 존재·manifest/schema/hash·shape·후보 대응·frame 번호·기대 후보 수를 확인해 `preflight.json`을 만든다. Correction fit이나 heldout metric은 계산하지 않는다.
4. §12의 unit/synthetic 검사를 통과시킨다. Float64 basis/solver는 CPU에서 구현 가능하다.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_scalar_spatial_diagnostic.py'
.venv/bin/python scripts/run_a2_s.py preflight --config configs/a2_s_scalar_spatial_protocol.json
```

### Step B: 등록

```bash
.venv/bin/python scripts/run_a2_s.py register --config configs/a2_s_scalar_spatial_protocol.json
```

새 실험 결과를 보기 전에 다음을 hash/copy로 고정한다: 본 md, protocol JSON, 새 코드, 사용 helper와 테스트, 입력 manifest, source local/registry, S0 map/cache, 기존 gauge, camera/GT mask, source/target 분할, solver/method/lambda/unsupported/gate/종료 조건. Dataset은 N2 manifest의 path/bytes/SHA-256을 검증한다. `zip_crc` 등의 부가 필드와 dict 전체를 비교하지 않는다.

Office3는 입력 정합 확인과 등록만 미리 가능하다. Fit/metric은 office2 seal 뒤에 계산한다. 기존 V1 결과를 알고 있는 validation이라는 사실을 기록한다.

### Step C: Office2 전체 단계

```bash
.venv/bin/python scripts/run_a2_s.py fit --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py build --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py evaluate --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py analyze --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py verify --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py seal --scene office2 --config configs/a2_s_scalar_spatial_protocol.json
```

- `fit`: source만으로 완결하고 beta/theta, mask hashes, support, loss/convergence를 저장한다. Target loader를 호출하지 않는다.
- `build`: 저장된 fit만 적용한다. 다시 fit하지 않는다.
- `evaluate`: map/fit/code hash를 확인하고 S0 5view parity 후 전체 400view를 평가한다.
- `analyze`: target contrast/ratio/route를 처음 계산한다.
- `seal`: 설정·solver·입력/생성 fit·테스트·office2 결과·amendment를 `development_seal.json`에 고정한다. 이 기본안에서는 office2 결과에 따른 parameter 탐색을 하지 않는다.

### Step D: Office3 validation

```bash
.venv/bin/python scripts/run_a2_s.py fit --scene office3 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py build --scene office3 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py evaluate --scene office3 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py analyze --scene office3 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py verify --scene office3 --config configs/a2_s_scalar_spatial_protocol.json
.venv/bin/python scripts/run_a2_s.py report --config configs/a2_s_scalar_spatial_protocol.json
```

Office3 fit 시작 시 seal의 code/protocol hash 일치를 assert하고 `validation_registration.json`을 저장한다. Office3에서도 source GT를 사용하는 Sk/Sf는 Oracle이며 GT-free inference 검증이 아니다. Office3 결과에 맞춰 tile/solver/lambda/gate를 바꾸지 않는다.

## 11. 환경·재사용·실패 시 처리

- GPU는 RTX 5060 8GB. Sandbox에서 `nvidia-smi`나 torch CUDA가 보이지 않으면 기존 환경과 같이 GPU 명령에 sandbox 외부 실행 권한을 요청한다. CPU 렌더러로 자동 대체하지 않는다.
- `torch.set_num_threads(2)`, `cv2.setNumThreads(2)`. Renderer에서는 `torch.backends.cuda.matmul.allow_tf32=False`.
- `.f32`와 depth cache는 memmap으로 읽고 map 하나씩 GPU에 올린다. Map 사이에 참조를 해제하고 `torch.cuda.empty_cache()`를 호출한다. 모든 map/RGB를 동시 보유하지 않는다.
- Open3D 의존성은 필요하면 기존 `results/E4_matched_budget/deps`를 sys.path에 추가한다. V1 evaluator를 참고한다.
- Image cache는 workspace 또는 `/tmp`에 둔다. Environment/version, command, GPU peak, wall time, fresh/reused map-view 수를 기록한다.
- S0 5view parity: covered mask 불일치=0, common-covered depth max 차이≤0.002m. 주 position S0도 기존 C00와 같은 mask에서 지표가 일치해야 한다. 다른 비교군 mask에서 과거 C4 MAE와 조금 다른 것은 가능하지만, 같은 mask의 replay 차이는 구현 오류다.
- 완료 파일은 code/config/map/input hash가 같을 때 재사용한다. 실패 partial은 `failed_attemptN/`에 보존하고 별도 attempt 경로에 생성해 성공 후 채택한다.
- Bug 수정은 amendment JSON에 이유, 변경 전후 code hash, 이미 본 결과, 영향 범위를 기록한다. 과거 registration hash를 덮어쓰지 않는다.
- 수치·mask·loss·threshold를 바꾸는 수정을 “구현만 수정”이라고 부르지 않는다. 새 protocol/amendment를 등록하고 영향받은 office2부터 다시 실행하며 office3 독립성 저하를 보고한다.
- 입력 부족·hash 차이·solver 실패·coverage gate 실패를 성공할 때까지 조건 변경해 없애지 않는다. 과학적 FAIL/INCONCLUSIVE도 결과 문서까지 작성하면 실행을 완료할 수 있다.

## 12. 필수 테스트와 최종 artifact 검증

`unittest`의 작은 synthetic fixture로 다음 실패를 검출한다. 기존 helper를 그대로 따라 쓰는 테스트에 그치지 않는다.

1. Tile index, 2pixel guard, 두 fold 교환, fit/eval 비교집합, 모든 방법의 동일 source eval mask.
2. Office2 `frame_id=142`는 원본284이며 office3 source234는468이 되지 않음.
3. Office3 `reference_replace=False`에 극단값을 넣어도 fit이 불변.
4. Validity mask를 고정한 채 target depth와 source evaluation tile GT 값을 바꿔도 fit 계수 불변. Prefix 외 GT 변화가 Sg에 영향 없음.
5. 상수 log-bias synthetic에서 Sk/SkH가 역scale을 회복하고 Sf도 거의 상수 회복. 허용오차를 테스트에서 미리 명시.
6. 알려진 smooth bilinear field synthetic에서 field가 opposite tile error도 줄이고 scalar에는 잔차가 남음. Regularization이 있으므로 exact 계수 회복을 강제하지 않고 heldout 개선을 확인.
7. B의 끝점·node 순서·행 합=1, L의 24edge, 상수 theta에서 Ltheta=0.
8. Unsupported KF의 Sk/SkH/Sf 중심=S0, source fitted error=null, candidate ID/count/order 불변.
9. `y'=exp(d)*y`의 ray 보존, Q 불변, packed covariance/RGB/opacity bitwise 불변. z만 변경하는 negative control 검출.
10. Ef≥E0, 10% 미만, support 실패, ratio>1, coverage loss, 두 fold 불일치의 올바른 판정.
11. Baseline hash 불일치 또는 변경 code로 resume 시 거부. Optional RGB None 집계에서 KeyError 없음.

최종 `verify`는 map hash와 candidate 속성 외에 다음을 독립 재계산한다.

- KF별 corrected source point의 world 재변환과 packed mean 정합.
- Source fit/eval 비교집합과 Sg prefix-only 참조.
- 같은 target mask에서 전체400view의 E0/Ek/Ef, ratio/gate를 cache로 재계산.
- Unsupported 비율과 source/target 분모, zero-support의 null 처리.
- 단계 marker, code/input hash, reused S0 hash, amendment chain 정합.

## 13. 필수 산출물과 종료 조건

최소 CSV/JSON:

- `source_folds.csv`: scene/gauge/fold/KF/original_frame/fit_n/eval_n/support/reason/hash.
- `fit_parameters.json`: Sg, KF scalar/SkH, 16node field, objective/iterations/convergence.
- `source_spatial_residuals.csv`: fit/evaluation을 분리한 source 오차, KF와 candidate 분모.
- `target_methods.csv`: scene/gauge/fold/method, common group, MAE/AbsRel, coverage/correct coverage, pixel/view support.
- `scalar_sufficiency.csv`: 같은 common3의 E0/Ek/Ef, gain, ratio 또는 null과 이유, coverage/source/target gates.
- `gauge_pairs.csv`: paired common6에서 두 gauge의 효과.
- `surface_metrics.csv`: position의 fold/method별 TSDF surface 지표와 reference hash.
- `results_summary.json`, `verification.json`, `execution_manifest.json`.

Markdown 보고서는 다음 순서로 쓴다: 실행 status → 같은 mask의 주 표 → source cross-fit → scalar/field/loss 대조 → gauge·surface·coverage → unsupported/실패/수정 이력 → scene별 결론 → 다음 진단 후보.

종료 시 checklist:

- [ ] A2-S 코드·설정·테스트·manifest·정확한 실행 명령 저장.
- [ ] Office2 먼저 실행, seal 뒤 office3를 같은 설정으로 실행.
- [ ] 두 scene·두 fold·두 gauge·전체 method의 성공 또는 이유 있는 FAIL 보고.
- [ ] `A2_S_scalar_spatial_results.md`와 수치 요약 작성.
- [ ] 연구 계획의 A2-S 완료/미완료를 실제 상태로 갱신하고 A1_route_decision에 A2-S 결과를 추기. 과거 A1/V1 판정은 보존.
- [ ] A2-O와 보정 알고리즘 미실행, office4 보류, HK reference 미해결 유지.
- [ ] 최종 답변에 scene별 scalar 충분성, support/coverage 제약, 다음 진단 후보와 보고서 링크 제시.

**“실험 실행 COMPLETE”, “scalar 충분성 성립”, “RGB-only 보정 GO”는 서로 다른 status다. INCONCLUSIVE도 숨기지 말고 여기까지의 산출물을 완성해 종료한다.**
