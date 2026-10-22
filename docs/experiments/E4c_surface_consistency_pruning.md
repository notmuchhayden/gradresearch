# E4c: 추정 표면 일관성 기반 Gaussian pruning

**최신 상태: 개발 성립 단계 실행·INCONCLUSIVE(2026-10-22).** [결과 보고서](E4c_surface_consistency_pruning_results.md)에 5장면·네 두께 조합의 관측 분류·기하 이력·보정 실패를 기록했다. [A1 분할 변경](E4c_execution_amendment.md)과 [A2 구현 수정](E4c_v2_execution_amendment.md)을 적용했으며 최초 계획·각 실행의 코드와 결과는 별도 봉인에 보존했다. office0/office1에서 보정 가능한 공통 audit S가 각각 0개여서 임계값을 정하지 않았고, 새 장면 효능 평가로 진행하지 않았다.

**등록 전 상태 기록: 계획 초안·미구현·미실행(2026-10-22).** 아래는 최초 개발 가설과 평가 절차다. 제안한 모든 단계가 실행된 것으로 해석하지 않으며, 실제 실행 범위·판정·미수행 항목은 결과 보고서를 따른다.

## 1. 목적과 기존 실험과의 관계

**목표는 추정된 점군에서 일관된 표면을 보존하면서, 그 표면에서 이탈한 점에 대응하는 Gaussian만 선택적으로 제거하는 것이다.** 표면 전체가 실제 위치와 다르게 추정됐더라도, 해당 표면의 점들을 GT 위치 오차만으로 제거 대상으로 삼지 않는다. 공통 위치·스케일 오차의 교정은 이번 pruning의 목표와 구분한다.

[E4b 결과](E4b_reference_plane_audit_results.md)에서 office1의 엄격한 잘못된 지지 후보 31,412개 중 30,777개는 주변 공통 점의 ≥80%가 같은 방향으로 GT에서 벗어난 조건도 만족했다. 이는 **국소 patch의 공통 오차**를 확인한 결과이며, 여러 시점에서 안정적인 표면을 형성한다는 것까지 입증한 수치는 아니다. E4c에서는 국소 표면 지지와 여러 시점의 지지를 직접 구분해 검사한다.

현재 기하 점수에도 실행 시 GT는 들어가지 않는다. 변경할 대상은 **제거 대상의 정의, 명시적인 표면 지지 판정, 정책, 평가 기준**이다. 기존 GT bad 라벨은 그대로 보존하고 새 표면 일관성 분류와 교차 집계한다.

| 단계 | 역할 |
|---|---|
| [E4](E4_matched_budget.md) | 기존 정책의 동일 예산 지도 품질 비교. REVISE 유지 |
| [E4b](E4b_reference_plane_audit.md) | 기존 기준 평면과 판정 경로의 사후 진단. 완료 결과 보존 |
| **E4c** | 표면 일관성에 맞는 제거 정책 개발 및 별도 평가 |
| E5 | 공통 depth offset·scale bias·pose error 등을 주입하는 합성 스트레스 실험 |
| E6 | 실제 정책별 online replay와 지연·메모리 검증 |

E4c 결과로 기존 E4의 성공 조건이나 판정을 소급 변경하지 않는다. E5/E6의 자동 진행 보류도 유지한다. E4c의 제한된 통과 판정이 있을 때 후속 진행 여부를 별도로 기록한다.

## 2. 질문·가설·제거 범위

**주 질문:** 후보 자신을 제외한 주변 점들이 지지하는 표면을 보존하면서, 반복적으로 확인되는 표면 밖 후보를 기존 plane·depth 정책보다 잘 제거할 수 있는가?

| ID | 가설 | 반증 또는 판단 보류 조건 |
|---|---|---|
| H1 | GT와 위치가 달라도 일관된 국소 표면의 후보는 보존할 수 있다 | 그런 후보의 제거가 증가하거나 표면 coverage가 손상됨 |
| H2 | 명시적 표면 지지와 반복 충돌을 분리하면 기존 plane-zero veto보다 선택성이 좋아진다 | 같은 보존 조건에서 강한 depth/plane 대조군 대비 이탈 후보 제거 이득이 없음 |
| H3 | 후보를 제외한 robust 표면 추정이 단일 돌출점의 자기 지지를 줄인다 | 중심점을 제외해도 이상점에 평면이 끌리거나 정상 경계·얇은 구조가 삭제됨 |
| H4 | 관측 부족을 삭제 근거로 사용하지 않으면 신규·희소 구조를 보존할 수 있다 | unknown을 사실상 불량으로 처리하거나 미관측 영역에 공백이 생김 |

