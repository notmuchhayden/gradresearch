# E4e: 드론 데이터 적용 및 표면 이상점 사전 조사

**상태: 개발 B1 실행 완료·INCONCLUSIVE(2026-10-22).** interval=1 세 sequence를 확보하고 HKairport01의 등록된 60초 구간에서 B1 기준선을 실행했다. pose 산출률은 95.0%였으나 최장 연속 추적 중단 2.4초가 제안 gate 2초를 넘었다. 주 평가 AMtown01·AMvalley01의 baseline 예측, 표면 분류 및 이상점 판정은 수행하지 않았다. 실행 기록은 [E4e 결과](E4e_uav_dataset_pilot_results.md)에 있다. 주 평가 예측을 열기 전에 개발 gate와 평가기를 통과하고 설정·입력 목록을 봉인한다.

**목표:** 실내 Replica 대신 실제 드론 광역 촬영 데이터를 넣었을 때, 원본 지도에 **일관된 표면 밖의 고립 정점과 그에 대응하는 Gaussian이 충분히 발생하는지** 먼저 확인한다. 제거할 대상이 드물다면 pruning 개발의 우선순위를 낮춘다. E4e에서는 새 pruning 정책을 실행하거나 Gaussian을 추가로 삭제하지 않는다.

핵심 질문은 다음과 같다.

> 드론 영상에서도 현재 MASt3R 기반 예측·Splatt3R-SLAM 파이프라인이 표면 밖 이상점을 충분히 억제하는가, 아니면 후속 pruning을 연구할 만큼 이상점이 발생하는가?

## 1. 실행 순서와 해석 범위

사용자의 연구 순서 변경에 따라 **E4e를 다른 후속 실험보다 먼저 수행**한다. E4d는 계획 상태로 대기하며 완료를 E4e의 선행 조건으로 요구하지 않는다. E4e는 데이터와 문제 존재 여부를 확인하는 진단이다. E4d의 전체 표면 소속 정책·별도 모델 audit replay를 먼저 구현하지 않는다.

- [E4b](E4b_reference_plane_audit_results.md)의 GT 오류는 일관된 표면의 위치 오류도 포함한다. 이를 곧바로 고립 정점 수로 재사용하지 않는다.
- [E4c](E4c_surface_consistency_pruning_results.md)의 INCONCLUSIVE는 공통 평가 표본 부족이다. 이상점이 없다는 결과로 바꾸지 않는다.
- 드론에서도 이상점이 적으면 **검사한 조건에서 기존 파이프라인이 해당 문제를 실용적으로 억제했다**고 해석하고, MASt3R의 강한 기하 추정과 부합하는 관측으로 기록한다.
- MASt3R만의 인과적 효과로 확정하지 않는다. Gaussian head, 기존 confidence/scale 필터, KF 선택, pose, 입력 구간의 난이도가 결과에 영향을 줄 수 있다. 이를 구분하기 위해 raw pointmap부터 최종 active 지도까지 함께 측정한다.
- E4e는 E4의 REVISE를 소급 변경하거나 E5/E6 효능 검증의 자동 진입을 허용하지 않는다. 기존 E9의 드론 도메인 진단 중 데이터 준비·문제 존재 확인을 앞당긴 단계로 연결하고, E9에서 같은 결과를 새 독립 증거로 중복 집계하지 않는다.

## 2. 가설과 구분할 상황

| ID | 검증할 가설 또는 대안 | 관측과 해석 |
|---|---|---|
| H1 | 드론에서는 표면 밖 정점이 충분히 발생한다 | 평가 coverage가 확보된 서로 다른 장면에서 고립·표면 이탈 후보가 반복 관측되면 후속 제거 연구의 동기 확보 |
| H2 | 드론에서도 표면 밖 정점이 드물다 | raw와 active 모두 낮고 표면 누락도 크지 않으면 기존 기하 추정으로 충분할 가능성 지지 |
| A1 | 기존 active 필터가 오류를 대부분 숨긴다 | raw에서는 많고 active에서만 적으면 기존 필터 효과로 구분. MASt3R 단독 해결로 해석하지 않음 |
| A2 | 공통 pose/scale 오류 또는 일관된 표면 편향이 주 문제다 | 표면 전체가 GT와 다르지만 내부적으로 일관되면 정점 pruning보다 pose/geometry correction 문제 |
| A3 | 평가·재구성 자체가 부족해 적게 보인다 | LiDAR 미관측, 정렬 실패, 추적 실패, 낮은 지도 coverage면 INCONCLUSIVE |

