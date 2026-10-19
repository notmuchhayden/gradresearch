# 실험 보고서: E0b — Ancestry / causality audit

## 결론

- 날짜: **2026-10-19 (Asia/Seoul)**
- 상태: **E0b 파일럿 수행 완료. Raw 관측을 이용한 E1 오류 분석으로 진행 가능. 반복 교차관측에 근거한 REJECT 정책의 실행 가능성은 아직 확인되지 않음.**
- 계획서: [v3 §4, §8](../surface_guided_gaussian_mapping_research_plan_v3.md), 선행 실험: [E0](E0_baseline_reproduction.md).
- 기존 60입력/2-KF 구간과 확장 180입력/5-KF 구간을 실제 GPU에서 각각 1회 실행했다. 두 실행 모두 exit code 0, 모든 입력의 pose와 최종 맵 저장을 확인했다.
- 확장 구간에서 raw 관측의 **생성 시점 source-disjoint 후보 풀 비율은 60%**였다. 시야 방향·confidence·1° 이상 시차까지 요구하면 **고정 격자 후보 샘플의 10.93%**, 이후 KF 도착 시 재평가를 허용하면 **21.59%**가 한 번 이상 가용했다.
- 생성 시점 raw 출처가 분리된 후보–관측 6쌍 중 **3쌍(50%)은 fused ancestry를 반영하면 출처가 겹쳤다.** Fused 관측의 생성 시점 기하 가용성 proxy는 0%였다.
- **동시에 2개 이상의 관측이 source-disjoint·ray support·시차 조건을 만족한 샘플은 raw/fused 모두 0%**였다. 보류 후 재평가에서도 0%였다. 계획서 §5.1의 반복 관측 기반 충돌 판정을 검증했다고 볼 수 없다.

이 결과는 관측 확보 가능성의 감사다. Gaussian 오류 분류, 제안 gate의 효능, 통계적 독립성, 원본 논문 성능을 입증하지 않는다.

## 질문과 사전에 고정한 범위

확인 질문은 다음과 같다.

1. 후보와 raw/fused pointmap의 원본 이미지·pair를 추적할 수 있는가?
2. 후보 생성 이미지와 직접 겹치지 않는 KF 관측이 얼마나 존재하는가?
3. 해당 관측은 판단 시점에 실제로 존재했는가? 얼마나 기다려야 하는가?
4. 관측 방향과 시차를 고려해도 가용성이 남는가?
5. 판단 당시 pose와 최종 pose를 구분해 재현할 수 있는가?

[감사 설정](../../configs/e0b_audit.json)을 두 실행 전에 고정했다. 이번 파일럿의 운영상 진행 기준은 provenance/revision/causality 검사 통과, KF 3개 이상, 생성 시점에 **최소 1개**의 출처 분리 관측과 기하 proxy를 확보한 샘플 비율 10% 이상이었다. 확장 구간은 10.93%로 이를 충족했다. 이는 정식 성능 사전등록이나 연구 전체 GO 기준이 아니며, 최소 2개 관측에 의한 REJECT 가능성 기준을 대체하지 않는다.

## 실행 조건과 재현

| 항목 | 조건 |
|---|---|
| 기준 코드 | Splatt3R-SLAM `74ffc37454dfa7560c9531b1534825c54c36a89e` + E0/E0b 계측·하드웨어 패치 |
| GPU | RTX 5060, 8,151 MiB, driver 595.99.02 |
| 환경 | 기존 E0 `.venv`: Python 3.11.17, PyTorch 2.13.0+cu132; 이번 실험에서 환경 패키지를 추가 설치하지 않음 |
| 모델·retriever | E0와 동일한 checkpoint 및 retrieval 자산; [기존 hash 명세](../../configs/e0_weights_manifest.json) |
| 장면 | NICE-SLAM rendered Replica `office0` |
| 짧은 구간 | 원본 `[0,120)` 중 짝수 60장, 기존 `data/Replica` 그대로 사용 |
| 확장 구간 | 원본 `[0,360)` 중 짝수 180장, 별도 `data/E0b/Replica` 사용 |
| GT 사용 | Mapper의 GT trajectory 변환 비활성화. 감사에서도 GT depth·trajectory를 읽지 않음 |
| 입력·예산 | 512×288, subsample 2, spatial stride 1, keyframe buffer 16, seed 0 |
| 원본 정책 | tracking/admission 및 KF 선택 기준 유지, confidence 1.5, depth percentile 0.98, max scale 1.0, 기본 opacity 0.3 |
| 메모리 조건 | 미리보기·프레임별 렌더링 비활성화, low-VRAM 캐시 반환·대기, faiss scratch 64 MiB |
| 최적화 | 원본 pose backend 및 loop closure 활성화, refiner 없음, conf-fade 0 |