다음 범위를 고정한다.

- **보존 대상:** 추정 점군 안에서 일관된 표면을 이루는 후보. GT 기준 위치 오차와 중복 여부는 별도 속성이다.
- **제거 대상:** 신뢰할 수 있는 국소 표면 지지가 없고, 다른 출처의 가시성 확인 가능한 관측에서 반복적인 표면 앞 충돌을 보이는 후보.
- **판정 보류:** 경계·곡면·얇은 구조·희소 영역·가림·출처 불명·관측 부족·상충 관측. 보류 후보는 렌더 가능한 상태로 유지한다.
- **해결 범위 밖:** 일관된 잘못된 벽, 함께 움직인 잘못된 표면, 안정적인 이중 표면, pose 교정, 표면 뒤쪽에 숨은 후보의 일반적인 판별. 일관성만으로 실제 존재 여부를 확정하지 않는다.

따라서 이번 정책은 모든 기하 outlier를 찾는 검출기가 아니라 **보수적인 표면 이탈 후보 제거기**다. 표면 양쪽의 절대 거리만으로 후보를 삭제하지 않는다.

## 3. 데이터·분할·인과성

### 3.1. 장면 역할

| 역할 | 장면 | 허용 용도 |
|---|---|---|
| 개발 | office0, office1 | 표면 추정·게이트 개발, 임계값 선택, 오류 분석. 둘 다 이미 살펴본 장면 |
| 회귀 | room0, room1, room2 | 기존 구조 보존·렌더링·기하 회귀 검사. 새 독립 test로 표현하지 않음 |
| 새 평가 예정 | office2 주 평가, office3 확인 평가 | 정책·임계값·평가기 봉인 후 최초 평가 |

office2/office3의 데이터 확보와 미노출 여부는 아직 확인하지 않았다. **데이터 접근 전** 저장소·이전 실행 기록에서 장면 사용 여부를 감사하고 등록한다. 이미 살펴본 장면이면 개발 데이터로 분류하고, 미노출 Replica office4를 순서대로 대체 후보로 검토한다. 장면 결과를 본 뒤 유리한 장면으로 교체하지 않는다. 두 미노출 장면을 확보하지 못하면 개발·회귀 결과까지만 보고하고 새 효능 판정은 보류한다.

새 장면은 E4와 같은 원본 1,000프레임 중 짝수 500입력, backbone·weights·seed 0·32-KF buffer·원본 active filter·refinement 0 step을 사용한다. 가용 프레임 부족이나 baseline 생성 실패는 원인과 진행 시점을 기록하며 결과를 보고 입력 길이를 바꾸지 않는다.

### 3.2. 후보·관측 계약

- 대상은 각 장면의 **모든 original-active Gaussian**이다. 제거하기 쉬운 후보만 사후 선별하지 않는다.
- stable ID는 원본 prediction event·branch·pixel과 연결한다. array index와의 대응표를 보존한다.
- 후보, raw pointmap, source-image ancestry, 실제 KF snapshot, 그 시점의 Sim(3)·pose revision을 읽는다. 기존 E4/E3c 상속 경로를 manifest에서 해석한다.
- 실제 판정에는 해당 시점까지 도착한 raw 관측만 사용한다. final pose, 미래 관측, GT pose·depth·mesh·라벨을 feature에 넣지 않는다.
- 후보와 다른 관측의 직접 source-image 중첩을 배제한다. 다른 KF라도 같은 모델·pose graph를 공유할 수 있으므로 통계적 독립이라고 부르지 않는다.
- 표면은 **원본의 고정 raw 점군**으로 추정한다. 정책별 삭제 결과로 기준 표면을 반복 재구성하지 않아 삭제의 자기강화를 막는다.

### 3.3. 정책 관측과 평가 관측 분리

새 정책의 잔차나 최종 membership을 그대로 정답으로 재사용하지 않는다. raw 관측을 prediction event 순서로 정렬한 뒤 `index mod 3 == 2`인 event를 **audit pool**, 나머지를 **policy pool**로 지정한다. 같은 원본 이미지를 직접 공유하는 policy 관측은 audit pool과의 중첩이 없도록 제외한다. 분할·제외 순서와 각 후보의 source 중첩은 별도 manifest에 남긴다.

주 평가용 모든 방법은 같은 policy pool만 접근한다. 후보 생성에 사용한 관측은 해당 후보의 cross-view 근거로 세지 않는다. 후보의 자기 출처 관측은 §4의 **국소 보존 검사**에만 허용한다. audit pool은 추정 표면 평가에만 사용하고, 그 내용으로 test 정책을 갱신하지 않는다. 미래 audit 관측을 사용한 분류는 사후 평가이며 온라인 당시의 가용 증거와 구분한다.

