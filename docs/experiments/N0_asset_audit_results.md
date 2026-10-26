# N0: 기존 자산 고정 및 실내 기준선 재현 결과

- **수행일:** 2026-10-26 (Asia/Seoul)
- **판정:** **PASS — N1 좌표계·단위 계약 검증에 착수 가능**
- **상위 계획:** [Pointmap·Pose 오류 분해 연구 계획서](../pointmap_pose_error_decomposition_research_plan_v1.md)
- **범위:** 기존 환경·가중치·입력·결과의 식별, `office0`의 저장 맵 재평가와 새 RGB-only 기준선 실행. A0의 오류 원인 분해나 보정 효능은 평가하지 않았다.
- **전체 출력:** `results/N0_asset_audit/2026-10-26/`
- **실행 시각:** 13:22:15~13:23:19 KST. 아래 문서 작성 시간은 실험 실행 시간에 포함하지 않는다.

## 1. 수행 내용과 판정

| 검사 | 이번에 실제 수행한 내용 | 결과 |
|---|---|---|
| 실행 환경 | 프로젝트 Python·패키지, GPU, CUDA toolkit, `pip check`, 실제 CUDA 연산 | PASS |
| 가중치 | 기존 명세의 4개 파일 크기·SHA-256 재계산 | 모두 일치 |
| E0 입력·GT | RGB 120개, depth 120개, 카메라·trajectory 각 1개 재해시 | 242개 모두 일치 |
| 소스 고정 | 자체 코드·설정·관련 문서와 upstream 소스 복사, hash 및 Git diff 저장 | 4,616개 파일 고정 |
| 저장 export | 2 KF의 raw self-branch·픽셀 인덱스·Gaussian mean 연결 및 60개 pose 확인 | PASS |
| 저장 맵 재평가 | 기존 E0 맵의 export·Sim(3)·PLY 및 60개 held-out RGB/depth 평가 재실행 | 기존 집계 지표와 동일 |
| 새 기준선 | 현재 코드에서 RGB 60입력, seed 0, refinement 0 실행 후 동일 평가 | 기존 집계 지표와 동일 |
| 과거 결과 점검 | E0~E4e summary, E4 5장면 metric hash, E4e/E4f 주요 run·평가 기록 확인 | 해당 파일 확인 완료 |
| 원본 보존 | E0 raw export·출처·map·기존 metric 등 69개 파일을 실행 후 재해시 | 변경 없음 |

과거 E0b~E4f의 모든 추론·정책·대규모 감사를 다시 실행한 것은 아니다. 이번 기준선 재현은 짧은 `office0` 한 장면이며, UAV archive 및 과거 전체 raw 데이터의 전수 hash 검증도 수행하지 않았다. N0 PASS는 이 범위의 자산 재사용과 실내 실행 가능성을 뜻한다.

## 2. 재현 환경과 고정 정보

| 항목 | 이번 확인값 |
|---|---|
| GPU / VRAM | NVIDIA GeForce RTX 5060 / 8,151 MiB |
| 드라이버 / compute capability | 595.99.02 / 12.0 |
| Python | 프로젝트 `.venv`, 3.11.17 |
| PyTorch / runtime CUDA | 2.13.0+cu132 / 13.2 |
| 프로젝트 nvcc | 13.2, V13.2.78 |
| 기존 명세 패키지 버전 | E0에 기록된 패키지의 버전 차이 없음 |
| 의존성 검사 | `pip check`: `No broken requirements found.` |
| upstream HEAD | `74ffc37454dfa7560c9531b1534825c54c36a89e` |
| upstream 작업 트리 | 10개 수정 파일 존재. 현재 diff와 소스 사본을 별도 보존 |

기본 샌드박스에서는 `nvidia-smi`와 PyTorch CUDA 조회가 실패했지만, 호스트 접근 실행에서는 GPU 조회와 faiss GPU add/search, lietorch Sim(3), rasterizer 연산이 모두 통과했다. 샌드박스의 CUDA 비가시성을 호스트 GPU 장애로 해석하지 않는다.

가중치는 [기존 weights 명세](../../configs/e0_weights_manifest.json)의 Splatt3R checkpoint, retrieval training-free 자산, codebook, LPIPS AlexNet backbone 총 4개를 재검증했다. 데이터는 [기존 E0 download 명세](../../configs/e0_replica_download_manifest.json)의 SHA-256·크기와 비교했다.

E0 당시 자체 코드 명세와 비교하면 `scripts/download_e0_replica.py`, `src/e0_export.py`의 hash가 달랐다. 현재 downloader에는 장면·출력 경로 등의 일반화가, exporter에는 선택적인 E0b audit 호출이 포함돼 있다. 과거 코드와 동일하다고 처리하지 않고 **현재 소스와 diff를 새로 고정**했다. 입력 hash와 새 실행의 지표 재현은 별도로 통과했다.

