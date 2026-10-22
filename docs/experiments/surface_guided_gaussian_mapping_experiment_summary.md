# Surface-guided Gaussian Mapping 실험 종합 및 종료 보고서

- 작성일: **2026-10-22 (Asia/Seoul)**
- 실험 기록 범위: **2026-10-15~2026-10-22, E0~E4f**
- 종료 결정: 현재의 **교차관측·국소 표면 기반 Gaussian 편입/보류/pruning 주제는 여기서 종료하고 연구 주제를 전환한다.** 사용자의 연구 범위 결정이며, 아래의 과거 실험별 PASS/REVISE/INCONCLUSIVE 판정을 소급 변경하지 않는다.
- 상위 설계: [연구·실험 계획 v3](../surface_guided_gaussian_mapping_research_plan_v3.md)
- 작성 기준: 저장된 개별 실험 보고서·실행 manifest·평가 코드와 대화에서 확인한 정성 관찰을 정리했다. 이 문서를 작성하면서 새 모델 추론이나 추가 효능 실험은 수행하지 않았다.

## 1. 종료 시점의 핵심 결론

**표면 기반 판정으로 일부 GT 오류 후보를 보수적으로 제거할 수 있었지만, 강한 depth 대조군보다 실제 지도 품질을 더 개선한다는 핵심 효용은 확보하지 못했다.** 새 장면·동일 Gaussian 수·동일 파라미터 바이트를 사용한 E4가 이를 직접 확인한 실험이다. 이후 감사에서는 같은 예측 pointmap의 잘못된 표면이 불량 후보를 다시 지지하는 사례와, 충분한 검증 관측을 얻기 어려운 문제가 확인됐다.

야외 파일럿과 PLY 관찰에서는 고립된 중심점 이상치 외에 표면의 단차·왜곡, 하늘의 부유 구조, 자동차의 잔상 및 누적 불일치가 두드러졌다. Gaussian 중심은 raw pointmap을 그대로 따르는 경로였으므로, pointmap과 pose의 오차가 지도에 이어질 수 있다. 점을 제거하는 정책만으로 이런 표면 형상을 복원하기는 어렵다는 연구 판단에 이르렀다.

이 결론을 **“Gaussian 이상점은 전혀 없다” 또는 “모든 실패 원인은 MASt3R의 깊이 추정이다”**로 확대하지 않는다. E1의 GT-front 오류 proxy는 실제로 존재했으나 고립 floater의 확정 라벨이 아니었고, E4f에서도 local geometry와 pose/scale 배치의 영향이 함께 나타났다. 다음 주제는 아직 확정하지 않았다.

## 2. 처음 검증하려던 가설

원래 질문은 연속 RGB 영상에서 feed-forward 모델이 만든 Gaussian 후보를 전역 지도에 편입할 때, 다른 시점의 국소 표면 증거를 사용해 정상 구조를 보존하면서 불량 후보를 제거할 수 있는가였다.

후보의 중심·Gaussian extent를 다른 출처 pointmap의 국소 PCA 평면 및 깊이와 비교했다. 반복적인 앞쪽 충돌은 제거 증거로, 표면 지지는 보존 증거로 사용하고, 증거가 부족하면 KEEP/REJECT를 강제하지 않고 DEFER 또는 PROVISIONAL로 처리했다. 비교 대상은 confidence, 자기 pointmap 잔차, 교차시점 depth, RGB NCC, DoG, voxel 중복, 무작위 선택이었다. 일부 대조군은 관련 연구의 요소를 옮긴 proxy이며 원 논문 전체 시스템의 재현은 아니다.

최종 성공 기준은 후보 분류 성능이나 Gaussian 수 감소만이 아니라, **동일 자원 예산에서의 RGB·기하 품질 개선과 정상 표면·coverage 보존**이었다.

## 3. 실행 환경과 평가 범위