개발 단계에서 이 분할로 source-disjoint 반복 관측이 충분한지 먼저 검사한다. 부족하면 개발 데이터에서만 새 분할 규칙을 amendment로 정하고 다시 봉인한다. 새 평가 후 분할을 완화하지 않는다. 기존 전체 관측을 쓰는 E4 정책의 원래 재현은 별도 참고 arm으로 남겨 관측 축소 효과를 확인한다.

## 4. 기준 표면과 관측 상태

### 4.1. 후보를 제외한 국소 표면

자기 출처 patch와 다른 관측 patch 모두 다음 절차를 사용한다.

1. 기존 predicted-ray 대응으로 5×5 patch를 정한다. GT camera나 GT depth로 대응을 교정하지 않는다.
2. 대응 중심 pixel을 제외한다. 자기 출처 검사에서는 stable ID로 후보와 같은 raw 점이 남지 않았는지도 확인한다. 후보 Gaussian의 중심·opacity는 평면 fit의 입력으로 쓰지 않는다.
3. finite·양의 깊이·confidence ≥1.5 점을 사용하고, 기존 depth-edge·영상 경계 마스크를 적용한다. 최소 9개 점이 없으면 `unreliable`이다.
4. 초기 PCA 뒤 절대 법선 잔차가 큰 상위 20%를 한 번 제외하고 PCA를 다시 계산한다. 동점은 pixel ID 순서로 처리하며, 남은 점이 9개 미만이면 판단을 보류한다.
5. 최종 eigenvalue가 `smallest/middle ≤0.1`, `middle/largest ≥0.05`, `middle >0`을 만족해야 한다. 중심점 주변이 여러 표면이거나 넓게 휘어진 경우 단일 평면을 강제하지 않는다.
6. 법선은 관측 카메라 쪽으로 향하게 한다. 평균·법선·평면 내 점 분포·잔차 두께·인접 점 간격·사용 pixel ID를 저장한다.

이 절차는 robust fit의 시작 설계이며 실패 가능성도 평가한다. 큰 이상점 군집이 평면을 만들면 보존될 수 있다. 곡면 모델·전역 mesh 재구성·학습 기반 segmentation은 주 정책에 추가하지 않는다.

### 4.2. 표면 두께와 Gaussian 크기

관측 patch의 중심을 \(\bar p_j\), 법선을 \(n_j\), 법선 잔차의 robust scale을 \(s_j=1.4826\,\mathrm{MAD}\), 유효 인접 점 간격의 중앙값을 \(h_j\)라 한다. 허용 표면 두께는 다음과 같다.

\[
\tau_j=\max(c_s s_j,\;c_h h_j,\;\varepsilon_j),\qquad
\varepsilon_j=10^{-6}\|\bar p_j\|.
\]

후보를 관측 좌표로 변환한 중심 \(p_i\), covariance \(\Sigma_i\)에 대해

\[
d_{ij}=n_j^\top(p_i-\bar p_j),\qquad
\sigma_{ij}=\sqrt{n_j^\top\Sigma_i n_j},\qquad
u_{ij}=\frac{\max(0,d_{ij}-3\sigma_{ij})}{\tau_j}.
\]

자기 출처 검사에도 같은 단위와 covariance 변환을 적용한다. 추정 pose의 scale은 중심과 covariance에 각각 \(s\), \(s^2\)로 반영한다. GT alignment scale은 평가에만 사용한다. pose 불확실성의 보정된 covariance가 있다고 가정하지 않는다.

개발 탐색은 `(c_s, c_h) ∈ {(3,1), (3,2), (5,1), (5,2)}` 네 조합으로 제한한다. 새 평가 전 한 조합만 선택·봉인한다. 점군 간격과 Gaussian 크기가 큰 후보가 지나치게 쉽게 보호되는지 크기별 결과를 별도로 보고한다.

### 4.3. support / conflict / unknown

기존 plane 점수는 앞쪽 잔차를 0에서 자르므로 **점수 0이 표면 소속을 뜻하지 않는다.** 이번 정책은 원래 signed 잔차와 가시성을 유지해 세 상태를 따로 계산한다.

| 관측 상태 | 정의 |
|---|---|
| `support` | reliable patch이며 `abs(d) ≤ τ + 3σ`. 후보의 평면상 수선점이 patch inlier의 평면 내 convex hull 안에 있어야 함 |
| `conflict` | source-disjoint이고 대응·시차·경계 조건을 통과하며, `u > t`이고 후보가 관측 표면보다 확실히 앞에 있음 |
| `unknown` | 표면 뒤 가림, 대응 불명, patch 범위 밖, 불충분한 점, 비평면, 중간 잔차, 기타 검사 불가 |

