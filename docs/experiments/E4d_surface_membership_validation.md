# E4d: 정점의 표면 소속 판정과 pruning 효용 검증

**상태: 계획 초안·미구현·미실행(2026-10-22).** 이 문서는 [E4c 결과](E4c_surface_consistency_pruning_results.md)를 확인한 뒤 작성한 새 개발 계획이다. 데이터 가용성·audit pose/scale 호환성·평가기 성립 여부는 아직 확인하지 않았다. 아래 수치는 제안 기준이며 개발 구현 후 새 평가 전에 설정·코드·분할·임계값과 함께 등록·봉인한다.

**목표:** 추정 점군의 일관된 표면에 속하는 정점은 보존하고, 신뢰할 수 있는 주변 표면에서 이탈한 정점에 대응하는 Gaussian을 선택적으로 제거한다. 실제 위치에서 벗어난 표면 전체의 교정은 별도 문제로 남긴다.

E4d는 다음 두 단계로 나눈다.

| 단계 | 확인할 것 | 다음 단계 조건 |
|---|---|---|
| **E4d-A: 평가·개발 성립** | 표면 소속 분류, 별도 audit 관측, 보정 가능 표본, 개발·회귀 안전성 | A0/A1/A2 gate를 모두 통과하고 정책·평가기 봉인 |
| **E4d-B: 새 장면 효용** | 미노출 장면에서 실제 제거·표면 보존·지도 품질·강한 대조군 비교 | 두 새 장면의 주 기준을 모두 만족하면 `GO_FOR_E5_REVIEW` |

E4d-A만 통과하거나 실험을 실행했다는 사실로 E5에 자동 진입하지 않는다. 기존 E4 REVISE와 E4c INCONCLUSIVE는 보존하며 E5/E6 효능 검증 보류도 별도 진행 판정 전까지 유지한다.

## 1. E4c에서 바꾸는 부분

| E4c의 관측 또는 한계 | E4d의 변경 |
|---|---|
| audit용 KF를 떼어 내면서 policy 반복 관측과 평가 대상이 겹치지 않음 | **policy는 전체 기존 KF 관측을 유지**하고, 별도의 평가 입력으로 audit 관측을 생성 |
| 다른 두 관측과의 앞쪽 충돌을 이탈 정답 O로 정의 | **주변 표면에 속하지 않는다는 적극적인 증거**와 audit 충돌을 함께 요구 |
| 자기 출처 support에 Gaussian의 3σ를 포함 | 정점 중심의 표면 소속과 Gaussian의 표면 중첩을 별도 계산 |
| source 중심의 큰 깊이 점프가 dilated edge mask를 통해 주변 fit 자체를 막을 수 있음 | 후보를 제외한 이웃의 경계·다중 표면 구조를 검사하고, 후보 중심의 잔차는 별도 평가 |
| support 수선점의 hull 조건을 충돌에도 적용한 초기 구현 오류 | [E4c A2](E4c_v2_execution_amendment.md)의 구분 유지: support는 수선점, 충돌 자격은 ray–plane 교점의 유효 표면 범위 |

office1의 E4c audit O 13,926개 중 13,908개는 당시 자기 출처 support를 받았다. **이 수치는 3σ를 포함한 판정이며, 정점 중심들이 실제로 일관된 표면을 이룬다는 증명은 아니다.** E4d에서 center-only 소속을 다시 확인한다. 반대로 이 후보들을 다른 관측과 충돌한다는 이유만으로 모두 제거 정답으로 재사용하지 않는다.

## 2. 가설과 범위

| ID | 가설 | 반증·보류 조건 |
|---|---|---|
| H1 | 정점 중심의 표면 소속을 사용하면 일관된 추정 표면을 보존하면서 이탈 후보를 구분할 수 있다 | 보호해야 할 표면 손상 또는 원본/강한 대조군 대비 유효한 제거 이득 없음 |
| H2 | 추가 audit 입력으로 policy 관측을 줄이지 않고 같은 후보를 평가할 수 있다 | pose/scale 호환성 또는 공통 평가 표본 부족 |
| H3 | 신뢰할 수 있는 국소 비소속 증거와 반복 앞쪽 충돌의 결합이 선택적이다 | 희소·경계·얇은 구조를 삭제하거나 전부 보존하는 무효 운영점만 존재 |
| H4 | 이 정책의 효용은 실제 지도에서도 유지된다 | coverage·렌더링·기하 품질 손상 한도 초과 |

