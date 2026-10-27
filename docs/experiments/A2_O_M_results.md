# A2-O-M 결과 — 마지막 RGB mask/support 진단

**실행일: 2026-10-27 (Asia/Seoul). 상태: COMPLETE_EARLY_STOP / STOP_INSUFFICIENT_SUPPORT.**

고정된 수정안 R1에서 일부 RGB pair의 support는 회복됐지만, KF별 fit/audit 증거를 확보하지 못했다. **현재 데이터·표현·고정 절차에 대한 보정 개발 경로를 종료한다.** RGB-only 보정의 기하 효능이나 일반적인 RGB 관측 불가능성을 판정한 결과는 아니다.

[실행 계획](A2_O_M_execution_plan.md) · [기계 판독 요약](../../configs/a2_o_m_results_summary.json) · [실행 manifest](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/execution_manifest.json) · [등록 원 계획](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/registered_code/docs/experiments/A2_O_M_execution_plan.md)

## 1. 실제 실행 범위

| 단계 | 실제 수행 | 판정 |
|---|---|---|
| 구현·입력 QA·등록 | Native-only adapter, archived code hash, frame/event/ancestry, camera 및 native ID 확인 | PASS |
| M0 | Office2 양 gauge·양 fold, fit/audit pair 288개 레코드의 gate 분해·4가지 support ablation | 기존 실패 재현 |
| M1 | Analytic positive/negative와 nuisance 대조, 정보 분리·mask 검사 | 필수 대조 36/36, 전체 기대 판정 검사 77/77 충족 |
| M2 fit | 전체 40개 KF context를 지원 기준으로 점검하고 미지원 결과 봉인 | 계수 선택 불성립, profile 행 0개 |
| 독립 검증 | 288개 pair cache × 4 variant의 bitset·mask·지원율 및 seal 재계산 | 1,152건 PASS |
| RGB audit loss·source GT·map·400 target | 선행 fit gate 실패 | NOT_RUN_DUE_TO_GATE |
| Office3 validation | Office2 개발 gate 실패 | NOT_RUN_DUE_TO_GATE |

Source/audit의 **지원 mask·수치 진단**은 M0에서 수행했지만, audit loss 및 GT 성능 평가는 실행하지 않았다. Office3의 새 데이터 평가, office4, HKairport는 실행하지 않았다. Field·pose 추정·joint optimizer·새 inference·학습은 수행하지 않았다.

## 2. 입력과 원 결과 정정

Office2의 native 11KF / 1,545,979개 후보, post-prefix 10KF / 1,405,054개 native 후보, final pose revision 520을 확인했다. 기존 local·final snapshot hash가 일치했고 90개 pair row 중 72개가 provenance-disjoint였다. 이 72개에 양 gauge·양 fold를 적용한 288개 평가 레코드 중 fit은 160개, audit는 128개다. 같은 이미지 쌍의 반복 평가를 독립 표본으로 세지 않는다.

M0에서 원 등록 코드의 `evaluate_pair_candidates`를 실제 호출하여 fit 160개 모두의 eligible·retained 수와 exact mask를 대조했다. **최대 eligible=171, 최대 retained=0**을 재현했다. 기존 A2-O 문서의 “공통 mask 후 최대 171개”는 부정확하며 171은 교집합 전 수치다. [정정 감사 기록](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/legacy_result_correction_audit.json)에 원 문서 hash와 근거를 보존했고 원 실험 문서를 덮어쓰지 않았다.

RGB adapter는 NPZ의 native prediction·native mask·candidate ID만 읽었다. Registry 안에 reference 배열이 함께 저장돼 있는 사실은 유지되지만 reference 배열의 접근을 차단하는 검사도 통과했다. 파일 checksum 계산은 전체 파일의 해석하지 않은 바이트를 읽는다. 기존 prefix GT alignment가 포함된 gauge를 재사용하므로 전체 파이프라인이 GT-free metric scale을 얻었다는 주장은 하지 않는다.

## 3. R1과 support ablation

R1은 사전 고정한 **stride 2 sampling + symmetric predicted-depth agreement의 RGB mask gate 제거**다. 41개 log-scalar grid, texture 0.02, parallax 1°, ray error 1pixel, patch 9점·evidence 4-neighbor validity·edge dilation 2pixel, pair당 256개 및 eligible 대비 50% 기준은 유지했다. 실제 geometry와 RGB loss를 보고 다른 조합을 선택하지 않았다.

| Variant | Pool | 레코드 수 | 최대 eligible | 최대 common | 지원 pair |
|---|---|---:|---:|---:|---:|
| L4: 기존 mask, stride4 | Fit | 160 | 171 | 0 | 0 |
| L4 | Audit | 128 | 86 | 0 | 0 |
| L2: 기존 mask, stride2 | Fit | 160 | 704 | 0 | 0 |
| L2 | Audit | 128 | 343 | 0 | 0 |
| R4: 수정 mask, stride4 | Fit | 160 | 173 | 110 | 0 |
| R4 | Audit | 128 | 96 | 64 | 0 |
| **R1: 수정 mask, stride2** | **Fit** | **160** | **706** | **410** | **6** |
| **R1** | **Audit** | **128** | **372** | **234** | **0** |