상세 환경·패키지, 자체 저장소 commit·작업 상태, 소스 hash는 각각 `environment.json`, `source_manifest.json`, `frozen/`에 저장했다. 이 실험의 실행 기준은 해당 사본이며, 이후 작성한 본 보고서·README·N0 요약 명세까지 실행 전 snapshot에 들어 있는 것은 아니다.

## 3. export·GT 점검

| 항목 | KF0 | KF1 |
|---|---:|---:|
| 입력 frame ID | 0 | 41 |
| 원본 frame ID | 0 | 82 |
| 생성 source image IDs | `[0]` | `[0, 41]` |
| 이미지 해상도 | 512×288 | 512×288 |
| raw Gaussian 후보 | 147,456 | 147,456 |
| raw `means == pts3d` | 정확히 일치 | 정확히 일치 |
| KF local mean == raw self-branch mean | 정확히 일치 | 정확히 일치 |

- 후보 ID 규칙은 `<prediction_event_id>:self:<row-major-pixel-index>`다. 폭 512에서 픽셀은 `u = index % 512`, `v = index // 512`로 복원할 수 있다.
- pose 파일은 원본 짝수 frame `0, 2, ..., 118`의 60개 행을 갖고, finite 값과 단위 quaternion을 확인했다.
- 기존 TUM-format `groundtruth.txt`의 timestamp·translation·rotation을 원본 `traj.txt` 첫 120개 pose와 대조했다.
- frame 0·1·82·119에서 RGB/depth 해상도 1200×680, depth `uint16`, 변환 계수 6553.5를 확인했다. 해당 표본의 유효 depth 비율은 약 99.80~99.85%다. 전체 파일 내용의 무결성은 별도의 242개 hash 검사로 확인했다.
- 실제 GPU export 검사에서 mean·covariance의 Sim(3) 변환, scale 제곱, 역변환, PLY 복원·렌더링을 검증했다.
- local 후보를 다시 bake한 맵과 PLY 렌더링의 RGB 평균 절대 차이는 `3.50924e-08`, 최대 차이는 `0.00102586`으로 기존 검사 결과와 같았다.

기존 E0 및 이번 fresh KF dump에는 `pose_revision=final_snapshot_unversioned`, `fused_ancestry_status=unknown`이 남아 있다. 새 실행은 별도로 E0b audit journal·snapshot을 생성했지만, N0에서 이 journal 전체의 인과 재생 검증까지 완료했다고 주장하지 않는다. N1에서는 별도 audit 기록과 KF dump를 연결해야 한다.

## 4. 새 RGB-only 기준선과 평가 재현

새 실행은 [E0 split](../../configs/e0_replica_split.json)과 동일한 데이터·설정을 사용했다.

- Mapping: 원본 짝수 RGB 60입력, seed 0, `E0_DISABLE_GT=1`, refinement 0.
- Tracking backend는 기존 설정 유지. keyframe buffer 16, spatial stride 1.
- Native filter: depth percentile 0.98, max scale 1.0, min confidence 1.5; refiner confidence fade 0.
- 결과: **60/60 pose, 2 KF, raw 후보 294,912개, active Gaussian 286,208개**.
- Mapping subprocess wall time: **26.82초**. 모델 로드·저장·export·audit를 포함하며 사후 평가는 제외한다. 기존 26초 기록과의 성능 비교나 실시간 처리 성과로 해석하지 않는다.

| 평가 split | 프레임 수 | PSNR (dB) | SSIM | LPIPS Alex ↓ | Depth L1 (m) ↓ | Depth coverage ↑ |
|---|---:|---:|---:|---:|---:|---:|
| Validation | 20 | 18.349837 | 0.569353 | 0.336710 | 0.108294 | 97.099548% |
| Held-out test | 40 | 15.467388 | 0.414395 | 0.432237 | 0.110685 | 79.969801% |

위 표는 **과거 E0 기록, 저장 맵 재평가, 새 mapping 후 평가에서 모두 동일**했다. JSON에 기록된 split별 PSNR·SSIM·LPIPS·coverage·L1·AbsRel·프레임 수의 차이는 전부 0이었다. 전체 텐서나 모든 프레임의 bitwise determinism을 주장하는 결과는 아니다.

실행 전 스크립트에 고정한 회귀 허용 오차는 다음과 같다. Gaussian 수는 두 경로 모두 정확히 일치해야 한다.

- 저장 맵: PSNR 절대 오차 `1e-4 dB`, 나머지 집계값 `1e-6`.
- 새 mapping: 프레임 수 정확 일치, PSNR `0.05 dB`, 나머지 집계값 `0.002`.

평가는 E0의 alpha-weighted expected rendered depth, compositing weight `>1e-3`의 coverage 규칙과 프레임별 단순 평균을 그대로 재현했다. 단일 trajectory Sim(3) scale은 **1.067586563**이었다. 이 정렬은 기존 전체 mapping trajectory를 사용하는 **회귀 확인용 규칙**으로, A0의 calibration-prefix 정렬을 검증하거나 확정한 것은 아니다.

