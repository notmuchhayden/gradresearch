# E4f: KITTI 야외 기하 정합성 진단 계획

**상태: B1 A2b 실행 및 오프라인 진단 완료, MIXED (2026-10-22).** 실행 결과는 [E4f 결과 보고서](E4f_kitti_geometry_diagnostic_results.md)를 참조한다. Raw pointmap에서 거리 의존 depth mismatch가 관측됐고, 단일 OXTS pose oracle에서 누적 LiDAR coverage가 개선됐다. 따라서 local geometry와 pose 배치가 모두 기여할 가능성이 있다. 단일 drive 결과로 원인 비중이나 연구 주제를 확정하지 않는다. **이 계획은 새 기하 보정법의 효능을 검증하지 않는다.**

## 1. 목표와 질문

KITTI Raw에서 단일 전방 RGB 영상만 B1에 입력하고, 동기화된 Velodyne·GPS/IMU pose는 평가 참조로만 사용해 다음 원인을 구분한다.

> 최종 지도의 표면 왜곡은 (a) 이미지 쌍에서 나온 raw pointmap의 국소 깊이 오차, (b) 추정 camera pose 및 keyframe 정합 오차, (c) pointmap을 world map/Gaussian으로 누적하는 경로의 변형 중 무엇과 가장 잘 부합하는가?

E4f는 원인 분리용 진단이다. **GT는 모델 입력, tracker, map update, Gaussian 생성, parameter 선택에 사용하지 않는다.** 결과를 보고 주제를 “Gaussian 이상점 제거”에서 “MASt3R-SLAM 기하 정합성”으로 자동 변경하거나 E5/E6에 진입하지 않는다.

## 2. 데이터셋 및 장면 선택

### 2.1. 우선 데이터: KITTI Raw

