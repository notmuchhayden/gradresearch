# A2-O-M 실행 계획 — RGB mask/support 및 최소 방향 판별 진단

작성: **2026-10-27 (Asia/Seoul)**.

**실행 상태: COMPLETE_EARLY_STOP / STOP_INSUFFICIENT_SUPPORT (2026-10-27).** [실제 결과](A2_O_M_results.md)를 참조한다. M0 재현·M1 필수 대조를 통과했지만 R1의 지원 KF가 모든 context에서 0/10이어서 미지원 상태 봉인·검증 후 종료했다. RGB audit loss·source GT·target·office3 평가는 진행하지 않았다.

아래 본문은 실행 전에 고정한 설계이며 조건부 단계의 구현·실행 완료를 뜻하지 않는다. 원 `PLAN_ONLY / NOT_REGISTERED / NOT_IMPLEMENTED / NOT_EXECUTED` 버전은 [등록 snapshot](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/registered_code/docs/experiments/A2_O_M_execution_plan.md)에 보존했다.

근거: [A2-O 실행 기록](A2_O_rgb_observability_results.md), [A2-O 기존 계획](A2_O_execution_plan.md), [A2-S 결과](A2_S_scalar_spatial_results.md), [경로 판정](A1_route_decision.md), [상위 연구 계획](../pointmap_pose_error_decomposition_research_plan_v1.md).

## 1. 목적과 종료 원칙

이번에 답할 질문은 **“기존 A2-O의 support 실패는 측정 절차가 유효 표본을 제거해서 발생했는가? 그 문제를 한 번 수정한 뒤, RGB가 KF별 scalar depth 보정의 올바른 방향을 선택할 수 있는가?”**다.

| 단계 | 질문 | 결과에 따른 처리 |
|---|---|---|
| **M0: Support 분해** | 어느 gate에서 표본이 사라지고, 등록 코드와 계획에 차이가 있는가? | 기존 실패를 재현하고 원인과 분모를 기록 |
| **M1: 합성 대조** | 수정된 mask에서 알려진 scalar를 회복하고, 정보 없는 조건을 성공으로 오판하지 않는가? | 필수 대조 통과 시에만 실제 RGB 선택 진행 |
| **M2: 최소 방향 판별** | Office2에서 RGB가 선택한 scalar가 RGB audit·source GT·target depth를 개선하는가? | 순차 gate 통과 시에만 office3 고정 검증 |

**과학적 프로토콜 수정은 기존 A2-O에서 R1으로 한 번만 허용한다.** R1은 이 문서에서 미리 정한다. M0 결과가 나쁘다고 R2를 만들거나 loss·pair·threshold·탐색 범위를 다시 고르지 않는다. M0를 보고 원인이 이 수정안의 범위 밖이라고 판단하면 수정 없이 종료할 수 있다. R1을 실행한다면 그 전체를 적용한다.

이번에는 field, joint optimizer, pose 추정, 새 SLAM/네트워크 추론, 학습, Gaussian admission/pruning, 새 데이터 확보로 확대하지 않는다. Office4는 봉인하고 HKairport는 제외한다. A2-S와 기존 A2-O의 코드 snapshot·선택 seal·결과는 읽기 전용으로 보존한다.

검사가 가설을 지지하지 않아도 원인·한계·종료 판정을 보고서에 남기면 진단은 완료다. 종료는 **현재 데이터·표현·변수·objective에 대한 개발 중단**이며, 모든 RGB 기반 보정의 불가능성을 뜻하지 않는다.

## 2. 이미 확인한 사실과 아직 등록되지 않은 관찰

### 2.1 저장된 A2-O 결과

대상은 `results/A2_O_rgb_observability/2026-10-27/profile_selection_v2/office2/selected_parameters.json`이다. 2026-10-27에 `selections → fit_support → reasons`를 읽기 전용으로 재집계한 값은 다음과 같다.

| 항목 | 값 |
|---|---:|
| Gauge × fold × post-prefix KF | 40개 |
| Fit pair 평가 레코드 | 160개 |
| S0 eligible center가 1개 이상인 레코드 | 78개 |
| Pair당 eligible center 최댓값 | **171개** |
| 41개 scalar 교집합의 retained center 최댓값 | **0개** |
| Pair support 기준 | 256개 이상 및 eligible의 50% 이상 |

160개는 gauge/fold별 평가 레코드 수이며, 독립적인 160개 이미지 쌍이라는 뜻이 아니다. 기존 결과 문서의 “공통 mask 후 최대 171개”는 저장 결과와 다르다. **171은 교집합 전 eligible, 교집합 후 retained는 모두 0**이다. M0에서 machine-readable 감사 기록을 만든다. 기존 문서의 정정이 필요하면 정정 근거와 원문 hash를 별도 보존한다.

현재 `src/rgb_observability.py`는 각 후보에서 다음을 동시에 요구한다.

```text
abs(z_projected(a) - z_evidence(a)) <= max(0.05m, 0.05*z_evidence(a))
common_mask = intersection(valid(a) for a in scalar_grid)
scalar_grid = [-0.20, -0.19, ..., 0, ..., +0.20]  # log scale
```

이 규칙은 예측 depth와의 일치 여부를 가림·projection 유효성과 함께 처리한다. 틀린 후보 하나가 유효하지 않으면, 정답 후보에서 사용할 표본도 전체 비교에서 제외된다. 또한 교집합 전부터 모든 pair가 256개 미만이므로 **교집합만 고쳐도 지원이 확보된다고 가정할 수 없다.**