| 항목 | 기록 |
|---|---|
| 기준 시스템 | Splatt3R-SLAM, 원본 upstream commit `74ffc37454dfa7560c9531b1534825c54c36a89e`에 계측·호환 패치 적용 |
| 주요 GPU | NVIDIA GeForce RTX 5060, VRAM 8,151 MiB |
| 전용 환경 | Python 3.11.17, PyTorch 2.13.0+cu132, 프로젝트 CUDA 13.2 확장 |
| 모델 | 고정 Splatt3R checkpoint와 MASt3R retrieval 자산; 실험별 manifest에 hash 기록 |
| 주요 조건 | RGB-only mapping, 주 실행 seed 0, 기준선 native filter 유지, Gaussian/map appearance refinement 0 |
| GT | depth·pose·LiDAR는 평가 또는 명시적 oracle에만 사용 |
| 실내 | NICE-SLAM rendered Replica `office0`, `room0`, `room1`, `room2`, `office1` |
| UAV | UAVScenes `HKairport01` 개발 기준선 실행; `AMtown01`, `AMvalley01`은 확보·preflight 후 기준선 미실행 |
| 차량 전방 RGB | KITTI Raw `2011_09_26_drive_0015_sync` 단일 drive |

샌드박스에서 CUDA가 보이지 않는 경우에도 호스트 실행에서는 GPU에 접근할 수 있었다. E0에서 전용 환경·CUDA 확장·8GB 메모리 대응을 구축했고 후속 실험에서 사용했다. E3 정책 렌더링은 저장 CUDA 결과와 대조한 CPU 적응 경로였으며, 이를 GPU latency/VRAM 성과로 보고하지 않았다. 후속 GPU 실행과 구분한다.

Replica의 여러 실험은 동일 장면을 개발·회귀에 재사용했다. 각 단계의 새 평가 장면은 해당 단계에서만 미노출이었으며, 모든 결과를 서로 독립인 반복 실험으로 합산하지 않는다. UAV와 KITTI 수치를 실내 결과 또는 서로 간의 동일 조건 비교로 해석하지 않는다.

## 4. 실험 전체 이력

| 실험 | 목적과 수행 내용 | 핵심 결과 | 당시 판정 |
|---|---|---|---|
| [E0](E0_baseline_reproduction.md) | 기준선 설치·실행, raw 후보·pose 저장, GT/RGB 평가 연결 | office0 60/60 pose, 2 KF, active 286,208개. Held-out PSNR 15.47dB, depth coverage 79.97% | 파일럿 완료 |
| [E0b](E0b_ancestry_causality_audit.md) | raw/fused 출처와 판단 시점·pose revision 감사 | 확장 180입력·5 KF. Fused 출처 혼합 확인; 당시 2+ 유효 분리 관측 0% | 감사 완료, 관측 제약 확인 |
| [E1](E1_error_taxonomy.md) | 고정 지도 오류를 GT-front/support/duplicate/ambiguous로 분류 | active 705,772개 중 front proxy 12.81%; GT-anchor에서도 10.35% | 오류 분류 파일럿 완료 |
| [E2](E2_signal_discriminability.md) | 동일 후보에서 confidence/depth/RGB/DoG/plane 점수 비교 | 좁은 집합 P1 AP 0.4268, confidence 0.4830. 전이 임계값 P1 bad recall 0%; 2+ 관측 0개 | REVISE |
| [E2b](E2b_repeated_observations_threshold_transfer.md) | 긴 영상으로 반복 관측과 장면 간 임계값 전이 확보 | room0 반복 관측 16.14%; normal 보존 99.9887%, bad recall 3.3742% | E3 진행 조건 통과 |
| [E3](E3_admission_decision.md) | 실제 편입·DEFER·BYPASS 정책 비교 | DEFER가 동일 불량 제거량에도 정상 active 보존을 77.59%로 낮춤 | REVISE |
| [E3b](E3b_provisional_admission.md) | 즉시 PROVISIONAL 편입과 부분집합 위험 보정 | 새 room1에서 bad 5,104개·normal 0개 제거. B6 대비 추가 우위 미확인 | REVISE |
| [E3c](E3c_matched_evidence.md) | 관측 자격·집계·보호 규칙을 맞춘 depth/plane 비교 | 새 room2 공통 bad recall +7.53%p. Median-depth와는 +0.19%p 차이 | 조건부 E4 진입 통과 |
| [E4](E4_matched_budget.md) | 동일 Gaussian 수·바이트의 RGB/TSDF 품질 비교 | 새 office1의 plane은 median-depth 대비 Chamfer 0.162% 개선, B6 대비 2.272% 악화 | REVISE |
| [E4b](E4b_reference_plane_audit_results.md) | 기준 평면 오류와 정책의 관측 제한 분해 | office1의 잘못된 표면 지지 31,412개; B6-only 대부분은 plane 반복 관측 부족 | 사후 진단 완료 |
| [E4c](E4c_surface_consistency_pruning_results.md) | 명시적 표면 지지/충돌 기반 pruning 성립 검사 | 두 개발 장면 모두 policy 반복 관측과 audit의 공통 S/O가 0/0개 | INCONCLUSIVE |
| [E4d](E4d_surface_membership_validation.md) | 중심점 표면 소속과 실제 pruning 효용 검증 설계 | 계획만 작성; 구현·평가 미실행 | 계획 단계에서 종료 |
| [E4e](E4e_uav_dataset_pilot_results.md) | 실제 드론 데이터에서 원본 B1과 기하 문제 확인 | HKairport01 240입력, 21 KF, 3.24M active. 연속 pose 누락 2.4초 | 개발 gate INCONCLUSIVE |
| [E4f](E4f_kitti_geometry_diagnostic_results.md) | KITTI LiDAR/OXTS로 local geometry와 누적 배치 진단 | 120입력 완료. Raw depth mismatch와 oracle 배치 시 일부 거리 개선이 함께 관측 | 탐색적 MIXED 진단 |

