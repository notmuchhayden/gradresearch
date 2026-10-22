# E4b: 기준 평면의 GT 정확도와 depth/plane 판정 경로 진단

**상태: 설계 등록 완료·미실행(2026-10-22).** 분석 구현·후보별 집계·oracle 재계산은 아직 수행하지 않았다. 설정은 [e4b_reference_plane_audit.json](../../configs/e4b_reference_plane_audit.json), 등록 시점과 입력 해시는 [e4b_protocol_registration.json](../../configs/e4b_protocol_registration.json)에 기록한다.

E4b는 **“틀린 point cloud가 매끈한 평면을 이루어 불량 가우시안을 통과시켰는가?”**, **“B6는 제거했는데 plane은 남긴 이유가 기준 오류인가, 판정 조건 차이인가?”**를 확인하는 실험이다. 이미 확인한 [E4 결과](E4_matched_budget.md)를 설명하는 사후 진단이며, 새로운 독립 성능 검증은 아니다. E4의 REVISE와 E5/E6 효능 검증 보류는 유지한다.

## 1. 질문과 가설

| 질문 | 확인할 증거 | 해석의 한계 |
|---|---|---|
| H1. 잘못된 국소 평면이 불량을 지지했는가? | GT에서 벗어난 기준 평면, 같은 관측에서 GT-front인 후보, 원래 plane 점수 0의 동시 발생 | 평면 오차의 존재만으로 미제거의 원인까지 확정하지 않음 |
| H2. 관측 자격·반복 수·veto가 B6와의 차이를 만들었는가? | 동일 후보·시점의 유효 관측 수와 gate·집계값·임계값 여유 | 조건들이 겹칠 수 있고, 방법별 임계값도 달라 단일 원인 분해가 아님 |
| H3. 기준 평면을 교정하면 해당 판정이 바뀌는가? | 다른 조건을 고정한 GT-plane oracle에서 같은 후보가 새로 제거되는지 | GT를 사용하는 원인 진단이며, 실제 사용 가능한 개선 알고리즘이 아님 |

현재 plane은 전역 지도 전체를 묶은 평면이 아니라 다른 raw 관측의 **5×5 국소 patch**에서 추정한다. 후보와 기준 관측의 원본 이미지는 분리하지만 예측 모델은 같으므로 공통 오류가 가능하다. 같은 잘못된 깊이를 공유하면 B6도 놓칠 수 있다. 따라서 B6-only 사례와 두 방식 모두 놓친 사례를 함께 조사한다.

## 2. 데이터·대조군·분모

- **주 분석: office1.** E4에서 이미 결과를 본 장면이므로 E4b의 fresh test로 부르지 않는다.
- **보조 분석: office0·room0·room1·room2 전부.** 장면별 결과를 따로 제시하며 Gaussian 수를 독립 시행 수로 해석하지 않는다.
- **방법: B6_depth, D_maskmedian, D_shared, P2_plane.** E4 봉인의 임계값·원본 active filter·실제 natural 결정을 사용한다.
- **GT 라벨: creation 주 분석**, gt_anchor·cross_pose_consensus 민감도. bad=3, normal=1/2, unknown=0이며 기존 장면별 라벨과 manifest를 재사용한다.
- **예산용 rank/fallback 제거는 제외한다.** 75% 유지 지도에서 무작위로 빠진 후보를 B6나 plane이 발견한 불량으로 세지 않는다.

모든 original-active bad를 다음 네 집합으로 완전히 분할한다.

| 집합 | B6 자연 제거 | P2 자연 제거 | 역할 |
|---|---|---|---|
| B6-only bad | 예 | 아니오 | 주 분석: 두 방식의 차이 |
| Both-miss bad | 아니오 | 아니오 | 공통 기준 오류·관측 부재 확인 |
| Both-reject bad | 예 | 예 | 정상적으로 발견한 불량 대조 |
| Plane-only bad | 아니오 | 예 | plane에 유리한 반대 사례 |

정상 후보 전체도 같은 네 결정 집합으로 나누어 오제거를 확인하고 unknown은 별도 보고한다. 집계마다 **전체 bad / 해당 집합 / GT 검사 가능 후보 / GT 검사 가능 고유 patch / 후보×시점×관측 기록** 중 어느 분모인지 명시한다. 같은 patch를 여러 후보가 사용한 횟수와 고유 patch 수를 혼동하지 않는다. 통계는 전수 집계하며 그림만 고정 표본으로 제시한다.