확장 데이터는 공식 archive의 부분 다운로드로 준비했고, 기존 120장 중 일치하는 파일은 재사용했다. [다운로드 명세](../../configs/e0b_replica_download_manifest.json)에 360개 RGB와 camera metadata·trajectory 파일의 CRC/SHA-256을 기록했다. Trajectory 파일은 데이터 배포 자산으로 보관되지만 mapper/audit에서 사용하지 않는다. 홀수 프레임은 mapper와 감사 관측에 입력하지 않았다. 이번 실험에서 새 held-out 품질 평가는 수행하지 않았다.

프로젝트 루트에서 실행한 명령:

```bash
python3 scripts/download_e0_replica.py --frames 360 \
  --destination data/E0b/Replica \
  --manifest configs/e0b_replica_download_manifest.json \
  --rgb-only --reuse-from data/Replica --workers 4
bash scripts/run_e0b_audit.sh short
bash scripts/run_e0b_audit.sh extended
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/analyze_e0b.py short
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/analyze_e0b.py extended
MPLCONFIGDIR=results/E0b_ancestry_causality/.mplconfig .venv/bin/python scripts/plot_e0b.py
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python -m unittest discover -s tests -v
```

GPU runner는 이 실행 환경에서 GPU가 보이는 샌드박스 밖으로 실행했다. 분석·그림·테스트는 CPU에서 실행했다. Runner는 기존 `audit/events.jsonl`이 있으면 덮어쓰지 않고 종료한다. 재실행 시 기존 결과를 별도 보관한 뒤 빈 실행 경로를 사용해야 한다.

새 checkout에는 [누적 upstream 패치](../patches/e0b_upstream.patch)를 위 commit에 적용한다. **이 패치는 E0 패치를 포함하므로 E0 패치와 중복 적용하지 않는다.** 자체 `src/e0_export.py`, `src/e0b_export.py`도 필요하다. 환경 설치는 E0 보고서의 순서를 따른다. 실행별 `run_manifest.json`에 소스·설정·입력 hash를 기록했고 `code/`에는 해당 실행의 소스를 보관했다. 짧은 실행 이후 함수 import 이름 충돌을 피하는 alias와 소스 보관 코드를 보강했으며 확장 실행은 그 버전을 사용했다. 최종 자체 코드 명세는 [e0b_code_manifest.json](../../configs/e0b_code_manifest.json)이다.

## 계측과 지표 정의

### 출처와 fused ancestry

- Gaussian 후보 ID는 E0와 같은 `<prediction_event_id>:self:<row-major-pixel-index>`다. 실제 맵에 저장되는 self branch 후보를 감사한다.
- Raw 관측은 **KF 생성 event의 self-branch pointmap**이다. 각 raw event에는 양쪽 출력과 source image/pair를 저장하지만, 비-KF 프레임과 cross branch는 이번 가용성 평가의 관측 풀에 포함하지 않았다.
- Fused ancestry는 `weighted_pointmap`에 실제로 들어간 모든 raw 기여의 이미지·pair·event 합집합이다. 픽셀별 ancestry보다 보수적인 pointmap 전체 단위 출처다. 다른 filtering mode는 자동으로 `unknown` 처리한다.
- Source-disjoint는 후보 생성 이미지와 관측의 원본 이미지 합집합이 직접 겹치지 않는다는 뜻이다. 출처 미확인은 source-disjoint로 인정하지 않는다. 후보–관측의 출처 분리를 검사하며, 복수 관측끼리의 상호 독립성을 보장하지 않는다.
- 동일 모델 가중치, pose graph, 학습 bias는 공유한다. 이들을 image ancestry로 독립화했다고 주장하지 않는다.
- E0 호환용 `exports/candidate_sources/*.json`에는 과거 형식의 `unknown`/미버전 필드가 남는다. **E0b의 출처·revision 판정 원자료는 `audit/events.jsonl`과 `audit/snapshots/*.pt`**다.

### 판단 시점과 pose