앞쪽 확인은 후보와 관측점의 ray 거리 차이가 `3σ_ray + 0.03 × evidence_radius`보다 클 때로 고정한다. ray 대응 허용 각도와 후보–관측 시차는 기존 각각 ≤1°, ≥1°를 유지한다. cross-view에서는 source 분리·ray·시차·경계·patch 자격을 먼저 확인하고, 후보가 표면 뒤로 기존 occlusion band를 초과하면 support/conflict에 앞서 unknown으로 처리한다. 이 공통 자격은 D_surface에도 동일하게 적용한다. 자기 출처 보존 검사에는 source 분리·시차 조건을 적용하지 않는다. 평면의 무한 연장선이 후보를 지지하거나, 표면 뒤 후보가 단지 멀다는 이유로 충돌하는 것을 허용하지 않는다.

자기 출처의 reliable patch가 후보를 지지하면 `local_support`로 기록한다. 이는 후보를 포함한 self residual과 다르며 **보존 근거로만** 사용한다. 자기 출처에서 이탈했다는 사실만으로 삭제하지 않는다. 서로 다른 KF의 cross-view support/conflict 수와 그 시선 간 각도도 따로 저장한다.

## 5. 주 정책과 시간 처리

정책 이름은 `S_surface`로 한다. 매 actual KF snapshot에서 현재까지 도착한 policy 관측과 현재 revision으로 아래 순서대로 재계산한다.

```text
if reliable local_support:
    KEEP_LOCAL
elif cross-view support가 2개 이상이고 시선 간 각도 >= 1도:
    KEEP_MULTI
elif cross-view support가 하나라도 있음:
    UNKNOWN_MIXED로 보존
elif cross-view conflict가 서로 다른 KF에서 2개 이상이고
     그 시선 간 각도 >= 1도:
    REJECT
else:
    UNKNOWN으로 보존
```

- 동일 event의 여러 branch나 같은 KF의 중복 기록을 반복 근거로 세지 않는다. KF가 달라도 source/model 독립성을 보장하는 것은 아니다.
- 두 개의 양수 잔차만으로 삭제하지 않고, **표면 지지 부재와 반복적인 가시성 확인 충돌**을 함께 요구한다.
- `KEEP_LOCAL`, `KEEP_MULTI`, `UNKNOWN`은 렌더 가능한 상태다. hard DEFER와 queue 구현은 이번 범위에 넣지 않는다.
- 다음 실제 KF에서 살아 있는 후보를 재검사한다. 한 시점의 두 관측 조건을 여러 시점의 한 관측씩 누적으로 대체하지 않는다.
- REJECT는 E4와 같이 absorbing이다. 삭제 전의 support/conflict·pose revision·최초 제거 시점을 모두 남긴다. 이후 revision에서 판정이 뒤집힐 수 있었는지는 사후 진단으로만 보고한다.
- Gaussian 위치·covariance·색·opacity를 수정하지 않는다. 고정 후보 지도에서 membership만 바꾼다.

## 6. 비교군·ablation·임계값 개발

### 6.1. 필수 비교군

| 방법 | 역할 |
|---|---|
| B1 original | original-active 전부 유지 |
| P2 legacy | E4의 plane 점수·2+·plane-zero veto·봉인 임계값. policy pool에서 재실행 |
| B6 legacy | 기존 depth median·봉인 임계값. policy pool에서 재실행 |
| D_maskmedian legacy | 기존 공통 gate·median-depth·봉인 임계값. policy pool에서 재실행 |
| **D_surface** | S_surface와 같은 patch·가시성·local/cross support veto·2+ 조건에서 depth 잔차만 사용 |
| **S_surface** | 제안한 표면 지지·반복 plane 충돌 정책 |
| S_no_local / S_no_robust | 각각 자기 출처 국소 보존 검사 제거 / 중심 제외 후 trimming 제거. 기전 확인용 |
| B2 confidence, B7 RGB, B8 DoG proxy | E4 강한 참고 대조군. 접근 가능한 policy 관측·같은 후보·원래 임계값으로 실행 |

`D_surface`의 충돌 점수는 `max(0, evidence_radius - candidate_radius - 3σ_ray) / evidence_radius`이며, 그 외 support와 가시성·반복 조건은 S_surface와 같다. PCA를 쓰지 않는 baseline이라고 부르지 않는다. legacy 방법은 원래 정의를 유지하므로 관측 자격 차이가 남는다. D_surface가 잔차 종류의 추가 가치를 분리하는 주 대응 대조다.