### 2.2 비등록 평면 대조

앞선 검토 중 기존 함수로 정확한 4m 평면, 0.4m 수평 baseline, 400개의 textured patch를 구성했을 때, 후보 0만 평가하면 400개가 남고 41개 전체를 비교하면 0개가 남았다. 양 끝 후보의 projected Z는 약 3.275m와 4.886m이며, evidence 4m와의 허용차는 0.2m다.

이는 **사전 검토용 비등록 관찰**이며 정식 M1 통과 기록이 아니다. 당시 임시 실행은 등록된 fixture/code/artifact로 보존하지 않았다. 따라서 M1에서 seed·fixture·예상 결과·코드를 먼저 고정한 뒤 재현해야 한다. 이 평면 사례만으로 실제 데이터 탈락 원인의 비율이나 수정안의 효능을 추정하지 않는다.

## 3. 데이터, 좌표 및 정보 분리

### 3.1 입력 계약

| 항목 | 고정 규칙 |
|---|---|
| Scene 역할 | Office2 개발, office3는 A1/V1/A2-S에서 이미 사용한 validation |
| Office2 local | `results/A1_U_scale_reparameterization/2026-10-26/construction/office2/manifest.json`의 KF/local 대응 |
| Office3 local | `results/V1_office3_diagnostic/2026-10-26/maps/manifest.json` 및 `maps/local/` |
| Baseline·lineage | A2-O가 등록한 baseline, raw self-branch, candidate event, final snapshot/revision |
| 예상 KF | Office2 native 11개 / post-prefix 10개, office3 native 8개 / post-prefix 7개 |
| 평가 map 후보 | 기존 strict office2 1,200,827개, office3 855,796개 |
| Source 범위 | Native-active AND original frame ≥200. GT-derived strict로 RGB fitting 표본을 선택하지 않음 |
| Image | 실제 모델 입력과 같은 288×512 RGB, resize/crop 및 변환된 K |
| Frame ID | Office2 manifest 및 raw anchor의 subsample ID는 원본 frame으로 변환. Office3 local `source_frame`은 이미 원본 번호 |
| Gauge | Position primary, orientation 필수 sensitivity. 기존 gauge 변환과 단위를 재사용 |

보정은 `y'_k(u)=exp(a_k)*y_k(u)`로 xyz 세 축에 함께 적용하고, rigid `Q_k`는 고정한다. Prefix alignment가 있는 기존 gauge를 재사용하므로 전체 파이프라인의 GT-free metric scale 추론을 주장하지 않는다.

### 3.2 Pair와 holdout

M0와 R1은 **기존 A2-O의 pair manifest 및 fit/audit 배정을 그대로 재사용**한다. 등록 코드가 실제로 사용한 post-prefix evidence 집합을 기준으로 하며, prefix evidence를 새로 추가하지 않는다. Source/evidence ancestry 불공유를 실제 geometry provenance로 재검증한다. Shared-source 또는 unknown provenance를 지원 확보를 위해 허용하지 않는다.

Source-disjoint evidence를 `(original_frame, kf_idx)`로 정렬한 짝수 위치는 fit, 홀수 위치는 audit다. 한 pool에서 탈락한 pair를 다른 pool로 보충하지 않는다. 각 source KF는 fit/audit 각각 통과 pair가 2개 이상이어야 한다.

Source 공간은 8×8 checkerboard와 2pixel tile guard를 유지한다. Fold0는 parity0 fit/parity1 audit, fold1은 반대다. 모든 3×3 patch가 한 tile 안에 있어야 한다. 주 RGB audit는 **반대 tile × audit evidence**다.

400개 target `range(201,1000,2)`는 pair 선택·mask 구성·계수 선택·threshold 조정에 쓰지 않는다. Source별 evidence split은 scene 전체 이미지의 완전 불공유 split이 아니며, network 예측의 통계적 독립을 보장하지 않는다.

### 3.3 GT 접근 경계

RGB adapter에는 RGB, K, predicted y/Q, native active/confidence, candidate ID, frame/event/lineage만 전달한다. GT depth·pose·validity·strict·A2-S oracle 계수는 전달하지 않는다.

현재 `scripts/a2_s_common.py:kfs()`는 reference 배열도 읽는다. 이를 호출한 뒤 dictionary에서 reference key를 지우는 방식만으로 강한 I/O 분리를 주장하지 않는다. 새 RGB adapter는 native prediction 키만 읽고, registry에 native ID가 필요하면 해당 키만 선택적으로 읽는다. NPZ가 native/reference 배열을 함께 담는 경우 이를 공개하고 reference 배열의 접근을 금지한다. Reference evaluator는 선택 봉인 이후 별도 경로로 실행한다.

M0는 office2의 fit/audit **지원 수치와 mask 진단**만 볼 수 있고 photometric 곡선·선택 계수·GT 오차는 보지 않는다. M2에서는 fit-only 선택을 먼저 봉인하고 RGB audit와 GT를 연다. Office3는 office2 개발 결과 봉인 및 진행 gate 통과 후에만 새 RGB/mask 평가를 시작한다. Office3의 새 GT 후보 곡선·gradient·GT 최적 계수는 만들지 않는다.

