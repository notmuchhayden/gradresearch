# 교차시점 기하 정합성 기반 Gaussian Mapping 연구

연속 RGB 영상의 3D Gaussian Map에서 다른 Keyframe의 기하 관측을 이용해 이상 Gaussian의 편입을 억제하는 석사학위 논문 연구 저장소입니다.

현재는 **E4b의 기준 평면 GT 정확도·판정 경로 진단까지 완료한 단계**입니다. 앞선 E4에서는 15개 방법, 자연 정책·점수 ranker·공통 fallback을 분리해 5장면에서 실행했습니다. 새 office1의 75% 유지 조건은 모두 **860,701개·42.683 MiB**이며, TSDF Chamfer는 plane 0.108354 m, median-depth 0.108530 m, 원래 B6 depth 0.105947 m였습니다.

**E4 판정은 REVISE**입니다. plane의 median-depth 대비 개선은 0.162%로 사전 기준 2%에 미달했고 B6보다 기하 품질도 낮았습니다. RGB·coverage 비열등성은 통과했습니다. 자연 plane 정책은 bad 1,686개·normal 0개를 제거했지만 전체 bad recall은 0.587%로 낮았습니다. **E5/E6 효능 검증으로의 자동 진행은 보류**하고, 강한 depth 대조군과 제한된 관측 범위를 개발 단계에서 분석해야 합니다.

**[E4b 결과](docs/experiments/E4b_reference_plane_audit_results.md):** office1에서 잘못된 기준 평면이 미제거 불량을 지지한 후보 **31,412개**를 확인했습니다. 그중 **31,132개는 B6도 놓친 후보**입니다. B6만 제거한 bad 9,874개 중 **9,867개(99.93%)**는 B6 최초 제거 시점에 plane의 유효 관측 두 개를 확보하지 못했습니다. GT-plane/veto 재계산은 bad 5,209개를 추가 제거했지만 normal 409개·unknown 10,713개도 추가 제거했습니다. 기준 오류와 관측 조건의 제약을 함께 확인한 **사후 진단**이며 효능 GO는 아닙니다. [등록 당시 설계](docs/experiments/E4b_reference_plane_audit.md)와 설정은 보존했습니다.

- [E0: 기준선 재현·export·GT 평가](docs/experiments/E0_baseline_reproduction.md)
- [E0b: 관측 출처·융합 ancestry·판단 시점 감사](docs/experiments/E0b_ancestry_causality_audit.md) — 180입력/5-KF 실행 완료. 반복 교차관측 가용성은 추가 확인이 필요합니다.
- [E1: GT 오류 taxonomy·pose 민감도·held-out 깊이 평가](docs/experiments/E1_error_taxonomy.md) — 원본 active 후보의 반복 front 오류 proxy 12.81%, GT-anchor 진단 10.35%.
- [E2: confidence·교차 깊이/RGB·DoG·plane 판별력 비교](docs/experiments/E2_signal_discriminability.md) — 좁은 공통 집합에서 P1 AP 0.4268, confidence 0.4830. P1 개발 임계값의 시간 평가 거절 0개, 유효 2-view 후보 0개로 후속 보완이 필요했습니다.
- [E2b: 반복 유효 관측·개발/평가 장면 간 임계값 전이](docs/experiments/E2b_repeated_observations_threshold_transfer.md) — office0 개발 → room0 평가. 반복 관측 coverage 16.14%, GT bad 1,107개 거부 판정, 정상 보존 99.99%, 전체 bad recall 3.37%. **E3 진행 기준 통과**이며 실제 정책 효능 판정과 구별합니다.
- [E3: 실제 편입·거부·보류 정책 비교](docs/experiments/E3_admission_decision.md) — 10개 정책, 기존 office0/room0 재사용. P2는 active 후보 중 bad 1,105개·normal 79개를 제거했으나, 보류 때문에 정상 active 보존 77.59%, 깊이 coverage 93.82%→73.97%. 즉시 BYPASS 후 재검사는 같은 후보를 제거하며 coverage를 유지했습니다. **REVISE**, GPU 성능·새 독립 test·matched-budget 우위는 미검증입니다.
- [E3b: 임시 편입 후 재검사·부분집합 보호 보완](docs/experiments/E3b_provisional_admission.md) — office0에서 보정·봉인, room0 회귀 및 새 room1에서 11개 정책 실행. room0 bad 823개·normal 6개, room1 bad 5,104개·normal 0개 제거. 유한 normal 보존 99.89% / 100%, 깊이 coverage 유지. room1 공통 후보에서 B6와 정밀도 100% 동률이고 제거량은 B6가 더 많아 **추가 우위 미확인·REVISE**로 기록했습니다.
- [E3c: 동일 인과적 관측 조건의 depth/plane 비교](docs/experiments/E3c_matched_evidence.md) — 7개 정책, office0 개발 / room0·room1 회귀 / 새 room2 평가. room2 주 비교에서 plane bad recall +7.53%p, 두 방법 normal 오거부 0개. 대칭 support veto에서도 +7.50%p. **E4 비교 실험에 조건부 진입 가능**, 장면별 혼합 결과와 median-depth 근접 성능을 함께 기록했습니다. 63개 테스트·4장면 무결성 검사 PASS입니다.
- [E4: 동일 수·바이트에서 RGB·TSDF·실제 compact 메모리 비교](docs/experiments/E4_matched_budget.md) — office0 개발 / room0·room1·room2 회귀 / 새 office1 평가. 525개 조합 중 461개 도달, 64개 도달 불가를 명시했습니다. 99%·90%·75% 유지 예산, B1~B8·median-depth·P1/P2/P3 및 무작위 3 seeds 포함. **REVISE: 기하 추가 개선 기준 미달**. 75개 테스트·CUDA/TSDF 합성 검사·5장면 무결성 검사 PASS입니다.
- [E4b: 기준 평면의 GT 정확도·B6/plane 판정 경로 감사 결과](docs/experiments/E4b_reference_plane_audit_results.md) — **실행 완료**. office1 주 분석 / 기존 네 장면 보조 분석. 5장면 원본 점수·최초 제거 정확 재현, 후보×시점×관측 116,265,669행 감사, 두 GT-plane oracle·pose/라벨 민감도·원본 patch 중복 제거·200개 고정 사례 포함. 13개 테스트·입력 1,155개와 결과 무결성 검사 PASS. E4 REVISE 유지입니다.