R1의 지원 fit pair는 position fold0에서 KF9→7과 KF10→7, fold1에서 KF10→7이며 orientation에서도 같은 조합이었다. 각 source KF에 fit evidence가 최대 한 개뿐이다. Audit는 최대 234개로 최소 256개에 미달했다.

| Context | 지원 fit pair | Fit 지원 KF | Audit 지원 KF | 지원 native 후보 |
|---|---:|---:|---:|---:|
| Position fold0 | 2/40 | 0/10 | 0/10 | 0/1,405,054 |
| Position fold1 | 1/40 | 0/10 | 0/10 | 0/1,405,054 |
| Orientation fold0 | 2/40 | 0/10 | 0/10 | 0/1,405,054 |
| Orientation fold1 | 1/40 | 0/10 | 0/10 | 0/1,405,054 |

KF 지원은 fit/audit pool 각각 통과 pair 2개 이상이며, scene 진행에는 KF·native 후보 지원율 각각 80%가 필요하다. **R1의 표본 회복은 관측됐지만 모든 context가 진행 기준에 실패했다.**

Stride2의 3×3 patch는 겹친다. Center 수 증가는 독립 정보량이 같은 비율로 늘었다는 뜻이 아니다. Exact center, patch pixel union, spatial tile 점유율 및 gate bitset을 함께 저장했다. Pair별 NPZ에 gate bitset을 분산 저장했고 위치·hash는 [mask manifest](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/mask_manifest.json)로 관리한다.

## 4. 어디서 표본이 줄었는가

아래는 **position fold0의 fit 40개 pair 레코드에서 누적 통과 center 수를 합산**한 예시다. Pair가 반복 사용하는 source pixel도 반복 집계되므로 unique 관측 수나 물리적 오류 원인의 기여율이 아니다.

| 누적 gate | L4 | R1 |
|---|---:|---:|
| Grid·tile guard·native 3×3 존재 | 144,292 | 577,040 |
| Source Z jump | 143,588 | 574,148 |
| Source texture | 30,620 | 122,000 |
| Center ray-grid ≤1pixel | 15,532 | 62,048 |
| Parallax ≥1° | 15,532 | 62,048 |
| S0 projection의 image bounds·finite·positive Z | 3,180 | 12,351 |
| Evidence native sample validity | 1,255 | 5,032 |
| S0 depth agreement | 1,163 | 적용하지 않음 |
| S0 warped texture, 즉 eligible | 689 | 2,828 |
| 41개 후보의 공통 mask | 0 | 1,233 |

Source texture·ray 일치·시야 중첩·evidence validity에서 이미 표본이 크게 줄었다. Parallax는 이 누적 순서에서 추가 탈락을 만들지 않았다. 전체 evidence raster의 raw 점유율은 121,505–137,550pixel이었고 edge/invalid 경계 제외 후 65,801–90,660pixel이 남았다. 이는 raster hole과 edge 처리가 support 범위를 줄였음을 보여주지만, 임계값을 완화해 보정 성공을 만들 근거는 아니다.

후보별 교집합 경과와 독립 gate bitset도 보존했다. 상세 자료는 [support waterfall](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/support_waterfall.csv), [support ablation](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/support_ablations.csv), [gate diagnostics](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/gate_diagnostics.json)에 있다.

등록 코드의 bilinear bounds에는 `y>=0`가 빠져 있었다. Legacy 재현은 원 동작을 유지했고 R1에는 계획의 image-inside 조건을 적용했다. 따라서 L4/L2와 R4/R1의 mask 차이에는 depth gate 제거와 이 경계 계약 복구가 함께 포함된다. 이를 순수 depth-gate 단독 효과로 분해하지 않는다. Source edge의 4-neighbor jump와 evidence의 2pixel dilation도 별도 동작으로 유지했다.

## 5. 합성 대조 및 구현 검사

[등록된 controls specification](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/controls/specification.json)을 먼저 저장한 뒤 [77개 control 기록](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/controls/results.json)을 실행했다.

- Legacy 4m 평면의 0-only retained 400개 / 41개 교집합 0개를 재현했고 R1에서는 지원을 회복했다.
- 2/4/8m, 정면·경사면, source log-bias ±0.05/±0.10의 **24개 회복 조건 모두 grid 오차 0**이었다. Clean 6조건도 통과했다.
- Pure rotation 0°/1°, low texture, joint scale ±0.10의 기대 지원 실패·불변성 검사를 통과했다. 이를 metric scale 복원 성공으로 처리하지 않았다.
- 필수 positive/negative/invariance는 36/36 통과했다. 나머지 41개 nuisance 진단에서는 24개 방향 개선, **13개 photo/geometry mismatch**, 3개 미해결 photo gain, 1개 support 부족을 기록했다.