각 행의 판정은 그 단계의 질문에 대한 것이다. E2b/E3c의 진행 조건 통과를 연구 전체의 효능 성공으로 읽지 않는다.

## 5. 단계별로 얻은 주요 증거

### 5.1. 실행·추적 기반을 구축했지만 검증 관측은 제한적이었다 — E0/E0b

E0는 원본 기준선을 RTX 5060에서 실행하고 raw pair·Gaussian·pose를 저장해 GT 및 held-out RGB 평가로 연결했다. 초기 retrieval 메모리 부족과 CUDA PTX 호환 실패, 프로세스 간 메모리 중첩은 별도 시도 기록으로 보존했다. 성공한 office0 파일럿은 active 286,208개, held-out PSNR 15.4674dB, SSIM 0.41440, LPIPS 0.43224였다.

E0b에서는 raw와 fused pointmap의 출처를 구분하고 실제 의사결정 당시 pose를 재생했다. 180입력 확장 실행에서 raw 기반 분리 관측·ray·시차 조건을 생성 시점에 충족한 격자 표본은 10.93%, 이후 KF 도착까지 허용하면 21.59%였다. 동시에 두 관측을 만족한 표본은 없었다. Fused map은 다른 이미지의 기여가 누적되므로, 후보와 생성 pair가 다르다는 이유만으로 독립 검증 자료가 되지 않았다.

### 5.2. GT 오류 proxy와 표면 밖 고립점은 다른 개념이었다 — E1/E2

E1의 active Gaussian 705,772개 중 반복 GT-front proxy는 90,376개(12.81%), GT-anchor 진단에서는 73,077개(10.35%)였다. 양쪽에서 front인 후보는 39,907개(5.65%)였다. 이는 GT 표면에 대한 오류 후보가 존재한다는 증거지만, 일관된 잘못된 표면과 그 표면에서 따로 떨어진 floater를 구분한 정답은 아니다.

추정 pose의 180개 held-out view에서 rendered-depth MAE는 0.09966m, 단순 coverage는 89.97%, 허용 깊이 오차까지 만족한 coverage는 40.04%였다. 단순히 영상에 가우시안이 채워졌다는 사실과 정확한 표면을 표현한다는 사실이 달랐다.

E2에서는 선택된 작은 공통 집합에서 plane 점수의 단서가 있었지만 confidence보다 낮았다. 더 넓은 기하 공통 집합에서는 AP가 plane 0.3847, depth 0.3964, confidence 0.4239였다. 개발 임계값을 마지막 KF에 고정 전이하면 plane은 아무 후보도 거부하지 않았다. 높은 정상 보존율만으로 유효한 제거 정책이라고 판단할 수 없었다.

또한 B5 자기 잔차는 `Gaussian mean = 같은 prediction의 pts3d`인 생성 경로에서 상수였다. 같은 원본 pointmap과의 일치는 외부 표면 정확도를 검증하지 못했다.

### 5.3. 안전한 일부 제거는 가능했지만 보류와 coverage 사이 비용이 컸다 — E2b/E3/E3b

