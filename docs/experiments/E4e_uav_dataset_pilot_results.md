# E4e 결과: UAVScenes 개발 기준선 실행

**실행일: 2026-10-22. 판정: INCONCLUSIVE — 개발 추적 gate 미통과.** 사용자가 알려준 실행 방식으로 샌드박스 밖의 GPU를 조회했고, RTX 5060을 통해 HKairport01의 B1 기준선은 끝까지 실행됐다. 개발 구간의 pose 산출률은 정확히 95%였지만 연속 추적 중단이 2.4초로 사전 한도 2초를 넘었다. 따라서 LiDAR 이상점 분류와 두 주 평가 장면은 실행하지 않았다. 이 결과는 UAV에서 이상점이 적거나 많다는 뜻이 아니다.

## 실행 범위와 데이터

- 공식 UAVScenes 저장소가 연결한 interval=1 데이터 중 등록한 세 sequence archive만 받았다. 합계 37,390,235,179 bytes다. 파일 SHA-256과 다운로드 명세는 [dataset manifest](../../configs/e4e_dataset_manifest.json)에 기록했다. 원본 저장소는 전체 interval=1과 1/5 크기의 interval=5를 별도로 안내하며, Hugging Face 공개본은 interval=5다. ([UAVScenes 공식 저장소](https://github.com/sijieaaa/UAVScenes))
- 등록된 [A1 amendment](../../configs/e4e_window_amendment_A1.json)는 최초 HKairport01 [30s,90s) 구간에서 RTK 속도 1m/s 이상인 매핑 시점이 43.1%여서 대표성 gate를 통과하지 못한 사실만 근거로 삼았다. 예측 결과를 보기 전에 amendment를 기록하고, 결정 규칙이 고른 가장 이른 적격 구간인 **시퀀스 시작 기준 [60s,120s)**를 세 장면 모두에 적용했다.
- timestamp 이름만 사용해 장면당 300개 5Hz 격자를 만들었다. 매핑 240장, held-out 60장이며 held-out RGB 픽셀은 추론에 넣거나 열어보지 않았다. 입력 목록은 [split manifest](../../configs/e4e_input_split.json)에 있다.
- raw RTK easting/northing에서 1m/s 이상인 매핑 시점 비율은 HKairport01 93.3%, AMtown01 91.7%, AMvalley01 95.0%였고 각 장면의 최대 수평 이동 범위도 30m를 넘었다. 모두 대표성 gate를 통과했다. 이미지–LiDAR timestamp 차이의 최대값은 각각 0ms, 18.7ms, 43.8ms였다.
- official MARS-LVIG camera–LiDAR calibration을 사용했다. 개발 HKairport01의 LiDAR scan 1개에서 공식 extrinsic 방향은 LiDAR→camera일 때 이미지 안에 투영되는 점이 98.36%였고 역방향은 유효 양의 camera-z 투영이 0개였다. 이는 방향 기전 확인일 뿐, 세 장면 전체의 projection/calibration 정확도 gate 완료를 뜻하지 않는다. distortion remap은 기준선 설정대로 끈 채 진행했다.

## HKairport01 B1 기준선

[B1 설정](../../configs/e4e_uav_dataset_pilot.json), 실행 명령·코드·가중치·입력 hash는 [run manifest](../../results/E4e_uav_dataset_pilot/development/HKairport01/baseline/run_manifest.json)에 저장했다. 모델과 기존 native filter는 E4 B1, seed 0, refinement 0이며 GT pose와 LiDAR는 mapping 과정에 사용하지 않았다. 실행은 return code 0으로 끝났다. 시작 시 CUDA allocator OOM 경고가 한 번 있었지만 실행은 중단되지 않았다.

| 항목 | 측정값 |
|---|---:|
| 매핑 RGB 입력 | 240 |
| raw pair export | 240개 / 51,118,080 pointmap rows (전체 pair 발생량) |
| 최종 지도에 남은 keyframe | 21 |
| 등록 KF self-branch raw pointmap | 4,472,832점, 모두 finite |
| pre-active Gaussian 후보 | 4,472,832개, 모두 finite |
| native filter 후 active Gaussian | 3,242,219개 |
| pre-active에서 active로 제외 | 1,230,613개 (27.5%) |
| pose 산출 | 228 / 240 (95.0%) |
| 최장 연속 pose 누락 | 12개 매핑 프레임 / 2.4초 |
| trajectory 단일 Sim(3) 정렬 scale | 39.87 |
| 위치 잔차 (전체 정렬) | RMSE 2.35m, median 2.13m, p95 3.60m |
| 회전 잔차 | median 4.96°, p95 5.70°, max 6.40° |

pre-active Gaussian 중심은 개발 기준선에서 같은 candidate ID의 raw self-branch pointmap과 4,472,832개 모두 동일했다(측정한 offset norm median/p95 0). All-pair의 51.1M rows는 반복 예측을 포함하므로 고유 지도 정점 수로 해석하지 않는다.

## 판정과 미실행 범위

사전 tracking gate는 매핑 pose 산출 `≥95%`와 최장 연속 중단 `≤2s`를 함께 요구한다. 첫 조건은 경계값으로 통과했지만 두 번째 조건은 0.4초 초과했다. 단일 Sim(3)은 계산 가능했으나, 실패를 본 뒤 다른 구간을 고르면 사후 선택이 되므로 구간을 바꾸지 않았다.

이에 따라 개발 단계에서 protocol을 seal하지 않았고, AMtown01/AMvalley01 baseline 추론을 열지 않았다. C/N/U 내부 표면 분류, LiDAR 기반 A/F/B/U와 T/T_repeat, q_local/q_ext/r_T, coverage, held-out render, threshold 민감도는 **미측정**이다. 기존 native filter가 27.5%를 제외했다는 것만으로 이상점 제거 효과를 주장하지 않는다.

원본 archive는 `data/E4e/archives/`, mapping용 HKairport01 입력은 `data/E4e/eth3d/HKairport01/`, 개발 LiDAR와 Terra pose 참조는 `data/E4e/evaluation_only/HKairport01/`에 있다. 평가 RGB는 별도 추출하지 않았다. 실행 summary와 기하/추적 gate 상세는 [preflight 결과](../../results/E4e_uav_dataset_pilot/development/HKairport01/preflight.json) 및 [대표성 결과](../../results/E4e_uav_dataset_pilot/representativeness.json)에 기록했다.

이 INCONCLUSIVE는 실행 환경 문제가 아니라, 이번 60초 B1 개발 실행의 추적 gate 결과다. E4/E4c 기존 판정과 E5/E6 보류는 변경하지 않는다.