현재 단계는 고정 후보·고정 추정 pose에서 membership만 바꾸는 실험이다. Gaussian 위치·크기·색·opacity, tracker, 원래 mapping-input KF 선택과 refinement 0 step은 유지한다. 전역 표면 교정·중복 제거·온라인 큐·SLAM 속도 개선은 주 목표에 넣지 않는다.

추정된 표면이 GT와 다르거나, 별도의 일관된 표면 성분이 존재한다는 이유만으로 삭제하지 않는다. 경계·곡면·얇은 물체·미관측·가림·pose 불안정·관측 모순은 명시적인 불확실 상태로 남긴다. 이번 제거 양성은 신뢰할 수 있는 주변 표면에서 법선 방향으로 이탈하고 앞쪽 관측으로 확인 가능한 경우다. 접선 방향의 표면 끝 바깥, 뒤쪽·미관측 후보 전체의 검출까지 주장하지 않는다.

## 3. 장면·입력·출처 계약

### 3.1. 장면 역할

| 역할 | 장면 | 용도 |
|---|---|---|
| 개발 | office0, office1 | 이미 확인한 장면. 평가기·audit 파이프라인·임계값 개발 |
| 회귀 | room0, room1, room2 | 구조·지도 보존 확인. 독립 효능 test로 재사용하지 않음 |
| 새 평가 후보 | office2, office3 | 데이터 접근 전 사용 이력을 감사하고, 봉인 후 최초 효능 평가 |
| 사전 대체 후보 | office4 | 위 후보가 미노출/가용 조건을 만족하지 못할 때만 순서대로 검토 |

미노출 여부는 로컬 기록과 실행 manifest로 먼저 확인한다. 두 새 장면이 확보되지 않으면 개발 결과만 보고한다. 새 장면의 결과·T 개수·점수를 본 뒤 평가 장면을 교체하지 않는다.

기준선 입력은 기존과 같은 원본 frame 0–999의 짝수 500개, 같은 backbone·weights·seed 0·32-KF buffer·원본 active filter다. 기존 장면의 원본 산출물은 읽기 전용으로 재사용하고 상속 경로와 해시를 manifest에서 해석한다.

### 3.2. policy pool

원래 KF raw self-branch 중 **후보 생성 원본과 source-image가 겹치지 않고 판정 시점까지 도착한 모든 관측**을 사용한다. audit 때문에 이 관측들을 제거하지 않는다. 각 관측의 정확한 raw event·branch·source pair·decision-time Sim(3)와 revision을 연결한다.

후보는 모든 original-active Gaussian이다. 자기 출처 이웃은 국소 소속/비소속 검사에만 사용하며, 반복 cross-view 관측 수에 포함하지 않는다. 서로 다른 KF와 ≥1° 시선 다양성을 요구하고, 같은 KF의 여러 branch를 반복 관측으로 세지 않는다.

출처 ID는 모든 파이프라인에서 `(scene, original_frame_id)`로 정규화한다. 기존 `source_image_ids`의 mapping-input index는 `2 × index`로 원본 frame에 대응하고, 새 audit의 입력 index도 별도 mapping으로 원본 frame에 대응한다. 서로 다른 입력 목록의 정수 index를 직접 비교하지 않는다.

## 4. 별도 audit 관측 확보

### 4.1. 평가 입력과 RGB test 분리

policy에 쓰지 않은 홀수 frame으로 **평가 전용 replay**를 별도로 실행하는 방식을 우선 검증한다. 모델·weights·seed는 고정하고, 이 replay의 pose/map/pointmap을 원래 policy baseline에 되먹이지 않는다. audit 계산 비용은 평가 비용으로 따로 보고한다.

최종 RGB test frame은 기존의 `1,101,201,301,401,501,601,701,801,901,999`로 고정한다. **이 11개 frame은 audit tracking·pair prediction·pose fit을 포함한 audit의 모든 입력에서도 제외한다.** 따라서 audit replay 후보 입력은 나머지 홀수 489개다. 단지 policy에 들어가지 않았다는 이유로 audit가 본 RGB를 held-out 렌더 평가에 사용하지 않는다.