- 모든 KF의 삽입 직후, **해당 KF의 backend 최적화 전**에 `decision` snapshot을 저장했다. Backend 처리 후와 전체 종료 후에도 저장했다.
- Shared KF write 및 backend pose write를 순서화하고, pose 값과 revision을 기록했다. Revision은 공유 상태 write 단위 버전이며, 실제 pose 변경 횟수와 다르다.
- 생성 시점 평가는 해당 decision snapshot에 이미 존재한 관측과 pose만 사용한다. 보류 가능성 평가는 **새 KF가 도착한 decision snapshot에서만** 이전 후보를 재평가한다. 실제 admission/DEFER queue를 실행한 것은 아니다.
- 종료 후 전체 관측·최종 pose로 계산한 수치는 `hindsight_final_revision`으로 분리했다. Causal eventual은 여러 실제 시점 중 한 번이라도 가용했던 샘플의 합집합이므로, 단일 최종 상태의 hindsight 수치보다 높을 수 있다. 최종 상태 수치를 시간 전체의 상한으로 해석하지 않는다.

### 기하 가용성 proxy

- 후보 풀당 147,456개 전체 후보 중 8픽셀 간격의 고정 격자 **2,304개**를 사용했다. 확장 구간은 총 **11,520개 샘플**이다. source-disjoint 여부는 후보 풀 전체에 대해 정확히 계산하지만 기하 수치는 이 격자에 대한 값이다.
- 후보 Gaussian mean과 관측 pointmap을 **동일한 판단 시점의 camera-to-world Sim(3)**로 정렬했다.
- GT pinhole intrinsics를 대신 넣지 않고 관측 pointmap 자체의 유효 unit ray에 KD-tree 대응을 구했다. 후보·관측 confidence ≥1.5, 최근접 ray와 각도 ≤1°, 두 카메라 중심에서 후보를 보는 시차 ≥1°를 요구했다.
- **가림·깊이 충돌·국소 patch 신뢰도·RGB 일관성을 검사한 최종 가시성 판정이 아니다.** 조건을 만족해도 올바른 Gaussian이라는 뜻이 아니며, 만족하지 않아도 REJECT하지 않는다. 1°와 confidence는 이번 감사의 고정 운영 조건이고 성능 최적 임계값이 아니다.
- 표의 분모는 confidence 부족 샘플까지 포함한 전체 고정 격자다. 독립 무작위 표본이나 통계적 신뢰구간으로 해석하지 않는다.

## 실행·무결성 결과

| 항목 | 짧은 구간 | 확장 구간 |
|---|---:|---:|
| 추정 pose / 입력 | 60 / 60 | 180 / 180 |
| 최종 KF | 2 | 5 |
| KF 원본 frame IDs | 0, 82 | 0, 82, 148, 222, 298 |
| Raw KF 후보 | 294,912 | 737,280 |
| 최종 active Gaussian | 286,208 | 705,772 |
| Raw pair event / journal event | 60 / 246 | 180 / 738 |
| Snapshot | 5 | 11 |
| Fused ancestry unknown | 0 | 0 |
| Raw → fused 수치 재계산 최대 절대 차이 | 1.669e-6 | 1.669e-6 |
| 최종 공유 상태 revision | 62 | 188 |
| 실제 값이 변경된 backend pose update batch | 1 | 4 |
| Device-wide 메모리 관측 최대 | 7,404 MiB | 6,850 MiB |
| 전체 mapper wall time | 35초 | 49초 |

모든 snapshot에서 raw 기여와 저장된 상대 Sim(3)로 weighted pointmap을 다시 계산하여 pointmap·평균 confidence·업데이트 횟수·출처 합집합을 대조했다. Pose도 journal의 write들을 재생해 snapshot의 값과 정확히 일치하는지 확인했다. 후보 mean과 원본 raw 예측은 KF별로 정확히 일치했고, 모든 사용 event가 해당 snapshot 이전에 생성되었는지 검사했다. 두 구간 모두 PASS였다.

짧은 구간은 기존 E0와 **KF 선택·후보 mean·최종 pose·최종 fused pointmap이 모두 정확히 일치**했다. 이 1회 대조에서 계측 때문에 결과가 바뀌지 않았음을 확인했으며 모든 환경의 결정성을 증명하지 않는다.

확장 구간에서 판단 당시와 최종 pose 사이 최대 차이는 translation **0.03636 SLAM 좌표 단위**, rotation **0.6797°**, scale 비율 **0.8185%**였다. GT scale 정렬을 하지 않았으므로 translation을 미터라고 부르지 않는다.

메모리는 200ms 간격의 GPU 전체 사용량이다. Allocator의 정확한 순간 peak가 아니며, 두 실행의 관측 최대 차이를 KF 수나 계측 비용만으로 설명할 수 없다. Wall time은 모델 로딩·계측·맵 저장을 포함하고 데이터 다운로드·CPU 감사는 제외한다. 두 실행에 upstream CUDA IPC lifetime 경고가 남았으나 종료와 저장·재생 검사는 통과했다. 장기 실행의 자원 정리·VRAM 한계는 미검증이다.