## 3. 먼저 E4의 실제 판정을 복원

E4 설정과 E3c의 상속 경로를 따라 baseline raw-pair, audit snapshot, score history, natural `decisions.npz`, GT label manifest를 읽는다. 이전 장면의 scores/labels가 E4 디렉터리에 모두 복사되어 있다고 가정하지 않는다. 입력 경로·크기·해시, 환경·분석 코드 commit/hash를 실행 manifest에 저장한다. 원본 결과는 읽기 전용으로 취급하고 출력은 `results/E4b_reference_plane_audit`에만 쓴다.

1. 각 실제 decision snapshot의 pose revision·Sim(3)·raw 관측 출처로 E4 기하 점수를 다시 계산한다. 미래 관측은 허용하지 않는다.
2. 원래 float32·NaN·엄격한 `score > threshold` 연산을 보존해 점수·finite mask·최종 natural membership·최초 제거 시점과 revision을 원본과 대조한다. 불일치가 있으면 원인 해석을 중단하고 차이를 기록한다.
3. 주 집합은 **B6가 처음 제거한 바로 그 시점**의 P2 판정과 비교한다. 최종 pose나 각 방법이 유리한 다른 시점을 가져와 비교하지 않는다. 출생부터 마지막 snapshot까지의 이력도 보존한다.
4. 다른 집합의 그림 기준 시점은 어느 한 방법의 최초 제거 시점, 둘 다 미제거이면 최초 shared 2+ 시점, 그것도 없으면 출생 시점으로 고정한다.

REJECT는 흡수 상태다. 뒤의 관측이 지지하더라도 이미 제거한 후보를 복구하지 않는다. Source-disjoint는 후보와 각 기준 관측의 이미지 출처 분리이며, 기준 관측끼리 또는 모델끼리 독립이라는 뜻이 아니다.

## 4. 기준 point cloud와 평면을 GT로 검사

기준 관측의 원본 frame에 대응하는 GT 깊이를 E1/E4와 동일한 resize/crop·카메라로 정렬한다. GT 유효 범위 0.1–10m, depth edge 제외, 허용 오차 **max(5cm, GT z의 2%)**를 적용한다. 기준 patch는 실제 ray matching이 선택한 evidence pixel의 5×5 영역이다.

GT 유효·비경계와 predicted-valid의 공통 점이 9개 이상인 patch에서 calibrated K로 GT 점들을 역투영하고 동일 가중치 PCA로 GT 평면을 만든다. GT 평면에도 E2의 고유값 비율(작은값/중간값 ≤0.1, 중간값/큰값 ≥0.05)을 적용한다. 유효 GT가 부족하거나 실제 표면이 평면으로 근사되지 않으면 평면 품질은 **검사 불가**로 남긴다. 검사 불가를 정확한 평면으로 세지 않는다. 원래 predicted 평면은 GT mask에 맞춰 재적합하지 않는다.

좌표 비교에는 기존 label manifest의 전역 alignment scale과 **해당 snapshot 기준 관측 pose의 scale**을 곱해 predicted local 단위를 m로 바꾼다. patch마다 GT에 맞춰 scale·위치를 재보정하지 않는다.

| 지표 | 정의·의미 |
|---|---|
| 점들의 깊이 오차 | source pixel별 scaled predicted z − GT z; 부호·중앙값·분위수·허용 오차 초과 비율 |
| ray·투영 오차 | predicted ray와 calibrated pixel ray의 각도, predicted 점을 calibrated K에 투영한 위치의 GT 깊이 오차; 같은 pixel의 z 일치만으로 3D 정확성을 보장하지 않음 |
| 평면 위치 오차 | GT 법선 방향의 `abs(n_GT · (m_pred − m_GT))`; 두 중심은 m 단위 |
| 평면 방향 오차 | 법선 부호를 무시한 `acos(abs(n_pred · n_GT))` |
| 평면 오류 tag | 위치 오차가 max(5cm, GT 중심 z의 2%) 초과 또는 방향 오차 >10°; 연속값도 반드시 보고 |
| 점군의 일관된 오류 tag | 원래 reliable patch의 공통 점 ≥9개 중 ≥80%가 같은 부호로 깊이 허용 오차 초과; 앞/뒤를 구분하고 **모든 점 오류** 여부도 따로 보고 |