## 연구 계획

- [연구·실험 계획서 v3](docs/surface_guided_gaussian_mapping_research_plan_v3.md)
- [이전 계획서 v2](docs/surface_guided_gaussian_mapping_research_plan_v2.md)
- 현재 논문 제목: **연속 영상 기반 3D Gaussian Splatting에서 이상 Gaussian 감소를 위한 기하 정합성 기반 최적화 연구**
- 작업용 연구 명칭: *Cross-View Surface-Supported Gaussian Admission*

핵심 질문은 후보 Gaussian을 생성한 관측과 가능한 한 분리된 교차시점 기하 증거가, 정상 표면의 표현을 유지하면서 잘못된 Gaussian의 Map 편입을 줄일 수 있는지입니다.

초기 구현 범위:

1. Splatt3R-SLAM 기준선 재현 및 Keyframe별 pose·Pointmap·confidence·Gaussian·생성 관측 출처 저장
2. 교차시점 대응, 가시성 검사, 신뢰 가능한 국소 표면 추정
3. `KEEP / REJECT / DEFER(BYPASS)` Gaussian 편입 정책
4. 동일 Gaussian 예산에서 confidence filtering, uniform thinning, voxel deduplication, self-surface filtering과 비교
5. 독립 GT 기하, held-out rendering, 표면 coverage, 처리시간 및 실제 메모리 평가

Soft projection과 surface-aware deduplication은 핵심 실험 이후의 선택 확장입니다.

## 기반 프로젝트