E2b는 원본 1,000프레임·짝수 500입력으로 구간을 늘렸다. room0에서 동시 2+ 유효 관측을 확보한 raw 후보는 16.14%였다. 개발 임계값을 고정한 평가에서 bad 1,107개, normal 80개를 거부 대상으로 판정했고 정상 보존 99.9887%를 보였다. 이는 실제 지도 삭제 전의 `would_reject` 결과다.

E3에서 실제 membership을 적용하자 hard DEFER의 비용이 드러났다. 같은 불량 1,105개·정상 79개를 제거하는 정책이라도 즉시 BYPASS는 정상 active 보존 99.9886%를 유지한 반면, 2-KF DEFER는 77.5857%에 그쳤다. 종료 시 282,890개가 보류 상태였고 깊이 coverage는 원본보다 19.8583%p 낮았다. 미판정을 제거하지 않았다는 이유로 보존 성공으로 셀 수 없었다.

E3b에서는 즉시 PROVISIONAL 편입 후 재검사하도록 바꿔 queue를 없앴다. 새 room1에서 bad 5,104개·normal 0개를 제거하고 coverage를 유지했다. 그러나 모든 신호 공통 후보에서는 B6도 정밀도 100%였으며 B6가 bad 4,966개, plane 정책은 4,338개를 제거했다. 안전성 보완과 강한 대조군 대비 효용은 별개였다.

### 5.4. 조건부 분류 이득이 실제 지도 품질의 추가 개선으로 이어지지 않았다 — E3c/E4

E3c는 동일한 관측 gate·support veto·집계·위험 보정을 적용했다. 새 room2에서 plane의 공통 bad recall은 79.5451%, 동일 집계 depth는 72.0122%로 +7.5330%p였다. 다만 median-depth는 79.3568%로 plane과 0.1883%p 차이였고, room0/room1에서는 depth가 더 많은 불량을 제거했다.

E4는 5장면·15개 방법, 자연 작동점과 99/90/75% 유지 예산을 평가했다. 주 비교는 새 office1·75% 유지였고, 모든 아래 방법이 active=resident 860,701개, Gaussian당 52 bytes, parameter buffer 42.683MiB를 사용했다.

| office1 75% 유지 | PSNR ↑ | LPIPS ↓ | Depth coverage ↑ | TSDF sampled Chamfer ↓ |
|---|---:|---:|---:|---:|
| Median-depth | 18.6209dB | 0.251221 | 95.8951% | 0.108530m |
| 동일 집계 depth | 18.6184dB | 0.251057 | 95.8951% | 0.108449m |
| Plane P2 | 18.6193dB | 0.251615 | 95.8951% | 0.108354m |
| 원래 B6 depth | 18.7513dB | 0.248052 | 95.8960% | 0.105947m |

Plane의 median-depth 대비 Chamfer 개선은 0.1619%로 사전 기준 2%에 미달했고, 원래 B6보다 2.2723% 악화됐다. 정상 보존 및 RGB·coverage 비열등성은 통과했지만 추가 기하 효용은 입증되지 않았다.

자연 P2가 제거한 후보는 bad 1,686개·normal 0개·unknown 212개였고 전체 bad recall은 0.5865%였다. 75% 예산에서 추가로 제거한 285,003개는 공통 무작위 fallback이었다. 전체 25% 메모리 감소를 plane 정책의 성과로 귀속할 수 없다.

이 RGB 평가는 홀수 11개의 temporal held-out view다. 기하는 동일 관측 범위의 GT-depth TSDF 표면에 대한 샘플 거리다. 충분한 각도 차이가 있는 신규 시점의 사진 수준 재구성을 증명한 실험은 아니다.

### 5.5. 잘못된 표면의 자기 지지와 별도 검증 표본 부족이 남았다 — E4b/E4c

E4b의 office1 감사에서는 잘못된 기준 평면이 미제거 bad를 지지한 후보 31,412개를 확인했다. 이 중 30,777개는 주변 공통 점의 80% 이상이 같은 방향으로 틀린 점군도 관측했다. 추정 표면이 일관돼 보인다는 조건만으로 정확한 표면이라고 할 수 없었다.

한편 B6만 제거한 bad 9,874개 중 9,867개(99.93%)는 B6의 최초 제거 시점에 plane 유효 관측이 두 개 미만이었다. 기준 평면 오류와 관측 수·정책 차이가 함께 작용했다. GT-plane oracle에서 새로운 bad 5,209개를 제거했지만 정상 409개도 더 제거했다. 정답 평면을 넣어도 기존 관측·판정 제한이 모두 해결되지는 않았다.