평가 pointmap probe는 각 mapping KF의 원본 frame `f`에 대해 `f + {-41,-21,-11,-1,1,11,21,41}` 중 범위 안의 허용 홀수 frame으로 정한다. 중복·RGB test frame은 제외하며 내용·점수·라벨에 따라 추가하거나 교체하지 않는다. audit pair의 두 원본 이미지도 모두 허용된 홀수 입력이어야 한다. audit 시선 ID는 probe의 원본 frame으로 정의하고, 같은 frame의 여러 branch를 여러 시선으로 세지 않는다. 서로 다른 probe라도 시선 각도 ≥1°를 요구한다. audit 관측끼리 reference 이미지를 공유하는 경우는 따로 기록하며 통계적으로 독립이라고 부르지 않는다.

이 방식은 **직접 geometry prediction 입력의 source 분리**다. 같은 가중치, 기존 추정 trajectory에 대한 정렬, 모델의 공유 오류가 남으므로 통계적 독립이나 외부 GT라고 표현하지 않는다.

### 4.2. audit pose와 scale: 구현 성립 gate

현재 저장된 non-KF raw에 임의로 가까운 KF pose를 붙이지 않는다. audit replay에서 probe raw self-branch와 정확히 대응하는 **추정 frame pose·scale·branch 변환·기록 시점**을 내보낼 수 있는지 먼저 확인한다. 이 export 기능은 아직 구현·검증되지 않았다.

별도 audit 좌표계와 원래 baseline 좌표계는 camera trajectory만으로 단일 Sim(3)을 정한다. 목표 camera center/orientation은 저장된 원래 추정 trajectory를 audit timestamp에 보간한 값이다. point cloud·Gaussian·GT depth/mesh에 대한 surface fitting, patch별 scale 보정은 금지한다.

초기 제안 정렬 gate는 대응 pose ≥6개, 시퀀스의 세 시간 구간에 대응 존재, camera-center `middle/largest` 분산 비 ≥0.05, 양의 scale이다. 원래 camera-center들의 기하 중앙값에 대한 거리 중앙값을 robust radius R로 정의하고, 정렬 중심 잔차 median ≤0.02R·p95 ≤0.05R, orientation 잔차 median ≤5°를 요구한다. R≈0이거나 scale이 식별되지 않으면 실패다. 이 gate는 개발에서 구현 수치 검사를 거쳐 새 평가 전 확정한다.

정렬 gate를 통과해도 잔차를 0으로 취급하지 않는다. 시간 세 구간을 하나씩 제외한 pose-only 정렬에서 scale 변동 `δs`, 전체 정렬의 translation 잔차 `r95`, orientation 잔차 `θ95`를 기록한다. 깊이 z의 초기 pose 여유는 `m_pose(z)=r95+z×sin(min(θ95,90°))+z×δs`로 두고, audit 앞쪽 이탈은 표면 band와 이 여유를 함께 넘는 경우만 확정한다. 이는 추정 정렬의 민감도 여유이며 보정된 통계적 신뢰구간이 아니다. audit C 판정은 여유를 더해 쉽게 통과시키지 않고, 구간 제외 정렬에서 소속이 바뀌면 U로 남긴다.

raw 좌표와 해당 pose의 결합, Sim(3)의 중심/covariance 변환, source-pixel ray와 투영, 시간 순서를 작은 고정 사례에서 재현한다. 정렬 잔차·검사 불가 frame·source 중첩을 전수 기록한다. 정렬 불안정으로 표면 소속이 달라지는 후보는 U로 남긴다.

**pose/scale 계약이 성립하지 않으면 audit 라벨을 만들지 않고 A1에서 중단한다.** 보완 관측 경로를 개발하려면 새 amendment를 먼저 남긴다. GT pose 또는 원래 policy pointmap에 대한 기하 정렬로 조용히 대체하지 않는다.

## 5. 평가용 표면 소속 정의

### 5.1. center-only와 extent 판정 분리

정점의 소속은 **중심 μ와 후보를 제외한 주변 정점의 표면**으로 정의한다. Gaussian covariance·opacity·policy score·REJECT 여부·GT 라벨을 평가용 center 소속의 입력으로 쓰지 않는다. Gaussian 3σ가 표면에 걸치는지는 별도 `extent_overlap` 속성이다.

표면 위치의 GT 오차는 분류 기준이 아니다. GT 라벨은 이후 별도 정확도 축으로 유지한다.

### 5.2. 후보를 제외한 두 평가기

평가기의 코드와 상수는 정책과 별도로 봉인한다. 주 기준은 다음 두 평가기의 **합의**다.