### 6.2. 보정과 선택 규칙

새 S_surface/D_surface의 임계값은 **개발 장면의 분리된 audit 표면 분류(§7)**로만 보정한다. 새 test GT나 RGB를 사용하지 않는다. 기존 legacy 임계값은 재보정하지 않고, 다른 보정 목적이라는 점을 표에 표시한다.

각 후보의 전체 개발 이력에 대해, **임계값과 support veto를 적용하기 전** 공통 관측 자격·반복 수를 통과한 snapshot의 두 번째 큰 잔차를 구하고 그 시간 최댓값을 calibration score로 쓴다. support로 보호되는 후보도 이 보수적인 보정용 잔차를 계산한다. 유효하지만 앞쪽 잔차가 없는 관측의 수치 잔차는 0이며, 그 값으로 support를 추론하지 않는다. 반복 관측 자체가 없으면 NaN으로 남긴다. 이후 실제 replay에서는 §5의 표면 보호와 별도의 앞쪽 확인을 적용한다. 임계값을 알아야만 calibration 표본을 만들 수 있는 순환을 허용하지 않는다.

own/common-ever-finite는 이 보정용 잔차의 유한 여부로 정의하고, 실제 정책의 표면 보호·판정 가능 비율은 별도로 보고한다. 시간 최댓값은 후보의 개발 중 한 번이라도 잘못 삭제될 위험을 보정하는 용도이며 실제 판정의 미래 gate로 사용하지 않는다.

- audit `surface-supported` 후보의 score에서 99% higher quantile을 계산하고 strict `>`로 제거한다. S_surface는 `t ≥1`로 제한한다.
- 개발 장면별 own-finite·두 방법 common-finite·anchor별 보존을 모두 확인한다. 각 집합 표본이 ≥100일 때 얻은 quantile의 최댓값을 사용하며, 필수 장면별 own/common 표본이 부족하면 보정 불가다. 작은 anchor는 별도 보고한다.
- 네 두께 조합 중 두 개발 장면 모두 audit 표면 보존 ≥99%, 기존 GT normal 보존 ≥99%, §9의 지도 손상 한도를 만족하는 조합만 남긴다.
- 그중 S_surface의 장면 평균 audit 이탈 후보 recall이 최대인 조합을 선택한다. 동률이면 장면별 표면 오삭제율의 최댓값이 작은 조합, 평균 scoring 시간이 짧은 조합, 위 기재 순서로 정한다. D_surface에도 선택된 같은 표면 조합과 동일한 보정 절차를 적용한다.
- 통과 조합이 없으면 개발 REVISE이며 새 평가를 열지 않는다. ablation은 같은 조합을 사용하고 각자의 임계값을 같은 절차로 개발 보정한다.

보존 조건으로 전부 남기는 정책이 선택되지 않도록 §9의 최소 제거량과 recall 기준을 적용한다. 개발 과정에서 정의나 탐색 범위를 바꾸면 노출 범위·이유를 amendment에 남긴 뒤 새 평가 전에 다시 봉인한다.

## 7. 평가용 표면 분류와 기존 GT 라벨

### 7.1. 분리된 관측에서 만드는 표면 일관성 proxy

audit pool의 raw 점군만으로 정책과 별도인 평가기를 만든다. 후보 자신과 후보 생성에 참여한 source 이미지는 제외한다. 평가는 고정된 원본 후보 전체에 적용하고 정책의 score, 삭제 여부, 선택된 두께 조합을 입력받지 않는다.

평가기는 audit 관측 각각의 **7×7 중심 제외 patch**, 최소 18개 유효 점, deterministic RANSAC plane fit을 사용한다. 평면 inlier 거리는 `2 × 해당 patch의 median spacing`, 반복 수 64, seed 0, 최소 inlier 비율 80%, spread 조건은 §4의 eigenvalue 조건으로 고정한다. 서로 다른 audit KF의 시선 간 각도 ≥1°를 요구한다. 구현 수치 검사 후 새 평가 전에 별도로 봉인하며, test에서 patch·거리·필터를 바꾸지 않는다.

후보의 3σ 법선 extent를 고려한 표면 band는 `2 × median spacing`이다. ray·경계·평면 hull 검사를 통과한 관측에서 `abs(d) ≤ band + 3σ`이면 audit support, `d > band + 3σ`이고 §4의 앞쪽 확인도 통과하면 audit conflict, 나머지는 unknown이다.

| audit 분류 | 조건 |
|---|---|
| `surface-supported` (S) | 서로 다른 audit KF 2개 이상의 support와 시선 다양성, conflict 0 |
| `surface-outlier` (O) | 서로 다른 audit KF 2개 이상의 conflict와 시선 다양성, support 0 |
| `ambiguous` (U) | support/conflict 혼재, 경계·비평면·가림·반복 부족 등 나머지 |