## 4. M0 — 기존 절차의 support 분해

### 4.1 등록 코드 재현과 gate waterfall

현재 working tree가 아니라 기존 `profile_selection_v2/registered_code/`를 참조하여 원 실행을 재현한다. 새 instrumentation은 별도 코드로 등록하고 원 loss/mask 계산과 parity를 확인한다. 양 gauge·양 fold·모든 등록 pair·fit/audit pool을 포함한다. 원 실행에서 audit는 평가하지 않았으므로 새 audit support 진단은 재현 수치와 구분한다.

각 pair에서 누적 통과 수와 각 gate의 독립 실패 bitset을 함께 저장한다. 누적 탈락률은 gate 순서에 의존하므로 이를 물리적 원인의 기여율로 해석하지 않는다.

| 순서 | 검사 | 필수 기록 |
|---|---|---|
| 0 | Native active, frame, lineage | 입력 수, provenance 제외 사유 |
| 1 | Stride 4, checkerboard, guard, patch 9점 존재 | Center 및 unique source pixel 수 |
| 2 | Source depth edge·source texture | 각 조건 실패 수, std 분포 |
| 3 | Center ray-grid error ≤1pixel | Error 분위수와 탈락 수 |
| 4 | S0 parallax ≥1° | 각도 bin, baseline/depth |
| 5 | S0 positive Z·RGB image bounds·finite | 9점별 실패 및 patch 실패 수 |
| 6 | Evidence native z-buffer 4-neighbor validity·edge | Rasterization 전후 점유율, hole/edge/dilation 탈락 수 |
| 7 | S0 symmetric depth agreement | 통과 수, signed/absolute z residual 분포 |
| 8 | S0 warped texture | 기존 `eligible` 재현 |
| 9 | 41개 후보 교집합 | 후보별 retained, 교집합 retained, 최초 소멸 후보 |

Candidate 0, ±0.01, ±0.05, ±0.10, ±0.20의 진단 수치를 별도 요약하되, 원 교집합은 41개 전체로 계산한다. Candidate 순서에 따른 최초 소멸 위치와 최종 교집합을 혼동하지 않는다.

원 구현에서는 source edge와 evidence edge의 처리가 다를 수 있다. 특히 source의 3×3 인접 jump 검사와 evidence의 2pixel dilation을 구분해 기록한다. Source ray 검사 범위, texture·validity의 patch 9점 집계, camera preprocessing도 문서와 대조한다. 차이를 발견했다고 M0 계산을 조용히 바꾸지 않는다.

### 4.2 M0 통과와 종료

- 원 fit 160개 레코드에서 `max(eligible)=171`, `max(retained)=0` 및 원 선택의 support 실패를 재현한다.
- 원 입력/hash가 달라지거나 parity가 안 맞으면 `REPRODUCTION_BLOCKED`로 기록하고 M2에 진입하지 않는다.
- Ray·camera·candidate 대응의 구현 오류가 있으면 원 로그와 code hash를 보존하고 계약을 복구한다. 오차 threshold를 넓혀 통과시키지 않는다.
- 근본 원인이 다른 데이터/geometry를 요구하면 `STOP_CURRENT_INPUT_LIMITATION`으로 종료할 수 있다.

## 5. 유일한 수정안 R1 — Depth agreement와 RGB 평가 가능성 분리

R1은 아래 두 변경을 **한 번의 사전 고정된 개정**으로 적용한다. 표본 수 기준은 유지한다. M0나 합성 결과에 맞춰 다른 조합을 선택하지 않는다.

| 항목 | 기존 A2-O | R1 primary |
|---|---|---|
| Center sampling | Stride 4 | **Stride 2**, `(u mod 2==0) AND (v mod 2==0)` |
| Symmetric predicted-depth agreement | S0 및 모든 후보의 유효성 gate | **RGB mask에서 제거**, 사후 진단 및 Gk loss로만 사용 |
| Candidate 공통 분모 | 모든 후보에서 기존 `valid` | 모든 후보에서 RGB projection 및 evidence native sample이 유효한 교집합 |
| Scalar grid | Log scale −0.20…+0.20, step 0.01 | 동일한 41개, 0 정확히 포함 |
| Texture/parallax/ray 기준 | 0.02 / 1° / 1pixel | 유지 |
| Pair support | ≥256 centers AND eligible의 ≥50% | 유지 |

Stride 2는 초기 표본 부족을 점검하기 위한 고정된 조밀 sampling이다. 3×3 patch가 겹치므로 256개를 독립 관측 256개로 해석하지 않는다. Unique center·9점 union·공간 tile 점유율을 함께 공개하고 pixel 수를 근거로 p-value나 독립 표본 confidence interval을 만들지 않는다.

### 5.1 R1 mask의 정확한 정의

```text
A = native 3x3 patch 존재 AND stride2 AND fold/tile guard
    AND source texture std>=0.02
    AND source center와 상하좌우 predicted Z jump<=5%
    AND center ray-grid error<=1pixel AND S0 parallax>=1deg

P(a) = 9점 모두 positive projected Z, finite projected 좌표/RGB
       AND RGB bilinear sample이 image 내부
       AND projected 위치의 evidence z-buffer 4개 이웃 모두 native-valid
           (predicted Z edge/invalid 경계의 2pixel dilation 제외 후)

eligible_R1 = A AND P(0) AND S0 warped gray std>=0.02
common_R1 = eligible_R1 AND intersection(P(a) for all 41 a)
```