**“77/77 기대 판정 충족”은 모든 nuisance에서 보정이 성공했다는 뜻이 아니다.** Pose 오류 등의 조건에서 photo 감소와 depth 악화가 동시에 발생했고, 이를 geometry 성공으로 분류하지 않는 검사를 충족했다. 가림 대조는 지원 자체가 부족했으며, true visibility는 계수 선택 이후의 audit에만 사용했다. 지원 미달 synthetic 곡선은 한계 진단이며 primary 성공 근거가 아니다.

Focused unittest 11개와 저장소 전체 unittest **190개**가 통과했다. Native adapter의 reference 배열 접근 차단, audit/target/reference 변경에 대한 fit 불변성, checkerboard guard, 후보별 가변 분모 거부, 회전 scale 불변성, 미지원 KF 분모, 위쪽 image bounds, world translation을 고정하는 local 보정을 검사했다. 이 검사는 미실행된 real GT/map 평가를 대신하지 않는다.

## 6. 봉인, 검증 및 미실행 범위

M0/M1 완료 후 R1을 봉인하고, M2 fit에서 전체 40개 KF context의 미지원 상태를 생성했다. 지원 KF가 없어 Ok/Gk 계수와 Og는 선택되지 않았고 real `profiles.csv`·RGB audit·geometry map은 만들지 않았다. [선택 봉인](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/selection_seal.json)은 미지원 결과를 고정한 것이다.

[독립 검증](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/office2/verification.json)은 측정 함수 `diagnose/profile/context_support`를 호출하지 않고 저장된 bitset으로 1,152개 mask/support 기록과 KF/candidate 분모를 재계산했다. 선택 seal 및 artifact hash도 확인했다. 계수 argmin 검사는 real profile이 없어 해당 없음이다.

Source/target/office3 실행 명령이 선행 gate 실패로 거부되는 것도 [4개 guard 검사](../../results/A2_O_M_rgb_mask_diagnostic/2026-10-27/gate_refusal_checks.json)로 확인했다. 조기 종료 지점까지 구현·실행했으며 조건부 source/target evaluator 본문은 구현하지 않았다. 그 미구현이 이번 중단 원인은 아니다. 입력 support gate에서 먼저 종료했고 source GT·target은 열지 않았다.

M0의 측정 실행 시간은 약 60.25초였다. NumPy/CPU 경로를 사용했고 PyTorch 환경의 CUDA availability는 false였다. 새 map rendering에 진입하지 않아 CUDA renderer parity·target 효과는 미평가다. 다른 단계의 개별 walltime과 peak RSS는 별도 계측하지 않았다는 기록상 제한이 있다. 수행 명령·환경·계측 범위는 `command_history.json`과 실행 manifest, 로그는 `logs/`에 보존했다. 실행 후 입력·등록 코드의 hash 71건도 일치했다. 과학적 R2나 threshold 변경, 결과에 따른 재튜닝은 없었다.

## 7. 결론과 경로 종료

기존 common mask는 정상적인 합성 입력에서도 표본을 없앨 수 있었고, R1은 이 문제를 완화했다. 하지만 실제 입력에서는 fit/audit evidence와 충분한 sample을 가진 KF가 없었다. **현재 고정된 scalar RGB 보정 절차의 실행 가능한 support를 확보하지 못했으므로, 사전 합의한 중단 기준에 따라 이 개발 경로를 종료한다.**

Source depth 개선, target depth/coverage 개선, surface 품질 개선은 새로 측정하지 않았다. RGB 자체에 정보가 없다는 반증이나 모든 공간 field·pose 보정의 실패 증명으로 확대하지 않는다. A2-S의 office3 source/target 불일치도 그대로 유지하며, 이번 결과로 다른 optimizer 개발이나 office4 해제를 정당화하지 않는다.

## 재현 명령

이미 등록·봉인된 디렉터리를 덮어쓰지 않는다. 아래는 실제 수행 순서이며, 현재 상태에서 새 등록/선택 명령은 중복 실행을 거부한다. `verify`는 저장된 결과를 검증하는 명령이다.

```bash
.venv/bin/python scripts/run_a2_o_m.py preflight --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py register --config configs/a2_o_m_protocol.json
.venv/bin/python -m unittest discover -s tests -p 'test_rgb_mask_diagnostic.py' -v
.venv/bin/python scripts/run_a2_o_m.py support-audit --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_a2_o_m.py controls --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py seal-r1 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py profile --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py freeze-selection --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py verify --scene office2 --config configs/a2_o_m_protocol.json
.venv/bin/python scripts/run_a2_o_m.py report --config configs/a2_o_m_protocol.json
```