검증 테스트 7개도 통과했다. 특히 출처 누적에 따른 source-disjoint 자격 상실, unknown 출처 거부, 회전·이동·scale이 있는 Sim(3), 시차 없는 관측과 반대 방향 ray 거부를 검사했다. 실제 snapshot을 메모리에서 변조해 미래 생성 sequence·잘못된 pose·누락 ancestry를 넣으면 감사가 실패하는 것도 확인했다. 원본 파일은 수정하지 않았다.

## 출처 분리·시차·도착 지연 결과

### 확장 구간 전체

| 측정 | Raw KF 관측 | Fused KF 관측 |
|---|---:|---:|
| 생성 시점 출처 분리 관측이 ≥1개인 후보 풀 | 3/5 (60%) | 2/5 (40%) |
| 생성 시점 이전 KF와의 source-disjoint pair | 6/10 | 3/10 |
| 생성 시점 source-overlap pair | 4/10 | 7/10 |
| 생성 시점 출처 분리 + ray + 시차 ≥1개 | **1,259/11,520 (10.93%)** | **0/11,520 (0%)** |
| 생성 시점 위 조건을 만족하는 관측 ≥2개 | 0% | 0% |
| 이후 KF 도착 시 재평가까지 허용, 한 번 이상 가용 | **2,487/11,520 (21.59%)** | **1,218/11,520 (10.57%)** |
| 이후 재평가에서도 동시에 ≥2개 관측 가용 | 0% | 0% |
| 최종 pose·전체 관측의 hindsight | 21.36% | 10.21% |

Self 관측은 별도로 각 후보 풀당 1개, 총 5개다. 위 cross-view pair 분모 10에는 self를 포함하지 않았다. Raw와 fused 모두 출처만 보면 이후에 모든 후보 풀이 1개 이상 분리 관측을 확보했지만, 기하 proxy까지 만족한 샘플은 훨씬 적었다. 짧은 2-KF 구간에서는 source-disjoint 및 기하 가용성이 raw/fused 모두 0%였다.

### 확장 구간 KF별 생성 시점

| KF / 원본 frame | 후보 source 원본 frames | Raw 출처 분리 관측 수 | Raw 기하 proxy 가용 비율 | Raw ray 대응의 시차 중앙값 | Fused 출처 분리 관측 수 | Fused 기하 proxy 가용 비율 |
|---|---|---:|---:|---:|---:|---:|
| 0 / 0 | 0 | 0 | 0% | 해당 없음 | 0 | 0% |
| 1 / 82 | 0, 82 | 0 | 0% | 해당 없음 | 0 | 0% |
| 2 / 148 | 82, 148 | 1 | 20.49% | 2.64° | 0 | 0% |
| 3 / 222 | 148, 222 | 2 | 10.55% | 20.08° | 1 | 0% |
| 4 / 298 | 222, 298 | 3 | 23.61% | 13.01° | 2 | 0% |

시차 중앙값은 출처 분리·ray 대응 조건을 만족한 후보–관측 표본들의 값이며 1° 하한 적용 전이다. 관측 수가 2~3개 있어도 동일 후보의 유효 시야가 겹친다는 보장은 없었다.

### Fused contamination

Raw pointmap만 보면 분리된 pair 중 다음 3쌍은 fused pointmap이 후보 source 이미지를 이미 포함했다.

| 후보 KF | 검증 KF | 겹친 원본 이미지 |
|---|---|---|
| KF2 (frame 148) | KF0 | frame 82 |
| KF3 (frame 222) | KF1 | frame 148 |
| KF4 (frame 298) | KF2 | frame 222 |

예를 들어 KF0의 최초 raw source는 frame 0뿐이다. 하지만 frame 82를 처리해 KF1이 생성될 때까지 KF0의 pointmap에는 그 구간 관측들이 융합된다. 따라서 frame 82와 148에서 생성한 KF2 후보를 KF0의 **fused** map으로 검증하면 frame 82를 공유한다. anchor KF ID나 최초 raw source만으로 fused 관측을 분리 판정하면 잘못된 자격을 부여한다.

확장 종료 시 KF0~4의 fused 원본 이미지 수는 각각 42, 35, 39, 40, 32개였고, 대응하는 raw 기여 event 수는 42, 34, 38, 39, 31개였다. 각 원본 이미지 ID는 summary와 event 원자료에 보관했다.

### 관측 도착 지연