80% tag를 “전체 점이 틀렸다”라고 부르지 않는다. **점군 오차와 평면 오차도 구별한다.** 예를 들어 평면에 평행한 점 이동과 평면 자체의 잘못된 위치는 다른 현상이다. 절대 깊이 허용 오차 2/5/10cm, 방향 5/10/20° 민감도를 모두 제시하며 유리한 조건을 골라 주 결과로 바꾸지 않는다.

엄격한 **잘못된 기준의 지지(shared_wrong_support)**는 다음이 함께 성립할 때만 기록한다: 미제거 GT-bad 후보, 원래 finite plane 점수 정확히 0, GT로 확인한 기준 평면 오류, 같은 evidence view에서 후보의 3σ 범위까지 GT보다 앞에 있음. 후보를 calibrated K로 투영한 위치가 검사 patch 밖이면 대응 불확실로 남긴다. 점군의 80% 일관된 오류는 추가 tag이며 평면 오류만으로 추정하지 않는다. 이 조건은 관측된 동시 발생이고, 판정에 대한 기여는 §6에서 따로 확인한다.

기준 관측 **자기 카메라 좌표의 오류**와 추정 상대 pose로 후보를 옮겼을 때의 오류를 분리한다. 같은 scale을 유지하고 GT-anchor 상대 pose를 넣는 민감도도 제시해 pose 영향이 큰 사례를 표시한다. 카메라 궤적 전역 정렬의 오차나 shared predictor bias를 이 진단만으로 유일 원인으로 확정하지 않는다.

## 5. B6는 왜 제거했고 P2는 왜 남겼는가?

각 후보×시점×관측에 ray matching·confidence·경계·시차·가림·patch reliability, depth/plane residual, 두 방향의 σ, 상대 점수와 GT 기준 품질을 저장한다. 후보×시점에는 유효 관측 수·집계값·veto·임계값 여유·정책 상태를 기록한다.

**B6 native는 finite depth 관측의 median이며 한 관측으로도 점수가 생길 수 있다.** P2는 shared mask에서 두 관측 이상, 두 번째 큰 값, plane 점수 0에 의한 veto를 사용한다. 따라서 단순히 “plane residual이 열등하다”로 해석하면 안 된다. 점수 0 역시 GT 정확성을 보증하는 지지가 아니라 원래 규칙상 비충돌이라는 뜻이다.

snapshot별로 다음 순서의 첫 차단 단계에 후보를 분류하되, 모든 동시 gate flag와 기준 오류 tag도 보존한다.

1. 출처·시간 조건을 만족하는 관측 없음.
2. finite native depth 관측 없음(ray·confidence·경계·시차·가림의 세부 실패 포함).
3. finite shared plane 관측 없음(patch reliability 포함).
4. shared 관측이 두 개 미만.
5. plane-zero support veto가 켜짐.
6. finite 점수가 제거 임계값 이하.
7. 임계값 초과로 제거.

**B6 → D_maskmedian → D_shared → P2**의 후보별 결정을 함께 보여 자격/veto, median과 두 번째 큰 값, depth와 plane residual의 차이를 비교한다. 각 방법의 고정 임계값과 조건의 상호작용이 있으므로 이 차이를 순수한 인과 효과의 합으로 부르지 않는다. 시점별 분류와 전체 이력의 미제거 원인은 구분한다.

## 6. GT 평면으로 바꾸는 보조 진단

다음 세 arm을 출생부터 독립적으로 재생한다. GT plane oracle은 **설계에 포함된 보조 분석**이며 현재는 미실행이다.

| Arm | 바꾸는 것 | 고정하는 것 |
|---|---|---|
| factual_common | 없음, 동일 데이터 처리 경로의 사실 기준선 | 원래 모든 값·gate·veto·임계값 |
| GT_plane_fixed_veto | GT 검사 가능한 원래 shared pair의 평면 중심·법선 | 원래 대응 pixel, finite mask, veto, 후보·covariance, 추정 pose, radius/spacing 정규화, 집계·임계값 |
| GT_plane_recomputed_veto | 위 평면과, 바뀐 점수에 따른 plane-zero veto | 원래 shared pair 집합과 나머지 조건 전부 |