이는 **분리된 예측 관측에 대한 일관성 proxy**이며 물리적 GT가 아니다. 같은 predictor의 공통 오류와 평가기 자체의 실패가 남을 수 있다. 후보별 단순 이분법 외에 audit 관측 수·잔차·각도·검사 불가 사유를 함께 저장한다.

필수 지표는 `O recall = 제거한 O / 전체 O`, `S retention = 보존한 S / 전체 S`, `precision = 제거한 O / 제거한 (S+O)`다. U 제거량·비율을 별도로 보고하며 U를 정상·이상 어느 쪽에도 넣지 않는다. 전체 active, audit 분류 가능, 각 방법 판정 가능, 공통 판정 가능 분모를 모두 보고한다. 주 recall은 방법의 finite 여부로 분모를 줄이지 않는다.

### 7.2. GT 정확도는 별도 축으로 유지

기존 E1 creation 라벨의 bad=3, normal=1/2, unknown=0을 그대로 생성·보존한다. GT-anchor와 cross-pose-consensus는 민감도 분석으로 남긴다. `S/O/U × GT bad/normal/unknown`을 교차 집계하고 각 칸의 보존·제거 수를 보고한다.

특히 **`S ∩ GT bad`의 보존율**을 제시한다. 이 후보를 보존했다고 GT 정확도가 좋아졌다고 주장하지 않으며, 해당 목표에서 의도한 보존인지 확인한다. 기존 GT bad recall 증가를 E4c의 주 성공 조건으로 삼지 않는다. GT normal 손상·렌더링·기하 악화는 계속 검사한다.

새 평가 장면에서는 모든 방법의 membership와 최초 제거 기록을 봉인한 뒤 audit 분류·GT 라벨·held-out RGB·기하 품질을 산출한다. 평가 파일을 feature 추출 경로에서 읽을 수 없는지 검사한다.

## 8. 지도 품질·수량·시간 평가

**주 arm은 natural pruning이다.** 제거량을 늘리기 위한 random fallback은 주 실험에 넣지 않는다. 장면별 원본 수·제거 수·local/multi support 수·unknown 수·남은 parameter bytes를 함께 보고한다.

- 최종 지도 RGB: E4와 동일한 홀수 frame `1,101,201,301,401,501,601,701,801,901,999`의 PSNR/SSIM/LPIPS. source appearance·렌더러·resize/crop·노출 정규화는 전 방법 동일하다.
- 시간별 지도: 각 actual KF 직후 첫 홀수 frame에서 coverage·RGB·depth를 검사한다. 아직 태어나지 않은 후보를 넣지 않는다.
- 기하: GT-valid pixel coverage, 공통 covered pixel의 depth L1, 방법별 covered pixel의 L1과 valid 표본 수를 함께 보고한다. coverage 감소로 오차가 좋아 보이는 경우를 구분한다.
- TSDF: E4의 짝수 20개 fusion view, voxel 4 cm·truncation 12 cm·weight >0.001·최대 depth 10 m·seed 0 표면 100,000개 샘플·5 cm precision/completion/F1을 재사용한다. 관측 영역 reference이며 전체 장면 GT mesh라고 부르지 않는다.
- GT 정렬은 E4와 같은 평가 전용 global Sim(3)로 고정한다. 후보·patch·방법별 depth fitting을 하지 않는다.
- scoring CPU/GPU 시간·최대 메모리·후보당 비용·최종 Gaussian 수와 52 bytes/Gaussian parameter buffer를 보고한다. 실제 compact buffer의 resident/allocated/peak 측정이 없으면 VRAM 절감으로 표현하지 않는다.

보조 자원 비교는 장면마다 **S_surface natural의 생존 수 K**로 고정한다. B1 random seeds 0/1/2, B2/B6/B7/B8/P2/D_surface에 E4의 동일 seed 0 survivor fallback을 적용한다. 자연 생존 수가 K 미만인 방법은 도달 불가로 표시하고 복구하지 않는다. 자연 제거와 fallback 제거를 분리하며 이 비교는 사후 동일 수량 진단이다. online quota 효과나 주 효능 판정을 대신하지 않는다.

## 9. 사전 성공 기준과 해석

아래 수치는 **E4c의 제안 기준**이다. 개발·평가기 구현 및 실행 등록 시 확정해 새 평가 전에 봉인한다. E4/E3c 기준을 소급 교체하지 않는다.

### 9.1. 평가 성립 조건