| 평가기 | 후보 이웃과 방법 | 초기 제안 자격 |
|---|---|---|
| R_image | 자기 출처 raw의 중심 제외 7×7/13×13 patch, deterministic RANSAC | 유효 점 ≥18/36, inlier ≥80%, seed 0·64 hypotheses, 두 scale 법선 차 ≤15° |
| R_space | 같은 raw에서 후보를 뺀 3D kNN 32/64, robust plane/component 검사 | 접선 spread·연결성·후보 주변 분포 확인. 반대편/다른 성분이 섞이면 U |

R_image의 초기 RANSAC inlier band는 fit 전에 이웃만으로 계산한 `2 × median spacing`으로 고정하고, R_space는 한 차례 상위 20% 잔차 trimming 후 refit을 시작점으로 한다. E4c의 eigenvalue spread/planarity 조건을 계승하되 두 평가기의 연결 성분·다중 표면 판정·동점·근접 중복 처리까지 A0에서 명문화한다. 구현 후 새 장면을 열기 전에 확정하지 못한 조건을 남겨 두지 않는다.

각 scale의 표면 band는 `τ_ref = max(3 × normal-residual MAD scale, median neighbour spacing, 10^-6 × surface_mean_range)`으로 시작한다. 마지막 range는 후보를 제외한 fit 중심의 거리다. MAD scale은 1.4826을 포함한다. center 포함 간격이나 후보까지의 거리를 band 추정에 사용하지 않는다. 표면의 tangential hull과 후보 주변 네 방향 중 최소 세 방향의 이웃 분포를 확인한다.

- **소속 증거 C:** 두 평가기의 두 scale에서 center 법선 거리 ≤τ_ref이고 유효 표면 범위 안에 있음.
- **비소속 증거 N:** 두 평가기의 두 scale에서 신뢰할 수 있는 주변 표면이 존재하고 center 거리 >3τ_ref이며, 방향이 일관된 이탈을 확인함. 자기 출처의 후보 광선–평면 교점이 양의 거리에서 해당 표면 hull 안에 있어야 함.
- **불확실:** 두 band 사이, 평가기 불일치, 다중 표면 선택 불명, 부족한 점, 경계·곡면·얇은 구조 등.

단순 저밀도나 fit 실패는 N이 아니다. 후보 중심의 깊이 점프만으로 주변 patch 전체를 edge-invalid로 만들지 않고, 후보를 제외한 이웃들 사이의 경계·분리 성분을 검사한다. 여러 일관된 표면이 있으면 그중 어느 표면에라도 속하는 후보를 N으로 만들지 않는다. 작은 구조의 소속을 확인할 수 없으면 U다.

R_image/R_space는 같은 추정 데이터를 공유하므로 합의도 물리적 정답은 아니다. 이는 정책 결과를 재사용하지 않는 **추정 표면 소속 proxy**다. 고정 사례·두 평가기 불일치·정렬 민감도와 실제 지도 품질을 함께 보고한다. 평가기 상수는 개발 검증 후 확정하고 새 장면에서 바꾸지 않는다.

### 5.3. 최종 P/T/U 라벨

| 라벨 | 정의 |
|---|---|
| **P: protected surface** | 자기 출처에서 C, 또는 서로 다른 audit 시선 두 개 이상이 동일한 표면 성분의 center 소속을 지지. 다른 관측의 앞쪽 충돌만으로 P를 뒤집지 않음 |
| **T: confirmed target** | 자기 출처에서 N **및** source-disjoint audit의 서로 다른 두 시선에서 가시성이 확인된 앞쪽 표면 충돌 **및** 어떤 신뢰할 수 있는 표면에서도 C 지지가 없음 |
| **U: unassessable** | 위 두 조건을 충족하지 않거나 pose/대응/가림/소속이 불명 |

P를 먼저 검사하고 P/T는 상호 배타적으로 저장한다. audit의 support는 center 거리와 수선점의 유효 범위로, 앞쪽 충돌은 양의 ray–plane 교점이 표면 범위 안인지와 depth 방향으로 검사한다. audit 표면 band·pose 정렬 오차 범위를 넘어서 확실한 앞쪽 사례만 T에 사용한다. 뒤쪽 거리만으로 T를 만들지 않는다.

**P에는 자기 출처에서 분명한 표면에 속한 후보가 포함되므로 P 전체에 audit 두 시선을 요구하지 않는다.** 반면 T를 확정할 때는 추가 audit 두 시선을 요구한다. E4c처럼 모든 보호 후보까지 네 시점의 동시 관측을 요구하지 않는다.