Source/evidence native validity와 finite positive source points는 사전 확인한다. Evidence z-buffer는 기존 predicted point를 K로 투영하여 nearest-pixel z-buffering하고 hole을 보간하지 않는다. Source의 4-neighbor jump 검사에는 새 dilation을 추가하지 않는다. 이는 R1에서 사용할 명시적 규칙이며 기존 문서의 포괄적인 edge 표현과 구분한다.

`P(a)`에는 `z_projected≈z_evidence` 조건을 넣지 않는다. Texture는 source 및 S0 warp에서만 고정하며, 후보에서 texture가 낮아졌다고 표본을 빼지 않는다. 모든 후보는 정확히 같은 patch를 평가한다. 후보별 가변 분모, missing loss=0 처리, reference visibility로 primary mask를 만드는 행위는 금지한다.

**이 mask는 predicted-depth agreement에 의해 탐색을 차단하지 않기 위한 측정 규칙이며, 올바른 가림 판정을 보장하지 않는다.** Edge 제외와 native validity만으로 가림 내부·반복 texture·잘못된 대응을 제거할 수 없다. Synthetic true-visibility 사후 audit와 실제 RGB/GT 불일치 평가가 필수다. Depth consistency 제거로 support가 늘었다는 사실만으로 성공을 판정하지 않는다.

### 5.2 Support 원인 구분용 고정 ablation

Office2에서 아래 네 조합의 **지원 수치만** 모두 저장한다. Loss·GT 성능을 비교해 primary를 고르지 않는다.

| ID | Sampling | Agreement gate | 역할 |
|---|---|---|---|
| L4 | Stride 4 | 기존 조건 포함 | M0 legacy 재현 |
| L2 | Stride 2 | 기존 조건 포함 | Sampling 단독 효과 |
| R4 | Stride 4 | 제거 | Mask 단독 효과 |
| **R1** | **Stride 2** | **제거** | **유일한 실제 선택 절차** |

R1에도 지원이 없으면 local grid 축소, stride 1, patch 크기 변경, pair 보충, gate 완화로 재시도하지 않는다.

## 6. M1 — 합성 positive/negative 및 정보 분리 검사

외부 asset 없이 analytic renderer를 구현한다. Seed=0, H=288/W=512, fx=fy=400, cx=255.5/cy=143.5를 고정한다. Depth 2/4/8m의 평면·경사면에 비주기 연속 texture를 사용하고, 0.4m 수평 baseline을 positive로 둔다. 주입 오류는 예측값에만 적용하고 실제 RGB는 clean scene에서 생성한다. Expected label·수치 허용 범위·fixture 범위를 결과 확인 전에 `controls/specification.json`에 등록한다.

| Control | 입력/주입 | 예상 결과와 확인 사항 |
|---|---|---|
| **Legacy plane collapse** | §2.2의 정확한 4m 평면·400개 patch | Legacy 0-only retained=400, 41개 교집합=0 재현. R1은 ≥256개 및 eligible의 ≥50% 유지 |
| **Clean no-op** | Static textured plane, 오류 없음 | R1 support PASS, 선택 `abs(a)<=0.01`, 0 대비 gain이 1e-4를 넘지 않으면 보정 성공 선언 안 함 |
| **Source-only scalar recovery** | Source y만 `exp(e)` 배율, e=±0.05/±0.10; pose/evidence clean | 각 depth와 부호에서 `abs(a_selected+e)<=0.01`. Primary mask로 회복해야 함 |
| **Pure rotation / zero baseline** | Translation=0, textured scene, 회전 0 및 1° | Primary parallax support 실패. Parallax gate 전 raw photo profile은 float64 범위 차이 ≤1e-8. 깊이 회복 성공 금지 |
| **Low texture** | Source/evidence 상수 RGB | Texture support 실패. Null을 0 gain 또는 올바른 보정으로 처리하지 않음 |
| **Joint scale gauge** | 모든 predicted y와 camera translation에 `exp(e)`, e=±0.10 | 동일 candidate의 RGB profile 차이 ≤1e-8, 공통 mask 동일. Absolute metric scale 성공 주장 금지 |
| **Shared depth bias** | Source/evidence depth에 같은 e=±0.10, baseline은 고정 | Geometry agreement와 RGB 선택을 별도로 기록. Residual 상쇄를 정확성으로 오판하지 않음 |
| **Pose-depth confusion** | Evidence pose에 각 축 translation ±0.02m 또는 rotation ±1°, 단독 및 source e=±0.10 결합 | Photo 감소와 실제 depth 오류를 분리. GT 악화면 `POSE_DEPTH_CONFUSION`/`PHOTO_GEOMETRY_MISMATCH` |
| **Occlusion / dynamic / repeated texture** | 전경 사각형 가림; 중앙 20% 폭 RGB를 +8pixel 이동; 주기 8pixel texture를 각각 별도 적용 | False correspondence 비율, 후보별 true visibility, 선택 depth 오류·다중 최소를 사후 기록. 잘못된 낮은 photo loss를 성공으로 분류하지 않음 |

Positive fixture의 valid FOV는 source bias와 전체 41개 후보를 수용하도록 기하적으로 미리 정한다. 결과가 좋게 나오는 crop을 사후 탐색하지 않는다. 합성 control은 pair 수준에서 support를 검사하며 real scene의 KF 지원율을 적용하지 않는다.

