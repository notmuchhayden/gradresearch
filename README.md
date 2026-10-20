# 교차시점 기하 정합성 기반 Gaussian Mapping 연구

연속 RGB 영상의 3D Gaussian Map에서 다른 Keyframe의 기하 관측을 이용해 이상 Gaussian의 편입을 억제하는 석사학위 논문 연구 저장소입니다.

현재는 **기준선 실행·관측 출처 감사·GT 오류 분해·신호 판별력·반복 관측 및 임계값 전이 파일럿을 완료한 단계**입니다. RTX 5060 8GB에서 E0, E0b, E1, E2, E2b를 수행했습니다. E2b는 E3 검증 진행 기준을 충족했으며, 제안 admission 정책의 최종 성능 향상과 독창성은 아직 검증하지 않았습니다.

- [E0: 기준선 재현·export·GT 평가](docs/experiments/E0_baseline_reproduction.md)
- [E0b: 관측 출처·융합 ancestry·판단 시점 감사](docs/experiments/E0b_ancestry_causality_audit.md) — 180입력/5-KF 실행 완료. 반복 교차관측 가용성은 추가 확인이 필요합니다.
- [E1: GT 오류 taxonomy·pose 민감도·held-out 깊이 평가](docs/experiments/E1_error_taxonomy.md) — 원본 active 후보의 반복 front 오류 proxy 12.81%, GT-anchor 진단 10.35%.
- [E2: confidence·교차 깊이/RGB·DoG·plane 판별력 비교](docs/experiments/E2_signal_discriminability.md) — 좁은 공통 집합에서 P1 AP 0.4268, confidence 0.4830. P1 개발 임계값의 시간 평가 거절 0개, 유효 2-view 후보 0개로 후속 보완이 필요했습니다.
- [E2b: 반복 유효 관측·개발/평가 장면 간 임계값 전이](docs/experiments/E2b_repeated_observations_threshold_transfer.md) — office0 개발 → room0 평가. 반복 관측 coverage 16.14%, GT bad 1,107개 거부 판정, 정상 보존 99.99%, 전체 bad recall 3.37%. **E3 검증 진행 가능**이며 대조군 우위와 실제 Map 품질은 추가 검증합니다.

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
- [ ] 보수적 admission 및 matched-budget 비교 구현