E4c는 후보 제외 국소 표면, 명시적 support/conflict/unknown, 별도 audit 관측을 구현했다. 분할 amendment와 hull 자격 수정 V2까지 수행했지만 office0/office1 개발 장면 모두에서 policy 반복 관측과 audit S/O가 겹치는 후보가 0/0개였다. 필수 보정 표본이 없어 임계값·실제 제거 membership·새 장면 효능 평가는 만들지 않았다. 이를 제거 0개의 성공 정책 또는 이상점 부재로 해석하지 않는다.

E4d는 표면 소속을 독립적으로 확인하는 후속 설계만 작성했다. 실행 결과는 없다.

### 5.6. 드론에서는 표면 단차가 관찰됐고 추적 자격이 부족했다 — E4e

UAVScenes의 세 archive를 확보하고 대표성·timestamp preflight를 수행했다. 최초 구간이 주행 대표성 조건에 미달해 예측 전 amendment로 [60s,120s) 구간을 선정했다. 실제 B1 추론은 개발 장면 HKairport01에서만 실행했다.

| HKairport01 | 측정값 |
|---|---:|
| 매핑 입력 / 최종 KF | 240 / 21 |
| Raw self-branch 및 pre-active 후보 | 각각 4,472,832개 |
| Native active Gaussian | 3,242,219개 |
| Pose 산출 | 228/240 (95.0%) |
| 최장 연속 pose 누락 | 2.4초; 사전 한도 2초 초과 |
| 단일 Sim(3) trajectory 위치 RMSE / p95 | 2.35 / 3.60m |

Raw self-branch와 pre-active 중심은 같은 ID의 전 후보에서 일치했고 offset median/p95는 0이었다. 사용자가 기울여 본 PLY에서는 활주로로 해석한 표면의 높이 단차·왜곡이 두드러졌다. 이는 정성 관찰이며 실제 LiDAR 기반 단차 측정이나 MASt3R 단독의 원인 판정은 아니다.

Tracking gate 미통과로 내부 표면·실측 LiDAR 이상점 라벨, held-out 렌더링, AMtown01/AMvalley01 기준선은 실행하지 않았다. **세 UAV archive 확보와 세 UAV 장면의 모델 평가 완료는 다르다.**

### 5.7. 도로에서는 local depth와 pose 배치 문제가 함께 나타났다 — E4f

선정 순서에 따라 frame 수가 부족한 drive_0005/0013을 제외하고 drive_0015의 첫 240개 synchronized 기록(24.75초)을 골랐다. 첫 10Hz 실행은 32-slot keyframe capacity를 넘어 실패했다. A2 실행도 launcher의 고정 인자 오류로 같은 capacity를 적용했다. 두 기록을 보존하고 A2b에서 capacity 128, RGB stride 2의 120입력(약5Hz)을 완료했다.

| KITTI A2b | 측정값 |
|---|---:|
| RGB 입력 / pose / 최종 KF | 120 / 120 / 114 |
| Keyframe raw Gaussian 후보 / active PLY | 8,404,992 / 5,148,781개 |
| Trajectory 단일 Sim(3) scale | 5.480m / SLAM unit |
| 정렬 translation RMSE / p95 | 5.54 / 10.66m |
| Orientation median / p95 | 12.51° / 13.11° |

LiDAR/OXTS와 36개 tracklet은 평가 전용이었다. Tracklet 제외 후 native raw depth는 LiDAR보다 낮게 나타났고, trajectory에서 구한 전역 scale 5.480을 적용한 뒤에도 다음 잔차가 남았다.

| LiDAR range | 비교 점 수 | 해당 단일 scale 후 abs depth median / p95 |
|---|---:|---:|
| 0–10m | 569,175 | 2.77 / 5.48m |
| 10–20m | 730,900 | 4.83 / 10.27m |
| 20–40m | 478,747 | 8.52 / 22.17m |
| 40–80m | 182,289 | 11.41 / 34.18m |

Raw Gaussian 중심과 keyframe 중심의 일치를 확인한 오프라인 배치 비교에서는 confidence와 고정 간격으로 선택한 raw 중심 319,966개를 사용했다. 아래 값은 실제 active PLY 전체를 재렌더링한 NVS 결과가 아닌, 누적 static LiDAR에 대한 최근접 거리다.