새 평가 두 장면 각각에서 audit S ≥100, O ≥100, `(S+O)/original-active ≥1%`여야 한다. S_surface/D_surface의 common-ever-finite 후보에서도 S와 O 각각 ≥100을 요구한다. 평가 성립 조건을 충족하지 못하면 **관측·평가 coverage 부족으로 판단 보류**하며 작은 부분집합 결과만으로 GO를 내리지 않는다.

### 9.2. 주 정책 통과 조건

office2/office3의 확정된 두 새 장면 **각각**에서 다음을 모두 만족해야 한다.

| 항목 | 기준 |
|---|---|
| audit 표면 보존 | 전체 S 및 own/common-ever-finite S에서 retention ≥99%. S ≥100인 anchor별로도 ≥99% |
| GT normal 보존 | 전체 및 own-ever-finite normal에서 ≥99%. normal ≥100인 anchor별로도 ≥99% |
| 유효한 제거 | O 제거 ≥30개, 전체 O recall ≥5% |
| 잔차의 추가 가치 | S_surface의 전체 O recall이 D_surface보다 ≥2%p 높고, labeled precision 하락 ≤0.1%p |
| 기존 정책 대비 효용 | B6 legacy, D_maskmedian legacy, P2 legacy 중 §9의 보존·지도 손상 한도를 만족한 각 방법보다 O recall ≥2%p 개선 |
| 최종·시간별 coverage | B1 대비 최종 및 각 시간별 frame의 손실 ≤0.5%p |
| RGB 보존 | B1 대비 최종 평가 frame 평균 PSNR 손실 ≤0.2 dB, SSIM 손실 ≤0.005, LPIPS 증가 ≤0.01 |
| depth 보존 | B1 대비 공통 covered GT-valid pixel의 평균 depth L1 증가 ≤5 mm |
| TSDF 보존 | B1 대비 sampled Chamfer 악화 ≤2%, completion ratio 손실 ≤1%p |

legacy 세 방법이 모두 보존·지도 조건에 실패하면 그 실패는 보고하되, 강한 기존 정책 대비 효용은 **비교 성립 불충분**으로 남긴다. D_surface는 보존·지도 한도와 최소 O 제거·recall 조건을 만족해야 주 대응 비교가 성립한다. 이를 만족하지 못하면 S_surface 단독 결과만으로 plane 잔차의 우위를 주장하지 않는다. 분모가 0이거나 도달 불가인 지표를 통과로 처리하지 않는다.

개발·회귀 장면에도 표면/GT normal 보존 및 지도 손상 한도를 적용해 회귀 실패를 공개한다. 회귀 안전 조건 실패는 새 장면 통과와 별도로 남기며 전체 정책 승격은 보류한다. S∩GT bad가 100개 이상인 장면은 그 부분집합 retention ≥99%도 요구하고, 그보다 적으면 해당 가설은 표본 부족으로 표시한다.

### 9.3. 판정 종류

- **GO_FOR_E5_REVIEW:** 두 새 장면의 평가 성립·주 조건과 회귀 안전 조건을 모두 충족. ‘고정 후보 지도에서 표면 일관성 기준의 선택적 제거 이득’을 지지한다. E5 진행 검토를 허용하며 전반적 GT 복원 개선·다장면 일반화·실시간성·논문 novelty를 확정하지 않는다.
- **REVISE:** 평가가 성립했지만 주 비교 이득·보존·지도 조건 중 하나라도 미달. 제거 0개로 안전 조건만 통과한 경우도 포함한다.
- **INCONCLUSIVE:** 미노출 장면 확보 실패, audit 분류·common 관측 부족, baseline/필수 대조군·평가 산출 실패. 실패 사유와 완료 범위를 명시한다.

장면 평균으로 한 장면의 손상을 상쇄하지 않는다. 개발에 사용한 office0/office1을 독립 검증 근거로 세지 않는다. 후보 수백만 개를 독립 표본으로 취급한 유의성 주장은 하지 않는다.

## 10. 검증·고정 사례·산출물

### 10.1. 구현 시 필요한 수치·인과성 검사