Clean·scalar recovery·수치 불변성 및 정보 분리 검사는 모두 통과해야 M2에 진입한다. Nuisance control에서 실제 선택이 틀리는 현상은 가능한 과학적 결과다. 그런 경우 오류를 올바른 label로 기록해야 하며, 모든 가림·pose 오류에 강인하다는 주장을 하지 않는다. Negative에서 거짓 성공을 출력하거나 positive가 회복되지 않으면 `STOP_CONTROL_FAILURE`로 종료한다.

True depth/pose/visibility는 generator와 사후 evaluator만 보유한다. True-visibility subset에서 loss를 추가 기술할 수 있으나 mask·계수 재선택에는 쓰지 않는다. 합성 주입량을 실제 scene의 오류 크기로 간주하지 않는다.

필수 정보 분리 검사는 다음과 같다.

- Reference loader를 호출 불가로 하고 reference 배열/GT mask를 바꿔도 RGB mask·profile·선택 hash가 동일하다.
- Audit 경로의 RGB/evidence와 target 입력을 바꿔도 해당 KF의 fit 선택이 동일하다. 반대 tile의 3×3 guard 누출도 검사한다. Og는 pooled fit 입력을 고정한 상태에서 감사한다.
- Source/evidence identity 및 알려진 translation의 warp 방향, resize/crop K, frame/event/candidate 대응을 확인한다.
- Out-of-image/invalid sample이 생길 때 모든 후보의 mask가 동일하게 고정되고 null 사유가 보존된다.

## 7. M2 — Scalar RGB 선택과 순차 평가

### 7.1 Arm과 선택 규칙

| Arm | 계수 결정 | 역할 |
|---|---|---|
| O0 | a=0 | 무보정 기준 |
| Ok | KF별 fit RGB loss 최소 | Primary RGB scalar |
| Og | Fit 지원 KF의 loss를 KF 등가중 pooling하여 공통 scalar 선택 | Global scalar 대조 |
| Gk | 같은 fit pair·mask·grid에서 predicted geometry loss 최소 | Depth agreement 대조 |

기존 `0.85*(1-ZNCC)/2 + 0.15*mean(abs(RGB_source-RGB_warp))`를 유지한다. RGB는 [0,1], gray 가중치 (0.299,0.587,0.114), ZNCC epsilon=1e-12 및 [-1,1] clipping이다. Exposure/color 계수는 fit하지 않는다. Gk는 `Huber(log(z_projected/z_evidence), delta=0.05)`를 사용한다. RGB objective에 geometry residual을 섞지 않는다.

Patch 등가중 → pair 등가중 → KF 등가중으로 집계한다. 41개 grid를 한 번 평가하고 반복 최적화하지 않는다. Loss 차이 ≤1e-8은 동률이며 `abs(a)`가 작은 것, 다음으로 수치 a가 작은 것을 선택한다. `a=±0.20` 최소는 `SEARCH_BOUNDARY`, `max(J)-min(J)<=1e-4`는 `FLAT_OR_UNRESOLVED`, O0 대비 gain≤1e-4는 `NO_RESOLVED_PHOTO_GAIN`이다. 경계 최소를 근거로 grid를 확대하지 않는다.

### 7.2 Support와 분모

| 수준 | 기준 |
|---|---|
| Pair/fold/pool | `common_R1>=256` AND `common_R1>=0.5*eligible_R1` |
| Fit 지원 KF | 해당 fold의 fit pool에서 통과 evidence pair ≥2 |
| Audit 지원 KF | 반대 tile × audit pool에서 통과 evidence pair ≥2 |
| Scene fit support | 전체 post-prefix KF의 ≥80% AND 그 KF의 native post-prefix candidate 수가 전체의 ≥80% |
| Scene audit support | 전체 post-prefix KF 중 fit·audit 동시 지원 KF ≥80% AND 그 KF의 native candidate 비율 ≥80% |

각 gauge/fold에서 별도로 판정한다. Office2는 최소 8/10 KF, office3는 최소 6/7 KF이고 candidate 비율도 함께 통과해야 한다. Strict-map 후보 지원율은 별도 보고한다. Pair 지원 여부는 loss를 보기 전에 정하고, 지원 pair 전부를 사용한다. 유리한 pair만 남기지 않는다.

Map apply-mask와 Og pooling 집합은 **fit support만으로** 고정한다. Audit support·GT 효과를 본 뒤 보정 KF를 줄이지 않는다. 미지원 KF는 모든 arm에서 O0를 유지한다. Audit가 실패하면 계수를 다시 고르는 대신 해당 과학적 평가를 중단한다.

### 7.3 순차 gate와 평가 순서