이 정의는 일관된 잘못된 표면을 보호할 수 있다. 안정적인 허위 표면의 존재 자체를 교정하는 검출 성능으로 확대 해석하지 않는다. P/T 생성에는 policy threshold·membership를 사용하지 않는다.

## 6. 제안 정책과 대조군

### 6.1. S_center_surface

정책은 평가기 라벨을 읽지 않는다. 현재까지의 raw pointmap·실제 snapshot pose만 사용한다. 자기 출처는 후보 제외 5×5/9×9 robust PCA로 검사하고, center의 다중 scale 소속과 **신뢰할 수 있는 표면에 대한 비소속**을 구분한다. 평가기의 7×7/13×13 RANSAC·3D kNN 결과를 feature로 사용하지 않는다.

초기 정책은 다음 순서다.

```text
1. center가 자기 출처의 reliable한 다중 scale 표면에 속하면 KEEP_LOCAL
2. 다른 source-disjoint 관측의 center 표면 지지가 있으면 보존
   (두 시선 지지 KEEP_MULTI / 한 시선 지지 UNKNOWN_SUPPORTED)
3. 자기 출처의 reliable한 다중 scale 비소속 증거가 없으면 UNKNOWN으로 보존
4. source-disjoint 두 KF에서 같은 snapshot에 유효한 앞쪽 충돌이 있고
   시선 간 각도 >=1도이며 봉인 임계값을 초과하면 REJECT
5. 그 외 UNKNOWN으로 보존
```

정책의 표면 band는 E4c의 `(c_s,c_h)={(3,1),(3,2),(5,1),(5,2)}` 네 조합으로 제한한다. 소속은 center 거리 ≤τ, 비소속은 두 reliable scale 모두 >3τ로 시작한다. 각 scale의 평면 신뢰성·최소 점 수·연결성·경계 처리는 A0에서 명문화해 봉인한다. 곡면·얇은 구조의 불확실성을 비소속으로 바꾸지 않는다.

Gaussian의 3σ는 **반복 충돌을 확신할 수 있는지**의 여유에만 사용한다. center 소속의 허용 두께를 3σ로 늘리지 않는다. ray 허용 각도 ≤1°, 후보–관측 시차 ≥1°, 가림 band와 앞쪽 여유는 E4c V2를 시작점으로 유지한다. support용 수선점 hull과 충돌용 ray-hit hull을 분리한다.

각 actual KF snapshot에서 살아 있는 후보를 재평가한다. 미래 관측·final pose·audit는 정책에 들어가지 않는다. UNKNOWN은 렌더 가능하게 보존하고 REJECT는 absorbing으로 한다. 최초 제거 frame/revision·근거·이후 pose 갱신의 판정 민감도를 저장한다.

### 6.2. 필수 비교

| 비교군 | 비교 목적 |
|---|---|
| B1 original | 모든 original-active 유지 |
| **D_center_surface** | 같은 center 보호·비소속·관측·집계 조건에서 depth 잔차만 사용. PCA를 안 쓰는 baseline이라고 표현하지 않음 |
| **D_median, B6 depth** | 강한 median-depth/native-depth 점수. 새 개발 P 보존 기준으로 보정한 arm과 기존 봉인 arm을 구분 |
| **P2 plane** | 기존 plane-zero veto 정책. 새 보정 arm/기존 봉인 arm을 구분 |
| **KNN distance** | 단순 공간적 이상점 점수. 같은 P 보호 위험 기준에서 보정 |
| E4c extent 보호 / center 보호만 변경 / 국소 N 조건 제거 | Gaussian extent 보호, center 소속, 적극적 비소속 조건의 기여 분리 |
| B2 confidence, B7 RGB, B8 DoG proxy | 기존 강한 참고 대조군과 동일 수량 진단 |

모든 정책은 같은 후보·policy 입력·pose·렌더러를 사용한다. audit 입력을 특정 방법의 삭제 근거에 추가하지 않는다. E4c는 정책 임계값이 미보정이므로 기존 natural membership가 존재하는 것처럼 비교하지 않고, 정의된 feature/보호 규칙을 새 개발 보정한 ablation으로만 사용한다.

## 7. 개발 보정과 단계별 gate

### A0 — 표면 소속 측정 성립

audit replay를 대량 실행하기 전에 office0에서 center-only/extent 판정, 후보 제외 이웃·간격, 두 평가기 합의와 소규모 기전 검사를 구현한다. office1에서 같은 정의를 확인한다.