KITTI는 독일 Karlsruhe 도로·도시·교외·고속도로에서 차량에 장착한 카메라로 촬영한 실제 RGB 영상이다. Raw 자료는 동기화·보정된 색상 영상, Velodyne 점군, GPS/IMU, 카메라·LiDAR 보정값을 포함한다. KITTI 공식 설명에 따르면 센서 데이터는 10Hz로 기록되며, synchronized+rectified 스트림은 센서별 frame index가 대응한다. ([공식 Raw Data 설명](https://www.cvlibs.net/datasets/kitti/raw_data.php?type=road))

우선 후보는 **2011-09-26의 `drive_0005_sync`**로 고정한다. 공식 접근이 되지 않거나 아래 입력 성립 조건을 충족할 수 없을 때만, 모델 예측 전에 순서대로 `drive_0013_sync`, `drive_0015_sync`를 확인한다. 장면은 drive 하나만 사용하며 결과를 본 후 바꾸지 않는다. 후보 순서·다운로드 가능 여부·연속 frame 수·손상 여부·주행거리만 metadata preflight에서 확인하고, 통과한 첫 drive를 config에 봉인한다.

지도 형성을 볼 수 있도록 선택 drive에서 첫 유효 시점부터 **연속 240개 RGB/LiDAR/OXTS frame(약 24초)**을 사용한다. 최소 성립 조건은 RGB–LiDAR–OXTS의 동기화 자료 240개, 연속 camera 이동거리 30m 이상, 손상 RGB 0개다. 조건을 만족하는 후보가 없으면 입력 기준을 완화하지 않고 E4f를 데이터 접근/대표성 INCONCLUSIVE로 종료한다. 후보를 확인하는 데 사용하는 RGB 미리보기는 허용하지만, Splatt3R-SLAM 예측·PLY·depth 오차를 본 뒤 선택하지 않는다.

개별 Raw drive와 날짜별 calibration만 요청한다. KITTI Odometry 전체 색상 이미지와 Velodyne 묶음은 각각 공식 페이지에 65GB, 80GB로 기재되어 있어 다운로드하지 않는다. Raw drive 크기와 저장 공간은 다운로드 전에 확인한다. KITTI 자료는 공식 안내상 **CC BY-NC-SA 3.0** 조건을 따른다. 비상업 연구 용도, 데이터 출처 표기, 재배포 제한을 지킨다. ([KITTI 사용 조건·데이터 설명](https://www.cvlibs.net/datasets/kitti/), [Odometry 데이터 크기](https://www.cvlibs.net/datasets/kitti/eval_odometry.php))

### 2.2. 입력과 참조의 분리

| 신호 | 사용 | 매핑 사용 여부 |
|---|---|---|
| 동기화·rectified `image_02` 전방 RGB | B1 카메라 입력·모델 예측 | **사용** |
| 같은 시각 Velodyne scan | depth 비교, GT surface reference | **금지** |
| GPS/IMU(OXTS) trajectory | 추정 pose 평가, 오프라인 pose-oracle 진단 | **금지** |
| camera–Velodyne·camera–IMU calibration | 센서 좌표 변환 및 평가 projection | mapping config에 주입 금지; GT 투영에만 사용 |
| KITTI tracklet object labels | 동적 차량·보행자·자전거 mask 및 평가 coverage 분리 | **금지** |

KITTI의 Velodyne depth는 영상 전체에 값이 있는 dense depth가 아니라 가시 표면에 희소하게 투영되는 실측점이다. 빈 픽셀은 “깊이가 없음”으로 취급하고 오류나 free-space 증거로 세지 않는다. 같은 RGB와 OXTS pose에서 생성된 점군은 완전히 독립적인 데이터가 아니므로 이를 외부 참조라고 과장하지 않는다. depth 오차는 LiDAR 가시·유효 coverage 안에서만 보고한다.

차량 주행 장면의 동적 객체는 static background geometry와 섞지 않는다. 예측 전 등록한 A1 amendment에 따라 동기화된 KITTI tracklet 3D 상자를 평가에서만 사용해 LiDAR 점과 대응 image pixel을 제외/표시한다. 라벨 밖의 동적 객체가 남을 수 있으므로 annotated-dynamic 제외 전후 coverage와 residual을 함께 보고하며, 라벨을 mapping input이나 시각화 frame 선택에 사용하지 않는다.

**A1 amendment (2026-10-22, model prediction 전):** moving-object tracklet mask를 LiDAR/RGB 평가 자격 분류에 추가한다. B1 입력·모델·pose·후보·매핑 동작 및 frame 선택은 변경하지 않는다. 동적 mask 적용 후 비교 표본이 부족하면 정적 표면 지표를 INCONCLUSIVE로 남긴다. mask로 결과를 유리하게 만들거나 tracklet에 없는 물체를 정적이라고 단정하지 않는다. 상세 등록은 [A1 amendment](../../configs/e4f_amendment_A1.json)에 둔다.

**A2 amendment (첫 실행 종료 후, 재실행 prediction 전):** 첫 RGB 10Hz 실행은 33번째 input에서 32 keyframe storage capacity에 도달해 중단됐다. 8GiB GPU에서 240-slot buffer의 선할당이 안전하지 않아, 선택한 동일 24.75초·240개 timestamp 구간은 그대로 두고 짝수 index RGB 120장(약 5Hz)만 B1에 넣는다. buffer capacity만 128로 높이고 LiDAR/OXTS 240개는 평가 자료로 유지한다. 이는 원본 10Hz B1과 matched-rate가 아니므로 10Hz 실패와 A2 결과를 분리 보고한다. A2 상세는 [A2 amendment](../../configs/e4f_amendment_A2.json) 참조.

**A2b launcher correction (재실행 전 등록):** A2 설정을 적용해야 할 두 번째 launcher가 `--keyframe-buffer 32`를 고정 전달해 A2 시도도 input frame 33에서 실패했다. 이 실행 오류를 보존하고, 데이터·모델·평가 protocol 변경 없이 capacity 128 인자만 수정해 새 `baseline_A2b/`에 재실행했다. 상세는 [A2b amendment](../../configs/e4f_amendment_A2b.json) 참조. 최종 유효 설정은 [effective config](../../configs/e4f_kitti_A2b_effective.json)다.

## 3. 가설과 구분할 원인

| ID | 관측 패턴 | 우선 해석 |
|---|---|---|
| H1 local depth/pointmap | camera-local raw pointmap이 같은 시각 LiDAR와 크게 다르고, 추정 pose 대신 OXTS pose를 사용해도 오차가 유지됨 | 이미지 쌍의 depth/pointmap 또는 calibration·projection 문제 가능성 |
| H2 pose/정합 | local raw pointmap의 유효 LiDAR 영역 오차는 작지만 B1 world map에서 표면 위치가 벌어짐; 같은 raw pointmap의 OXTS-pose 오프라인 재배치에서 불연속이 줄어듦 | tracker·pose/keyframe 정합 오차 가능성 |
| H3 fusion/좌표 처리 | local 기하와 pose 비교는 양호한데 실제 B1 누적 지도가 크게 달라짐; raw→pre-active 또는 pre-active→active 대응에서 변형이 확인됨 | coordinate conversion, revision/fusion, Gaussian serialization 경로 조사 필요 |
| H4 mixed/unknown | 원인이 겹치거나 GT coverage·calibration·pose 정렬이 부족함 | INCONCLUSIVE; 한 원인으로 귀속 금지 |

이 결과는 MASt3R 네트워크 단독의 인과 효과를 분리하지 않는다. B1의 tracker, keyframe 선택, confidence/native filter, calibration과 SPLAT Gaussian 변환을 포함한 **전체 파이프라인 진단**으로 기술한다.

## 4. 실행 조건

### 4.1. 기준선

E4의 **B1 original, seed 0, refinement 0, 새 pruning 없음, native filter 유지**를 기준선으로 한다. 현재 저장소의 실제 E4 B1 config, weights, upstream Splatt3R-SLAM commit, camera resize/crop, confidence·depth·scale·Gaussian 한도, 실행 옵션을 상속하고 모두 hash/manifest에 기록한다. 데이터로더와 timestamp/calibration 입력만 KITTI 형식에 맞게 구현한다. B1 자체의 모델/가중치/추론·지도정책을 바꾸지 않는다.

입력은 `image_02` 한 대의 색상 카메라만 사용하고 stereo 오른쪽 카메라, LiDAR, OXTS를 추론 과정에서 읽지 않는다. 원본 이미지와 모델 입력 간 rectification·intrinsics·resize transform을 기록한다. 공식 camera–Velodyne transform 방향, 축 순서, metre 단위, timestamp matching은 고정 기전 사례로 확인한다.

### 4.2. 필수 산출물 및 lineage

동일 source ID와 frame/pixel lineage를 가능한 한 유지하며 최소 다음 단계를 구분한다.

1. **Raw prediction:** camera-local self-branch pointmap와 confidence. 단일 pair 출력과 누적/필터된 raw 출력이 다르면 둘 다 별도 저장한다.
2. **Pre-active candidates:** Gaussian `means`, covariance, opacity와 raw pointmap ID/pixel 대응.
3. **Active map:** native filter 후의 실제 map, point ID와 탈락 원인.
4. **Pose/fusion trace:** frame별 estimated pose, timestamp, keyframe 선택, loop/revision event, 각 snapshot의 pose version과 map update lineage.

raw-to-Gaussian 후보 ID가 이어지지 않으면 각 단계 수량과 분포만 따로 보고하고 후보별 삭제 원인을 주장하지 않는다. 모든 output은 새로운 `results/E4f_kitti_geometry_diagnostic/` 아래에 쓴다. E4/e의 실행 산출물과 체크포인트는 덮어쓰지 않는다.

### 4.3. 진단 비교군

- **B1 primary:** RGB만으로 끝까지 실행한 결과. A2 기준은 사전 등록한 5Hz RGB 120장이고 모든 예측·Gaussian 생성은 추정 pose를 사용한다. 실패한 10Hz 시도는 별도 resource failure로 보존한다.
- **Local pointmap vs LiDAR:** 우선 raw camera-local pointmap을 같은 camera frame의 projected Velodyne와 비교한다. 사용한 pair branch·frame·timestamp와 유효 투영 mask를 남긴다.
- **Trajectory evaluation:** 추정 camera trajectory와 OXTS trajectory를 trajectory 대응만 사용해 단일 Sim(3)으로 정렬한다. map/point cloud에 ICP나 부분별 scale fitting을 하지 않는다.
- **Pose-oracle diagnostic (offline only):** 구현상 raw camera-local geometry와 대응이 정확히 보존된 경우에 한해, **기존 raw pointmap은 그대로 두고** OXTS pose로 별도 world map을 만드는 평가 전용 비교를 추가한다. B1 지도나 예측에 GT pose를 되먹이지 않는다. 좌표 lineage를 검증할 수 없으면 이 비교군은 생략하고 그 원인을 INCONCLUSIVE로 기록한다.

Pose-oracle 진단은 예측 모델 성능이나 배포 가능한 성능이 아니다. 단지 예상되는 pose error를 제거했을 때 누적 표면 차이가 변하는지 확인하는 원인 분리 수단이다.

## 5. 지표 및 성립 gate

모든 주요 metric은 LiDAR가 실제 투영되는 위치에서만 계산하며 거리 구간(예: 0–10m, 10–20m, 20–40m, 40m 이상)과 시간 구간별로 나눈다. 구간 경계·최소 점 수·outlier 절단 규칙은 GT 오차 결과를 보기 전에 작은 calibration 표본과 고정 fixture로 정하고 봉인한다.

| 축 | 지표 |
|---|---|
| Local pointmap depth | sparse LiDAR와의 depth absolute/relative residual median·p95, 유효 비교 pixel/점 수, range별 coverage |
| Pose | estimated-vs-OXTS 단일 Sim(3) scale, translation/orientation residual 및 trajectory coverage |
| 누적 geometry | 추정 pose 지도와 OXTS-pose oracle 지도 각각의 LiDAR surface residual·coverage; 표면 위치의 시간별/공간별 오차 분포 |
| Gaussian 변환 | raw pointmap→pre-active 중심 offset, native filter 전후 점 수/공간 coverage; Gaussian center를 depth 품질과 혼동하지 않음 |
| 장면 보존/실패 | fixed-view map/PLY 스크린샷과 선택 이전에 고정한 frame index; 렌더링 인상은 정량 GT 판정을 대체하지 않음 |

평면 오차를 계산할 때 도로를 완전한 수평 단일 plane으로 강제하지 않는다. 도로의 종·횡단 경사와 배수 crown이 있을 수 있으므로, 확인 가능한 국소 LiDAR surface와만 비교한다. KITTI의 희소점 coverage가 surface 평가에 부족하면 평면 단차 판정은 미실행으로 남긴다.

실행 gate는 RGB mapping 입력 pose 산출률 **≥95%**, 최장 연속 중단 **≤2초**, camera/LiDAR 시각 대응 및 calibration 좌표계 검사 통과, OXTS trajectory의 단일 Sim(3) 식별 가능, 평가 영역별 LiDAR coverage 유효성을 요구한다. 실패한 축의 수치는 진단 참고로만 제시하고 전체 원인 결론은 INCONCLUSIVE로 남긴다. 특히 RGB pose gate 실패가 local pointmap의 단일-frame depth 평가 자체를 무효화하지는 않지만, 전역 누적 지도 비교는 유효하지 않을 수 있다.

## 6. 실험 순서와 결과에 따른 결정

1. **사전 확인:** 현재 dataset dir·여유 용량·KITTI access/licence·선정 후보의 RGB/LiDAR/OXTS·calibration 파일 수와 hashes를 확인한다. 다운로드 전체 archive가 불필요하게 크면 중단하고 개별 drive 경로를 확인한다.
2. **Metadata-only 선택:** 후보 순서, timestamp 대응, frame 수·이동거리 조건으로 첫 유효 drive/240-frame window를 봉인한다. 모델 실행 전 config·입력 split hash를 남긴다.
3. **Loader/calibration 성립:** 입력 image transform, LiDAR→camera 투영 방향, OXTS pose 변환과 단위, 고정 기전 사례를 검증한다. 실패 시 모델 추론 전 중단한다.
4. **B1 개발 진단:** RGB only로 기준선을 실행하고 pointmap/pose/map lineage와 평가 전용 LiDAR/OXTS 비교를 산출한다. 주장이 가능한 coverage인지 먼저 판정한다.
5. **오프라인 원인 분리:** 좌표계가 검증된 경우에만 같은 raw geometry의 OXTS-pose oracle 누적 지도를 추가한다. GT를 B1 실행에 주입하지 않는다.
6. **결과 보고:** H1–H4 중 부합하는 범위, 반대 증거, coverage·pose 한계를 함께 기록한다. 화면 시각화를 결과를 보고 선택했다면 탐색 그림으로 구별한다.

| 판정 | 기준 | 후속 |
|---|---|---|
| `LOCAL_GEOMETRY_DOMINANT` | camera-local raw depth 오류가 크고 oracle pose로도 유지 | depth/pointmap calibration·cross-view geometry 방법을 별도 설계. MASt3R 단독 귀속은 보류 |
| `POSE_OR_FUSION_DOMINANT` | local 점군은 비교 가능하고, 추정 pose map에서만 누적 불일치가 커지며 oracle에서 줄어듦 | tracker/keyframe/fusion의 특정 오류를 더 좁혀 새 가설 등록 |
| `MIXED` | 두 단계 모두 유의한 불일치 | 하나의 원인으로 단순화하지 않고 다음 연구 범위를 개발 등록 |
| `NO_CLEAR_GEOMETRY_FAILURE` | coverage가 충분한 범위에서 local 및 누적 오차가 작음 | 해당 조건에서 관측된 지배 오류 없음. 이상점 pruning이 불필요하다는 보편 결론은 금지 |
| `INCONCLUSIVE` | GT coverage·alignment·tracking·loader·좌표 lineage 부족 | 입력/평가 자격을 수정해 amendment 등록; 결과에 맞춘 사후 gate 완화 금지 |

## 7. 재현·누설 방지·산출물

GT LiDAR와 OXTS는 loader, tracker, retrieval, pair selection, keyframe 선택, map update, Gaussian filter, rendering parameter, threshold tuning에서 사용하지 않는다. 평가 임계값과 고정 시각화 목록은 지표를 열기 전에 기록한다. E4f는 단일 개발 drive에 대한 진단이므로 독립 장면 일반화, 새 depth correction 방법의 효능, 연구주제의 최종 타당성을 주장하지 않는다. 후속 평가가 필요하면 두 번째 미노출 drive와 새 등록을 추가한다.

예정 문서·설정·산출물:

```text
docs/experiments/E4f_kitti_geometry_diagnostic.md
configs/e4f_amendment_A1.json
configs/e4f_amendment_A2.json
scripts/register_e4f_a2_sampling.py
configs/e4f_kitti_selection.json
configs/e4f_kitti_geometry_diagnostic.json
configs/e4f_kitti_input_split.json
configs/e4f_kitti_dataset_manifest.json
scripts/prepare_e4f_kitti_inputs.py
scripts/run_e4f_kitti_baseline.py
scripts/evaluate_e4f_kitti_geometry.py
results/E4f_kitti_geometry_diagnostic/<selected_drive>/
  input_manifest.json  run_manifest.json  pointmaps/  poses/  maps/  lidar_eval/  figures/
docs/experiments/E4f_kitti_geometry_diagnostic_results.md
```

이 계획 작성 단계에서는 데이터 다운로드, loader 구현, B1 실행, 결과 plot을 수행하지 않았다. 실행 전에 자료 크기·라이선스·선정 frame·평가 상수를 확인하고 config/hash에 등록한다.

## 참고 자료

- [KITTI Raw Data](https://www.cvlibs.net/datasets/kitti/raw_data.php?type=road): synchronized+rectified RGB, Velodyne, GPS/IMU, calibration 설명
- [KITTI Odometry](https://www.cvlibs.net/datasets/kitti/eval_odometry.php): sequence 및 pose 제공 범위, 전체 archive 용량
- [KITTI Vision Benchmark Suite](https://www.cvlibs.net/datasets/kitti/): 출처 및 CC BY-NC-SA 3.0 사용 조건