1. **Office2 fit:** 양 gauge·양 fold의 support와 전체 arm 계수를 생성하고 exact mask·profile·hash를 봉인한다. Fit support 실패 context가 있으면 전체 scene 진행 gate는 FAIL이다. 부분 결과는 남기되 target·office3를 실행하지 않는다.
2. **RGB audit:** 봉인 계수를 반대 tile × audit evidence에 적용한다. Audit mask도 동일 41개 grid의 RGB 유효 교집합으로 구성하지만, audit 후보 loss 곡선은 계산하지 않고 O0/선택 계수만 평가한다. Audit loss가 선택·pair·apply-mask에 영향을 주면 안 된다.
3. **Source GT:** 봉인 이후 opposite-tile native/reference-valid, finite positive Z, 동일 guard의 고정 pixel 집합에서 O0와 선택 arm의 Z MAE/AbsRel/log residual을 paired 평가한다. KF별 최소 2,048개를 요구하고 지원 KF/candidate 비율 80%를 유지한다. Orientation gauge의 reference는 기존 A2-S evaluator와 같은 단위 변환을 봉인 이후에 적용한다. RGB audit center의 reference-valid subset도 분모와 함께 보조 보고한다. GT subset으로 재선택하지 않는다.
4. **방향 판정:** 전체 post-prefix KF의 ≥80%에서 Ok의 audit photo가 O0 대비 >1e-4 줄고 같은 KF의 source GT MAE도 감소해야 한다. 지원 실패 KF는 성공 분모에서 빼지 않는다. KF 등가중 source MAE도 감소해야 한다. 양 fold·양 gauge 모두 충족해야 다음으로 간다. Og/Gk는 같은 지표로 별도 판정하며 Ok 실패를 대체하지 않는다.
5. **Office2 target:** 방향 판정 통과 시에만 §8의 map·400-target 평가를 수행한다. Target depth gate까지 통과한 뒤 독립 검증과 개발 seal을 만든다.
6. **Office3 고정 검증:** Office2 source/audit/target gate와 검증이 모두 통과한 경우에만 시작한다. 같은 R1·grid·support·loss·pair split을 사용하여 fit→봉인→audit→source→조건부 target 순서를 반복한다. Office3에서 조건을 바꾸지 않는다.

Office2 GT profile은 주 판정에 필요하지 않으므로 새 GT 최적 scalar/gradient sweep을 기본 산출물에 포함하지 않는다. RGB 선택 후 얻은 source GT 평가만으로 방향 판정을 한다. Office3는 baseline과 선택된 arm만 GT 평가한다.

이 gate는 마지막 진단의 개발 의사결정 기준이다. 국소 일부 KF 또는 global scalar에 신호가 있어도 전체 gate 실패 시 조건부 결과로 남기고 범위를 확대하지 않는다. Scalar 실패가 모든 공간 field의 실패를 논리적으로 뜻하지는 않는다.

## 8. 조건부 map·target 평가

계수 봉인 후 기존 strict packed S0를 복사하여 fit-supported KF의 중심 `[:, :3]`만 변경한다. Candidate ID·순서·수 및 `[:,3:]`의 covariance/RGB/opacity는 bitwise 보존하고 Q는 고정한다. Native RGB source와 strict 평가 map의 분모가 다름을 공개한다. Apply-mask는 O0/Og/Ok/Gk 전체에 동일하다.

중심은 candidate ID로 native local y와 대응시켜 `X'_w = Q_k * (exp(a_k)*y_k)`로 다시 계산한다. World 좌표 전체에 `exp(a_k)`를 곱해 camera translation까지 scale하지 않는다. a=0의 재구성이 S0와 수치 허용 범위 안에서 일치해야 한다.

본 평가 전에 S0의 고정 5뷰 `[201,401,601,801,999]` replay를 수행한다. Covered mask 불일치=0, 공통 depth 최대 차이≤0.002m여야 한다. Target camera는 raw GT pose를 평가에만 사용한다. 이미 정렬된 map에 alignment를 중복 적용하는 negative 검사를 포함한다.

| 항목 | 고정 규칙 |
|---|---|
| Target | 400뷰 `range(201,1000,2)` 전부 |
| Primary | O0+Ok 동일 common-covered/reference-valid interior pixel의 view별 MAE, view 등가중 |
| Simple 대조 | O0+Og+Ok+Gk 공통 mask에서 arm 비교 |
| Gauge sensitivity | Position/orientation의 O0+Ok 네 map 공통 pixel에서 방향 비교 |
| Coverage | Covered weight>0.001, reference interior 정의는 N1/A2-S와 동일 |
| Correct coverage | `abs(depth-GT)<=max(0.05m,0.02*GT)`를 전체 reference interior 분모로 계산 |
| Target support | 400뷰의 ≥80%에서 common≥1,000pixel AND reference interior의 ≥50% |
| Primary 효과 | O0 대비 Ok MAE ≥10% 감소, interior coverage 감소 허용 1e-6, correct coverage 감소≤1%p |
| 보조 | Own-covered MAE, full reference correct coverage, depth bins [0.1,1,2,4,10] 및 KF별 apply 비율 |

두 fold·두 gauge 모두 primary gate를 통과해야 scene의 `TARGET_DEPTH_EFFECT_SUPPORTED`다. Simple/gauge 공통 mask에서도 Ok의 개선 방향이 반대면 `CONDITIONAL_OR_INCONCLUSIVE`로 낮춘다. 서로 다른 common mask의 숫자를 직접 빼서 효과를 만들지 않는다. Og/Gk의 성능과 비용을 함께 보고하되 Ok가 그들보다 우수해야 한다는 별도 field/novelty 주장은 이번에 검증하지 않는다.

TSDF는 이 마지막 진단의 필수 gate에 포함하지 않는다. Primary는 heldout target depth와 coverage이며, 통과해도 surface Chamfer·scene completeness 개선을 주장하지 않는다. A2-S surface 결과를 새 RGB 보정의 증거로 재사용하지 않는다. Renderer/CUDA가 실행 불가하면 source 진단과 target 미실행 상태를 구분하고 `EVALUATION_BLOCKED`로 종료한다.