가용해진 샘플만을 대상으로 하면 raw의 첫 기하 proxy 가용 지연 중앙값은 0 입력 프레임, p95는 75 입력 프레임이었다. 처음에 가용하지 않다가 이후 회복된 raw 샘플 **1,228개**만 보면 중앙값 74, p95 75, 최대 111 입력 프레임이다. 원본 프레임 기준으로는 각각 148, 150, 222 프레임이다. Fused의 회복 샘플은 1,218개이며 같은 지연 중앙값·p95·최대를 보였다.

Fused 가용 샘플의 첫 도착은 중앙값 2 KF 뒤였다. 계측 실행의 wall-clock 지연 중앙값은 약 13.49초였지만, 파일 재생·모델 실행·저장 비용을 포함하므로 센서 실시간 지연으로 해석하지 않는다. 본 구간 내에서 끝내 가용해지지 않은 샘플은 지연 통계에서 제외되어 있으며, 그 비율은 raw 78.41%, fused 89.43%다. 보류 비용이 작다고 결론낼 수 없다.

![E0b 가용성 측정](../../results/E0b_ancestry_causality/figures/availability.png)

[그림 PDF](../../results/E0b_ancestry_causality/figures/availability.pdf)

## 판단과 다음 단계

1. **E0b 계측·추적 파일럿은 완료했다.** Raw/fused 직접 출처, 실제 융합 재생, 판단 당시 pose 값·revision, 미래 관측 분리 기록이 작동한다.
2. **Raw 관측으로 E1 오류 taxonomy를 시작할 근거는 있다.** 확장 데이터는 RGB 위주로 준비했으므로 필요한 GT depth를 평가 전용으로 별도 확보하고, 원본 고정 후보 풀과 비교해 outlier·중복이지만 유효한 후보·정상·모호 영역을 구분해야 한다. 현재 10.93%는 판별 성능이 아닌 가용성 proxy다.
3. **Fused를 raw 관측처럼 쓰면 안 된다.** 후보–관측마다 당시 ancestry를 조회하고 겹치는 쌍을 제외한다. 이번 결과에서 생성 즉시 fused 기반 gate를 일반적으로 적용할 근거는 없다.
4. **반복 관측 기반 REJECT/KEEP의 충분성은 미확인이다.** 최소 2개 관측이 동시에 가용한 샘플이 없었다. E2 판별력 실험 전에 더 긴/재방문 구간, 추가 장면 또는 관측 풀 확장을 통해 각도 다양성과 반복 관측을 확인해야 한다. 그때도 KF 정책·후보 풀·메모리 조건의 변경을 별도 config로 기록한다.
5. **가시성 검증을 추가해야 한다.** Ray 가용성 다음에 occlusion·signed depth conflict·depth edge·patch 신뢰도를 검사하고, 관측 부재를 오류로 취급하지 않는다. Shared-model bias와 RGB 보조 신호의 효과는 이후 대조 실험 대상이다.

현재 판정은 **“E1 진입 가능, 반복 관측 gate는 추가 가용성 확인 필요”**다. 연구 전체 GO, novel admission 정책의 성공, 8GB 장시간 무제한 실행을 뜻하지 않는다.

## 산출물

- [짧은 구간 요약](../../results/E0b_ancestry_causality/short/audit_summary.json), [확장 구간 요약](../../results/E0b_ancestry_causality/extended/audit_summary.json)
- [추적 가능한 소형 결과 사본](../../configs/e0b_results_summary.json), [소스·분석 코드 hash](../../configs/e0b_code_manifest.json)
- 각 실행의 `run_manifest.json`, `code/`, `audit/events.jsonl`, `audit/snapshots/*.pt`, `pair_audit.jsonl`
- [확장 mapper 로그](../../results/E0b_ancestry_causality/extended/logs/baseline.log), [감사 로그](../../results/E0b_ancestry_causality/extended/logs/audit.log), `device_memory.csv`, `timing.csv`, `wall_seconds.txt`
- [확장 Gaussian PLY](../../results/E0b_ancestry_causality/extended/map/office0_gaussians.ply), [180개 추정 pose](../../results/E0b_ancestry_causality/extended/map/office0_frames.txt), `map/office0_kfgauss.pt`
- `exports/raw_pairs/*.pt`, `exports/candidate_sources/*.json`, [그림 PNG](../../results/E0b_ancestry_causality/figures/availability.png), [그림 PDF](../../results/E0b_ancestry_causality/figures/availability.pdf)

실행 대형 artifact·데이터·외부 소스는 기존 정책대로 Git 추적 제외이며, 보고서·설정·소형 결과·자체 코드·패치는 추적 대상이다. 이번 작업에서 commit은 만들지 않았다.
