# E4c 개발 실행 변경 기록 — A1

**2026-10-22, 기하 feature·audit 라벨·정책 결과 계산 전 등록.**

[원래 계획](E4c_surface_consistency_pruning.md) §3.3의 매 3번째 raw event 분할을 source ancestry 메타데이터로 먼저 검사했다. 기존 다섯 장면은 각각 raw event 500개이며, audit 166개의 원본 이미지와 직접 겹치는 policy event를 제외하면 모두 policy event가 0개다. KF 대응 raw만 같은 방식으로 분할해도 office0/office1에는 policy KF가 각각 2개, room0/room1/room2에는 각각 1개만 남는다. 이 검사는 점 좌표·GT·audit 분류·효능 지표를 보지 않고 수행했다.

이유는 연속된 예측이 같은 기준 KF 이미지를 공유하기 때문이다. 원래 계획에서 허용한 개발 단계 amendment로 다음을 고정한다.

1. 관측 라이브러리는 기존 E4/E3c scorer와 같은 **decision-time pose가 있는 KF 대응 raw self branch**로 한정한다. 전체 raw event 메타데이터의 원래 분할 실패도 별도 보존한다. KF pose가 없는 non-KF raw를 임의로 KF 좌표에 놓지 않는다.
2. **KF index 2, 3을 audit**, 나머지를 policy 후보로 정한다. audit와 원본 이미지를 공유하는 policy 관측은 계속 제외한다. 후보 생성 원본과의 source 분리·중복 KF 배제·시선 다양성 조건도 유지한다.
3. 이 분할은 두 개발 장면의 ancestry만 보고 정했으며 모든 회귀/새 장면에 동일하게 적용한다. policy/audit 관측 상호 간 모델 독립성을 주장하지 않는다.
4. audit 평면·분류와 정책 표면·점수는 별도 단계로 계산한다. test에서는 membership 봉인 후 audit 평가를 연다. 개발에서만 audit 라벨을 보정에 사용한다.

수정 분할의 policy KF는 office0 `[0,5,6,7,8,9,10]`, office1 `[0,5,6,7]`, room0/room2 `[0,5,6]`, room1 `[0,5,6,7,8,9]`다. source 집합만으로 policy/audit 각각 2개 관측이 가능한 후보 KF가 존재한다. 실제 ray·가림·표면·시차 자격과 S/O 표본 수는 아직 확인하지 않았으며 후속 계산으로 검사한다.

기하 계산에 앞서 중심 제외 trimming은 점 수의 80%를 내림해 보존하고, audit RANSAC의 64개 triplet은 row-major 이웃 slot에서 seed 0으로 고정한다. MAD·간격은 남은 inlier와 유효 이웃으로 계산하며 후보 중심을 간격 계산에도 사용하지 않는다. 후보의 평면 수선점이 inlier convex hull 안에 있는지는 2D 각도의 최대 gap이 π 이하인지로 검사한다.

임계값의 반복 잔차는 시선 각도 ≥1°인 서로 다른 KF 쌍의 `min(score_a, score_b)` 중 최댓값으로 정의한다. 모든 쌍이 시선 조건을 만족할 때 기존 두 번째 큰 값과 같으며, 방향이 같은 두 관측만으로 반복 근거를 만드는 것을 막는다. support 보호와 앞쪽 확인을 적용한 정책 잔차, 이를 적용하기 전 보정 잔차를 별도로 저장한다.

이번 등록은 **개발 관측·기하·보정 성립 단계**의 실행 봉인이다. 새 장면 baseline·GT·RGB는 열지 않았다. 개발 S/O·common 반복 관측/보정이 성립하지 않으면 INCONCLUSIVE, 보정 후 최소 제거·지도 조건이 실패하면 개발 REVISE로 보고하고 새 평가로 진행하지 않는다. 기존 실험 산출물은 변경하지 않는다.