## 9. 종료 판정과 허용되는 결론

| 상태 | 근거 | 종료·보고 문구 |
|---|---|---|
| `STOP_CONTROL_FAILURE` | Positive 회복/불변성/정보 분리/오판 방지 검사 실패 | 측정 절차의 유효성이 확보되지 않아 보정 효능 미판정 |
| `STOP_INSUFFICIENT_SUPPORT` | R1 후 fit/audit/source/target 지원 기준 미달 | 현재 데이터·표현·고정 절차에서 충분한 평가 support 확보 실패 |
| `STOP_FLAT_OR_AMBIGUOUS` | 충분한 support에도 flat·boundary·미해결 선택 때문에 방향 gate 실패 | 검사한 scalar 범위에서 안정적인 RGB 선택 근거 미확보 |
| `STOP_PHOTO_GEOMETRY_MISMATCH` | RGB loss 감소가 source 또는 target 개선으로 이어지지 않음 | 현재 objective의 RGB 개선을 geometry 보정으로 사용할 근거 미확보 |
| `STOP_EFFECT_NOT_ESTABLISHED` | 방향/target 최소 효과 gate 미달, 명확한 반대 방향은 아님 | 사전 고정한 유용성 기준의 효과를 입증하지 못함 |
| `STOP_VALIDATION_NOT_ESTABLISHED` | Office2 통과 후 office3에서 support/방향/target gate 실패 | 장면 간 효능 미입증, 세부 원인 label 병기 |
| `CONDITIONAL_OR_INCONCLUSIVE` | Fold/gauge 또는 공통 mask 비교의 방향 불일치 | 조건부 신호는 있으나 일관된 보정 근거 미확보 |
| `SCALAR_RGB_EVIDENCE_SUPPORTED` | 두 scene의 필수 검사·source/audit/target·검증 gate 전부 통과 | 기존 gauge·평가 support에 조건부인 scalar RGB 보정 근거 확보 |
| `REPRODUCTION_BLOCKED` / `EVALUATION_BLOCKED` | 입력/code parity 또는 평가 구현·실행 환경 실패 | 실행 장애로 미완료, RGB 실패로 해석하지 않음 |

상태를 한 개 숫자로 합치지 않는다. `execution_status`, `controls_status`, `fit_support_status`, `audit_status`, `source_status`, `target_status`, `validation_status`, `final_decision`을 각각 저장한다. 가장 이른 중단 이유와 후속 단계 `NOT_RUN_DUE_TO_GATE`를 명시한다. Flat 여부만으로 깊이가 틀렸다고 판정하지 않는다. Null은 0 gain과 구분한다.

R1 이후 과학적 gate가 실패하면 이번 보정 개발 경로를 종료한다. 지지 근거가 확보되더라도 A2-O-M은 field 추가 자유도·새 방법의 독창성·D/P/joint optimizer·office4 실행을 승인하지 않는다. 후속 연구 여부는 별도 판단 사항이다.

종료 시 사용할 기본 문구:

> 검사한 데이터·표현·scalar 후보·RGB objective에서 재현 가능한 RGB-only 보정 효능을 입증하지 못해 이 개발 경로를 종료한다. Support 부족, 선택 모호성, RGB/geometry 불일치 및 실행 장애를 구분했으며, 모든 RGB 기반 깊이 보정의 불가능성을 주장하지 않는다.

## 10. 구현·실행 계약

### 10.1 예정 파일

| 파일 | 역할 |
|---|---|
| `configs/a2_o_m_protocol.json` | 본 문서의 R1·split·control·gate를 고정. 현재 미생성 |
| `src/rgb_mask_diagnostic.py` | Gate bitset, legacy/R1 mask, scalar profile, 판정. Reference I/O 제외 |
| `scripts/a2_o_m_common.py` | Native-only 입력 adapter와 별도 reference evaluator, frame/lineage 검증 |
| `scripts/run_a2_o_m.py` | 단계별 CLI, hash 등록·봉인·재개·보고 |
| `tests/test_rgb_mask_diagnostic.py` | Positive/negative, 누출, mask, map 보존 및 판정 검사 |
| `docs/experiments/A2_O_M_results.md` | 실제 실행 결과와 종료 이유. 현재 미생성 |

기존 projection/photo primitive는 hash를 고정하고 재사용할 수 있다. Legacy의 `valid`에 포함된 depth agreement를 R1에서 우회할 때, legacy 함수를 수정하여 기존 결과를 소급 변경하지 않는다. 새 경로에서 validity 요소를 명시적으로 분리한다.

출력 root는 `results/A2_O_M_rgb_mask_diagnostic/<시작일>/`이며 Asia/Seoul 기준 날짜를 한 번 고정한다. 기존 run을 덮어쓰지 않고 변경 code/config와 같은 hash의 결과만 재개한다.

### 10.2 예정 CLI 순서