| 프로젝트 | 연구에서의 역할 | 공개 저장소 |
|---|---|---|
| MASt3R | Pointmap 및 이미지 matching prior | [naver/mast3r](https://github.com/naver/mast3r) |
| MASt3R-SLAM | Tracking, Keyframe 관리, loop closure | [rmurai0610/MASt3R-SLAM](https://github.com/rmurai0610/MASt3R-SLAM) |
| Splatt3R | 이미지 쌍 기반 Gaussian 예측 | [btsmart/splatt3r](https://github.com/btsmart/splatt3r) |
| Splatt3R-SLAM | 초기 기준선 및 Gaussian mapping 통합 구현 | [Looong01/Splatt3R-SLAM](https://github.com/Looong01/Splatt3R-SLAM) |

먼저 통합 Splatt3R-SLAM 구현을 재현하고, 독립 실행이나 비교가 필요한 경우 다른 저장소를 추가합니다. 외부 코드와 pretrained weights의 라이선스 및 인용 조건은 각 원본 프로젝트를 따릅니다.

## 저장소 구조

```text
.
├── README.md
├── configs/       # 추적할 실험 설정, 데이터 split 및 환경 명세
├── src/           # 자체 연구 구현
├── scripts/       # 실행, export 및 평가 스크립트
├── tests/         # 좌표 변환, 관측 출처, admission 등 검증
├── docs/          # 구현 문서와 실험 노트
│   └── experiment_template.md
├── thirdparty/    # 로컬 외부 저장소 (Git 추적 제외)
├── data/          # 원본 및 전처리 데이터 (Git 추적 제외)
├── checkpoints/   # 사전학습 가중치 (Git 추적 제외)
└── results/       # 실험 출력 (Git 추적 제외)
```

빈 디렉터리는 `.gitkeep`으로 유지합니다. `data/`, `checkpoints/`, `thirdparty/`, `results/`의 실제 내용은 커밋하지 않습니다. 재현에 필요한 설정과 데이터 출처·split·외부 commit·가중치 hash 등의 명세는 `configs/` 또는 `docs/`에 저장합니다. 논문에 사용할 선별된 그림과 표는 크기와 공유 가능 여부를 확인한 뒤 `docs/`에 보관할 수 있습니다.

## 환경 준비 및 첫 실행

E0의 설치·빌드·실행 스크립트와 환경·가중치 명세는 `scripts/`, `configs/`에 있습니다. 실제 설치 순서와 하드웨어 조정 사항은 [E0 보고서](docs/experiments/E0_baseline_reproduction.md), E0b 실행·감사 명령은 [E0b 보고서](docs/experiments/E0b_ancestry_causality_audit.md)를 따릅니다.

1. GPU, VRAM, NVIDIA 드라이버 및 CUDA toolkit 환경을 확인합니다.
2. Splatt3R-SLAM 소스를 `thirdparty/Splatt3R-SLAM/`에 준비하고 사용할 commit을 기록합니다.
3. 별도 Conda 또는 가상환경에서 **해당 commit의 설치 안내**에 따라 의존성과 CUDA 확장을 설치합니다.
4. 안내된 pretrained weights를 준비하고 출처 및 hash를 기록합니다.
5. 짧은 공개 시퀀스로 원본 기준선(E0)을 실행하고 export 및 좌표계를 확인합니다.
6. 동일 입력에서 자체 필터를 먼저 후처리로 검증한 뒤 mapping 과정에 연결합니다.

실제로 사용한 버전과 실행 명령은 각 실험의 명세에 기록합니다. 상위 프로젝트의 패키지 이름이나 최신 버전만으로 설치 환경을 추정하지 않습니다.

## 실험 기록 원칙

- 실험마다 자체 코드와 외부 코드의 commit, 환경 버전, pretrained weight hash, dataset/split, seed와 정확한 실행 명령을 기록합니다.
- 기준선과 제안 방법의 입력, pose, 전처리, refiner 설정 및 Gaussian 예산을 통제합니다.
- 후보 생성 관측과 검증 관측의 출처를 기록하고, 공유 정보를 독립 관측으로 세지 않습니다.
- 내부 surface residual과 독립 GT 기반 기하 정확도를 구분합니다.
- Candidate / active / resident Gaussian 수와 실제 GPU 메모리를 구분해 측정합니다.
- 성공 사례와 함께 정상 표면 삭제, 가림, 얇은 구조, 식생 및 tracking 실패 사례를 기록합니다.

실험 노트는 [템플릿](docs/experiment_template.md)을 복사해 `docs/experiments/<experiment_id>.md`로 작성합니다. 상세 실험 설계와 판정 기준은 연구 계획서를 따릅니다.

실험 출력의 권장 구조:

```text
results/<experiment_id>/
├── config.yaml
├── git_commit.txt
├── environment.txt
├── dataset_split.json
├── metrics.json
├── gaussian_decisions.csv
├── observation_sources.csv
├── map_stats.csv
├── timing.csv
├── trajectory.txt
├── render/
├── geometry/
├── figures/
└── logs/
```

## 초기 진행 항목

- [x] 사용할 외부 저장소 commit과 실행 환경 고정
- [x] E0 기준선 재현 (짧은 파일럿; 논문 수치 재현은 미검증)
- [x] Keyframe export 및 Sim(3) 좌표 변환 검증
- [x] 후보 생성 관측과 교차시점 관측의 출처 분리 가능성 확인 (E0b; 반복 관측 충분성은 미확인)
- [ ] 공개 GT benchmark와 초기 드론 파일럿 선정
- [x] 보수적 admission·DEFER/BYPASS 정책 비교 구현 및 E3 실행 (REVISE)
- [x] E3 실패 분석에 따른 임시 편입·부분집합 보정 및 새 room1 평가 (E3b)
- [x] E3c: 동일 인과적 관측 조건 비교 및 새 room2 평가 (주 비교 PASS; 전반적 우위 미확인)
- [x] E4 matched-budget 비교 및 새 office1 평가 (REVISE; E5/E6 효능 검증 진행 보류)
- [x] E4b 기준 평면·판정 경로 진단 설계 등록
- [x] E4b 전수 감사·GT-plane oracle 실행 및 원인별 결과 보고 (기준 오류·관측 제한 확인; E4 REVISE 유지)