- 각 개발 장면에서 자기 출처 C로 확인한 `P_source ≥1,000`개와 reference N ≥100개를 확보한다. 이 단계의 P는 P_source만을 뜻하며 audit를 포함한 최종 P/T/U는 A1에서 생성한다.
- **보호 조건·국소 N 조건·score threshold 적용 전** 두 source-disjoint policy 관측이 있는 집합 E를 정의한다. 각 개발 장면 `E∩P ≥100`을 요구한다.
- 점군 중심 소속과 Gaussian extent 소속의 교차표, 중앙 깊이 spike·실제 경계·얇은 구조의 불확실 처리를 확인한다.
- label 정의와 raw branch/pose 계약이 성립하지 않으면 `INCONCLUSIVE_MEASUREMENT`로 보고하고 추가 audit 실행을 열지 않는다.

### A1 — audit 관측과 공통 평가 성립

office0의 audit replay·정렬·probe를 먼저 검증하고 통과 후 office1 및 회귀 장면으로 확장한다. source-ID·RGB test 분리와 §4.2 정렬 gate를 모두 통과해야 한다.

각 개발 장면에서 `P ≥1,000`, `T ≥100`, `E∩P ≥100`, `E∩T ≥30`, `|E∩(P∪T)|/|E| ≥20%`를 요구한다. 전체 active의 일정 비율이 반드시 불량이어야 한다는 조건은 두지 않는다. 회귀 장면은 최소 P·공통 P와 구조 보존을 확인하며 T가 적으면 해당 recall을 해석하지 않는다.

부족한 표본은 U 또는 평가 불가로 남긴다. `INCONCLUSIVE_OBSERVABILITY`이면 신규 효능 test를 열지 않는다. source 분리·T 정의·표본 기준을 결과 확인 후 완화해 통과시키지 않는다. 변경 시 별도 개발 amendment와 새 봉인이 필요하다.

### A2 — 보정·개발 효용·회귀 안전성

새 방법의 threshold는 개발 P의 **보호 veto와 국소 N 조건 적용 전 shadow score** 시간 최댓값에서 보정한다. 반복 score는 시선 ≥1°인 서로 다른 KF 쌍의 `min(score_a,score_b)` 중 최댓값이다. 유효 관측이 없으면 NaN이며 보호 여부로 calibration 분모를 지우지 않는다.

장면별 own-finite/common-finite P와 P≥100인 anchor별 99% higher quantile 중 최댓값을 사용하고 strict `>`로 제거한다. 여기서 finite는 veto 이전 shadow score의 유한 여부고, 주 common은 S_center_surface와 D_center_surface의 교집합이다. 다른 baseline도 own-finite와 S_center_surface와의 paired common을 보고한다. τ로 정규화한 S_center_surface plane threshold만 최소 1로 제한하며, 다른 단위의 legacy plane·depth에 이 하한을 적용하지 않는다. baseline도 각자의 score 단위에서 같은 개발 P 보존 목표로 보정한다. 보정 후 실제 시간순 absorbing replay로 전체·finite·anchor P 보존을 다시 검사한다.

네 band 조합 중 두 개발 장면의 P 보존·§8의 최소 제거·지도 손상 한도를 만족하는 조합만 남기고, 장면별 T recall의 최솟값이 가장 높은 조합을 선택한다. 동률은 최대 P 손상, scoring 비용, 기재 순서로 결정한다. 회귀에서 손상이 발생하면 새 장면을 열지 않고 개발 REVISE다. 이 경우 회귀 결과를 본 사실도 노출 기록에 남긴다.

실제 보정·baseline·평가에 필요한 공통 표본이 없으면 임계값을 만들지 않는다. 비교군의 유효한 보정 운영점에서 제거가 0개인 것은 그대로 보고할 수 있지만, 주 제안의 제거 0개는 통과가 아니다.

## 8. E4d-B: 새 장면의 주 평가와 E5 진입 기준

### 8.1. 실행 순서

1. E4d-A가 통과한 뒤 정책·평가기·정렬·모든 상수·baseline·성공 기준·코드/모델/입력 해시를 봉인한다.
2. 미노출 두 장면의 짝수 입력 baseline을 생성하고, 모든 방법의 natural 점수·membership·최초 제거/revision을 확정·봉인한다.
3. 정해진 홀수 audit 입력의 별도 replay·pose 정렬·probe와 P/T/U를 생성한다. test label을 보고 정책을 바꾸지 않는다.
4. 고정 RGB test·GT 평가·지도 품질·회귀·대조군 결과를 모두 계산한다. 개발에서와 같은 source/pose 검사와 평가 성립 조건을 적용한다.