GT 중심을 해당 snapshot의 evidence local 단위로 변환한다. 법선이 바뀌면 **동일 covariance에서 새 법선 방향의 σ를 다시 계산**한다. GT가 검사 불가인 pair는 모든 arm에서 사실 값을 유지하고 그 수와 후보 coverage를 별도 보고한다. GT로 원래 없던 유효 관측을 만들지 않는다. 후보 ID와 정책은 arm별로 따로 유지하며 원본 결정을 덮어쓰거나 제거 후 복구하지 않는다.

주 집합에서 새로 제거되는 bad 비율뿐 아니라 전체 active의 **새로 제거/더 이상 제거되지 않는 bad·normal·unknown, 전체 bad recall·normal retention, GT 검사 가능한 pair/후보 비율**을 함께 보고한다. 기준 평면 오류와 같은 후보의 판정 전환이 함께 있어야 “기준 품질이 해당 판정에 기여했다”는 근거로 센다. fixed-veto와 recomputed-veto의 차이는 기준 오류가 veto를 통해 미친 영향을 살펴보는 보조 대비다.

Oracle에서 회복이 없더라도 잘못된 평면이 없다는 뜻은 아니다. 원래 관측 부재·잘못된 대응·가림·pose 오류·GT 불완전성은 그대로 남는다. 새 제거가 늘어도 정상 손상을 숨기지 않는다. 이 단계에서는 RGB/TSDF를 다시 평가하지 않으므로 **E4의 Chamfer 차이를 설명하거나 개선했다고 주장하지 않는다.**

## 7. 출력·그림·완료 기준

예정 출력은 `input_manifest.json`, `reproduction_check.json`, `cohorts.npz`, 후보/관측/고유 patch별 `*_audit.parquet`, `oracle_summary.json`, `summary.json`, `example_ids.json`, `figures/`다. 보고서에는 장면별 네 집합 수, gate funnel, 기준 평면·점군 오류율과 검사 불가율, oracle 변화, pose/라벨 민감도를 제시한다.

그림은 seed 0으로 정렬된 stable candidate ID에서 bad 네 집합당 최대 8개, 전체 normal에서 최대 8개를 무복원 추출한다. 그림 검사 전에 ID를 저장하며 검사 불가나 불리한 사례를 다른 것으로 교체하지 않는다. source/evidence RGB, 해당 patch의 predicted/GT 깊이, 후보·예측 평면·GT 표면의 단면, 판정 시간선을 보여준다. 보기 좋은 예시만으로 전체 빈도를 추론하지 않는다.

**완료 조건:** 사실 재현 일치, 정해진 모든 집합·분모·검사 불가 사유, 두 oracle 대비, pose 민감도와 고정 표본을 보고할 것. 미완료 단계나 재현 불일치를 명시한다. 분석 성공을 bad recall 증가와 동일시하지 않으며 **GO 임계값은 두지 않는다.** 결론은 다음을 구분한다.

- **잘못된 기준의 지지 관측:** §4의 엄격한 조건을 만족한 후보·고유 patch 수와 추적 가능한 사례.
- **기준 품질의 판정 기여 관측:** 같은 후보의 기준 오류와 사실→oracle 미제거→제거 전환. 정상 오제거와 bad 제거 손실도 병기.
- **미확인/판단 불가:** 적격 사례가 없거나 GT·대응·pose coverage가 부족함. 모든 평면이 정확하다는 결론이 아님.

조건의 중첩과 검사 불가 사례가 있으므로 단일 지배 원인이나 공유 모델 편향의 인과성을 확정하지 않는다. 분석으로 알고리즘 개선안을 만들면 별도 개발·봉인 후 아직 살펴보지 않은 데이터에서 검증한다. office1은 이후 untouched test로 재사용하지 않는다.

## 8. 실행 준비 상태

이번 변경은 실험 설계와 설정·등록만 추가한다. 실행 스크립트는 아직 없으며, 존재하지 않는 재현 명령을 제시하지 않는다. 후속 실행 순서는 **분석 코드 구현 → 입력 manifest/무결성 점검 → 사실 재현 → 집합·GT 기준·판정 경로 전수 감사 → oracle → 고정 그림·보고서**다. 구현 후 전체 분석 전에 코드 hash·환경을 봉인하고, 프로토콜 변경이 필요하면 변경 이유와 분석 진행 여부를 amendment로 남긴다. 원래 SLAM 재실행·학습·임계값 재보정은 필요하지 않다.