| 배치 | Map→LiDAR NN median / p95 | LiDAR→map NN median / p95 |
|---|---:|---:|
| Estimated B1 pose | 1.25 / 6.50m | 1.05 / 5.30m |
| OXTS pose oracle | 0.71 / 7.89m | 0.45 / 2.07m |

일부 거리가 줄었지만 map→LiDAR p95는 커졌다. 기존 보고서는 이를 MIXED로 해석했다. 종료 보고서에서도 **local geometry와 배치 오차가 함께 의심되는 탐색적 진단**으로 한정한다.

해석 시 다음 조건을 함께 보아야 한다. Native pointmap 좌표가 곧 metre 정확도라는 보장은 없으므로 raw 단위의 잔차를 모델의 metric depth 오차로 단정하지 않는다. 위 scale은 trajectory에서 정한 한 값이며 모든 가능한 전역 scale을 조사한 결과도 아니다. Oracle 구현은 estimated arm의 keyframe별 Sim(3) scale을 쓰는 배치와 OXTS SE(3)+전역 scale 배치를 비교하므로, 회전·이동만의 단일 변수 효과로 해석하지 않는다. NN 감소는 고정 거리 기준의 coverage 비율 측정과도 다르다.

사용자 PLY 스크린샷에서는 하늘색의 넓은 부유 구조와 자동차 주변의 반복·번짐이 관찰됐다. Mapping에는 하늘 mask나 tracklet 기반 제거를 넣지 않았고, mask 전후 지도 ablation도 실행하지 않았다. 하늘은 유효 LiDAR depth 평가 영역과도 다르므로 위 표가 하늘 가우시안의 비율이나 오류를 정량화한 것은 아니다.

## 6. 관측 사실과 남은 해석

| 쟁점 | 확인된 내용 | 확정하지 않은 내용 |
|---|---|---|
| Gaussian 생성 위치 | 검사한 경로에서 raw pointmap과 Gaussian 중심이 일치 | 그 pointmap의 표면 정확도, 중심 외 covariance·opacity·색상의 적절성 |
| 이상점의 존재 | GT-front 오류 proxy와 시각적 아티팩트 존재 | 고립 floater의 보편적 존재율 또는 부재 |
| 표면 일관성 | 틀린 점군도 일관된 평면을 만들고 후보를 지지할 수 있음 | 모든 표면 일관성 신호가 쓸모없다는 일반 명제 |
| Pruning 효용 | 정상 보존을 유지한 일부 제거 가능 | 강한 depth 대조군 대비 일관된 지도 품질 우위 |
| Novel-view 품질 | E0/E4 정량 RGB와 사용자 PLY 관찰에서 품질 한계 확인 | 모든 시점·모든 설정의 NVS 실패 또는 원본 3DGS 재현 실패 |
| MASt3R 관련 원인 | pointmap 오차가 이후 지도에 이어질 수 있고 배치 오차도 관측됨 | MASt3R 네트워크 단독의 인과 책임 |
| 동적 객체·하늘 | KITTI 화면에서 해당 영역의 큰 아티팩트 관찰 | 그 영역 Gaussian 수·기여율, semantic mask의 개선 효과 |

사용자가 대화에서 비교한 세 샘플 모두 사진 수준에 미치지 못했다는 관찰은 연구 동기를 재검토하는 근거로 기록한다. 이를 동일 protocol로 수행한 세 독립 NVS benchmark의 정량 판정으로 바꾸지는 않는다. 주요 실행은 refinement 0이고, E4의 appearance도 원본 degree-0 조건이었다. 장면별 충분한 최적화와 시점 coverage를 갖춘 offline 3DGS 결과와 동일한 실험이라고 볼 수 없다.

## 7. 주제를 전환하는 이유

