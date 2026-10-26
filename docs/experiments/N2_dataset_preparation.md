# N2: 미사용 GT 실내 장면 확보·QA 및 데이터 분할 등록

- **수행일:** 2026-10-26 (Asia/Seoul)
- **판정:** **PASS — 등록한 3장면의 데이터 준비 완료**
- **상위 계획:** [Pointmap·Pose 오류 분해 계획서](../pointmap_pose_error_decomposition_research_plan_v1.md)
- **선행 단계:** [N0](N0_asset_audit_results.md), [N1](N1_coordinate_contract.md)
- **사전 등록:** [장면·구간·역할·QA 규칙](../../configs/n2_dataset_registration.json)
- **전체 파일 명세:** [n2_dataset_manifest.json](../../configs/n2_dataset_manifest.json)
- **요약·검증 hash:** [n2_results_summary.json](../../configs/n2_results_summary.json)
- **데이터:** `data/N2/Replica/`
- **산출물:** `results/N2_dataset_preparation/2026-10-26/`

이번 단계는 데이터 확보와 GT 좌표 정합 확인이다. 모델 추론·tracking·Gaussian 생성·A0 오류 효과·보정 효능은 평가하지 않았다.

## 1. 데이터 출처와 미사용 확인

[NICE-SLAM 공식 다운로드 스크립트](https://github.com/cvg/nice-slam/blob/master/scripts/download_replica.sh)가 안내하는 `https://cvg-data.inf.ethz.ch/nice-slam/data/Replica.zip`에서 HTTP Range로 필요한 파일을 추출했다. 전체 ZIP 크기는 **12,442,855,671 bytes**, ETag는 `"2e5a6e8f7-5dbe690e59caa"`였으며 기존 E0 archive 식별값과 같았다.

기존 저장소에서 사용한 장면은 `office0`, `office1`, `room0`, `room1`, `room2`였다. [E4c 기록](E4c_surface_consistency_pruning_results.md)은 `office2`·`office3`의 데이터·RGB·GT·baseline을 열지 않았다고 명시하며, N0/N1의 로컬 장면 목록에도 신규 세 장면은 없었다. `office4`의 과거 데이터·실행 명세도 확인되지 않았다.

이에 남은 rendered Replica scene ID를 숫자 순으로 배정했다. **장면 역할과 프레임 구간은 다운로드·decode 전에 등록**했다. ‘미사용’은 이 저장소의 실험 기록에 대한 표현이며 모델 사전학습에서의 미노출을 보증하지 않는다. 세 장면은 모두 같은 synthetic indoor domain이다.

## 2. 확보한 데이터와 고정 역할

| 장면 | 역할 | RGB / depth | 원본 trajectory | 사용 구간 GT pose | 제공 GT mesh |
|---|---|---:|---:|---:|---|
| `office2` | 진단·개발, 첫 A0 대상 | 1,000 / 1,000 | 2,000 poses | 1,000 poses | 확보·구조 및 좌표 QA PASS |
| `office3` | 검증 | 1,000 / 1,000 | 2,000 poses | 1,000 poses | 확보·구조 및 좌표 QA PASS |
| `office4` | 최종 평가용 보류 | 1,000 / 1,000 | 2,000 poses | 1,000 poses | 확보·형식 QA만 수행 |

공통 `cam_params.json` 1개를 포함해 **archive 원본 파일 6,007개**, 압축 해제된 payload **2,413,840,408 bytes (약 2.248 GiB)**를 확보했다. 이는 실제 네트워크 전송량이 아니다. 부분 다운로드의 overfetch나 압축 전송량은 측정하지 않았다.

- RGB 3,000개, GT depth 3,000개.
- `traj.txt` 3개, 원본 polygon mesh 3개, 공통 camera JSON 1개.
- 파생 파일 6개: 사용 이미지 구간에 맞춘 `groundtruth.txt` 3개와 고정 fan triangulation mesh NPZ 3개.
- 장면 역할 간 **동일 RGB 파일 SHA-256 교집합은 모두 0개**였다. 이 검사는 파일의 직접 중복 확인이며 모든 종류의 공간적·통계적 독립성을 증명하지는 않는다.

## 3. 프레임·calibration·평가 계약

각 장면의 원본 frame **`[0,1000)`**를 같은 규칙으로 나눴다.

| 용도 | 원본 frame ID | 개수 / 장면 |
|---|---|---:|
| RGB 모델 입력 | 짝수 `0,2,...,998` | 500 |
| Gauge calibration에 사용할 GT pose | `[0,200)`의 짝수 `0,2,...,198` | 100 |
| Primary held-out RGB/depth/pose 평가 뷰 | `[200,1000)`의 홀수 `201,203,...,999` | 400 |
| Calibration prefix의 홀수 RGB | `1,3,...,199`; 모델·주 평가에서 제외 | 100 |
| Primary candidate anchor 자격 | `[200,1000)`의 짝수 입력 frame | 400개 입력 frame |

모델 입력과 held-out 뷰는 겹치지 않는다. Calibration prefix 밖의 GT로 global alignment나 KF별 scale을 다시 맞추지 않는다. 정렬은 N1의 **고정 prefix Sim(3) 한 번 + 모든 KF에 같은 local 단위 환산** 규칙을 사용한다.

위의 100개는 **제공되는 GT calibration pose 수**다. 실제 추적 pose와 KF 수는 아직 측정하지 않았다. KF가 선택되면 source input index와 원본 ID의 관계는 기존과 같이 `original_frame_id = 2 * input_index`로 연결해야 한다.

Primary local-effect 분석에서는 prefix 이후 anchor의 self-branch 후보를 사용한다. Prefix KF는 context로 두며, 이를 포함한 전체 맵 효과는 별도 full-map sensitivity로 보고한다. 인접 프레임을 서로 다른 독립 장면으로 세지 않는다.

`office4`는 최종 알고리즘과 평가 프로토콜이 고정될 때까지 model inference·A0 Oracle 비교·튜닝에 사용하지 않는다. 첫 A0는 `office2`에서 시작하고, 프로토콜 확인은 `office3`에서 진행한다. `office4`를 먼저 사용한다면 더 이상 최종 미노출 장면으로 유지할 수 없다.

## 4. 파일·카메라·pose QA

6,007개 원본 파일에서 **archive member 크기·ZIP CRC·로컬 SHA-256**을 대조했다. RGB/depth는 전 파일을 decode해 형식과 해상도를 검사했다. 원본 파일은 QA 후 다시 재해시했고 변경이 없었다. ZIP 전체의 SHA-256은 계산하지 않았다.

카메라 계약은 N1과 같다.

- RGB: 1200×680, 3-channel `uint8` JPEG.
- Depth: 같은 해상도 `uint16` PNG, **camera Z-depth**, metre = raw / **6553.5**.
- Pose: `traj.txt`의 row-major camera-to-world 4×4, translation은 metric 단위.
- Synthetic pinhole, distortion/remap 없음.
- 평가 resize/crop: 512×290 → top 1, left 0, 512×288.
- Timestamp는 **원본 frame ordinal**이다. 실제 센서 주기나 초 단위를 가정하지 않는다.

각 raw trajectory 2,000개 행 모두 finite 값·homogeneous row·SO(3) rotation을 검사했다. 이미지가 있는 첫 1,000개 행만 TUM 형식으로 변환해 원본 pose와 다시 비교했다. GT backprojection/projection 수학적 왕복 최대 오차는 세 장면 모두 **2.28e-13 pixel 이하**였다.

| 장면 | 프레임별 최소 valid-depth 비율 | GT prefix 위치 span (m) | Prefix 두 번째 singular value |
|---|---:|---:|---:|
| office2 | 89.1684% | 1.4281 | 1.8025 |
| office3 | 94.2725% | 0.9140 | 1.9279 |
| office4 | 99.9919% | 1.1022 | 1.3561 |

Valid depth는 등록한 `[0.1,10] m` 범위다. 모든 프레임이 사전 최소 비율 50%를 통과했다. GT prefix의 위치 span과 비퇴화 조건도 통과했지만, 실제 추정 trajectory의 정렬 가능성은 A0 기준선 실행 때 별도로 확인해야 한다.

## 5. GT 간 좌표 정합 QA — office2·office3만

등록한 frame 쌍 `(0,2)`, `(200,202)`, `(800,802)`에서 source GT depth → GT world → target camera → target GT depth를 대조했다. N1의 depth-edge mask와 고정 stride 8을 사용했고, 남은 occlusion outlier를 결과에서 임의로 제거하지 않았다.

| 장면 | Pair별 median absolute Z residual (mm) | 각 pair의 일치 비율 |
|---|---|---|
| office2 | 2.540 / 2.363 / 1.006 | 모두 100% |
| office3 | 1.916 / 1.974 / 1.664 | 모두 100% |

사전 gate는 공통 표본 200개 이상, median residual 0.03 m 이하, `max(0.05 m, 2% depth)` 이내 비율 90% 이상이었다. 실제 pair별 공통 표본은 1,694~1,991개였고 모두 통과했다. 이 수치는 **GT 데이터 간 정합**이며 예측 모델의 depth accuracy가 아니다.

제공 mesh와의 좌표 호환성은 frame 0·200·800의 고정 GT-depth 표본을 같은 world 좌표로 옮겨 모든 mesh 정점과 비교했다. ICP나 좌표 fit은 하지 않았다.

| 장면 | 표본 수 | Nearest-vertex median (m) | p95 (m) |
|---|---:|---:|---:|
| office2 | 303 | 0.005280 | 0.007857 |
| office3 | 304 | 0.005370 | 0.007933 |

등록한 median 0.05 m·p95 0.15 m 이하 조건을 통과했다. 이는 데이터 좌표 호환성 검사이며 exact point-to-triangle 거리나 실제 재구성 결과의 accuracy/completion이 아니다.

## 6. 제공 mesh 형식과 기술 수정

Archive에는 세 장면의 mesh가 실제로 포함돼 있어, geometry QA 전에 [A1](../../configs/n2_mesh_qa_amendment_A1.json)로 구조·좌표 점검을 등록했다. 최초 `office2` 검사는 삼각 face를 가정한 파서가 **사각형 face**에서 실패했다. 당시 cross-view·mesh 거리 QA는 실행되기 전이었다.

[A2](../../configs/n2_mesh_qa_amendment_A2.json)에서 parser/schema 가정을 수정했다. 최초 [실패 기록](../../results/N2_dataset_preparation/2026-10-26/qa_office2/failure.json)은 보존했다. 장면 역할·frame 구간·좌표 QA pair·임계값은 바꾸지 않았다.

| 장면 | 원본 vertices | 원본 quad faces | 파생 triangle faces |
|---|---:|---:|---:|
| office2 | 858,623 | 857,845 | 1,715,690 |
| office3 | 1,187,140 | 1,185,992 | 2,371,984 |
| office4 | 993,008 | 992,909 | 1,985,818 |

원본 mesh는 그대로 보존했다. 각 polygon의 저장된 순서·winding을 유지해 `[v0,v1,...] → [v0,vi,vi+1]`의 고정 fan triangulation을 별도 NPZ에 저장했다. 이는 입력 형식 변환이며 새 mesh completion이나 지도 개선 기법이 아니다. A0에서 reference를 사용할 때는 이 고정 변환을 사용하고, 관측 가능한 영역의 completeness와 장면 전체 completeness를 구분해야 한다.

## 7. 최종 평가 장면의 보류 상태

`office4`에서 수행한 것은 file hash/CRC, RGB/depth decode·형식·유효 범위, pose/카메라 형식, 수학적 self-projection, mesh 구조 및 고정 triangulation이다.

다음 작업은 수행하지 않았다.

- RGB/mesh의 시각적 표시.
- GT cross-view residual 및 depth-to-mesh 거리 분석.
- 모델 추론, tracking, Gaussian 생성, Oracle 성능 지표 또는 튜닝.

이 보류는 manifest에 등록한 작업 절차다. 파일 접근을 암호화하거나 OS 권한으로 차단했다는 의미는 아니다.

## 8. 시험·재현 명령·산출물

데이터 계약 시험 **8개 PASS**: 입력/held-out 분리, 잘못된 prefix 거부, metric SE(3) 형식, 합성 평면의 cross-view 정합, 잘못된 pose/time 대응 탐지, 유효 depth 부족 탐지, quad/mixed polygon의 winding 보존, 잘못된 face index·arity 거부.

다운로드는 다음 명령을 `office2`, `office3`, `office4`에 대해 순서대로 실행했다. 기존 E0/E4 데이터와 결과 경로를 사용하지 않았다.

```bash
.venv/bin/python scripts/download_e3b_replica.py \
  --scene office2 --frames 1000 --workers 8 \
  --destination "$PWD/data/N2/Replica" \
  --manifest "$PWD/results/N2_dataset_preparation/2026-10-26/office2_download_manifest.json"
.venv/bin/python scripts/acquire_n2_meshes.py
.venv/bin/python -m unittest discover -s tests -p test_dataset_contract.py -v
```

최종 scene QA와 metadata 고정:

```bash
.venv/bin/python scripts/validate_n2_datasets.py --scene office2 \
  --output results/N2_dataset_preparation/2026-10-26/qa_office2_v2
.venv/bin/python scripts/validate_n2_datasets.py --scene office3 \
  --output results/N2_dataset_preparation/2026-10-26/qa_office3
.venv/bin/python scripts/validate_n2_datasets.py --scene office4 \
  --output results/N2_dataset_preparation/2026-10-26/qa_office4
.venv/bin/python scripts/finalize_n2.py
```

위 명령은 당시 저장한 사전 등록 JSON과 N0/N1 실행 환경을 전제로 한다. 완료된 QA 출력은 덮어쓰지 않는다. QA 재실행 시 새 output 경로를 지정하며, `finalize_n2.py`도 기존 추적용 manifest·summary를 덮어쓰지 않는다. 사용한 downloader·QA·변환 코드의 SHA-256과 소스 사본을 보존했다. N1에 등록한 소스 11개도 변경이 없음을 확인했다.

- [완료 판정](../../results/N2_dataset_preparation/2026-10-26/completion.json), [사전 등록 시각·hash](../../results/N2_dataset_preparation/2026-10-26/preregistration.json)
- [실제 취득 명령](../../results/N2_dataset_preparation/2026-10-26/acquisition_commands.json), [mesh manifest](../../results/N2_dataset_preparation/2026-10-26/mesh_download_manifest.json)
- [office2 QA](../../results/N2_dataset_preparation/2026-10-26/qa_office2_v2/office2_qa.json), [office3 QA](../../results/N2_dataset_preparation/2026-10-26/qa_office3/office3_qa.json), [office4 QA](../../results/N2_dataset_preparation/2026-10-26/qa_office4/office4_qa.json)
- [시험 로그](../../results/N2_dataset_preparation/2026-10-26/unit_tests_v2.log), [N1 source 보존](../../results/N2_dataset_preparation/2026-10-26/prior_n1_source_preservation.json)
- [데이터 계약 구현](../../src/dataset_contract.py), [오프라인 QA 스크립트](../../scripts/validate_n2_datasets.py)
- 각 scene QA 폴더의 `verified_files.json`, `preservation.json`, `source_manifest.json`, `*_frame_split.csv`에 원자료 hash·보존 검사·코드·프레임 역할을 기록했다.

## 9. 다음 실행

**첫 A0 대상은 `office2`다.** N2 split을 입력으로 RGB-only 기준선을 실행하고 실제 tracking·KF·calibration pose 가용성을 확인한 다음, N1 계약을 새 raw 후보에 적용해 4군의 기하·coverage를 평가한다.

N2 PASS는 새 장면의 추론이 GPU 8GB에서 성공하거나 A0가 특정 오류 원인의 우세를 입증했다는 뜻이 아니다. `office3`는 검증 역할을 유지하고, `office4`의 model/Oracle 평가는 최종 프로토콜 고정 이후까지 보류한다.
