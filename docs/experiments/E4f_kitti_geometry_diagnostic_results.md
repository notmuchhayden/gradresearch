# E4f KITTI 야외 기하 정합성 진단 결과

**실행 상태: B1 A2b 완료, 기하 원인 판정은 MIXED (단일 drive 개발 진단, 2026-10-22).** 첫 10Hz 시도와 A2 launcher 오류는 별도로 보존했다. 이 결과는 B1 전체 파이프라인에 대한 관찰이며 MASt3R 네트워크 단독 인과 결과가 아니다.

## 실행 기록

- 선정 sequence: `2011_09_26_drive_0015_sync`; 처음 240개의 synchronized RGB/LiDAR/OXTS 기록(24.75초). LiDAR와 OXTS는 모델 실행에서 차단했다.
- 실행 GPU: NVIDIA GeForce RTX 5060, VRAM 8,151 MiB; PyTorch 2.13.0+cu132, CUDA 13.2.
- 최종 run: [baseline_A2b](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/baseline_A2b/run_manifest.json), 120 RGB 입력(원본 frame stride 2, 약 5Hz), keyframe capacity 128, refinement 0, seed 0. 2분 10초 내 정상 종료했고 114개 keyframe을 저장했다.
- 첫 10Hz 실행은 32-slot keyframe 용량을 넘어 입력 frame 33에서 실패했다. A2에서 등록한 128 용량이 두 번째 launcher 실행에 반영되지 않아 `baseline_A2`도 같은 이유로 실패했다. A2b는 launcher 인자를 128로 수정한 뒤 새 디렉터리에 실행했으며 앞선 두 출력은 보존했다.
- 저장된 trajectory는 120/120 input timestamp와 정확히 대응했고, 예상 tracking break는 0초였다. 세션 용량 제한 때문에 model 입력은 5Hz이므로 이 결과를 10Hz 결과나 UAV 실행과 matched-rate 비교하지 않는다.

## 관측 결과

| 항목 | 결과 |
|---|---:|
| RGB pose coverage | 120/120 (100%) |
| RGB–pose 최대 timestamp 오차 | 0 ms |
| keyframe 수 | 114 |
| 단일 Sim(3) trajectory scale | 5.480 m / SLAM unit |
| Sim(3) 정렬 translation 오차 | RMSE 5.54 m, median 4.61 m, p95 10.66 m |
| orientation 오차 | median 12.51°, p95 13.11° |
| tracklet box로 가려진 LiDAR 점 비율 | 0.41% |
| keyframe raw Gaussian 후보 | 8,404,992 (114 × 144 × 512) |
| active Gaussian PLY | 5,148,781 |

### Raw camera-local pointmap과 LiDAR depth

각 입력에서 기록한 self-branch camera-local `pts3d`를 같은 timestamp Velodyne에 투영해 비교했다. 이미지 resize/crop 및 카메라 보정 투영을 적용했고, 같은 pixel에서는 가장 가까운 LiDAR return만 남겼다. KITTI의 36개 tracklet 3D 상자 안에 든 LiDAR 점은 평가에서 제외했다. 점 수는 0–10m 569,175개, 10–20m 730,900개, 20–40m 478,747개, 40–80m 182,289개였다. 80m 이상은 이 구간에서 유효 표본이 없었다.

| LiDAR range | Native pointmap signed median | Native abs median / p95 | 단일 trajectory scale 적용 후 static signed median | 단일 scale 후 abs median / p95 |
|---|---:|---:|---:|---:|
| 0–10 m | -5.80 m | 5.80 / 7.33 m | +2.77 m | 2.77 / 5.48 m |
| 10–20 m | -10.54 m | 10.54 / 14.62 m | +4.81 m | 4.83 / 10.27 m |
| 20–40 m | -20.32 m | 20.32 / 29.38 m | +8.41 m | 8.52 / 22.17 m |
| 40–80 m | -38.57 m | 38.57 / 56.83 m | +10.76 m | 11.41 / 34.18 m |

Raw pointmap의 native z는 LiDAR보다 낮게 나타났고, trajectory로 구한 전역 scale 하나를 적용하면 오차 방향이 반대로 바뀌지만 range가 커질수록 오차가 남았다. 따라서 단일 상수 scale 문제만으로 이 depth 차이를 없앨 수 없었다. 이는 이 drive·이 입력 해상도·B1 설정의 local geometry 불일치 증거다. 정적 배경 관측에서도 같은 패턴이 남았고 tracklet mask 전후 차이는 작았다.