1. **핵심 추가 효용이 부족했다.** E4에서 비용과 후보 수를 맞춘 강한 depth 대조군보다 기하 품질을 충분히 개선하지 못했다. 조건부 분류 이득만으로 논문 기여를 뒷받침하기 어렵다.
2. **검증 증거 확보 비용이 컸다.** 출처·시점·가시성·표면 신뢰도를 함께 요구하면 판단 가능한 후보가 크게 줄었고, hard DEFER는 지도 공백을 만들었다. E4c에서는 별도 audit와의 공통 보정 표본을 확보하지 못했다.
3. **원래 제거 목표와 관측된 주 결함이 어긋났다.** 점들이 함께 틀린 표면을 이루면 고립점 제거로 형상을 바로잡을 수 없다. UAV 단차와 KITTI의 하늘·이동체 아티팩트는 기하 추정·정합·정적 장면 가정의 문제를 함께 제기했다.
4. **새 문제는 별도 설계가 필요하다.** Pointmap의 cross-view 정합, pose/scale, 동적 장면, 하늘과 미관측 영역, appearance refinement를 다루려면 현재의 고정 후보 pruning 범위를 넘어간다. 기존 실험을 계속 확장하기보다 새 질문과 평가 기준을 정하는 편이 적절하다고 판단했다.

현재 주제 종료는 “모든 pruning 방법이 실패한다”는 결론이 아니다. 이 baseline·데이터·관측 정책에서 확보한 결과가 선택한 연구 기여를 충분히 지지하지 못했고, 사용자가 연구 방향 전환을 결정했다는 기록이다.

## 8. 종료 범위와 보존할 자산

현재 주제의 추가 실험은 진행하지 않는다. E4d, E4c의 미노출 office2/office3 효능 평가, E4e의 AMtown01/AMvalley01 기준선, 계획된 E5 이후 단계는 미실행 상태로 남긴다. 연구 계획서의 이후 단계·‘다음 작업’ 문구는 당시의 계획 이력이며 현재 실행 지시가 아니다.

다음 자산은 후속 연구에서도 재사용할 수 있다.

- 고정 환경·weights·입력 hash, GPU 실행 wrapper 및 실패 시도 기록.
- Raw pair·Gaussian·frame/pixel ID, fused ancestry, decision-time snapshot과 pose revision 추적.
- GT proxy 분류, confidence/depth/plane/RGB/DoG 대조 코드와 보정·봉인 절차.
- 실제 membership 기반 compact map 렌더러, 동일 수·바이트 평가 및 TSDF 평가 도구.
- Replica 기준선, UAVScenes/KITTI 입력·보정 자료, LiDAR/OXTS 평가 경로.
- 정상 보존·부분집합 보존·coverage·미판정 후보를 구별한 실패 분석 기록.

이미 확인한 장면은 후속 연구에서 개발·진단 자료로 취급한다. 새 주제의 효능을 검증하려면 새 가설과 대조군을 정하고, 이전 결과를 보지 않은 평가 구간 또는 장면을 확보해야 한다. 이 보고서는 새 주제의 방법·효과를 사전 승인한 문서가 아니다.

## 9. 원본 기록과 주요 결과 경로

개별 보고서 링크는 §4에 모았다. 정확한 재현 명령·설정·hash·원자료 위치는 해당 보고서의 산출물 절을 따른다.

| 범위 | 주요 결과 디렉터리 또는 명세 |
|---|---|
| 환경·weights | [환경 명세](../../configs/e0_environment_resolved.json), [weights 명세](../../configs/e0_weights_manifest.json) |
| E0 | `results/E0_baseline_reproduction/` |
| E2b~E4 | 개별 보고서의 설정·봉인·결과 summary와 원본 run 경로 |
| E4b 감사 | [E4b 결과 및 artifact 목록](E4b_reference_plane_audit_results.md) |
| E4c V2 | `results/E4c_surface_consistency_pruning/v2/` |
| E4e 개발 | [HKairport01 run manifest](../../results/E4e_uav_dataset_pilot/development/HKairport01/baseline/run_manifest.json) |
| E4f 최종 실행 | [KITTI A2b run manifest](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/baseline_A2b/run_manifest.json) |
| E4f local/trajectory | [최종 지표 v3](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_tracklet_masked_v3/metrics.json) |
| E4f oracle | [Oracle 지표](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_pose_oracle/metrics.json), [평가 명세](../../results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/evaluation_pose_oracle/evaluation_manifest.json) |

스크린샷에 대한 관찰은 사용자 제공 화면을 바탕으로 한 대화 기록이다. 해당 첨부 이미지의 저장 경로를 확인하지 못해 새 파일이나 고정 시점 정량 평가 artifact로 만들지 않았다. 원본 데이터·실행 결과·이전 보고서는 종료 시점 상태로 보존한다.