**아래 명령은 미구현 CLI 계약이다. 지금 실행 가능한 명령 목록이 아니다.**

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_rgb_mask_diagnostic.py'
.venv/bin/python scripts/run_a2_o_m.py preflight --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py register --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py support-audit --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py controls --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py seal-r1 --config configs/a2_o_m_protocol.json
```

`preflight`는 파일/hash/shape/native ID/lineage와 실행 환경만 확인한다. `register`는 M0 instrumentation, controls specification, R1 전체 규칙, 입력 및 의존 코드를 snapshot한다. `support-audit`는 M0와 네 support ablation만 실행한다. `controls`는 등록된 expected 결과를 변경하지 않고 M1을 실행한다. `seal-r1`은 M0 재현·M1 검사 결과와 동일 R1을 연결하며, 계수 profile 전에 필수 gate를 확인한다.

이후 office2에서 다음 순서를 gate에 따라 실행한다.

```bash
.venv/bin/python scripts/run_a2_o_m.py profile --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py freeze-selection --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py evaluate-source --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py evaluate-target --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py verify --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py seal-development --scene office2 --config configs/a2_o_m_protocol.json
```

`evaluate-source`는 RGB audit를 먼저 수행하고 source GT를 사후 평가한다. `evaluate-target`는 source/audit gate·selection seal·map parity를 검사한다. `verify`는 별도 cache 재계산으로 argmin/tie, 고정 mask, 지원율, MAE/coverage 및 label을 확인한다. 실패/null도 검증한다.

Office3는 `register-validation`이 office2 개발 seal과 진행 자격을 검사한 뒤 동일 `profile → freeze-selection → evaluate-source → 조건부 evaluate-target → verify`를 실행한다. 어느 단계에서 중단해도 `report`는 실행 가능해야 한다. Office2 gate 실패 상태에서 office3를 호출하면 이유와 함께 거부한다.

### 10.3 구현 실패와 수정 한도의 구분

입출력·수치·frame mapping 등 계약을 복구하는 버그 수정은 실패 출력과 수정 전 코드를 보존하고 구현 amendment를 남긴다. 영향 있는 단계와 봉인을 무효화한 뒤 다시 수행한다. 검증을 통과하지 못한 구현을 과학적 실패로 해석하지 않는다.

Mask·sampling·loss·grid·threshold·pair·scene scope를 바꾸는 것은 버그 수정으로 부르지 않는다. 그런 변경은 R1 이후 허용하지 않는다. Office3 결과를 본 뒤 fitting/evaluation 동작에 영향을 주는 수정이 필요하면 validation provenance를 손상된 것으로 명시하고 성공 판정을 보류한다.

CPU chunk 처리를 기본으로 하고 torch/cv2 thread=2, fit/transforms float64, packed/render float32, renderer TF32=False를 유지한다. GPU는 조건부 map 평가에서 사용한다. CUDA/renderer parity는 실제 같은 실행 환경에서 확인하며, 이전 환경의 smoke 통과를 대신 쓰지 않는다. Runtime·최대 메모리·candidate 평가 수·재사용/신규 render 수를 기록한다. 새 패키지·모델 다운로드를 실행 전제로 두지 않는다.

## 11. 산출물과 완료 점검

최소 보존 산출물:

- `registration.json`, `preflight.json`, `registered_code/`, `input_manifest.json`, 원 A2-O hash와 정정 감사 기록.
- `office2/support_waterfall.csv`, `gate_failures.npz`, `support_ablations.csv`, candidate별 교집합 경과 및 정확한 center index/hash.
- `controls/specification.json`, `controls/results.json`, fixture·true-visibility 사후 audit 및 실패 로그.
- `r1_seal.json`, scene별 `pair_manifest.csv`, `mask_manifest.json`, `profiles.csv`, `selected_parameters.json`, `selection_seal.json`.
- 실제 실행된 단계의 `rgb_audit.csv`, `source_geometry.csv`, `maps/manifest.json`, `target_methods.csv`, `target_coverage_bins.csv`, `gauge_pairs.csv`, 고정 시각화.
- 조건부 `development_seal.json`, `validation_registration.json`, `verification.json`, `amendments/`, `execution_manifest.json`, `summary.json`, 결과 Markdown.

미실행 단계는 빈 CSV를 성공 artifact처럼 만드는 대신 상태·이유를 manifest에 기록한다. 보고 순서는 **실행 상태 → 기존 실패 재현 → gate별 표본 감소 → R1/합성 검사 → RGB 선택/audit → source GT → 조건부 target → 조건부 office3 → 종료 판정**이다.

- [ ] 기존 A2-O의 171 eligible / 0 retained를 재현하고 문서 차이를 기록했다.
- [ ] R1 한 개와 support ablation을 loss/GT 결과 전에 등록했다.
- [ ] Positive recovery, pure rotation/low texture/gauge negative 및 정보 분리 검사를 수행했다.
- [ ] 계수·mask·apply-mask 봉인이 audit 및 모든 GT 성능 평가보다 앞섰다.
- [ ] 양 gauge·양 fold·전체 KF의 지원 분모와 null/실패를 공개했다.
- [ ] RGB audit, source 오차, target depth·coverage를 별개 결과로 보고했다.
- [ ] Gate 실패 시 후속 실행을 멈추고 재튜닝 없이 종료 보고서를 완성했다.
- [ ] 실제 cache 독립 검증과 코드·입력·환경·amendment hash를 보존했다.
- [ ] Office3는 이미 사용한 validation으로 표시하고, office4/HKairport 봉인을 유지했다.
- [ ] 실행 완료와 RGB 보정 근거 확보를 서로 다른 상태로 기록했다.