### 동일 raw geometry의 pose-oracle 비교

keyframe마다 raw self-branch의 Gaussian `means`와 저장된 keyframe Gaussian 중심이 bit-exact하게 일치함을 확인했다. 그 동일한 카메라-local 중심을 바꾸지 않고, estimated final pose 또는 OXTS pose로 재배치했다. 하나의 trajectory scale만 사용했으며 ICP와 frame별 scale fit은 사용하지 않았다. LiDAR 참조는 tracklet 상자 제외 후 같은 camera crop에 투영된 점 1,961,334개다.

| 배치 pose | Map→static LiDAR NN median / p95 | Static LiDAR→map NN median / p95 |
|---|---:|---:|
| Estimated B1 pose | 1.25 / 6.50 m | 1.05 / 5.30 m |
| OXTS pose oracle | 0.71 / 7.89 m | 0.45 / 2.07 m |

Oracle에서 LiDAR→map coverage와 median이 개선됐지만 map→LiDAR의 p95는 악화됐다. pose 배치가 누적 오차에 기여한다는 증거와 local pointmap 자체의 depth mismatch 증거가 함께 관측되어 `MIXED`로 분류한다. 다만 NN 지표는 누적 희소 surface 비교이므로 pose oracle이 전 영역을 개선한다고 결론 내리지 않는다.

## 판정 및 한계

- **Local geometry:** 뚜렷한 거리 의존 depth 불일치가 있다. 단일 전역 trajectory scale 뒤에도 잔차가 남는다.
- **Pose/map placement:** trajectory가 단일 Sim(3) 뒤 RMSE 5.54m이며, OXTS pose oracle에서 LiDAR→map median/p95가 감소했다. 따라서 pose 정합도 지도 오차의 한 요인이다.
- **Fusion/filter:** raw-to-keyframe Gaussian 중심은 정확히 일치한다. 이는 해당 단계에서 별도 center shift가 없음을 뜻한다. active PLY는 5.15M 중심을 포함하지만, active filtering 이후의 개별 candidate lineage는 저장되지 않아 삭제 원인을 점별로 주장할 수 없다.
- **연구 해석:** 이 결과는 “Gaussian 이상점 pruning만으로 문제를 해결한다”는 가설을 지지하지 않는다. 반대로 새로운 depth correction의 효능을 입증하지도 않는다. B1 전체 pipeline의 혼합 기하 문제로 한정한다. MASt3R 단독의 책임을 주장하거나 연구 주제를 자동 변경하지 않는다.
- 단일 drive의 약 5Hz 개발 진단이며, 독립 장면 일반화·10Hz 성능을 말하지 않는다. Tracklet 밖 동적 객체가 남을 수 있고 LiDAR는 희소하다. 이 drive의 80m 이상 구간에는 유효 점이 없어 평가하지 않았다.

## 산출물

- [실행 manifest](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/baseline_A2b/run_manifest.json)
- [pointmap 및 trajectory 지표](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_tracklet_masked_v3/metrics.json)
- [pose-oracle 비교 지표](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_pose_oracle/metrics.json)
- [evaluation input/code hashes](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_pose_oracle/evaluation_manifest.json)
- [frame별 local depth 표](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_tracklet_masked_v3/raw_depth_per_frame.csv)
- [평가 코드](../../scripts/evaluate_e4f_kitti_geometry.py), [pose-oracle 코드](../../scripts/evaluate_e4f_pose_oracle.py)
- [유효 A2b 설정 요약](../../configs/e4f_kitti_A2b_effective.json), [launcher 수정 amendment](../../configs/e4f_amendment_A2b.json)

10Hz 및 잘못 적용된 A2 실행은 각각 `baseline/` 및 `baseline_A2/`에 보존되어 있다. 결과를 이유로 E5/E6 평가를 시작하거나 연구 계획을 바꾸지 않는다. 후속 기하 보정 검증은 이 단일 drive에서 방법 개발을 하고, 미노출 KITTI drive에 새 평가를 사전 등록한 뒤 진행해야 한다.