1. 후보·주변 평면·카메라를 함께 같은 Sim(3)로 변환하면 국소 표면 지지와 정규화 점수가 유지되는지 확인한다. GT 정확도 주장이 아닌 좌표·단위 검사다.
2. 중심점만 이동한 작은 고정 fixture에서 후보 제외 fit과 반복 conflict가 동작하고, 중심점 포함 fit의 자기 지지를 구분하는지 확인한다.
3. 표면 뒤 가림, 경계, 곡면, 얇은 구조, 점 부족이 conflict로 강제 변환되지 않는지 확인한다.
4. 양·음의 큰 signed 잔차와 0 score를 넣어 `support != score_zero`를 검사하고, patch hull 밖 지지를 차단한다.
5. 하나의 event/KF 중복·미래 관측·source 중첩·audit 접근을 탐지한다. 두 KF 수와 시선 다양성 조건을 각각 검사한다.
6. Sim(3) 중심/covariance 변환, NaN 전파, strict threshold 동점, 최초 제거/revision, absorbing 상태와 재현성을 검사한다.
7. 기존 전체 관측 legacy 점수·finite mask·membership가 봉인된 E4 결과와 일치하는지 확인한 뒤, policy-pool arm을 별도 경로로 계산한다.

대규모 공통 offset·scale·pose perturbation의 성능 곡선은 E5에 남긴다. 위 작은 fixture 검사를 새로운 합성 효능 실험으로 보고하지 않는다.

### 10.2. 고정 사례와 그림

각 장면의 `(S/O/U) × (보존/제거)` 집합에서 stable ID 정렬 후 seed 0으로 최대 8개를 뽑는다. 별도로 `S∩GT bad`에서 최대 8개를 뽑는다. **그림 검사 전에** ID를 저장하며 빈 집합·검사 불가·불리한 사례를 교체하지 않는다.

source/evidence RGB, 중심을 제외한 patch와 inlier, 표면 단면·두께·Gaussian 3σ extent, support/conflict/unknown 시간선, 원본/선택 지도 렌더 차이를 보여준다. local support와 multi-view support를 같은 표시로 합치지 않는다. 방법 간 선택 차이는 전체 집계와 함께 보고한다.

### 10.3. 예정 산출물

이번 변경은 계획 Markdown만 추가한다. 아래는 구현·실행 시 만들 경로이며 현재 존재나 실행 가능성을 보장하지 않는다.

- 설정·등록: `configs/e4c_surface_consistency_pruning.json`, `configs/e4c_protocol_registration.json`, `configs/e4c_preregistration.json`.
- 실행: `results/E4c_surface_consistency_pruning/` 아래 `input_manifest.json`, `exposure_audit.json`, `evidence_split.json`, `environment.json`, `seal.json`, `sealed_code/`.
- 장면별: 원본 ID 대응, patch 통계·실패 gate, 후보×snapshot×관측 상태, membership/최초 제거/revision, audit S/O/U·GT 교차 라벨, calibration·비교 지표, 고정 사례·그림.
- 검증·보고: `configs/e4c_validation.json`, `configs/e4c_results_summary.json`, `docs/experiments/E4c_surface_consistency_pruning_results.md`.

## 11. 실행 순서와 완료 조건

1. **실행 등록 준비:** 새 장면의 노출 이력·데이터 가용성, 기존 baseline 상속, candidate ID·source ancestry 계약을 확인한다. 이 단계에서 새 장면 RGB/GT/점군 결과를 살펴보지 않는다.
2. **개발 구현:** office0/office1에서 후보 제외 robust patch, 세 관측 상태, local 보존, paired depth, audit 분할·평가기를 구현한다. 수치·인과성 검사를 통과한다.
3. **개발 성립 검사:** 분리 관측 coverage, audit S/O 표본, 네 조합의 개발 보정과 회귀 안전성을 검사한다. 불충분하면 원인을 기록하고 개발 단계에서 개정한다.
4. **새 평가 전 봉인:** 장면·분할·후보 scope·표면/평가 정의·방법·임계값·성공 기준·코드/입력/모델 hash·환경을 확정한다. test에서 변경할 항목을 남겨 두지 않는다.
5. **새 baseline·정책 실행:** 같은 조건으로 두 새 baseline을 생성하고 모든 방법의 policy-pool 점수·natural membership·최초 제거를 확정한다. 접근 기록과 정책 결과를 먼저 봉인한다.
6. **평가:** audit 분류와 GT 라벨을 생성하고 최종·시간별 RGB/depth/TSDF, 회귀, 고정 사례, 보조 동일 수량 비교를 수행한다.
7. **최종 보고:** 모든 필수 방법·분모·unknown·미달·실패·hash 검증을 포함한 결과 문서를 작성하고 §9의 판정을 낸다. 미완료 단계가 있으면 실행 완료나 GO로 표현하지 않는다.

기존 E4/E4b 문서·봉인·결과 디렉터리는 덮어쓰지 않는다. E4c 평가를 본 뒤 정책을 바꾸면 해당 장면은 개발/회귀 데이터로 전환하고 새로운 독립 검증을 별도로 등록한다. E4c의 실행 명령은 구현 후 실제로 검증한 것만 결과 문서에 기록한다.