새 평가 장면의 T 부족·audit 정렬 실패도 결과다. 다른 장면으로 바꾸거나 검사 가능한 일부 후보만으로 전체 효능 GO를 내리지 않는다.

### 8.2. 장면별 제안 통과 기준

아래 조건은 **두 새 장면 각각**에 적용한다. 장면 평균으로 한 장면의 손상을 상쇄하지 않는다.

| 항목 | 기준 |
|---|---|
| 평가 성립 | A1의 P/T/common 표본·20% 평가 coverage·pose/source gate 충족 |
| 표면 보존 | 전체 및 own/common E의 P retention ≥99%, P≥100인 anchor별 ≥99% |
| coherent-but-GT-wrong 보호 | P∩기존 GT bad가 ≥100이면 그 집합 retention ≥99%. 작은 집합은 표본 부족 표시 |
| 유효한 제거 | T 제거 ≥30개, 전체 T recall ≥5% |
| labeled precision | `제거 T / 제거(P+T) ≥95%` |
| 평가 불가 제거 | 제거 중 U 비율 ≤10%. 초과 시 평가 coverage 부족으로 GO 불가 |
| 강한 대조군 대비 | 같은 P 보존·지도 한도에서 보정된 D_center_surface·D_median·B6·KNN 각각보다 전체 T recall ≥2%p 높음, precision 손실 ≤1%p |
| GT normal 보호 | 기존 GT normal 전체 및 finite 집합 retention ≥99%. P/T 정의를 GT로 교체하지 않음 |
| coverage | B1 대비 최종 및 각 temporal 평가 frame 손실 ≤0.5%p |
| RGB | B1 대비 최종 frame 평균 PSNR 손실 ≤0.2 dB, SSIM 손실 ≤0.005, LPIPS 증가 ≤0.01 |
| depth/TSDF | 공통 covered GT-valid depth L1 증가 ≤5 mm, sampled Chamfer 악화 ≤2%, completion ratio 손실 ≤1%p |

전체 T recall의 분모는 policy finite 후보만으로 줄이지 않는다. 각 방법의 E/finite coverage·unknown·보정 실패를 함께 보고한다. 필수 comparator가 보정 불가이면 비교를 빼고 GO로 처리하지 않는다. 같은 risk 수준에서 보정되었으나 T 제거가 0개인 baseline도 비교 결과로 남긴다.

이 수치는 E4의 GT Chamfer ≥2% 개선 조건을 소급 수정한 것이 아니다. E4d의 새 목표에서 선택적 표면 이탈 제거와 지도 보존을 검사하는 기준이다. 작은 후보 차이를 통계적 유의성으로 부르지 않고 장면·KF·표면 성분별 분모와 편차를 함께 보고한다.

### 8.3. 지도·자원 평가 계약

최종 RGB는 §4.1의 11개 test frame, 시간별 평가는 actual KF 직후 첫 허용 홀수 test frame을 사용한다. 즉시 다음 홀수가 audit 입력이면 사용하지 않고 고정 RGB test 목록의 다음 frame을 사용한다. audit가 본 frame으로 시간별 새 시점 품질을 주장하지 않는다. 동일 frame에 대응하는 여러 snapshot은 각각 저장하고, snapshot과 평가 frame의 시간 차이도 보고한다. 모든 방법과 B1은 같은 snapshot/frame 쌍을 비교한다.

GT geometry는 E4의 동일한 짝수 fusion 20개 view·TSDF voxel 4 cm·truncation 12 cm·seed 0 표면 100,000 sample과 coverage 정의를 유지한다. 공통 covered pixel의 depth 오차와 각 방법의 coverage·pixel 수를 함께 제시한다. 관측 영역 reference이며 전체 장면 GT mesh라고 부르지 않는다.

주 arm은 natural pruning이다. 동일 수량 비교는 S_center_surface의 자연 생존 수 K에서 공통 seed 0 fallback 및 random seeds 0/1/2를 쓰는 보조 진단으로 분리한다. 도달 불가를 명시하고 fallback 제거를 알고리즘 효용에 합산하지 않는다. 정책 scoring과 평가용 audit 비용, parameter bytes와 실제 GPU resident/peak를 구분하며 측정하지 않은 온라인 속도·VRAM 이득을 주장하지 않는다.