이상점의 수가 많다는 사실만으로 렌더링에 해롭거나 안전하게 제거 가능하다고 결론 내리지 않는다. 이 두 가지는 후속 실험의 질문이다.

## 3. 데이터 선택과 GT 계약

### 3.1. 주 데이터: UAVScenes

UAVScenes는 실제 드론의 연속 RGB·LiDAR, 6DoF pose, calibration과 재구성 지도를 제공한다. 개발 1장면과 주 평가 2장면만 우선 확보한다. 전체 데이터셋을 먼저 다운로드하지 않고 다운로드 단위·용량·로컬 저장 공간을 확인한다. ([공식 저장소](https://github.com/sijieaaa/UAVScenes))

| 역할 | 시퀀스 | 목적 |
|---|---|---|
| 개발·입력/평가기 확인 | HKairport01 | 시간 동기화·카메라 보정·좌표계·정렬·평가 band 결정 |
| 주 평가 1 | AMtown01 | 건물·지면이 있는 마을 환경 |
| 주 평가 2 | AMvalley01 | 지형·식생이 있는 계곡 환경 |

공식 정보의 순항 고도는 HKairport01/AMtown01 80m, AMvalley01 130m다. 이는 실제 선택 구간의 지상고를 보장하지 않으므로 해당 구간의 비행 상태도 확인한다. ([MARS-LVIG 시퀀스 정보](https://mars.hku.hk/dataset.html))

**기준 데이터의 성격을 분리한다.** UAVScenes의 6DoF pose와 mesh는 GNSS 초기값을 사용한 DJI Terra SfM 재구성이다. 완전히 독립적인 실측 pose/표면 정답으로 부르지 않는다. 논문의 depth 기준은 대응 LiDAR 프레임에서 생성한다. E4e의 외부 기하 주 평가는 calibration된 실측 LiDAR의 유효 관측 영역을 사용하고, Terra mesh는 보조 진단으로만 사용한다. 원본 MARS-LVIG의 RTK·DJI L1 기준 자료가 추가로 필요하면 실제 제공 파일과 좌표계 호환성을 먼저 확인한다. ([UAVScenes §3.1·§4.6](https://arxiv.org/html/2507.22412v1))

실측 LiDAR와 같은 RGB로 만든 재구성 mesh의 결과를 같은 종류의 GT로 합산하지 않는다. LiDAR도 희소성·센서 오차·가림·동기화 오차를 가지므로 미관측 공간은 빈 공간이 아니다.

### 3.2. 구간과 입력 목록

개발·주 평가의 초기 구간은 각 시퀀스의 첫 RGB timestamp를 0으로 하여 **[30s, 90s)**의 60초로 고정한다. 선택은 오류 이미지나 예측 결과를 보기 전에 timestamp만으로 수행한다.

- 5Hz 시간 격자마다 가장 가까운 RGB를 선택한다. 허용 시간차 ≤0.05s, 중복 선택 금지, 동률은 이른 timestamp 우선이다.
- 매 다섯 번째 격자 `k mod 5 = 4`는 held-out RGB다. 최대 300장 중 mapping 240장, held-out 60장이다. mapping 경로에서 추가 subsample을 적용하지 않는다.
- held-out RGB는 tracker·retriever·pair prediction·KF 선정·지도 생성에 넣지 않는다. LiDAR와 기준 pose는 평가 전용 경로에 둔다.
- 60초를 세 개의 20초 구간으로 나누어 시간별 오류·coverage를 보고한다. 최종 지도 외에 각 구간 끝의 실제 snapshot을 저장한다.
- 선택 구간이 이륙·착륙·정지에 치우치지 않았는지 기준 trajectory/비행 메타데이터로 확인한다. 제안 대표성 gate는 구간 내 camera-center 이동 범위 ≥30m 및 mapping frame 중 ≥80%가 순항 상태인 것이다. 순항 상태의 판별 방법은 개발에서 비행 메타데이터 가용성에 맞춰 봉인한다. 판별 불가면 대표성 미확인으로 남긴다.
- timestamp 누락·파일 손상·비행 대표성 실패 시 해당 구간을 무효로 보고한다. 오류가 적거나 많다는 이유로 더 유리한 구간으로 이동하지 않는다. 재선정이 필요하면 접근 사유와 새 구간을 amendment로 먼저 등록한다.

이 입력 규모는 단기 진단용이다. 넓은 지역 전체나 장시간 비행에 대한 일반화는 주장하지 않는다. 개발 장면의 결과는 주 평가의 독립 장면 수에 포함하지 않는다.

### 3.3. 대체 데이터

UAVScenes의 접근 또는 정량 평가가 성립하지 않으면 사유를 보고하고 다음 선택을 별도 등록한다. 자동으로 합성 데이터를 실제 드론 결과로 대체하지 않는다. 우선 대체 후보는 Mid-Air의 **왼쪽 RGB+대응 depth+pose**다. 제공 depth는 왼쪽 카메라 기준이며 16-bit float PNG이므로 downward RGB와 혼용하거나 uint16 millimeter로 읽지 않는다. Mid-Air 결과는 합성 야외 진단으로 별도 표기한다. ([공식 센서 명세](https://midair.ulg.ac.be/tech_specs.html))

## 4. 기준선과 변경할 수 있는 부분

주 기준선은 기존 E4 계열의 **B1 original, seed 0, refinement 0 step**이다. 기존 실험의 실제 config·checkpoint·native active filter·KF buffer·실행 옵션을 manifest에서 읽어 상속하고 해시를 기록한다. 오래된 E0/E0b launcher를 그대로 복사해 설정이 같다고 가정하지 않는다.

| 유지 | 드론 적용을 위해 개발에서 조정 후 봉인 |
|---|---|
| 모델·가중치, tracker/mapping 알고리즘, Gaussian head, 새 pruning 없음 | 데이터 로더, timestamp, 이미지·K 변환, distortion 처리 |
| 기존 native filtering과 raw→active 이력 기록 | 실제 좌표 단위·거리 범위에 맞는 평가·렌더 clipping 설정 |
| GT를 추론·지도 갱신에 넣지 않음 | 센서/카메라 좌표계, 평가용 LiDAR 투영·pose 정렬 |

우선 기존 camera 사용 모드를 유지한다. calibration을 추론에도 사용하는 별도 arm이 필요하면 개발에서 등록하고 uncalibrated 기준선과 분리한다. GT pose를 tracker 대신 넣어 성공한 결과를 RGB-only SLAM 성공이라고 부르지 않는다.

`max-scale`·depth percentile·confidence·Gaussian cap·렌더 far plane 등 기존 설정이 야외 후보를 얼마나 제한하는지 전수 기록한다. **낮은 이상점 비율이 강한 필터나 지도 누락의 결과인지 확인**한다. 기존 5cm 수준의 실내 오차 band나 짧은 depth 범위를 드론에 그대로 적용하지 않는다. native filter를 바꾼 추가 arm은 주 기준선과 섞지 않고 별도 등록한다.

## 5. 구현·평가 성립: 먼저 확인할 것

### 5.1. 입력과 lineage

RGB 크기·색 순서·K·distortion·resize/crop의 합성을 검증하고 원본 frame/timestamp와 모델 입력 index를 연결한다. LiDAR–camera 외부 파라미터의 방향, camera–body 변환, quaternion 순서, metric 단위를 명시한다. 동일 timestamp가 같은 센서 노출 시점을 뜻하는지와 시차를 기록한다.

최소 세 층을 따로 export한다.

1. **raw pointmap:** 생성된 `pts3d`와 confidence, source pair/pixel. 주 raw 집계는 등록된 KF self branch를 사용하고 전체 pair 발생량은 별도로 보고한다.
2. **pre-active Gaussian 후보:** `means`·covariance·opacity와 원래 pointmap pixel의 대응.
3. **original-active 지도:** native 필터 이후 실제 남은 Gaussian과 제외 사유. 후보 ID 중복 없이 snapshot별 집계한다.

raw 정점과 Gaussian 중심을 같다고 가정하지 않는다. backbone 예측 위치와 Gaussian head offset의 차이, active 탈락의 영향을 구분한다. raw→active 대응이 안 되면 두 집단의 비율은 각각 보고하되 필터 효과의 후보별 원인 분석은 보류한다.

### 5.2. 추적·정렬

실제 estimated pose와 pose revision을 저장한다. 주 기하 평가는 최종 snapshot의 후보와 그 revision의 pose를 사용한다. 과거 snapshot에는 해당 시점의 pose만 결합한다.

외부 평가 좌표계로의 변환은 timestamp가 대응하는 camera trajectory의 **단일 Sim(3)**으로 정한다. 후보 점군/mesh에 대한 ICP, patch별 depth scale, 후보별 재정렬은 하지 않는다. camera 분포의 퇴화, scale 식별성, 전체·세 시간 구간의 위치/회전 잔차와 정렬 민감도를 보고한다.

제안 실행 gate는 mapping 입력의 pose 산출 ≥95%, 최장 연속 추적 중단 ≤2s다. 정렬 허용 범위·LiDAR 동기화 허용 범위·투영 오차 여유는 개발의 calibration 검사에서 수치로 정한 뒤 봉인한다. 숫자를 정하지 못하거나 전 구간을 하나의 scale로 비교할 수 없으면 주 평가의 정량 기하 결론을 보류한다. gate 통과가 GT pose의 무오차를 보증하지는 않는다.

### 5.3. 평가기가 이상점을 놓치지 않는지 확인

고정된 작은 기전 사례로 좌표 왕복·depth 정의·가림·경계·곡면/얇은 구조·고립점·일관된 이동 표면을 확인한다. 개발의 복사본에만 알려진 법선 방향 이탈을 주입해 nominal band의 2/5/10배 거리에서 검출률을 보고한다. 실제 원본 지도와 합성 이탈 지도는 분리하며, E5의 모델 공유 편향 실험을 대신한 것으로 취급하지 않는다.

정답이 알려진 명확한 앞쪽 이탈의 ≥90%를 검출하고, 무잡음 표면 fixture의 오분류 ≤1%를 초기 gate로 제안한다. 통과하지 못하면 실제 이상점이 적다는 판정을 내리지 않고 평가기를 보완한다. 이는 이번에 측정된 성능 수치가 아니다.

## 6. 이상점 정의: 내부 표면과 외부 정확도를 분리

### 6.1. 내부 표면 상태 C/N/U

후보를 제외한 source-image 이웃과 같은 raw의 3D 이웃을 사용해 정점 중심의 표면 소속을 검사한다. [E4d §5](E4d_surface_membership_validation.md)의 center/extent 구분을 참고하되, E4d 정책 및 추가 audit replay는 요구하지 않는다.

- **C — 일관된 표면:** 여러 크기의 국소 이웃에서 유효 표면에 속한다. 작은 별도 물체·별도 일관된 표면도 C가 될 수 있다.
- **N — 적극적 비소속:** 주변의 신뢰할 수 있는 표면은 존재하지만 center가 법선 방향으로 명확히 이탈한다. 유효 범위와 연결 성분을 확인한다.
- **U — 불확실:** 단순 저밀도, fit 실패, 경계, 곡면의 평면 근사 실패, 얇은 구조, 다중 표면 선택 불명 등.

초기 개발 후보는 중심 제외 image 7×7/13×13 robust fit 및 3D kNN 32/64다. 표면 band는 후보를 뺀 이웃의 normal-residual MAD와 spacing에서 정하며, C는 band 안, N은 두 평가기의 두 scale에서 3배 band 밖인 경우로 시작한다. 최소 유효점·연결성·hull·곡률 처리와 동점까지 개발에서 확정하고 평가 장면에서 바꾸지 않는다. fit 실패를 N으로 처리하지 않는다. 3σ가 표면과 겹친다는 이유로 중심을 C로 바꾸지 않는다.

이 분류는 추정 데이터의 내부 proxy다. 두 검사 모두 같은 모델 출력을 보므로 합의만으로 실제 물리적 이상점을 확정하지 않는다. 내부 N 비율과 U 비율을 함께 보고한다.

### 6.2. 외부 LiDAR 상태 A/F/B/U

동기화·calibration·가림 검사를 통과한 실측 LiDAR의 camera-z depth와 후보의 투영 depth를 비교한다. z-buffer의 유효 픽셀만 사용하고, sparse depth를 무제한 보간해 dense GT로 만들지 않는다. 참조 점 주변 허용 투영 범위와 경계 제외 규칙은 개발에서 고정한다.

- **A — 표면 근접:** 센서·pose 오차를 고려한 depth band 안.
- **F — 앞쪽 free-space 위반:** LiDAR가 실제 표면까지 관측한 광선의 앞쪽에 후보가 band를 넘어서 존재. 동적 물체·경계·가림 모순을 제외.
- **B — 뒤쪽 depth 차이:** 관측 표면보다 뒤에 있음. 뒤의 물체가 가려졌을 수 있으므로 이상점 확정에 사용하지 않음.
- **U — 외부 평가 불가:** 미관측, 사거리 밖, 투영/정렬 불확실, 가림 또는 의미 불명.

초기 nominal band 후보는 `max(0.10m, 0.01 × reference_depth, sensor_error)`이며, 여기에 별도로 산출한 pose/calibration 여유를 기록한다. 이 식은 센서 정확도 보증이 아니라 개발 시작값이다. `0.005/0.01/0.02 × depth` 민감도와 여유 전후 판정을 함께 보고한다. 큰 여유로 오류가 사라진 경우를 낮은 오류의 근거로 삼지 않는다. 실제 오차 모델을 정하지 못하면 INCONCLUSIVE다.

### 6.3. 교차 집계와 제거 목표

| 내부 × 외부 | 해석 |
|---|---|
| **N ∩ F** | 주 대상 T: 주변 표면 비소속과 실측 앞쪽 충돌이 함께 확인된 고립·표면 이탈 후보 |
| C ∩ F | 일관되지만 위치가 잘못된 표면 또는 잔여 pose/대응 오류. 별도 핵심 진단 |
| N ∩ A | 실제 구조를 내부 평가기가 이상으로 본 사례일 수 있음. 반드시 점검 |
| C ∩ A | 내부·외부가 함께 지지하는 표면 |
| N ∩ U / 내부 U | 이상점 부재로 세지 않고 불확실 비율로 보고 |

T는 GT 기반 **평가용 분류**이며 실제 GT-free 제거 정책이 아니다. 같은 후보가 다른 두 시점의 LiDAR로도 확인되는 `T_repeat`는 더 강한 보조 증거로 보고한다. 반복 시점 조건은 주 T 분모의 자격에 넣지 않아 E4c의 관측 교집합 실패를 반복하지 않는다. 다른 시점의 가시성과 변환이 불명하면 repeat만 U로 남긴다.

표면과 거리가 있다는 것만으로 모든 정점을 floating으로 부르지 않는다. Gaussian extent/opacity 때문에 중심 오류가 렌더에 드러나지 않는 경우도 따로 기록한다.

## 7. 지표와 분모

raw·pre-active·active마다 다음을 장면별·20초 구간별로 산출한다. snapshot 수치를 합쳐 같은 후보를 여러 개의 독립 표본으로 세지 않는다.

| 지표 | 정의/주의 |
|---|---|
| 전체 후보 수 N_all | 해당 층의 고유 후보, finite/nonfinite도 분리 |
| 내부 평가율 q_local | C 또는 N / N_all. C/N/U 전체 표 유지 |
| 외부 평가율 q_ext | 내부 C/N 및 외부 A/F/B가 모두 있는 후보 / N_all |
| **주 대상 비율 r_T** | T / 외부 평가 가능한 위 후보. 분자·분모 모두 표시 |
| 전체 대비 확인 비율 | T / N_all. 미평가 후보가 있어 **확인된 하한**으로만 해석 |
| 일관된 오류 비율 | C∩F / 외부 평가 가능 후보 |
| 불확실 비율 | 내부 U·외부 U 및 각 실패 사유를 분리 |
| 기존 필터 영향 | raw→pre-active→active의 대응, 제외 사유별 T/F/unknown 분포 |
| 표면 누락·재구성 coverage | 유효 LiDAR 표면 픽셀 중 실제 렌더 depth가 존재하는 비율 및 depth 오차 |
| 시각적 영향 | held-out RGB/depth, 고정 시점의 floater·hole 사례. 시각 관찰을 물리 정답과 구분 |

단순 후보 비율은 작은 Gaussian이 많은 영역에 편향될 수 있다. 고유 source-frame/pixel grid 단위와 공간 grid 단위의 분포를 함께 보고하고, 세 시간 구간·거리대·건물/지면/식생별 가능한 범위를 분리한다. 픽셀 수백만 개를 독립 표본으로 가정한 좁은 신뢰구간은 만들지 않는다. 불확실성은 source/KF 또는 시간 블록 단위의 변동으로 보고한다.

Gaussian 수·active/resident·VRAM·실행 시간은 실행 가능성 기록으로만 남긴다. 제거하지 않았으므로 메모리 감소나 pruning 품질 보존을 주장하지 않는다. 렌더 PSNR/SSIM/LPIPS는 가능하면 참고로 산출하되, 이 파일럿의 진행 gate로 새 최적화 목표를 만들지 않는다.

## 8. 사전 제안 판정 기준

수치는 문제 크기를 판별하기 위한 제안값이며, 개발 장면에서 측정 성립을 확인한 뒤 두 주 평가 장면을 열기 전에 고정한다. 오류가 많게 나오도록 평가 band나 구간을 조정하지 않는다.

### 8.1. 측정 가능 조건

각 주 평가 장면에서 다음을 모두 확인한다.

- 입력·좌표·추적·정렬·평가기 gate 통과 및 대표성 확인.
- 내부 평가율 `q_local ≥80%`.
- 외부 평가율 `q_ext ≥20%`, 평가 가능한 후보 ≥10,000개. 각 20초 구간에서도 외부 평가 후보 ≥1,000개.
- LiDAR 유효 표면에 대한 렌더 depth coverage ≥80%. 기존 cap·필터·range clipping 때문에 주요 표면이 사라지지 않았는지 별도 점검.
- 평가 대상이 특정 근거리·평면·시간대에만 몰렸는지 보고. 쏠림이 크면 결론을 그 부분집합으로 제한.

이 조건은 최소한의 진단 자격이지 전체 지도를 대표한다는 증명이 아니다. 특히 20%만 검사하고 나머지 80%에도 이상점이 없다고 추론하지 않는다.

### 8.2. 결과 판정

| 판정 | 제안 조건 | 후속 결정 |
|---|---|---|
| **TARGET_PRESENT** | 한 장면 이상에서 active `r_T ≥5%`, 최소 두 시간 구간에서 T 확인. band 민감도·고정 사례에서도 유지 | 다른 장면 결과와 차이를 함께 보고하고 해당 환경의 pruning 개발 검토 |
| **TARGET_SCARCE_IN_EVALUATED_REGION** | 두 주 장면 모두 active `r_T <1%`, 평가 가능한 각 시간 구간도 <1%, 민감도에서도 결론 유지 | 검사한 영역에서 pruning 동기가 약함. E4d/E5를 자동 실행하지 않고 방향 재검토 |
| **MIXED_OR_BORDERLINE** | 1–5%, 장면/시간/거리별 혼합, band에 따라 결론 변경 | 평균만으로 판정하지 않고 원인 분석 후 추가 표본 계획 |
| **INCONCLUSIVE** | 위 측정 가능 조건 미달·정렬 불명·추적 실패·심한 누락 | 이상점이 적다는 결론 금지. 데이터/평가기 보완부터 수행 |

SCARCE는 충분히 관측된 부분의 운영상 결론이다. 전체 지도에 대해서는 `T/N_all`과 미평가 후보를 모두 포함한 보수적 상한 `(T + N_unassessed)/N_all`도 제시한다. 상한이 크면 전체 지도에서 드물다는 주장을 하지 않는다. 두 장면만으로 드론 전체에 일반화하지 않는다.

**MASt3R 해석은 별도 열로 판단한다.** active가 SCARCE여도 raw에서 N/F가 많거나 native 필터 탈락·지도 누락이 크면 “기존 필터 또는 pipeline에서 억제”로 기록한다. raw와 active에서 모두 낮고 외부 depth 오차·coverage도 양호하면 다음과 같이 결론을 쓴다.

> 검사한 두 드론 구간의 평가 가능 영역에서는 기존 MASt3R 기반 파이프라인만으로 표면 밖 이상점이 드물었다. 이는 강한 기하 추정으로 해당 문제가 실용적으로 억제되었을 가능성과 부합하며, 이 조건에서 추가 pruning의 우선순위는 낮다.

C∩F가 많으면 고립점만 드물 뿐 기하 문제가 해결된 것은 아니다. MASt3R 단독 기여를 확정하려면 별도의 모델 대조/ablation이 필요하며, 그 인과 주장 검증까지 E4e의 필수 범위로 늘리지는 않는다.

## 9. 실행 순서와 산출물

1. **데이터 확보·등록:** 접근 가능성·라이선스·크기 확인, 지정 3시퀀스의 파일/구간 목록·원본 timestamp·calibration 해시 저장. 주 평가 예측 결과는 아직 생성하지 않는다.
2. **개발 성립:** HKairport01에서 로더·export·추적·정렬·LiDAR 평가·고정 기전 사례 검증. 모든 미정 상수와 입력 규칙을 확정한다.
3. **봉인:** 코드 commit/hash, weights, config, seed, raw/active 정의, 평가 band, mask, sampling, gate, source ID, 시각화 목록을 등록한다.
4. **주 평가 실행:** AMtown01·AMvalley01 각각 같은 설정으로 B1 실행. 실패도 결과로 보존하고 결과를 본 후 재조정하지 않는다.
5. **집계·사례 확인:** raw/pre-active/active의 교차 표·오류 분포·고정 시각화·threshold 민감도 산출. 장면별 판정과 MASt3R 관련 해석을 분리한다.
6. **진행 판단:** TARGET_PRESENT면 E4d를 드론 조건에 맞춰 재검토한다. SCARCE면 고립점 제거 연구를 보류하거나 중복/표현 효율 문제로 방향 변경을 검토한다. INCONCLUSIVE면 평가 기반부터 보완한다. E5로 바로 진행하지 않는다.

실행 산출물과 미완료 경로:

```text
configs/e4e_uav_dataset_pilot.json
configs/e4e_dataset_manifest.json
configs/e4e_results_summary.json
configs/e4e_window_amendment_A1.json
configs/e4e_window_selection_A1.json
configs/e4e_input_split.json
scripts/prepare_e4e_uav_inputs.py
scripts/run_e4e_baseline.py
results/E4e_uav_dataset_pilot/representativeness.json
results/E4e_uav_dataset_pilot/development/HKairport01/baseline/
  run_manifest.json  exports/  audit/  map/  logs/
results/E4e_uav_dataset_pilot/<primary-scene>/  # gate 미통과로 실행하지 않음
docs/experiments/E4e_uav_dataset_pilot_results.md
```

결과 보고서에는 장면별 실행/중단 이유, 데이터 구간, GT 종류, 추적·정렬 오차, raw/active 수, C/N/U×A/F/B/U 표, 평가 coverage, T/T_repeat, 일관된 표면 오류, 렌더 누락, native 필터 영향, 판정과 후속 결정을 포함한다. 대표 사례는 결과를 보기 전에 고정한 시간 격자의 영상·측면 점군과, 교차 분류별 seed 0 표본을 함께 사용한다. 큰 이상 사례의 추가 시각화는 탐색 사례로 표시한다.

기존 Replica의 데이터·baseline·결과·봉인 코드는 덮어쓰지 않는다. 이번 실행에서는 데이터 확보, 개발 입력 구성, B1 기준선과 추적·pose 사전 gate까지 진행했다. 개발 gate 실패 후 주 평가 장면을 열지 않았다. **후속 실행에서 설정이나 구간을 바꾸려면 새 amendment와 출력 version을 등록하고, 이번 실행 산출물은 보존한다.**
