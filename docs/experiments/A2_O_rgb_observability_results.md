# A2-O 실행 기록

**상태: PARTIAL_EXECUTION / OFFICE2_PROFILE_SUPPORT_FAILED / SCIENTIFIC_EFFECT_NOT_ESTIMATED** · 실행일: 2026-10-27 (Asia/Seoul)

## 실행 범위

프로토콜을 고정하고 수치 primitive 검사, 입력 preflight, 등록, raw self-branch provenance split까지 수행했다. 이번에는 RGB projection/patch loss, two-stage scalar/field candidate profile, common-mask selection, Ok/Og/Gk/Of1 선택을 등록하고 office2에서 실행했다. 40개 position/orientation×fold×post-prefix-KF 레코드 모두 41개 scalar seed의 pair support 조건을 통과하지 못했다. 공통 mask 유지 후 pair당 최대 171개, 최소 0개였고 기준은 256개다. 총 160개 fit pair 중 지원 pair는 0개였다. 따라서 profile 행·mask가 0개이고 RGB 계수는 선택되지 않았다. `selection_complete=true`는 모든 KF 선택 기록이 생성되었다는 뜻이며 성공적 coefficient selection을 뜻하지 않는다. GT를 열지 않고 미지원 상태를 봉인했다. RGB 방향 구별, source/target geometry 효과는 추정되지 않았다.

Office2는 개발 scene이고 office3는 이미 A1/V1/A2-S에서 사용된 validation scene이다. 이번 실행에서도 office3를 새로운 test scene으로 취급하지 않았다. Office4와 HKairport는 건드리지 않았다.

## QA와 지원 현황

| 항목 | office2 | office3 |
|---|---:|---:|
| Native KF / candidate | 11 / 1,545,979 | 8 / 1,136,762 |
| Post-prefix strict candidate | 1,200,827 | 855,796 |
| Final pose revision | 520 | 514 |
| Source KF provenance-disjoint pair | 72 / 90 pair rows | 30 / 42 pair rows |
| Fit/audit pool에서 pair 2개 이상인 post-prefix KF | 10 / 10 | 7 / 7 |
| Shared-source pair | 18 | 12 |

이 표는 사전 profile 전 provenance QA 수치다. Office2 profile에서는 texture, parallax, projection ray, predicted visibility 및 common-mask를 계산했지만 common mask 뒤 256 patch 조건을 만족한 pair가 0개였다. Office3는 profile을 실행하지 않아 해당 진단값이 없다. 원본 provenance pair 및 거부 사유는 각 장면 `pair_manifest.csv`에 있다.

입력 KF 수, native/strict candidate 수, 288×512 shape, local/map hash, final snapshot revision은 사전 기대값과 일치했다. Baseline snapshot/raw image ID는 subsample index이고 office3 canonical local `source_frame`은 원본 frame이라는 ID 규칙을 preflight에서 검증했다.

## 수치 검사

새 primitive에 대한 focused unittest 5개와 저장소 전체 unittest 179개가 모두 통과했다. Scalar grid의 0 포함, DCT 15 mode의 mean/RMS/직교성, bilinear partition of unity, identity patch loss의 epsilon 범위, ray-preserving scale 연산과 shared-scale residual 상쇄를 검사했다. Algebraic 대조 결과는 `controls/results.json`에 있다.

이 검사는 계획의 전체 합성 control suite가 아니다. Scalar recovery positive, pure-rotation/low-texture negative, pose-depth confusion, true-visibility audit, map attribute/replay parity 및 Office3 GT-profile API 차단은 실행하지 않았다.

## 실행 결과 및 중단 위치

focused `unittest` 5개와 전체 `unittest` 179개가 모두 통과했다. `register-profile`, office2 `prepare`, `profile`, `freeze-selection`도 명령상 완료됐다. Profile은 NumPy/CPU에서 실행됐으며 CUDA를 사용하지 않았다. 데이터 실행 중 z-buffer edge 계산에서 invalid subtraction 경고가 한 번 발생했으나 실행은 종료 코드 0으로 마쳤다. 결과와 봉인은 `results/A2_O_rgb_observability/2026-10-27/profile_selection_v2/office2/`에 저장했다. 선택 seal SHA-256은 `226bc2054240400384fd27d15c97d5c1d2e4e0434470e6c04acfe47ea642a83`이다.

`evaluate --scene office2`는 현재 CLI에서 명시적으로 비활성화되어 실패했다. 구현 오류 메시지는 “remaining profile/evaluation implementation must pass provenance, GT-isolation, and runtime gates first”이다. 따라서 correction map, RGB audit, GT source/400-target 평가, TSDF, independent verification, office3 profile은 진행하지 않았다. Office3 validation은 office2 개발 seal 이후여야 하므로 실행하지 않았다. 현재 선택의 scene support는 position/orientation의 양 fold 모두 0/10 KF, 0/1,405,054 후보로 FAIL이다. 이 결과는 RGB 관측 불가를 입증하지 않고, 등록된 mask/support 규칙 아래 유효 sample이 부족했음을 뜻한다.

## 중단 위치와 제한

환경 기록에서 `nvidia-smi`는 RTX 5060과 CUDA 13.2를 확인했지만, A2-O `.venv`의 PyTorch는 `torch.cuda.is_available() == false`와 device_count 0을 보고했다. CUDA Gaussian 합성 smoke는 통과했다. TSDF smoke는 `.venv`에 `open3d`가 없어 중단됐다. 상세 범위는 `cuda_verification.json`과 `AMENDMENT_A6.json`에 있다.

RGB profile/selection은 별도 code registration과 office2 실행을 완료했지만 support 실패로 후보 profile/선택 계수를 생성하지 못했다. 구현은 NumPy 기반이며 CUDA를 사용하지 않는다. 바깥 환경의 이전 CUDA Gaussian renderer smoke는 통과했지만 PyTorch 환경 보고는 `cuda_available=false`, TSDF smoke는 `open3d` 부재로 실패했다. map·target 점수는 없다.

프로파일/선택 디렉터리는 존재하나 `profiles.csv`와 `mask_manifest.csv`는 헤더만 있고 mask index 파일은 없다. `selected_parameters.json`에는 모든 40개 KF 선택이 미지원으로 기록됐고 `selection_seal.json`은 그 결과를 고정한다. 아직 없다: `rgb_audit.csv`, `source_geometry.csv`, source direction profiles, correction maps, 400-target metrics, TSDF/surface metrics, independent verification, development seal, office3 validation registration, 최종 scene 판정. A2-S 결과와 기존 oracle 계수는 재사용하거나 덮어쓰지 않았다.

고정 support threshold를 유지한 채 원인 진단/구현 점검이 필요하다. 결과를 개선하려고 threshold나 후보/pair를 사후 변경하지 않는다. 전체 synthetic positive/negative control은 아직 구현·실행하지 않았다. 이번 결과로 RGB 관측 실패나 D 경로/보정 GO 판정을 내리지 않는다.

## 재현 명령과 기록

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_rgb_observability.py'
.venv/bin/python scripts/run_a2_o.py preflight --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py register --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py controls --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py prepare --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py prepare --scene office3 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py register-profile --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py profile --scene office2 --config configs/a2_o_rgb_observability_protocol.json
.venv/bin/python scripts/run_a2_o.py freeze-selection --scene office2 --config configs/a2_o_rgb_observability_protocol.json
```

실패 후 수정한 import path, numerical test tolerance, frame ID verification, raw-pair memory use는 `results/A2_O_rgb_observability/2026-10-27/amendments/`에 보존했다. Protocol의 수치·범위는 바꾸지 않았다.