## 9. 검증·산출물·봉인

구현 시 최소 검사는 다음과 같다.

1. 후보 중심을 바꾸어도 후보 제외 fit·MAD·간격에 해당 중심이 섞이지 않는지, covariance만 키워 center 소속이 바뀌지 않는지 검사한다.
2. 중심 spike와 실제 depth edge·곡면·얇은 구조·다중 표면을 구분하고, fit 실패/저밀도는 U로 남기는지 확인한다.
3. 수선점이 hull 밖이고 ray-hit는 안인 앞쪽 후보, 반대 경우, 표면 뒤 가림을 각각 검사한다.
4. scene/원본 frame 단위 source 분리, audit/RGB test 전체 입력의 교집합 0, branch 중복과 시선 다양성을 검사한다.
5. pose/scale·좌표·covariance 단위·snapshot revision·최초 제거·strict threshold 동점·NaN·미래/audit/GT feature 접근 금지를 검사한다.
6. E4c에서 확인한 ‘충돌하지만 국소 표면 지지’ 사례를 고정 회귀 사례로 포함하되 기존 라벨을 강제로 P/T로 바꾸지 않는다.

소규모 고정 fixture로 공동 좌표 변환·일관된 이중 표면 보존·단일 정점 이탈을 검사한다. 대규모 공통 depth/scale/pose bias sweep은 E5에 남긴다.

그림은 장면별 P/T/U와 보존/제거, P∩GT bad, center/extent 불일치 집합에서 stable ID 정렬·seed 0으로 최대 8개씩 정한다. 사례 ID는 그림 검사 전에 저장하고 불리한 예시를 교체하지 않는다. 이웃 표면·중심 잔차·Gaussian extent·policy/audit 시선·시간선을 분리해 표시한다.

예정 산출물은 다음과 같으며 **현재 구현·존재하는 실행 도구로 보지 않는다.**

- 계획 설정·등록·봉인: `configs/e4d_surface_membership_validation.json`, `e4d_protocol_registration.json`, `e4d_preregistration.json`.
- 실행 원본: `results/E4d_surface_membership_validation/`의 source/입력/노출 manifest, audit RGB 제외 목록·event/pose 계약·trajectory 정렬, source/reference C/N·P/T/U, 관측 gate·shadow score·membership·최초 제거/revision, 비용·그림·봉인 코드.
- 단계별 기록: A0 측정 성립, A1 audit/coverage, A2 보정/회귀, B 새 장면 주 평가. 중단 gate·변경 사유·노출 범위를 남긴다.
- 최종 결과: `configs/e4d_results_summary.json`, `configs/e4d_validation.json`, `docs/experiments/E4d_surface_membership_validation_results.md`.

실행 명령은 구현·검증 후에만 제시한다. E4/E4b/E4c 결과·등록·봉인 경로는 변경하거나 덮어쓰지 않는다.

## 10. 판정과 E5의 역할

| 판정 | 의미·다음 조치 |
|---|---|
| `INCONCLUSIVE_MEASUREMENT / OBSERVABILITY` | 소속 분류·audit pose/scale·공통 표본·평가 coverage 부족. 해당 단계까지만 완료 보고 |
| `REVISE` | 평가가 성립했지만 개발 또는 새 장면의 제거 효용·표면/지도 보존 기준 미달 |
| `GO_FOR_E5_REVIEW` | A0/A1/A2 및 두 새 장면의 필수 비교·보존·회귀 조건을 모두 충족. E5 프로토콜 등록과 진입 검토 가능 |

E5는 이후 **일관된 표면의 공통 위치·스케일 편향은 보존하면서, 그 표면과 분리해 삽입한 이탈점은 제거할 수 있는지**, pose 오류·가림에서 어떤 한계가 생기는지를 정량화한다. 공동 편향이 있는 표면을 GT와 다르다는 이유로 모두 삭제하는 것을 성공으로 정의하지 않는다. expected KEEP/REJECT/UNKNOWN과 perturbation 범위는 E5 실행 전에 별도로 봉인한다.

E4d 통과는 이 제한된 스트레스 검증의 진입 근거다. 연구 전체 GO, 일반적인 GT 복원 정확도 개선, 실제 물체 존재 판정, 통계적 독립, E6 온라인 효용·실시간성·논문 신규성까지 입증하지 않는다.