Mapper는 exit code 0으로 종료했다. 기존과 같은 CUDA IPC tensor lifetime 경고가 종료 시 남았으나 export·재평가·원본 보존 검사는 통과했다. 장기 실행 자원 정리와 peak VRAM은 이번에 검증·측정하지 않았다.

## 5. 재사용할 자산과 N1에서 채워야 할 항목

| 자산 | 현재 재사용 가능 범위 | 남은 확인 |
|---|---|---|
| `.venv`, weights, CUDA 확장 | 실제 짧은 추론·렌더링 실행 통과 | 새 장면 메모리·장기 실행은 별도 |
| `src/e0_export.py`, `src/e0b_export.py` | raw pair, KF source event, 별도 audit 기록 | candidate registry와 명시적 pose revision 연결 |
| `scripts/check_e0_exports.py` | 기존 후보 출처·Sim(3)·PLY 검사 | A0 네 군의 ID·속성·개입 독립성 검사 추가 |
| `scripts/evaluate_e0.py` | Replica RGB/depth 및 카메라 crop을 포함한 평가 | A0 공통 valid mask, prefix 정렬, correct-depth coverage |
| E4 평가·compact renderer·TSDF 코드 | 기존 코드 존재, 5장면 metric hash 일치 | 이동한 중심·covariance를 넣는 경로와 표면 평가 통제 |
| E4f geometry·Pose Oracle | 기록된 KITTI run·평가와 코드 재사용 | local 단위·KF별 scale과 GT SE(3)를 구분해 A0로 재설계 |

다음 N1 작업은 아래 순서로 진행한다.

1. 기존 `office0`의 작은 self-branch 후보 집합에서 픽셀·후보·anchor·raw/local/world 변환을 명시한 계약을 만든다.
2. 임의 단위 local pointmap과 metric GT 사이의 고정 환산 계수, global gauge, KF별 scale 처리를 정의하고 검증한다.
3. 공통 GT 유효 집합과 후보·속성 hash를 고정하고, A10의 pose 불변 및 A01의 local geometry 불변 검사를 만든다.
4. 새 평가 장면의 RGB·depth·pose·카메라 및 surface reference 가용성을 확인하고 개발/검증/최종 평가 역할을 등록한다.

로컬에서 확인한 Replica scene은 `office0`, `office1`, `room0`, `room1`, `room2`이며 모두 과거 사용 장면이다. 새 A0 평가 장면의 확보·분할은 아직 완료하지 않았다. 이번 N0에서 미사용 scene의 다운로드나 GT 열람은 수행하지 않았다.

## 6. 실행 명령과 산출물

이번에 실행한 명령:

```bash
.venv/bin/python scripts/run_n0_audit.py --gpu
```

GPU가 보이는 호스트 실행 환경에서 수행했다. 출력 경로가 이미 있으면 덮어쓰지 않고 종료한다. 재실행할 때는 새로운 경로를 지정한다.

```bash
.venv/bin/python scripts/run_n0_audit.py --gpu \
  --output results/N0_asset_audit/2026-10-26-rerun
```

`--gpu` 없이 실행하면 CPU 자산 점검까지만 수행하고 전체 판정은 `INCOMPLETE`로 남긴다. CUDA smoke·mapping·평가 subprocess는 offline 설정으로 실행하며 새 weights나 데이터를 다운로드하지 않는다.

- [추적용 요약 명세](../../configs/n0_asset_audit.json)
- [재실행 스크립트](../../scripts/run_n0_audit.py)
- [전체 판정](../../results/N0_asset_audit/2026-10-26/audit.json)
- [환경](../../results/N0_asset_audit/2026-10-26/environment.json), [소스 manifest](../../results/N0_asset_audit/2026-10-26/source_manifest.json)
- [가중치·입력 hash](../../results/N0_asset_audit/2026-10-26/asset_hashes.json), [기존 baseline manifest](../../results/N0_asset_audit/2026-10-26/baseline_manifest.json)
- [CPU export·GT 검사](../../results/N0_asset_audit/2026-10-26/cpu_checks.json), [재현 비교](../../results/N0_asset_audit/2026-10-26/reproduction.json)
- [실행 명령·로그 위치](../../results/N0_asset_audit/2026-10-26/gpu_commands.json), [과거 자산 확인](../../results/N0_asset_audit/2026-10-26/historical_assets.json)
- [원본 보존 확인](../../results/N0_asset_audit/2026-10-26/preservation.json)
- 새 mapping: `fresh_baseline/`, 저장 맵 재평가: `saved_baseline_replay/`, 실행 당시 소스 사본: `frozen/source/`.

`results/`의 대규모 산출물은 기존 저장소 방침에 따라 Git 추적 대상에서 제외하고, 본 보고서·요약 명세·재실행 스크립트를 추적 가능한 위치에 남긴다.
