# MASt3R-SLAM 기반 3D Gaussian Splatting의 Scale 일관성·기하 오차 분해 및 조건부 보정 연구

## 연구 설계·구현·실험 계획서 v1.1 — A0/A0b 결과에 따른 후속 실험 재설계

- **작성일:** 2026-10-22 (Asia/Seoul)
- **개정일:** 2026-10-26 (Asia/Seoul). A0/A0b의 완료 기록은 보존하고 후속 실험 순서·개입 정의·판정 기준을 개정
- **연구 단계:** A0/A0b 이후 **단위·scale 배분, 참조 자료, 후보 support를 통제하는 진단 단계**. 새 보정 알고리즘의 성능과 독창성은 아직 입증되지 않음
- **직전 연구:** `surface_guided_gaussian_mapping_research_plan_v3.md` → `surface_guided_gaussian_mapping_experiment_summary.md` (E0~E4f, 2026-10-15~22 완료·연구 종료)
- **시스템:** MASt3R/MASt3R-SLAM + Splatt3R-SLAM, 단안 RGB 입력, 학습된 모델의 가중치는 기본적으로 고정
- **현재 논문 제목(가안):** **MASt3R-SLAM 기반 3D Gaussian Splatting에서 Pointmap 및 카메라 자세 오차가 3차원 재구성에 미치는 영향 분석**
- **조건부 후속 제목:** **MASt3R-SLAM 기반 3D Gaussian Splatting의 기하 오차 분석 및 선택적 깊이 보정**
- **영문 제목(가안):** *Decomposing Pointmap and Camera Pose Errors in MASt3R-SLAM-Based 3D Gaussian Splatting Reconstruction*
- **연구 운영 원칙:** Joint Oracle 개선을 RGB-only 보정 성능으로 해석하지 않는다. A1의 표현·요인 분리와 독립 검증 이후에만 보정 경로 하나를 선택한다.

> **진행 상태 (2026-10-26):** N0/N1/N2 **PASS**, [office2 A0 실행 완료·연구 판정 REVISE](experiments/A0_office2_factorial_results.md). 공통-pixel MAE는 A00/A10/A01/A11 각각 0.120683/0.152251/0.318686/0.017892m였다. 단독 치환은 악화되고 joint Oracle은 개선돼 강한 interaction을 확인했다. 다음은 **A1 local-unit/KF-scale/SE(3) 분리와 office3 검증 재현**이며, Depth-only 보정의 GO는 아니다. office4의 예측·Oracle 평가는 계속 보류한다. 아래 일정·체크리스트는 계획이며 개별 완료 여부는 실험 보고서를 따른다.

> **UAV 확장 A0b (2026-10-26):** [HKairport01 희소 LiDAR × Terra 참조 pose 진단 완료](experiments/A0b_HKairport01_factorial_results.md). 기존 240입력·21 KF에서 heldout 40뷰를 평가했다. 보정 공통 후보 6,368개의 A00/A10/A01/A11 공통 깊이 MAE는 21.046/35.400/45.628/1.601m였고, 보조 242,162개 후보에서도 단독 치환 악화·joint 개선을 관측했다. 공식 extrinsic의 직교성 오류, JPG distortion 처리와 Terra/물리 카메라 대응 미확인, prefix gauge와 sparse support 제약을 함께 보고했다. **COMPLETE_CONDITIONAL / REVISE_CALIBRATION_AND_A1**이며, 완전 GT Oracle·독립 새 장면 검증으로 취급하지 않는다. 기존 E4e tracking gate FAIL도 유지한다.

> **A1-U (2026-10-26) PASS:** [두 장면 4,788,198개 후보·32KF의 scale 흡수 검증 완료](experiments/A1_U_scale_reparameterization_results.md). C 배율·KF 단위 재배분의 6개 positive map/scene은 기존 A00과 SHA-256까지 동일했고, 60개 positive 렌더링 비교의 RGB/depth/weight 차이와 coverage 불일치는 0이었다. Nonunit 30KF의 잘못된 mean-only/scale-removal 변환을 검출했다. **다음은 A1-C**이며 깊이 개선·오차 원인 규명은 아직 미검증이다. Q0-HK는 미실행, UAV reference 상태는 미해결로 유지한다.

> **A1-C (2026-10-26) 실행 완료:** [유효 local × rigid pose 4군·CZ·covariance 대조 결과](experiments/A1_C_canonical_factorial_results.md). Office2의 C00/C10/C01/C11 공통 MAE는 **0.120241/0.072655/0.140378/0.018412m**, HKairport wide는 **20.410804/10.518980/17.763107/2.326588m**였다. 같은 A+C 8군 픽셀에서도 local 개입 이득으로 방향이 바뀌어 원 contrast의 scale 배분 의존성을 지지한다. 그러나 office2 rigid pose 단독 악화·잔여 interaction이 남고, HK common은 support gate 실패다. **다음은 A1-G/M → V1**, Q0-HK와 office3/office4는 미실행이며 보정 GO는 보류한다.

> **이번 개정의 실행 순서:** **A1-U(원본 지도 불변 재표현) → A1-C(유효 local geometry × rigid pose 재비교) → A1-G/M(정렬·support 대조) → V1(office3 고정 재현) → A2(잔여 형상·RGB 관측 가능성)**. **Q0-HK(참조 보정 QA)**는 A1-U와 함께 시작하되 UAV 정량 결론의 선행 조건으로 둔다. D/P 알고리즘 개발 및 office4 평가는 보류한다. 이 문서 개정은 후속 실험 실행 완료를 뜻하지 않으며, 실제 실행 전 별도 설정·manifest를 고정한다.

> **문서의 증거 구분**
> - **[기존 실험]**: E0~E4f 및 2026-10-26 A0/A0b 보고서에 기록된 관측 및 수치.
> - **[논문 근거]**: 첨부 MASt3R-SLAM, Splatt3R, 두 GeoGS-SLAM 등의 방법 설명.
> - **[가설/제안]**: 본 문서에서 새로 설계한 통제실험·평가 방법·보정 방식. 실제 효과는 아직 미검증.
> - 이번 계획은 기존 Pruning 프로젝트를 재개하는 지시가 **아니다**. 이전 프로젝트의 저장된 코드·데이터·평가 기반만 재활용한다.

---

# 0. 핵심 결론과 연구 변경 이유

## 0.1 한 문장 연구 문제

> **연속 RGB 영상에서 추정된 3D Gaussian Map의 형상 오류가 (A) 입력 Pointmap의 국소 깊이·형상 오차, (B) Keyframe의 Pose·Scale 배치 오차, (C) Gaussian 표현·렌더링 오류 중 어디서 발생하는지 실험적으로 구분하고, 주된 원인에만 제한적인 보정을 적용해 실제 기하 정확도를 개선할 수 있는가?**

## 0.2 과거 실험으로 이미 확인한 사항

| 관측 | 실험 기록 | 본 연구에서의 함의 |
|---|---|---|
| 검사한 Splatt3R-SLAM raw self-branch 후보에서 `Gaussian mean == source pts3d` | E4e: raw/pre-active 후보 각각 4,472,832개, offset median/p95=0 | 점 중심의 초기 배치 오류가 **새 Gaussian 생성 단계에서 독립적으로 추가되었다**고 가정하지 않음. Pointmap/월드 변환을 먼저 분석 |
| GT-front 오차 후보가 존재하지만 고립 floater의 확정 라벨은 아님 | E1: active 705,772개 중 반복 GT-front proxy 12.81% | 개별 중심 outlier 수만으로 지도 전체의 잘못된 표면을 대표할 수 없음 |
| 틀린 Pointmap도 일관된 국소 평면을 형성함 | E4b: 잘못된 평면이 미제거 bad 31,412개를 지지; 30,777개에서 주변 점의 대다수도 같은 방향 오류 | 같은 모델에서 나온 국소 평면에 projection하는 방법은 공유 편향을 교정하지 못할 수 있음 |
| 기존 plane admission의 추가 성능 이득 미입증 | E4 office1 75% 예산: plane TSDF Chamfer 0.108354m, B6 0.105947m | 후보 제거/보류/중복 판정 연구는 종료. 강한 Depth 대조군보다 나은지 반드시 확인 |
| UAV 실험에서 국소 표면 단차·왜곡을 관찰 | E4e HKairport01: 240입력, 21KF, tracking gate 미통과 | 시각적 현상만으로 원인을 확정할 수 없음. 우선 GT 보유 장면에서 분해 |
| 실제 UAV에서 local/placement 단독 치환 악화·joint 치환 개선 | A0b HKairport01: sparse 공통 후보 6,368개 및 보조 242,162개, heldout 40뷰 | local-unit/KF-scale과 rigid pose 분리 필요. 보정·gauge·support에 조건부이며 Depth-only 원인으로 귀속하지 않음 |
| KITTI에서 Depth 오류와 전역 배치 문제가 함께 의심됨 | E4f: 전역 Scale 후에도 거리별 Depth 잔차, OXTS 배치에서 일부 NN 거리 개선 | Pose 및 Scale을 **같이 바꾼 Oracle**로는 어느 요소가 원인인지 인과 분해 불가 |
| 기존 NVS 실험은 full appearance optimization의 대표 성능이 아님 | E0/E4: refinement=0, degree-0 appearance 설정 | 저 PSNR을 곧바로 Depth 오류로 단정하지 않고 refiner-on/off 별도 통제 |

**철회할 가정:** 'Gaussian 생성 자체가 무작위로 엉뚱한 위치를 만드는 것이 주된 문제'라는 포괄적 설명. 검사된 구현 경로에 한해서만 중심과 pointmap의 일치를 확인했으며, **Gaussian의 covariance·opacity·appearance 오차, pose/scale 오차, 모든 시퀀스의 동작까지 배제한 것은 아님**.

## 0.3 기존 프로젝트와의 경계

- `KEEP / REJECT / DEFER` 기반 candidate admission, repeated-plane-support pruning, surface-aware dedup은 **종료된 주제**이다.
- 신규 연구에서는 **같은 Gaussian ID와 속성을 유지한 채** Pointmap 또는 월드 배치의 변화가 지도 품질에 미치는 영향을 우선 검증한다.
- 마스크 기반 하늘/동적 객체 제거, 새로운 Gaussian의 재학습, mesh completion, 대규모 SLAM backend 재작성은 기본 필수 범위에서 제외한다.

## 0.4 A0/A0b가 바꾼 후속 실험의 전제

| 완료된 비교 | A00 / A10 / A01 / A11 공통 깊이 MAE (m) | 확인한 사항 / 남은 문제 |
|---|---|---|
| office2 A0 strict, 1,200,827후보·400뷰 | 0.120683 / 0.152251 / 0.318686 / 0.017892 | 단독 교체 악화·joint 개선. GT pose arm에 KF scale 제거까지 포함됨 |
| HKairport01 A0b 보정 공통, 6,368후보·40뷰 | 21.046052 / 35.399786 / 45.627794 / 1.601097 | 공통 target은 LiDAR-valid의 평균 4.104%, native 후보의 0.1964%만 검사 |
| HKairport01 A0b 추가 보조, 242,162후보·40뷰 | 21.790515 / 41.919585 / 31.838613 / 2.782529 | 더 넓은 support에서도 같은 방향. 결과 일부 확인 후 등록한 보조 비교이며 독립 재현이 아님 |
| HKairport01 A0b full-map mixed, 3,242,219후보 | 21.842800 / 23.441040 / 13.286802 / 13.234331 | 이 범위에서는 placement 교체가 개선됨. Local 교체는 7,609개(0.2347%)뿐이므로 완전 Oracle과 비교 불가 |

**현재 설명해야 할 현상은 “Depth 단독 오류가 크다”가 아니라 “왜 단독 개입은 악화되고 joint 개입만 개선되는가”다.** 다음 가설을 경쟁시킨다.

1. **표현·단위 배분:** raw local scale과 KF Sim(3) scale이 맞물려 있다. Raw local만 metric GT로 바꾸거나 KF scale만 제거하면 원래 정합을 깨뜨릴 수 있다.
2. **실제 기하·자세 결합 오류:** 단위를 일관되게 바꾼 뒤에도 local 형상과 rigid pose 사이에 결합된 잔차가 남을 수 있다.
3. **평가·표현 효과:** 거의 직선인 prefix의 gauge 불확실성, sparse 후보 선택, world covariance 변화, 가림·expected-depth renderer가 factorial contrast에 영향을 줄 수 있다.

이들은 **미검증 설명 후보**다. 강한 interaction만으로 실제 오차 상쇄, 특정 KF scale 오류 또는 joint optimizer의 필요성을 확정하지 않는다. 다음 순서로 가설을 제거한다.

| 변경 전 방향 | 이번 개정 |
|---|---|
| A0에서 local-vs-pose 우세를 골라 A1 또는 A2로 분기 | A1-U/C를 필수로 수행한 뒤 분기. 원 A01을 pure pose Oracle로 부르지 않음 |
| Local 공통 단위 C를 고정하는 것으로 분리 완료 | Native placement scale을 local 점·covariance에 함께 흡수하는 **지도 불변 재표현** 추가 |
| A11 잔차가 크면 representation 연구로 이동 | 먼저 reference-only 재투영, support·gauge를 확인하고 R-Q 최소 통제로 원인을 좁힘 |
| 모든 민감도 arm의 거대한 픽셀 교집합 | 동일 후보의 작은 비교군별 공통 분모와 관측률을 보고. 교집합 붕괴 시 결론 보류 |
| 개발 장면의 Oracle 개선으로 보정 구현 착수 | office3의 사전 고정 재현과 RGB-only 관측 가능성을 확인한 뒤 한 경로만 선택 |

## 0.5 다음 실행의 최소 범위와 명명 규칙

**A1-U와 A1-C는 완료했고 다음 실험은 A1-G/M**이다. 기존 prefix의 위치/방향 기반 gauge와 source-only/target-only sparse support를 대조해 C의 해석 범위를 확인한 뒤 office3 V1으로 재현한다. Q0-HK가 해결되지 않더라도 실내 진단은 계속할 수 있고, HKairport01 결과는 조건부로만 유지한다. C에서 local 참조 개입이 개선됐다는 이유만으로 A2/D나 joint optimizer로 건너뛰지 않는다.

이 문서의 **A1/A2는 연구 실험 시리즈**다. A0b 실행 당시의 `a0b_amendment_A1.json`/`a0b_amendment_A2.json`은 A0b 내부 변경 이력이며, 후속 A1/A2 완료를 뜻하지 않는다. 기존 A0/A0b 파일·판정·source support·post-hoc 표시는 바꾸지 않는다.

---

# 1. 연구 목표, 연구 질문, 가설

## 1.1 필수 목표(MVP)

1. **오류 전달 경로 계측:** raw pair pointmap → local frame → keyframe/global Sim(3) → Gaussian center → rendered depth/3D surface의 변환 및 provenance 확정.
2. **A0/A0b 후속 진단:** 기존 factorial 결과를 보존하고, A1-U/C에서 동일 원본 지도의 단위 재표현과 rigid pose/유효 local geometry의 교체를 구분.
3. **Scale 분리:** GT에서 얻은 보정과 native 표현의 재분배를 구분. A1-F의 scale 개입은 별도 요인으로 다루고 gauge에 조건부인 효과라고 표시.
4. **기하 중심 평가:** GT depth와 3D surface, coverage, 거리별/표면별 오류. 렌더링 지표는 별도로 보고.
5. **Go/No-Go:** 참조·support gate, A1-C 및 V1, A2 결과에 따라 Depth 보정, Pose/Scale 보정 또는 분석 연구 중 하나를 선택.
6. **재현성:** 동일 후보 풀·동일 공통 마스크·같은 test scenes·run manifest를 보존.

## 1.2 진단·독립 재현·관측 가능성 gate 이후에만 추가하는 목표

- **Depth 중심 결과:** RGB-only 정보를 활용하는 *저차원/국소 선택적 Depth 보정*의 성능을 기존 단순 scale·photometric reprojection 방식과 비교.
- **Pose 중심 결과:** full SLAM 개편 대신, pose/scale 재배치 진단과 제한된 외부-학습 없는 정렬 보정을 작은 실험으로 검증.
- **복합 결과:** Pointmap·Pose의 상호작용 분석까지를 연구 기여로 선택할 수 있으나, 두 분야를 동시에 본격 개선하는 것은 필수 목표로 만들지 않음.

## 1.3 연구 질문

| ID | 연구 질문 | 검증 실험 |
|---|---|---|
| **RQ1** | A0/A0b의 단독 악화·joint 개선 중 얼마가 local-unit/KF-scale 배분에 의존하는가? | A1-U/C, 필요 시 A1-F |
| **RQ2** | 단위를 재표현한 뒤에도 유효 local geometry와 **rigid 회전·이동**의 결합 효과가 남는가? | A1-C/RT, A1-G/M, V1 |
| **RQ3** | 남은 local 오차는 단일/KF scale인가, 공간적 형상 변형인가? RGB 관측으로 구별 가능한가? | A2 spatial cross-fit 및 RGB 관측 가능성 |
| **RQ4** | 선택한 RGB-only 보정이 강한 scale/photo/backend 대조군보다 새 장면의 기하·correct coverage를 개선하는가? | 조건부 D/P, F0 |
| **RQ5** | Reference·support·covariance·renderer 및 8GB 자원이 해석을 얼마나 제한하는가? | Q0-HK, A1-G/M, R-Q, 비용 기록 |

## 1.4 관측과 후속 가설의 구분

- **기존 H1의 경과:** “단독 GT 치환도 개선한다”는 예측은 현재 strict A0/A0b에서는 지지되지 않았다. 이를 성공 가설처럼 유지하지 않는다. 다른 표현·후보 집합에서의 효과까지 부정한 것은 아니다.
- **기존 H2의 경과:** 두 개발 장면의 지정된 지표에서 interaction을 관측했다. 그 물리적 원인과 새 장면 재현성은 미확정이다.
- **H-U:** placement scale을 local geometry에 흡수하는 가역 재표현 후, 단독 치환 악화가 줄어들 수 있다. 줄어들면 기존 contrast에 단위 배분이 관여했다는 증거이며 raw model이 정확하다는 증명은 아니다.
- **H-C:** 재표현 후에도 남는 coupling은 gauge/support/world covariance 통제와 office3 재현을 통과할 수 있다. 그렇지 않으면 coupling 일반화 주장을 보류한다.
- **H-S:** 유효 local depth 잔차의 상당 부분이 KF별 scalar로 설명될 수 있다. 그렇다면 공간적 depth field보다 단순한 scale 일관성 진단·보정을 우선한다.
- **H-D(조건부):** scalar 이후에도 남고 RGB로 관측 가능한 공간적 잔차에 한해서 선택적 Depth 보정이 단순 대조군을 넘을 수 있다. 아직 알고리즘 성능 가설이며 검증되지 않았다.

---

# 2. 선행연구와 독창성 경계

| 연구 | 기존 기여 | 본 연구에서 하지 말아야 할 주장 |
|---|---|---|
| DUSt3R / MASt3R | 두 이미지의 pointmap, confidence, matching descriptor; pose/depth 추정 기반 | Pointmap 자체를 출력한다는 것이 새로움이 아님 |
| MASt3R-SLAM | MASt3R pointmap과 matching, 카메라 추적 및 전역 정렬 | Sim(3) pose update 일반 원리 자체를 새로움으로 주장하지 않음 |
| Splatt3R | MASt3R 기반 per-pixel Gaussian 속성 예측; 원칙적으로 Gaussian 중심과 pointmap이 연계됨 | pointmap을 Gaussian 중심에 쓰는 것을 새로움으로 주장하지 않음 |
| GeoGS-SLAM, Geometry-Only (2026) | depth/normal 및 multi-view photo loss, local-plane PCA, coherent Sim(3) map update | local plane, depth smoothness, multi-view consistency 자체를 신기법이라고 표현 금지 |
| GeoGS-SLAM, Geometric Priors (2026) | VGGT priors, map/pose joint optimization, DoG sampling, photometric+depth objectives | 예측 depth와 RGB를 결합한다는 일반적인 아이디어를 독창성으로 주장하지 않음 |
| 기타 depth/pose refinement 연구 | BA, photometric consistency, smoothness, scale alignment 등 오래된 기법 | 단일 scale 또는 재투영 기반 depth refinement만으로 독창성 주장 금지 |

**잠정 차별화(검증 전):** **동일한 MASt3R-SLAM→Splatt3R 후보 경로에서 Pointmap·Pose·Gaussian 표현의 error source를 분리하는 재현 가능한 평가 계약**, 그 결과로 드러나는 실패 조건, 그리고 *특정 오류 유형에서만* 유효한 제한적 보정의 추가 효과.

**문헌 검토 게이트:** 최종 보정 방법을 확정하기 전, MASt3R/DUSt3R/VGGT 기반 depth refinement, SLAM scale drift, photometric/geometric BA, Gaussian pose/depth joint refinement와 직접 중복되는 연구를 추가 검색. 전체 시스템과 공정 비교할 수 없으면 기법별 비교군으로 구분.

---

# 3. 고정 파이프라인·데이터 계약

## 3.1 검증해야 할 좌표계

기본 표기(코드의 실제 규약과 일치하는지 테스트 후 확정):

> **N1 확인:** 개발 self-branch의 좌표계·xyzw·단위·픽셀 및 native active/PLY 연결은 [N1 계약서](experiments/N1_coordinate_contract.md)에서 검증했다. Raw Pointmap의 ray는 GT pinhole ray와 정확히 일치하지 않으므로, 아래 GT backprojection은 깊이와 ray를 함께 바꾸는 **local geometry** 개입으로 해석한다.

- $I_a, I_b$: Splatt3R/MASt3R 입력 이미지 pair
- $X_{v\leftarrow a}(u)$: 이미지 v의 픽셀 u에 대응하되 기준 이미지 a 좌표계로 표현한 3D pointmap
- $K_v$: 카메라 v의 intrinsics, $r_v(u) = K_v^{-1}[u_x,u_y,1]^T$: 비정규화 카메라 ray
- $D_v(u)$: **카메라 Z-depth**. LiDAR range(유클리드 거리)와 정의가 다를 수 있으므로 항상 기록
- $T_{w\leftarrow a}=(s_a,R_a,t_a)$: anchor a에서 공통 world로 변환하는 Sim(3)
- $G_i=(\mu_i,\Sigma_i,\alpha_i,c_i,\ldots)$: Gaussian의 position, covariance, opacity, color 등
- 원본에서 관찰된 raw self branch에서는 $\mu_{i,a}=X_{a\leftarrow a}(u_i)$였으나 **각 branch와 refiner 경로에서 다시 검증**해야 함.

기본 변환:

$$
\mu_{i,w}=s_a R_a\mu_{i,a}+t_a, \qquad
\Sigma_{i,w}=s_a^2 R_a\Sigma_{i,a}R_a^T.
$$

GT Depth 기반 로컬 점은 v 카메라 좌표계에서:

$$
X^{\mathrm{GT}}_{v\leftarrow v}(u) = D_v^{\mathrm{GT}}(u) K_v^{-1}[u_x,u_y,1]^T.
$$

**v가 anchor a와 다른 경우**, GT 상대 Pose를 이용해 $X^{\mathrm{GT}}_{v\leftarrow a}$로 변환한 후 후보의 원래 anchor 좌표계에 저장한다. `GT pose arm`으로 실험하기 전에 이 좌표 변환만으로 올바른 pointmap 대체가 성립해야 한다. 두 개를 동시에 GT로 교체해 버리는 누설을 금지한다.

### 필수 구현 검증

1. pose 저장 방향(camera-to-world vs world-to-camera), quaternion 순서, 단안 scale 단위 확인.
2. pair 1/2의 pointmap이 **어느 카메라 좌표계에 있는지**, Gaussian 생성 branch별 mean offset 유무 확인.
3. $K$의 왜곡 모델, undistortion, 렌더 해상도와 이미지 resize/crop 변환 확인.
4. `depth_z` vs `range`의 차이를 통합 depth evaluator에서 명시.
5. 변환 왕복 test: mean, covariance, projection residual; GT pose를 두 번 적용하는 버그 탐지.
6. raw 후보와 `active`/PLY 후보의 ID 연결, pruning/native filter, refiner 여부 확인.
7. tracklet/sky/occlusion mask 및 평가 GT 가용성 분리.

## 3.2 필수 logging 데이터 모델

| 항목 | 기록 |
|---|---|
| Scene/Run | scene ID, file hash, upstream commit, modified commit, checkpoint hash, seed, GPU/driver/CUDA/PyTorch |
| Image | frame timestamp, pair IDs, source branch, resolution, crop, K, distortion model |
| Candidate | `candidate_id`, `pixel_uv`, `anchor_kf_id`, source pair IDs, raw xyz, offset, confidence |
| Map | local/world mean, scale, quaternion/covariance, opacity, SH/color, native active mask, refiner state |
| Pose | estimated local/global Sim(3), GT pose, source convention, alignment Sim(3), pose revision |
| GT | raw GT units/source, valid depth masks, GT metric scale, mesh/LiDAR coverage, dynamic masks |
| Eval | registered candidate set hash, common valid mask hash, gaussian attributes hash, renderer options |

> **실행 비용 통제:** 처음에는 전체 수백만 후보 대신 **동일 후보 ID의 고정된 stratified subset**으로 A0 구현을 검증하고, pipeline이 정확한 것으로 확인된 뒤 scene 전체 결과를 산출한다. Subset 선택 기준은 GT outlier 여부가 아니라 픽셀/거리/깊이 strata와 고정 seed로 정의한다.

---

# 4. 완료된 출발 실험 A0/A0b — 원 계약과 해석 한계 보존

이 절은 완료 실험의 원 설계·수식이다. 실내의 dense GT 조건과 달리 A0b는 희소 LiDAR·Terra reference 및 미확인 static/보정 조건 때문에 **conditional diagnostic**으로 실행했다. 미충족 조건을 충족한 것처럼 소급 기록하지 않는다. 후속 비교군의 새 정의는 §5를 따른다.

## 4.1 목표

**동일 장면의 동일 관측 픽셀과 Gaussian 후보를 유지한 상태에서** local pointmap과 world placement를 각각 치환했을 때 독립 GT geometry가 얼마나 좋아지는지 측정한다. GT는 실험 안에서만 허용되는 Oracle이므로, 이 결과는 배포 가능한 RGB-only 알고리즘 성능이 아니다.

## 4.2 공통 유효영역·동일 후보 계약

- 각 source 픽셀에 GT depth가 존재하고, static/occlusion·FOV 조건이 일치하는 공통 집합 $\Omega_{\mathrm{common}}$을 먼저 고정한다.
- 네 실험군에서 **동일한 source pair, candidate ID, 픽셀 위치, candidate 수, active mask, 타임스탬프**를 사용한다.
- Gaussian의 `opacity, color/SH, rotation, covariance(local)`는 **기본 A0**에서 고정. 중심·월드 변환만 바꾼다.
- GT depth가 없는 후보를 한 군에서만 제거하지 않는다. ① 공통 후보만을 대상으로 하는 strict geometry analysis와 ② 미보유 후보를 변경하지 않는 full-map sensitivity를 분리한다.
- 후보 selection이나 native filter를 재실행하여 군마다 후보 수가 바뀌는 경우 별도 'end-to-end' 실험으로 간주하고 **A0 핵심 표에 혼합 금지**.
- 네 군 모두 **한 번 정해진 공통 metric gauge 및 정렬 규칙**을 적용한다. 군별로 매 프레임 GT에 맞춰 최적 정렬하는 것을 금지한다.
- 색상·opacity·covariance를 고정한 채 중심만 이동하면 렌더링이 오히려 악화될 수 있다. 이때 원인분해의 주 지표는 **기하 정확도**이고, renderer/appearance는 별도 효과로 해석한다.

## 4.3 2×2 비교군

| Arm | Local geometry (L) | Placement (P) | 질문 | 해석 |
|---|---|---|---|---|
| **A00** | 추정 Pointmap | 추정 Pose/Scale | 현재 원본의 기하 오차 | baseline |
| **A10** | **GT Depth를 동일 pixel·anchor에 backproject** | 추정 Pose/Scale | local depth 오류를 제거하면? | local geometry oracle |
| **A01** | 추정 Pointmap | **GT Pose(공통 gauge 정렬)** | world placement 오류를 제거하면? | placement oracle |
| **A11** | **GT local geometry** | **GT Pose** | 두 오류를 제거해도 남는 오차는? | oracle upper reference (완벽 재구성 보장 아님) |

**매우 중요한 주의:** source branch가 다른 카메라 b의 픽셀이라면 `GT depth_b → camera-b 좌표 → anchor-a 좌표`의 상대 Pose가 필요하다. 이 변환에서 GT 상대 Pose를 사용하면 A10에도 일부 pose 정보가 들어갈 수 있다. 그러므로 다음처럼 설계를 이원화한다.

1. **Primary strict A0:** raw *self-branch* 또는 **anchor-local native depth**로 대체 가능한 후보만 사용하여 local geometry와 global pose의 독립적인 개입을 보장한다.
2. **Secondary pair A0:** 다른 source view 후보까지 포함한다. `predicted relative pair transform`/`GT relative pair transform`을 분리한 보조 요인 또는 oracle로 명시하고, primary strict A0와 같은 인과 효과라고 주장하지 않는다.

**N1에서 확인한 해석 조건:** GT depth를 GT ray로 backproject하는 A10은 순수 Z-depth 교체가 아니다. Local oracle 효과를 Depth 보정으로 이어서 해석하려면, predicted ray를 유지하는 depth-only 보조 실험 또는 ray 오차의 별도 분석이 필요하다.

## 4.4 단안 Scale 정렬의 주의점

- MASt3R-SLAM의 native 단위는 meter가 아닐 수 있다. per-scene **단일 고정 Sim(3) alignment**를 사용하여 GT reference 좌표계와 맞춘다.
- Scale은 **GT trajectory의 정해진 calibration prefix** 또는 별도 validation 구간에서 한 번만 고정하고, test 구간은 같은 정렬값을 사용한다. 평가 중 각 keyframe에 별도의 최적 scale을 허용하지 않는다.
- 기하 오류 진단 시 두 보고를 병행한다: (i) metric-aligned depth error, (ii) *alignment-insensitive* 상대 깊이/형상(예: depth ratio/locally centered residual).
- A01에서 GT pose를 넣는다는 것이 frame-wise independently aligned depth를 의미하지 않는다.
- 완료된 A0/A0b의 A01은 estimated KF Sim(3)를 GT/reference SE(3)로 바꾸므로 **회전·이동과 KF scale 배분을 함께 바꾼다**. 원 결과를 pure SE(3) 오류로 재명명하지 않는다. 이 한계를 A1-C의 지도 불변 scale 흡수와 A1-F의 별도 scale 요인으로 조사한다.

### 공통 단위의 명시적 정의(구현 필수)

`GT Depth`의 단위가 미터이고 MASt3R raw local pointmap의 단위가 임의일 수 있으므로, **Oracle 값을 raw local 텐서에 숫자 그대로 대입하지 않는다.** 다음은 코딩 시 검증할 *개념적 공통화 예*이며 실제 pose composition과 저장 규약에 맞춰 부호·방향을 확인한다.

- 한 번 결정한 로컬 단위 환산 계수 $C > 0$(m / raw-local-unit)을 모든 KF에 고정한다. $\hat{X}_k^m = C\hat{X}_k^{\mathrm{raw}}$.
- 전역 게이지 정렬을 포함한 추정 Sim(3)를 $\hat{T}_k^m(X) = \hat{s}_k\hat{R}_k X + \hat{t}_k$로 다시 정의한다. 기존 raw 좌표를 world-metric으로 옮긴 결과가 보존되도록 $\hat{s}_k$를 변환하되, 원래 KF별 상대 scale 변화는 남겨 둔다.
- GT local geometry는 같은 카메라 축에서 $X_k^{\mathrm{GT},m} = D_k^{\mathrm{GT}}(u) K_k^{-1}\tilde{u}$로 만든다.
- $\mathrm{A00}: \hat{T}_k^m(\hat{X}_k^m)$, $\mathrm{A10}: \hat{T}_k^m(X_k^{\mathrm{GT},m})$, $\mathrm{A01}: T_k^{\mathrm{GT},\mathrm{SE3}}(\hat{X}_k^m)$, $\mathrm{A11}: T_k^{\mathrm{GT},\mathrm{SE3}}(X_k^{\mathrm{GT},m})$로 계산한다.
- GT Pose가 metric SE(3)이므로 **GT pose arm의 scale은 1**이며, 추정 pose arm의 $\hat{s}_k$ 변동은 placement factor에 포함한다. 최초 KF/보정용 prefix에서 원점을 고정하고 모든 test frame에는 동일한 $C$와 전역 gauge를 적용한다.

이 방식 역시 *게이지 정의에 조건부인 요인 분해*다. $C$를 변경하거나 GT/추정 내부 카메라 모델이 다르면 local-vs-placement contrast가 달라질 수 있으므로, **게이지 민감도 분석(개발 세트)**을 수행하고 `GT가 존재하므로 수학적으로 유일한 오차 기여를 얻었다`고 주장하지 않는다. 실제 자료에서 $\hat{s}_k$가 이미 local scale 보정을 포함하는 방식이 다르다면 위 공통화 식을 먼저 재정의하고 단위시험으로 검사한다.

## 4.5 수학적 평가: 2×2 factorial과 interaction

공통 GT geometry error metric을 $E_{00}, E_{10}, E_{01}, E_{11}$라 정의한다(낮을수록 좋음).

$$
\Delta_{L\mid P=\mathrm{est}}=E_{00}-E_{10},\quad
\Delta_{P\mid L=\mathrm{est}}=E_{00}-E_{01}.
$$

두 효과가 단순히 더해지는지 보려면 interaction을 계산한다.

$$
\mathcal I = E_{11}-E_{10}-E_{01}+E_{00}.
$$

- $\Delta_L$ 또는 $\Delta_P$가 양수여도 다른 요인 조건에서 효과가 바뀔 수 있으므로 **순수하고 보편적인 기여율(%)**로 해석하지 않는다.
- 평가 지표마다 같은 contrast를 계산하되, 각 장면을 독립 단위로 취급하고 frame/point를 독립 표본으로 과장하지 않는다.
- A11의 residual은 occupancy·Gaussian extent/opacity·sensor GT mask·occlusion·TSDF sampling 및 rendering limits 때문에 0일 필요가 없다.
- 추가로 $E_{00} - E_{11}$은 두 Oracle을 함께 사용했을 때의 개선 범위이지, local과 pose 개선을 정확히 합친 값은 아니다.

## 4.6 A0 세부 절차

1. 실행 manifest 고정: Scene, frames, weights, version, camera model, pose revision, native active mask.
2. **GT 픽셀 유효 집합**과 class별/거리별 strata, sky/dynamic/occlusion mask 확정.
3. self-branch local points의 camera projection을 검증하고, raw mean/pointmap equality를 새로운 장면에서 재현.
4. frame-level Sim(3) transform을 검증하고 **단일 metric gauge**로 4개의 arm을 생성.
5. 각 arm을 **후보 ID·Gaussian 속성 고정**하여 저장. 원본 map 전체를 덮어쓰지 않음.
6. 공통 mask에 대해 point-level residual, rendered depth, surface sampling, completeness/coverage를 계산.
7. Pose ATE/RPE와 per-Keyframe scale drift는 원인 추적 보조로 평가.
8. **공통 셋**의 4-arm 대조와 GT 미보유 영역을 유지한 full-map sensitivity를 구분해 저장.
9. Scene별 effect/interaction의 분산과 대표 실패 사례를 시각화.
10. A0 보고서를 봉인한 다음 **Go/Revise/No-Go 결정**을 내린다.

## 4.7 A0 필수 출력

- `A0_candidate_manifest.parquet` 또는 csv: source ID, pixel, depth GT valid, class, branch, anchor.
- `A0_alignment_manifest.json`: gauge estimate, metric scale, pose direction, calibration prefix, mask definition.
- `A0_four_arms.csv`: metric per scene/per arm; rendered-depth errors; sample Chamfer/accuracy/completion.
- `A0_effects.csv`: $\Delta_L$, $\Delta_P$, interaction, paired confidence intervals 또는 scene 분포.
- 단일 프레임/작은 구간 3D viewer: A00 vs A10 vs A01 vs A11, world/frame axes 함께 표시.
- GT geometry 기반 거리 구간·평면·깊이 경계·유리/하늘/동적 영역별 failure table.
- 이미지 비교: RGB test view, rendered depth/validity, local depth residual, placement residual.

---

# 5. 필수 후속 A1 — 지도를 보존하며 Local Geometry·KF Scale·Rigid Pose 재분리

**현재 상태: A1-U PASS, A1-C 실행 완료. A1-G/M·F/RT·Q0-HK·V1은 미실행.** A0/A0b의 연구 판정 REVISE에 직접 대응한다. 새 모델 학습과 backend 재작성 없이 저장된 raw self-branch·최종 pose·native active map을 재사용한다. 아래의 정렬·개입은 우선 **offline diagnostic**이며 온라인 추론 성능으로 보고하지 않는다.

## 5.1 Q0-HK — UAV 참조 자료 gate

Q0-HK는 A1-U와 함께 시작할 수 있는 **참조 QA**이며, office2/office3 진단을 막는 전역 gate가 아니다.

| 점검 | 고정할 증거 / 비교 | 통과하지 못했을 때 |
|---|---|---|
| HKairport extrinsic R | 공개 원본, 출처·버전, $\lVert RR^T-I\rVert_{\max}\leq0.001$, det/축·방향 | 공개값의 직교성 실패를 기록. SVD projection을 저자 확인 GT로 승격하지 않음 |
| JPG와 lens 모델 | raw/undistorted 여부, K/distortion/crop, Terra P3x3와 물리 K의 역할 | 두 가정을 별도 조건으로 유지. A11 MAE가 작은 쪽을 정답 보정으로 선택하지 않음 |
| LiDAR/reference pose 일관성 | 고정 prefix의 image epipolar·시간 차이·reference-only cross-view 잔차와 표본 수 | epipolar 통과만으로 metric pose나 extrinsic 정확도를 보증하지 않음 |
| Reference residual floor | heldout을 튜닝에 쓰지 않고 prefix에서 거리별 재투영·관측/가림 잔차 추정 | 이를 sensor noise 정밀도로 부르지 않음. 근거가 없으면 UAV absolute GO 불가 |

**산출물:** `Q0_HK_reference_contract.md/json`, calibration provenance, raw/rectified pixel 왕복·overlay, reference-only residual과 unknown 목록. 기존 source를 읽어 확인하는 작업부터 진행한다. 외부 저자 문의가 필요하면 문의안을 준비할 수 있으나, 이 계획 자체가 메시지 발송 지시는 아니다.

Q0-HK에서 해소하지 못한 항목은 **REFERENCE_UNRESOLVED**로 유지한다. HKairport01에서는 조건부 민감도·실패 진단까지 수행하고, 확정적인 물리 원인 귀속과 UAV 알고리즘 효능 주장은 보류한다. 결과가 좋아도 QA gate를 소급 완화하지 않는다.

## 5.2 A1-U — 원본 world map을 보존하는 scale 흡수

**실행 완료·PASS:** [A1-U 결과](experiments/A1_U_scale_reparameterization_results.md), [등록 설정](../configs/a1_unit_reparameterization.json), [요약](../configs/a1_u_results_summary.json). 아래는 실제 검증한 변환과 계약이며 A1-C의 baseline 불변성 전제다.

§4.4의 metric local point를 $x_{ki}=C\hat X^{\mathrm{raw}}_{ki}$, metric placement를 $(a_k,R_k,t_k)$, local covariance를 $\Sigma^x_{ki}$라 둔다. $a_k$는 **추정 placement의 남아 있는 scale**이며 GT 오류로 단정하지 않는다.

$$
\mu_{ki}=R_k(a_k x_{ki})+t_k,\qquad
\Sigma^w_{ki}=R_k(a_k^2\Sigma^x_{ki})R_k^T.
$$

다음처럼 native scale을 local geometry와 covariance에 **함께 흡수**한다.

$$
y_{ki}=a_k x_{ki},\qquad
\Sigma^y_{ki}=a_k^2\Sigma^x_{ki},\qquad
Q_k=(1,R_k,t_k).
$$

그 결과 $Q_k(y_{ki})=\mu_{ki}$이고 world covariance도 동일하다. 모든 KF에 $a_k=1$을 강제로 넣어 원본 지도를 바꾸는 **보정**과 구별한다. $y$는 native KF scale을 포함한 **유효 local geometry**이며 raw pointmap만의 오차가 아니다.

**필수 불변성:** candidate ID·active mask·color/SH·opacity, world center·world covariance, 같은 viewpoint의 expected depth/weight/RGB가 수치 허용 범위 안에서 보존되어야 한다. Raw Gaussian scale을 재표현할 때는 표준편차에 $a_k$, covariance에 $a_k^2$를 곱한다. 원래 covariance를 그대로 둔 채 mean만 scale 흡수하는 구현은 실패다.

**단위 변화 대조:** 임의의 양수 $q_k$에 대해 $x\mapsto q_kx$, $a_k\mapsto a_k/q_k$, $\Sigma^x\mapsto q_k^2\Sigma^x$를 적용해도 $y$, $\Sigma^y$, world map은 같아야 한다. 전역 C multiplier `0.8/1/1.25`와 seed 0의 KF별 가역 배율을 포함한다. 테스트용 배율은 GT에 fitting하지 않는다.

**통과 기준:** 먼저 float64 algebra 왕복을 `rtol=1e-9`로 확인한다. 같은 float32 renderer에서 compact mean/covariance 및 depth·RGB 오차 한도를 구현 smoke 이전에 등록하고, UAV 좌표 크기에 맞춘 절대·상대 오차를 함께 기록한다. 기존 native TF32 export 재생 parity와 float64 기준 비교는 별도다. 눈에 보이는 차이가 있으면 후속 arm을 평가하지 않고 구현을 수정한다.

**출력:** `A1_U_contract.json`, per-KF `a_k/C/local_unit` 표, invariance log, 동일 viewpoint 이미지 차이. Office2와 HKairport01 두 기존 map에서 검증하며 새 네트워크 추론은 하지 않는다.

## 5.3 A1-C — 유효 Local Geometry × Rigid Pose 2×2

**실행 완료:** [결과](experiments/A1_C_canonical_factorial_results.md), [등록 설정](../configs/a1_c_canonical_factorial.json), [요약](../configs/a1_c_results_summary.json). 3개 scope에서 6개 C/CZ map씩, office2 fixed-world covariance 4 map을 포함해 총 22 map을 평가했다. C00/A00는 map 및 전 480뷰 depth/coverage가 동일했다. 원 A 지표·분모를 전체 뷰의 cache에서 재현하고 60 map-view CUDA replay를 추가했다. 아래는 실제 수행한 개입 계약이다.

A1-U 통과 후의 **주 비교군**이다. $Y_k^{\mathrm{ref}}$는 같은 source camera에서 metric depth와 ray로 만든 참조 local point, $Q_k^{\mathrm{ref}}$는 metric SE(3) 참조다.

| Arm | Local 중심 | Rigid placement | 질문 |
|---|---|---|---|
| **C00** | $y=a_kx$ | 추정 $(R_k,t_k)$ | 원본 map과 같다는 것을 A1-U로 확인 |
| **C10** | $Y^{\mathrm{ref}}$ | 추정 $(R_k,t_k)$ | KF scale을 이미 포함한 유효 local 기하를 교체하면? |
| **C01** | $y=a_kx$ | 참조 $(R_k^{\mathrm{ref}},t_k^{\mathrm{ref}})$ | Local scale을 보존하고 **회전·이동만** 교체하면? |
| **C11** | $Y^{\mathrm{ref}}$ | 참조 $(R_k^{\mathrm{ref}},t_k^{\mathrm{ref}})$ | 같은 representation/support에서의 joint 참조 |

모든 C-arm의 local covariance는 **동일한 $\Sigma^y$**로 고정하고 world covariance는 각 rigid rotation으로 옮긴다. C00은 원본을 보존하지만, C-arm의 참조 covariance는 기존 A0의 $\Sigma^x$와 다르므로 **C11이 기존 A11과 같을 필요는 없다.** A0 대비 변화는 중심의 factor 정의와 covariance 계약의 변화로 나누어 보고한다.

함께 수행할 최소 대조:

- **CZ10/CZ11:** predicted ray $y/y_z$를 보존해 LiDAR/GT Z만 교체. C10/C11의 ray 교체 효과와 구분한다. 평가 시 네 C-arm과 CZ 두 arm의 공통 분모를 별도로 저장한다.
- **원 A0 replay:** 기존 A00/A10/A01/A11 수치·mask를 원 계약으로 재현한다. C00/A00 world-map 불변성과 source별 local-unit 변화도 함께 확인한다.
- **같은 GT 표본의 point/projection 잔차:** 렌더링 전 local Z·3D·ray 잔차와 렌더링 후 깊이 지표를 분리해 renderer 비선형성을 조사한다.
- **Covariance 최소 대조:** office2의 기존 고정 20뷰에서 C-arm의 world covariance를 C00 값으로 고정한 네 조건을 별도로 평가한다. Rigid rotation의 covariance transport와 비교해 효과 방향이 바뀌면 R-Q를 확대하고, local/pose 우세를 바로 판정하지 않는다.

**우선 실행:** office2 기존 strict 1,200,827후보와 400뷰. HKairport01은 기존 보정 공통 6,368개와 넓은 support 242,162개를 **서로 다른 scope로 유지**하고 같은 40뷰를 평가한다. 더 좋은 결과를 보이는 scope를 선택하지 않는다. UAV의 조건부 표시는 Q0-HK 판정에 따른다.

**해석:** C01은 rigid pose 개입으로 정의할 수 있지만 C10은 scale을 포함한 유효 local geometry 개입이다. 유일한 ‘raw depth 오류 기여율’은 아니다. C 표현의 단독 악화가 줄고 원 A0의 악화가 남으면 scale 배분의 영향을 지지한다. C 표현에서도 interaction이 크면 A1-G/M 및 아래 추가 대조를 거쳐 coupling 가설을 검토한다.

## 5.4 A1-F/RT — 필요한 경우에만 요인 수 확대

**A1-F:** 원 metric-local 표현에서 local(L: 추정/참조), rigid pose(P: 추정/참조), scale(S: $a_k$/1)의 **2×2×2, 총 8조건**을 구성한다. $t_k$는 같은 camera origin의 world translation으로 유지하고 local 좌표에만 scale을 적용한다. `S=1`은 이 계약의 intervention level이며 데이터가 제공하는 ‘GT KF scale’이 아니다. L×S·P×S·L×P 및 세 요인의 interaction을 계산하고, 표현 재배분의 영향과 지표 비선형성을 구분한다. C-arm과 F-arm의 local covariance 계약을 혼합하지 않는다.

**A1-RT:** C01 효과가 유의하거나 C의 coupling이 남을 때만, 같은 유효 local geometry에서 `(Rref,test)`와 `(Rest,tref)`를 추가해 R/t를 분리한다. Scale을 다시 바꾸지 않는다. 원점을 기준으로 world 좌표를 직접 회전해 translation까지 바꾸는 구현을 금지한다.

F/RT는 먼저 office2의 사전 고정 20개 fusion viewpoint에서 검사하고, 명확한 진단 질문이 남을 때 400뷰로 확장한다. 단순히 모든 조합을 생성하는 것을 연구 목표로 삼지 않는다.

## 5.5 A1-G/M — Gauge와 후보 support를 결론의 일부로 평가

**A1-G (필수):** 기존 prefix와 pose revision은 유지한다. Position-only Sim(3) 및 prefix orientation mean으로 회전을 정한 Sim(3)를 사전 지정한 두 alignment로 비교하고 prefix trajectory singular values·정렬 회전 차이를 보고한다. GT test pose를 포함해 가장 좋은 정렬을 고르거나 prefix를 오류가 작은 구간으로 옮기지 않는다. C의 단위 변경 불변성과 **서로 다른 alignment의 불확실성**을 구별한다.

**A1-M (필수):** strict common source, 넓은 단일 보정 support, 전체 native map의 mixed replacement를 분리한다. Scope마다 변경 local 후보 수/전체 native 수, 거리·source KF·예측 confidence strata와 미관측 영역을 보고한다. 실내 GT를 고정 seed로 픽셀/행 스캔 형태로 얇게 만든 **dense→sparse support 대조**도 같은 원본 지도에서 시행한다. Source 후보만 줄이는 경우와 target 측정만 줄이는 경우를 나눠, 지도 support 변화와 평가 표본 변화가 섞이지 않게 한다. 밀도·pattern은 mask만 보고 등록하고 오류가 큰 픽셀을 골라 제거하지 않는다. 이는 실제 LiDAR의 sensor/occlusion 모델을 복제하는 실험이 아니다.

보정 대조의 경우 16조건 전체 픽셀 교집합을 주 지표로 쓰지 않는다. 각 camera 안의 네 조건을 같은 참조로 평가하고, 공통 후보의 source ray·물리 LiDAR point ID 대응을 확인할 수 있는 경우에만 camera 간 paired 비교를 부가한다. 서로 다른 ray의 같은 pixel index가 동일 측정을 뜻한다고 가정하지 않는다. Camera 가정은 A11 성능으로 선택하지 않는다.

추적 실패 3뷰와 이후 구간도 기존 분할대로 남기고 공백 전/중/후 층화를 병행한다. 실패 프레임 제거로 결과를 개선하지 않는다. Support gate는 §11.5를 따른다.

## 5.6 V1 및 R-Q — 독립 재현과 최소 representation 통제

**V1 (필수):** office2에서 A1-U/C·주 gauge·mask·metric·판정 규칙을 봉인한 뒤 **office3**에서 한 번 동일 절차로 재현한다. N2의 500입력·prefix 100 pose·heldout 400뷰를 유지한다. Office3는 validation이며, 결과를 보고 변경하면 해당 변경과 재실행을 기록하고 독립 최종 test로 부르지 않는다. HKairport01의 개발 결과는 V1을 대체하지 않는다.

**R-Q (필요 시 확대):** §5.3의 covariance 소규모 검사는 필수다. C11 잔차가 크거나 그 검사에서 순위가 바뀔 때 (i) reference-only source→same/다른 view 투영의 Z-buffer residual, (ii) 동일 reference 후보·동일 viewpoint의 Gaussian expected-depth residual, (iii) C-arm의 **world covariance를 C00 값으로 고정한 보조 비교**를 확장한다. (iii)은 의도적인 표현 통제이며 정식 rigid transport arm과 혼합하지 않는다. Center nearest-neighbor를 surface 정답으로 쓰거나 LiDAR hole을 임의 보간하지 않는다. Appearance 최적화 연구로 바로 확장하지 않는다.

## 5.7 A1 완료 산출물과 경로 결정

- `A1_coordinate_reparameterization.json`: native/metric/canonical 변환, candidate·covariance hash 및 baseline 불변성.
- `A1_C_four_arms.csv`, `A1_effects.csv`, ray-only 대조, source local/placement/covariance별 residual.
- `A1_gauge_support_matrix.csv`: gauge × scope별 실제 평가 뷰/픽셀 수·coverage·방향 안정성.
- 필요 시 `A1_F_eight_arms.csv`, `A1_RT.csv`, `R_Q_reference_renderer.csv`.
- `V1_office3_replication.md`, `A1_route_decision.md`: **표현 효과 / 잔여 기하 효과 / 자료 부족**을 구분하고 A2·D·P·분석 경로 중 다음 한 단계만 지정.

**중단/보류:** A1-U 실패는 구현 문제다. Reference·support·gauge·representation에 따라 local/pose 우세가 뒤집히면 오류 기여율과 알고리즘 GO를 보류하고 원인을 먼저 좁힌다. UAV reference 미해결 때문에 실내 검증까지 중단하지는 않는다.

---

# 6. 조건부 A2 — 잔여 형상 오차와 RGB-only 수정 가능성

## 6.1 질문

**시작 조건:** A1-C/G/M과 V1 이후 유효 local geometry에 재현 가능한 개선 여지가 남아 있을 때. `Depth가 틀렸음`과 `GT 없이 깊이를 고칠 수 있음`을 구별한다. A1에서 우세가 정해지지 않으면 관측 부족 분석으로 제한하고 D 구현 자격을 부여하지 않는다.

## 6.2 A2-S — Scalar bias와 공간적 deformation 분리

기준 depth는 A1의 유효 local $y_z$다. 원 raw depth의 C-scaled 통계도 병기하지만 같은 의미로 합치지 않는다.

| 조건 | Fit 자료 / 자유도 | 확인할 것 |
|---|---|---|
| S0 | 보정 없음 | A1-C00의 local 잔차 |
| Sg | 정해진 prefix source GT로 맞춘 **한 global scalar** | test GT 없이 고정한 global scale로 설명되는 부분 |
| Sk-oracle | 각 mapping KF의 지정 source GT fitting tile에서 맞춘 **KF별 scalar** | spatially held-out tile·target view에서 남는 형상 오차 |
| Sf-oracle | 같은 fitting tile의 저해상도 `4×4` log-depth field | KF scalar 대비 추가 개선 가능성; GT 기반 진단 상한 |

KF oracle scalar의 예는 다음과 같으며 fit pixel 집합은 fitting split에만 속한다.

$$
\beta_k=\exp\!\left[\operatorname{median}_{u\in\Omega_{k,\mathrm{fit}}}
\log\frac{D_k^{\mathrm{ref}}(u)}{y_{k,z}(u)}\right].
$$

**교차 검증 규칙:** source image를 `8×8` tile로 나눠 checkerboard 두 fold를 사전 고정하고, fitting/evaluation tile을 교환한다. 인접 경계 guard band와 최소 관측 수를 실행 설정에 고정한다. Sparse GT가 부족한 KF는 unsupported로 보고하고 상한을 0으로 채우지 않는다. Sf의 regularization은 office2에서 고정하며 office3/office4 GT 성능으로 선택하지 않는다. Target heldout depth는 fit에 사용하지 않는다.

Sk/Sf는 source GT를 쓰므로 **Oracle/diagnostic**다. 같은 점에 fit하고 같은 점의 오차를 줄인 수치를 알고리즘 개선으로 보고하지 않는다. Ray 보존, 동일 후보·covariance·rigid pose 조건에서 scalar와 field를 비교하고, 두 oracle이 실제 rendered target geometry/coverage에도 도움이 되는지 별도 측정한다.

## 6.3 A2-O — RGB 관측 가능성과 공유 편향

정해진 source-disjoint 시점·visibility·baseline/parallax·texture 조건에서 RGB reprojection objective를 조사한다. Source-disjoint는 이미지 공유를 배제한다는 뜻이며, 동일 network의 예측을 독립적인 GT로 취급하지 않는다.

- 주어진 GT/reference는 objective에 넣지 않고 **오차 감소 방향을 사후 평가**하는 데만 사용한다. Development 데이터와 synthetic control에서만 basin/gradient 방향을 조사한다.
- 동일 scale 오류, piecewise scale, additive depth bias, 모든 시점의 shared bias, rigid pose 오류, 가림/동적 영역을 각각 주입한 control에서 photo objective가 잘못된 정답을 지지하는지 검사한다.
- 먼저 단일 scalar와 고정된 작은 field의 loss profile을 확인한다. 충분한 parallax의 영역에서조차 실제 깊이 개선 방향을 구별하지 못하면 더 큰 optimizer를 만들지 않는다.
- Depth-only와 pose가 흔들릴 때의 objective를 따로 보고한다. Pose 오차를 depth field로 흡수하는 현상을 성공으로 취급하지 않는다.

**A2 판정:** Sk가 공간 field의 개선 여지 대부분을 설명하면 P의 단순 scale 일관성 경로를 우선한다. Scalar 이후 재현 가능한 공간 잔차가 남고 RGB-only objective가 이를 구분하며 V1/§12 기준을 통과할 때만 D를 연다. Oracle만 좋아지고 RGB는 구분하지 못하면 **관측 한계·공유 편향 분석**을 결과로 남긴다.

---

# 7. 조건부 연구 경로 D — RGB-only 선택적 깊이 보정

> **현재 D는 보류다.** A1/V1에서의 단위·pose/support 통제와 A2-S/O를 통과해야 한다. A11의 큰 개선만으로 시작하지 않는다. 아래 공식은 알고리즘 가설이며 선행연구에서 그대로 사용한 기술일 수도 있다. 추가 검색·대조 실험 없이 originality를 주장하지 않는다.

## 7.1 연구 목표

- MASt3R/SLAM network weights와 rigid pose를 고정하고, A1에서 정의한 **유효 local geometry**의 depth만 수정한다. 결과를 native local/placement로 역변환할 때 원 지도를 중복 scale하지 않는다.
- 별도 입력 depth sensor 없이 RGB 원본 및 기존 추정 geometry만 이용.
- 적은 수의 조정 변수와 강한 regularization으로 기존 Pointmap의 신뢰 가능한 형상을 유지.
- 보정 후 3D Map을 **동일 후보 수·동일 appearance 조건으로 재투영**하여 독립 GT 기준 geometry error 개선 확인.

## 7.2 비교 방법(미리 정의)

| ID | 내용 | 목적 |
|---|---|---|
| **D0** | 추정 Pointmap 원본 | Baseline |
| **D1** | 단안 global scale 또는 KF별 단일 scale 보정(평가 구간 GT 사용 금지) | 간단한 scale 보정과 비교 |
| **D2** | 중복 시점 geometry만으로 전체 depth를 smooth/align하는 baseline | 기존 geometry-only 다중 시점 정합 |
| **D3** | Masked RGB photometric reprojection으로 제한된 depth 변수를 보정 | 일반 multi-view photometric baseline |
| **D4** | **선택적 지역 depth correction**: 신뢰 가능한 영역만 D3 성격의 objective 적용 | Proposed candidate(조건부) |
| D5 | D4 + 지역 신뢰도·low parallax·boundary gate | Optional uncertainty ablation |
| **O-D** | GT Depth 기반 local correction | Oracle 참조, 주 성능표와 분리 |

## 7.3 선택적 보정식 초안

각 Keyframe의 카메라 Z-depth에 제한된 correction field를 정의한다.

$$
D'_k(u)=D_k(u)\exp\{\delta_k(u)\},
\qquad
\delta_k(u)=\sum_m b_m(u)\theta_{km}.
$$

- $b_m(u)$는 저해상도 격자 또는 영역 기반 basis 함수. per-pixel 자유 최적화보다는 파라미터 수를 줄인다.
- $\theta_{km}$는 학습시킨 거대 backbone의 새 가중치가 아니라 **장면별 제한된 보정 변수**.
- RGB reprojection loss는 실제로 시점 간 충분한 overlap/parallax와 가시성이 확보된 곳에만 적용한다.
- regularization은 correction magnitude, 인접 영역 smoothness, RGB depth edges 보존.

예시 objective(구체 weight는 validation에서 결정):

$$
\min_{\theta}\; \lambda_{ph} L_{photo}(\theta)
+\lambda_{mv} L_{geom}(\theta)
+\lambda_{reg}\|\theta\|_2^2
+\lambda_{edge}L_{edge}(\theta).
$$

**기존 기술 대비 검증 포인트:** 같은 photometric objective를 *전체 유효영역*에 적용했을 때와 **신뢰 가능한 영역에만 선택 적용**했을 때의 순증분. 또한 D1/D2/D3와 비교하여 추가 정확도가 없다면 D4의 새로운 기여를 주장하지 않는다.

## 7.4 깊이 보정에 사용할 수 없는 증거

- GT Depth/LiDAR/GT pose를 실제 추론 objective의 직접 target으로 사용 금지(Oracle arm 제외).
- 장면 전체를 처리한 미래 프레임을 온라인 버전에서 현재 시점의 correction에 사용 금지(offline refinement arm과 구분).
- 다른 Keyframe이 같은 모델의 동일 systematic bias를 공유하면 단순 cross-view agreement를 정답 근거로 사용하지 않음.
- 하늘/유리/동적 물체/가려진 픽셀의 거짓 photometric match를 채택하지 않음.

## 7.5 Pointmap 보정 → Gaussian Map 반영 방식

1. 원본 Gaussian `candidate_id`와 `color/SH/opacity/rotation/scale`은 1차 실험에서 고정.
2. 보정 후 $X'$를 원래 anchor frame 좌표로 변환하여 Gaussian 중심 $\mu'$에만 적용.
3. 기존 생성 메서드에서 offset이 존재하면 $\mu_i=X_i+\Delta_i$를 유지한 채 $\mu'_i=X'_i+\Delta_i$로 변환; 검사한 self-branch의 offset 0 사실을 모든 경우로 확대하지 않는다.
4. 중심만 바꾼 Arm과, 위치 변경에 맞춰 scale/covariance만 **정해진 규칙으로** 재초기화한 Arm을 별도로 두어 표현의 영향을 분리한다.
5. renderer, color/SH, active candidate count, mask, pose, test viewpoint를 동일하게 유지.
6. 선택 확장으로 모든 비교군에 동일한 횟수의 Gaussian refiner를 적용하며, optimizer-on/off arm을 비교한다.
7. D 비교에서는 rigid pose를 고정한다. Native KF scale과 유효 local depth를 동시에 자유롭게 풀어 같은 변화를 두 변수에 중복 표현하지 않는다. A1/V1에서 joint coupling이 남고 단순 대조군이 실패했을 때만, 별도 등록한 소규모 scalar+SE(3) 교대 대조를 검토한다. 현재는 joint optimizer 구현 단계가 아니다.

---

# 8. 조건부 경로 P — Pose/Scale 배치 오류가 지배적일 때

A1-C의 **rigid-only pose 효과** 또는 A2-S의 **단순 scale 일관성 효과**가 V1에서 재현되면 검토한다. 원 A01의 개선/악화만으로 GO-P를 내리지 않는다.

- **P0:** 현재 MASt3R-SLAM pose (baseline).
- **P1:** 이미 시스템에 존재하는 Sim(3) global/loop alignment 단계 재점검 및 parameter/coordinate bug 확인.
- **P2:** 관측 시점 간 상대 변환·overlap·RPE/ATE를 기반으로 국소 pose/scale discrepancy를 정량화.
- **P3(조건부):** RGB/기존 matching만 이용한 KF scalar 일관성 또는 제한된 SE(3) 조정 중 **하나**를 구현해 기존 backend와 비교. 입력·matching·iteration budget을 맞추고 GT/RTK/LiDAR를 objective에 넣지 않음.
- **O-P:** GT pose oracle; 실제 알고리즘 성능으로 보고 금지.

**경계:** 카메라 Pose와 점군을 동시에 global ICP로 GT reference에 맞추는 것은 평가 정렬일 뿐 RGB-only SLAM 개선이 아니다. 모든 Keyframe을 각자 GT에 정렬해 error를 숨기는 조치를 금지한다. 신뢰할 수 있는 기존 optimizer가 같은 정확도를 달성한다면 새 알고리즘의 기여는 주장하지 않는다.

**최소 비교군:** 원본 → GT 없이 prefix/상대 관측으로 정한 단일 scalar → 같은 관측의 KF scalar → 기존 backend 동일 예산. 복잡한 P3는 이 순서의 가장 단순한 유효 대조군을 넘어야 한다. 매 KF의 GT로 fit한 Sk-oracle은 별도 상한 표에만 둔다.

---

# 9. Gaussian Representation/Rendering 통제 R

우선 §5.6의 **R-Q 최소 진단**만 허용한다. Reference QA와 sparse support를 확인하지 않고 A0b A11의 1.60/2.78m 잔차를 Gaussian 표현 오차로 귀속하지 않는다. 그 이후에도 representation 원인 가설이 남을 때 아래 R0–R3로 확장한다.

| 실험 | 고정/변경 | 해석 |
|---|---|---|
| R0 | center·pose 고정, 현재 renderer | reference |
| R1 | center·pose 고정, opacity/scale만 정해진 규칙으로 변경 | extent/coverage 기여 |
| R2 | center·pose 고정, 공정한 동일-iteration appearance refinement | 저 PSNR이 geometry만의 문제인지 |
| R3 | GT depth/pose 중심 고정 + representation/renderer 변경 | oracle residual의 원인 분리 |

R 경로는 핵심 연구와 무관한 고품질 NVS 개발로 확장하지 않는다. 기존 E0/E4의 refinement=0 결과와 최적화된 offline 3DGS PSNR을 동일 조건인 듯 직접 비교하지 않는다.

---

# 10. 데이터셋, 개발/검증/최종 평가 분할

## 10.1 이미 사용한 자산(개발/회귀 전용)

- Replica `office0`, `room0`, `room1`, `room2`, `office1`: E0~E4에서 이미 관찰. pipeline regression, unit-test, 시각화, tuning용.
- Replica `office2`: N2 당시 미사용이었지만 A0 이후 **현재 개발 장면**이다. 새 장면 test로 다시 계산하지 않음.
- UAVScenes `HKairport01`: E4e/A0b 개발 진단. Q0-HK 미해결이면 conditional reference만 허용. 전체 UAV 효능 검증용 독립 scene이 아님.
- KITTI Raw `2011_09_26_drive_0015_sync`: E4f 개발 진단/GT range 평가 코드 재활용.
- UAVScenes `AMtown01`, `AMvalley01`: 데이터 확보·preflight만 실행. 기본 mapping baseline 평가 완료라고 적지 않음.

## 10.2 새 연구 평가 세트(실행 가능성 확인 후 확정)

| 세트 | 목적 | 요건 | 주의 |
|---|---|---|---|
| **Replica 새 미노출 scene(s)** | 2×2 A0 main geometry, GT mesh/depth | camera GT, dense geometry, static scene | 원본 v3/E4 사용 장면과 구분. test 장면에서 조건 조정 금지 |
| **TUM RGB-D 또는 다른 독립 실내 세트** | 도메인 전이 확인 | RGB 입력, depth/pose는 평가만, valid masks | depth 센서의 FOV/정렬 및 time sync 확인 |
| **KITTI 미사용 drive** | 실외 sparse LiDAR/depth vs pose 성분 확인 | RGB, calibration, OXTS, LiDAR, dynamic/sky masks | LiDAR sparse points로 GT surface 전체 completeness를 주장하지 않음 |
| **UAV 별도 scene/구간** | trajectory 및 domain stress | scale/pose/reference 있으면 정량 | GT 부재 시 절대 기하 정확도 주장 금지 |

**분할 규칙:** 장면/drive 단위 Development / Validation / Final Test 분리. 서로 겹치는 공간을 촬영한 인접 프레임은 독립 장면이 아님. 기존에 많이 분석한 scene은 논문 main test에서 제외. 최소 실험 세트의 숫자는 실제 사용 가능한 ground truth와 GPU 리소스를 확인한 후 manifest에 사전 기록.

**N2 데이터 등록:** [N2 사전 등록](../configs/n2_dataset_registration.json)에 따라 기존 연구에서 미사용인 Replica `office2`는 진단·개발, `office3`는 검증, `office4`는 최종 평가용으로 구분한다. 각 장면은 원본 `[0,1000)`에서 짝수 RGB 500개를 입력으로 사용하고, calibration은 `[0,200)`의 짝수 pose 100개, 주 평가 뷰는 `[200,1000)`의 홀수 400개로 고정한다. `office4`는 무결성·형식 QA 이후 최종 방법·평가 규칙이 고정될 때까지 예측·Oracle 비교·튜닝에 사용하지 않는다.

**개정 후 최소 실험 범위:** 개발 `office2 + HKairport01` → V1 `office3` → 최종 F0 `office4`를 유지한다. 외부 도메인 검증은 Q0와 방법의 준비가 끝난 뒤 별도 장면을 등록한다. `AMtown01/AMvalley01`의 확보 사실은 baseline 실행·참조 신뢰성·독립 효능 검증을 대신하지 않는다. Replica만 통과하면 결론을 실내 범위로 제한한다.

**HKairport 분할 보존:** 기존 `[60,120)`초·mapping 240장·prefix grid `<100`의 80 pose·heldout grid `104…299` 40뷰를 유지한다. Tracking failure 이전/중/이후를 모두 포함한다. 더 좋은 비행 구간으로 바꿀 경우 기존 결과의 대체가 아닌 신규 개발 run으로 별도 등록하고 변경 근거를 기록한다.

## 10.3 GT 사용 레벨

1. `GT-depth/mesh/pose`를 **A0/A1 Oracle과 평가**에 사용하는 것은 허용; 이 Arm에는 Oracle 표기.
2. D/P에서 제출할 RGB-only 방법의 optimization/threshold 학습에 **최종 test GT 사용 금지**.
3. KITTI OXTS orientation/translation, GPS, LiDAR 기준 좌표와 이미지 타임싱크를 검증.
4. Unknown GT 부위는 **오류 0·빈 공간·정답 outlier**로 간주하지 않는다.
5. Dynamic/sky 라벨이 실제로 있을 때만 static mask를 주장한다. HKairport01의 현재 A0b 평가에는 semantic mask가 없으므로 static-only라고 부르지 않는다.
6. **서로 다른 GT 사용을 구분:** prefix의 전역 gauge, Oracle arm의 source GT, A2 source fitting tile, heldout target의 평가 GT를 별도 로그로 남긴다. Final test GT와 online 미래 frame은 실제 보정의 입력에서 제외한다.

---

# 11. 평가 지표 및 통계 설계

## 11.1 Pointmap의 국소 오류

- **Z-depth MAE / median / p95 (m):** GT와 추정의 metric 정렬 후 $\lvert D_{\mathrm{est}}-D_{\mathrm{GT}}\rvert$.
- **Abs Relative Error:** $\operatorname{mean}\left(\frac{\lvert D_{\mathrm{est}}-D_{\mathrm{GT}}\rvert}{D_{\mathrm{GT}}}\right)$ (GT $> \varepsilon$, 유효 픽셀만).
- **Log-depth ratio median/IQR:** C-scaled raw local와 native scale을 흡수한 effective local를 각각 표시. A2의 scalar fit 잔차는 spatial fitting/evaluation split을 구분.
- **거리별:** 실내는 기존 `[0.1,1,2,4,10]m`, HKairport는 `[2,25,50,75,100,150,200]m`를 유지. KITTI의 과거 bin을 다른 장면에 그대로 적용하지 않음.
- **평면/경계/비평면별:** wall/road/roof, depth edge, vegetation, shiny region/occlusion 여부.
- **Overlap/parallax:** 두 시점에서 실제 관측 가능한 영역의 비율과 관측 각도.

## 11.2 Map geometry 지표 — 핵심

- **Rendered depth**와 GT depth의 MAE/AbsRel/유효 픽셀 coverage 및 **correct-depth coverage**.
- GT mesh가 있는 장면: rendering depth로 얻은 3D samples → sampled GT surface의 accuracy, completion, symmetric Chamfer (샘플링·outlier truncation·거리 단위 고정).
- 해당 지표는 **rendered surface**와 **Gaussian-center proxy**를 구분한다. center→GT nearest distance만으로 실제 지도 형상을 결론 내리지 않는다.
- mask 및 coverage가 다른 방법은 **공통 유효 픽셀 지표와 전체 관측 가능 영역 coverage**를 함께 보고한다.
- 지도 오류를 작은 값으로 만드는 대신 표면 자체를 삭제한 방법은 completion/correct coverage에서 드러나게 한다.

## 11.3 Pose/Scale 지표

- ATE/RPE, orientation error, loop closure 이전/이후의 pose revision. Prefix alignment의 잔차와 post-prefix 잔차, 위치/방향으로 정의한 두 gauge의 차이를 구분.
- 단일 global alignment 이후 keyframe scale trajectory 및 relative scale drift.
- camera/world 좌표를 혼합하지 않도록 GT pose convention을 항상 기록.

## 11.4 NVS/효율 — 부차적

- Held-out PSNR↑, SSIM↑, LPIPS↓, 실제 novel viewpoint/angle/overlap metadata.
- `Gaussian count`, serialized bytes, resident/allocated/peak VRAM, mapping/refinement ms/KF, rendering FPS.
- center-only moved vs covariance-reinitialized, no-refiner vs identical refiner steps를 **같은 평가표 안에서 혼합하지 않음**.
- RGB 품질이 개선되지 않아도 geometry 연구로 성립할 수 있지만, 원본 대비 **영상 품질의 현저한 손상과 coverage 감소**는 반드시 보고.

## 11.5 통계 및 효과 기준

- Scene/sequence를 paired comparison의 독립 단위로 사용. 수백만 픽셀을 독립 실험 반복처럼 간주하지 않음.
- Mean/median 외 per-scene effect, paired plots, 분산, 가능한 경우 scene bootstrap CI를 보고.
- 평가 대상·고정 mask·GT align·가중치·정지 조건을 **최종 test 전에 고정**.
- 최초 개발 단계에서 최소 개선폭과 허용 손실폭을 validation에서 정하되, 결과를 보고 임의로 조정하지 않음.
- 어떤 효과가 개선돼도 서로 다른 scene/GT coverage 간 수치를 한 평균으로 합산하지 않는다.

**후속 실험의 잠정 개발 gate**는 아래로 고정한다. 이미 본 A0/A0b 결과의 성공 여부를 소급 변경하는 기준이 아니다. 실제 A1 설정에 수치와 근거를 기록하고, 변경 시 새 amendment와 이유를 남긴다.

| 항목 | 다음 실험에 적용할 기준 | 미달 시 처리 |
|---|---|---|
| Dense 공통 support | 등록 뷰의 ≥80%에서 `≥1,000 common pixels` 및 GT-valid의 `≥50%`를 동시에 확보 | 수치는 보고하되 효능/우세 경로의 근거로 사용하지 않음 |
| Sparse 공통 support | 등록 뷰의 ≥80%에서 `≥1,000 common pixels` 및 LiDAR-valid의 `≥20%`를 동시에 확보 | 조건부 sparse 진단으로 제한. Hole 보간/유리한 뷰 제거로 통과시키지 않음 |
| 집계 | 모든 등록 뷰·각 뷰의 분모/미정 값을 공개. 공통 픽셀 없는 뷰를 0 error로 넣지 않음 | Unscorable 뷰 수와 coverage를 함께 표시, support gate는 전체 등록 뷰 기준 |
| Correct-depth 허용 오차 | 실내 `max(0.05m,2% depth)`, HKairport `max(0.5m,2% depth)` | 참조 불확실성을 이 임계값으로 해결했다고 주장하지 않음 |
| 경로 후보의 최소 효과 | 적정 support에서 baseline 대비 공통 MAE ≥10% 감소, correct coverage 감소 ≤1%p | 경로 GO 보류. 효과가 없다는 보편적 결론으로 확대하지 않음 |
| 민감도·재현 | 주/방향 기반 gauge 및 covariance 진단에서 효과 방향이 모순되지 않고 office3 V1에서 재현 | gauge/support/representation-dependent로 표시, 지배 원인·방법 GO 보류 |
| A2 scalar 충분성 | Sk가 Sf 대비 Oracle MAE 개선량의 ≥90%를 두 spatial fold에서 설명하고 coverage 악화 없음 | 충족하면 공간 field 개발보다 단순 scalar 경로 우선; 미충족만으로 D GO는 아님 |

Scalar 충분성의 E는 같은 spatial fitting fold로 만든 S0/Sk/Sf 지도의 **동일 후보·같은 target 공통 픽셀의 heldout rendered-depth MAE**다. Spatial evaluation tile의 source 잔차도 병기한다. 분모 `E(S0)−E(Sf)`가 양수이고 최소 효과 기준을 충족할 때만 비율을 계산한다. `E(S0)−E(Sk)`와의 비가 1을 넘으면 Sk가 더 좋은 것으로 그대로 보고한다. 분모가 작거나 Sf가 개선하지 못하면 “scalar가 대부분 설명”이라고 계산하지 않는다.

네 조건 C의 우세 판단은 같은 mask에서 `C00→C10`과 `C00→C01` 및 반대 요인 조건의 효과를 함께 본다. MAE interaction 하나를 물리적 source의 비율로 분할하지 않는다. 작은 sensitivity group의 빈 교집합은 **근거 부족**이며 안정성 통과가 아니다.

---

# 12. 핵심 Go / Revise / No-Go 기준

## 12.1 현재 판정과 후속 gate

| 관찰 결과 | 판정 | 다음 행동 |
|---|---|---|
| **완료 A0/A0b:** 단독 악화·joint 개선 | **현재 REVISE 유지** | 다음 필수 실험은 A1-U/C. A11의 큰 개선만으로 D/P에 진행하지 않음 |
| A1-U에서 world map/render 불변성 실패 | **IMPLEMENTATION_FIX** | 단위·covariance·precision 버그부터 수정. 성능 결과로 해석하지 않음 |
| Q0-HK reference 미해결 | **UAV CONDITIONAL ONLY** | office2/office3 진단 계속, UAV의 절대 원인·효능 주장은 보류 |
| C 표현에서 단독 악화·interaction이 크게 줄어듦 | **표현 배분 가설 지지** | V1에서 재현하고 A2-S로 남은 scalar/형상 잔차 확인 |
| C10 효과가 §11.5 기준을 만족하고 C01 대비 ≥2배, ray 대조·V1도 지지 | **A2 진입** | Local 잔차와 RGB 관측 가능성 검증. D 구현은 아직 보류 |
| C01 효과가 §11.5 기준을 만족하고 C10 대비 ≥2배, gauge·V1도 지지 | **GO-P 검토** | RT 분해와 기존 backend 대조. Q0 미해결인 UAV 효능 GO는 불가 |
| C에서도 단독 악화·joint 개선 또는 큰 interaction 지속 | **COUPLING_DIAGNOSTIC** | A1-F/RT·G/M·R-Q로 설명 후보를 좁힘. 새로운 joint 학습으로 바로 확장하지 않음 |
| Scope/gauge/covariance에 따라 우세 방향이 바뀌거나 support 부족 | **INCONCLUSIVE** | 범위·정렬·표현 의존성을 연구 결과로 기록. 우세 원인/기여율은 미정 |
| C11에서도 잔차가 크나 reference/support가 충분 | **R-Q 우선** | Reference-only와 Gaussian expected-depth를 분리한 뒤 R 확장 여부 결정 |
| 차이가 작고 재현 가능한 보정 여지가 없음 | **NO-GO for correction** | 분석 연구의 새 지식·기여 충분성을 별도 평가하고 범위 축소/종료 검토 |

**효과 우세 규칙:** 두 단독 효과가 모두 양수이고 최소 효과를 만족할 때만 ≥2배를 우세 판단에 쓴다. 한쪽만 최소 효과를 만족하는 양수이면 비율을 만들지 않고, V1·민감도와 반대 요인 조건의 효과를 확인한 뒤 해당 A2/RT의 진단 자격만 검토한다. 두 효과가 비슷하면 한 경로를 임의로 정하지 않고 A2/RT에서 설명력을 조사한다. 이 비율과 최소 효과는 개발 의사결정 규칙이지 통계적 유의성 기준이 아니다.

**중요:** Oracle 이득은 실제 RGB-only 보정 가능성을 보증하지 않는다. **GO-D는 A1/V1 → A2-S/O → 문헌 검토를 통과한 뒤에만** 발행한다. 규칙을 통과한 실내 결과를 reference 미해결 UAV까지 확대하지 않는다.

## 12.2 D 경로 Go/No-Go

| 조건 | 판정 |
|---|---|
| Scalar 이후 공간 잔차가 남고 RGB objective가 올바른 방향을 구별하며 V1에서도 재현 | **D1/D3 최소 구현 자격**. D4부터 구현하지 않음 |
| D4가 D1/D2/D3 강한 대조군보다 신규 test에서 geometry를 개선하고 correct coverage를 보존 | 후보 기여를 검토하고 ablation·재현 실험 진행 |
| D4가 GT에서 개선하더라도 RGB/coverage를 크게 훼손 | 불충분; penalty/선택 정책을 재설계하되 결과를 숨기지 않음 |
| D4 vs D3 차이가 없거나 나쁨 | 새로운 선택적 보정의 기여 주장 보류; 가장 단순한 효과 있는 대조군 채택 또는 범위 축소 |
| GT-depth Oracle은 크게 개선하지만 RGB-only가 실패 | **관측 부족/공유 bias의 한계 분석**으로 연구 방향 재설정 |
| A2의 scalar 충분성 또는 D1의 단순 보정이 대부분의 개선을 달성 | D4 확대 중단; 가장 단순한 scale 일관성 대조를 우선하고 추가 기여가 없는지 검토 |

---

# 13. 실험 매트릭스와 결과표 서식

## 13.1 우선순위

| ID | 필수 | 목적 | 비교 | 필수 산출물 |
|---|---|---|---|---|
| **N0** | O | 환경/GT/재현성 점검 | 기존 B1, 저장된 E0~E4f | frozen manifest, file/pose checks |
| **N1** | O | 좌표계·자원 계약 점검 | raw vs active, self vs pair, Sim(3) | test log, common candidate IDs |
| **N2** | O | 미사용 GT 실내 장면 확보·QA·분할 등록 | RGB/depth/pose/camera/mesh, calibration/evaluation 분리 | file hashes, scene roles, frame split, dataset QA |
| **A0/A0b** | 완료 | office2 GT 및 HKairport 조건부 reference factorial | 기존 A00/A10/A01/A11 | 완료 결과 보존; REVISE에서 출발 |
| **Q0-HK** | UAV 필수 | calibration·JPG·Terra/reference 계약 | 공개값/가정별 QA, reference-only 재투영 | 출처, 검증/미해결 목록, UAV claim 범위 |
| **A1-U** | 완료 PASS | 원본 지도의 scale 흡수·가역성 | native vs effective local + rigid placement | 두 장면 4,788,198후보, 32검사, map/render 불변성 확인 |
| **A1-C** | 실행 완료 | 유효 local × rigid pose의 재비교 | C00/C10/C01/C11, CZ10/CZ11, office2 covariance | Local 단독 개선·잔여 coupling, 38검사 통과 |
| **A1-G/M** | 다음 필수 | gauge·support dependence | 두 prefix gauge, strict/wide/full-mixed, dense→sparse | 평가 분모·실패 포함 strata·효과 방향 |
| **A1-F/RT** | 질문 잔존 시 | scale 별도 요인 및 R/t 분리 | 8조건 L×P×S 또는 rigid R/t | interaction·질문별 진단 표 |
| **V1** | 필수 | office3 고정 재현 | 봉인된 U/C/G/M 절차 | V1 보고서·수정 이력·다음 경로 판정 |
| **R-Q** | 잔차/표현 의심 시 | reference-only/renderer/covariance 최소 통제 | 참조 투영, splat, fixed-world covariance | residual 원인의 근거 및 미분리 변수 |
| **A2-S/O** | A1/V1 후 | scalar vs deformation, RGB observability | spatial cross-fit scalar/field, shared-bias control | GT 진단 상한과 RGB-only 가능성 분리 |
| **D0–D5** | GO-D 후 | RGB-only 선택적 Depth 보정 | raw, scale, geom, photo, selective | GT geometry/RGB/coverage, ablation |
| **P0–P3** | GO-P 후 | 제한적 Pose/Scale 개선 | original, existing backend, limited fix | metric pose/geometry comparison |
| **R0–R3** | 조건부 | Gaussian representation 통제 | fixed center, scale/cov, appearance | render-vs-geometry sensitivity |
| **F0** | 결론 검증 시 필수 | office4 최종 평가 | 고정 A1-C + 선택된 한 경로 또는 분석 가설 | sealed results, 실패 포함; 개발에 역사용 금지 |
| **F1** | 선택 | 신뢰 가능한 신규 UAV/실외 scene | original vs 단순 대조군 vs 선택 방법 | 외부 도메인 범위·runtime·reference 한계 |

## 13.2 후속 C 표(원 A0/A0b 표와 구분)

| Scene / reference | Gauge / scope | Arm | Common candidates | Common pixels/view, scorable views | MAE depth ↓ | Correct coverage ↑ | Dense surface metric / sparse N/A |
|---|---|---|---:|---|---:|---:|---|
| TBD | TBD | C00 effective-local / estimated rigid | | | | | |
| TBD | 동일 | C10 reference-local / estimated rigid | | | | | |
| TBD | 동일 | C01 effective-local / reference rigid | | | | | |
| TBD | 동일 | C11 reference-local / reference rigid | | | | | |

`C00 world map == native A00` 검사와 covariance 정책을 표 제목에 연결한다. Mixed full-map은 local 교체 비율을 추가하고 완전 Oracle이라는 표현을 쓰지 않는다. Sparse reference에 dense completion 수치를 채우지 않는다.

## 13.3 Effect 분해 표

| Scene | Error metric | Δ local oracle | Δ placement oracle | Interaction | Alignment/mask version |
|---|---|---:|---:|---:|---|
| TBD | | | | | |

## 13.4 D 경로 표(조건부)

| Scene | Method | Adjusted pixels % | Mean correction magnitude | Depth MAE ↓ | Chamfer ↓ | Correct coverage ↑ | LPIPS ↓ | Extra ms/KF ↓ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| TBD | D0 raw | | | | | | | |
| TBD | D1 scale | | | | | | | |
| TBD | D3 photo | | | | | | | |
| TBD | D4 selective | | | | | | | |
| TBD | O-D oracle (diagnostic only) | | | | | | | |

---

# 14. 현재 코드 재사용과 후속 구현 구조

과거 연구 코드에서 `raw candidate export`, `GT evaluation`, `TSDF/Chamfer`, `frozen map renderer`, `run manifest`와 기타 데이터를 재사용하고, 후보 pruning/admission 코드를 중심 경로에서 제외한다.

**현재 존재하는 자산:** `src/pointmap_contract.py`, `src/a0_metrics.py`, `src/a0b_geometry.py` 및 A0/A0b runner·renderer. A1-U의 `src/scale_reparameterization.py`/`scripts/run_a1_unit_invariance.py`에 이어 A1-C의 `src/canonical_oracles.py`, `scripts/build_a1_canonical_oracles.py`, `scripts/evaluate_a1.py`, 분석·보고서 코드를 구현했다. 관련 검사 총 38개를 통과했고 기존 snapshot은 보존한다.

**추가 구현 예정:** A1-G/M runner, `scripts/prepare_v1_office3.py` 등 후속 실행 코드. 이들은 아직 구현·실행 완료를 뜻하지 않는다. Config에는 `reference_status`, `representation`, `gauge`, `scope`, `candidate_hash`, `covariance_policy`, `source_fit_split`, `target_eval_split`, `support_gate`를 필수로 둔다.

```text
research/
├── third_party/                         # upstream commit 고정
├── data_contract/
│   ├── pose_convention.py              # SE3/Sim3 저장·변환 규칙
│   ├── camera_geometry.py              # intrinsics, z-depth vs range
│   ├── candidate_registry.py           # frame/pixel/branch/anchor IDs
│   └── gt_alignment.py                 # one-time metric gauge
├── diagnostics/
│   ├── local_pointmap_error.py         # raw depth/pointmap 오류
│   ├── pose_scale_error.py             # trajectory/scale deviation
│   ├── shared_bias.py                  # common depth/pose perturbation
│   └── oracle_factorial.py             # A00/A10/A01/A11
├── correction/                          # A1/V1/A2 이후 조건부
│   ├── depth_global_scale.py
│   ├── depth_lowrank_field.py
│   ├── photometric_reprojection.py
│   ├── correction_gate.py
│   └── map_replacement.py
├── evaluation/
│   ├── depth_metrics.py
│   ├── map_surface_metrics.py
│   ├── rgb_metrics.py
│   ├── common_mask.py
│   ├── statistics.py
│   └── memory_runtime.py
├── experiments/
│   ├── configs/
│   ├── run_N0_N1.py
│   ├── run_A0_factorial.py
│   ├── run_A1_pose_scale.py
│   ├── run_A2_feasibility.py
│   ├── run_D_depth_correction.py       # conditional
│   └── run_final_sealed.py
├── tests/
│   ├── test_zdepth_range.py
│   ├── test_anchor_frames.py
│   ├── test_sim3_roundtrip.py
│   ├── test_pair_branch_gt.py
│   ├── test_oracle_factorial_independence.py
│   ├── test_common_masks.py
│   └── test_candidate_count_and_attributes.py
└── results/
    └── <experiment_id>/<scene>/<run_id>/
```

**주의:** 위 구조는 새 구현 제안이며 현재 저장소의 실제 디렉터리/CLI를 재현한 것이 아니다. 정확한 코드 삽입 지점·GPU patch는 repository 확인 후 확정한다.

---

# 15. 필수 단위시험·합성시험

1. **Known pinhole plane:** GT depth에서 만든 3D 점과 카메라 projection의 z 단위 검증.
2. **Z-depth vs Euclidean range:** 중심 광선 외에서 예상되는 range/z 차이를 계산하여 KITTI LiDAR와 혼동 방지.
3. **Sim(3) roundtrip:** scale≠1, arbitrary R/t; mean/covariance 왕복 및 rendering projection 검사.
4. **Branch reference:** 1번/2번 이미지 pixel의 GT depth가 올바른 anchor 좌표계로 옮겨지는지 확인.
5. **A0 no-leakage:** A10에서 pose 변수 hash가 A00과 동일한지, A01에서 raw local candidate hash가 A00과 동일한지 검증.
6. **Common-candidate invariant:** 같은 실험 표현 내 네 arm에서 후보 개수/ID/opacity/SH/**local** covariance hash 같음. A0→C 재표현에서는 local covariance가 달라지되 baseline world covariance가 보존되는지 별도 확인.
7. **Unit gauge:** 단안 estimated world scale 하나를 일관되게 사용하고 frame-wise GT scale fitting이 발생하지 않는지 검사.
8. **Synthetic depth scale:** local depth만 일정 배율 오류일 때 A10만 해당 오류를 줄이는지 확인.
9. **Synthetic pose translation/rotation/scale:** 주어진 오차 하나만 투입한 경우 A01로 제거되는지 확인.
10. **Error interaction:** depth+pose perturbation을 함께 투입해 interaction 계산의 부호/해석 검증.
11. **Invalid GT:** sky/occlusion/mesh 밖/tracklet mask가 모든 비교군에서 동일하게 제외되는지 검사.
12. **Representation isolation:** geometry-fixed refiner-on/off가 A0 중심 오차로 잘못 해석되지 않는지 확인.
13. **No future/test leakage:** RGB-only correction은 결정 시점까지의 프레임만 사용, final-test GT query 없음을 로그 검증.
14. **Determinism/manifest:** 실행 순서, seed, scene hash, model commit의 반복 결과 일치/허용 편차 확인.
15. **Scale absorption:** $y=a_kx$, $\Sigma^y=a_k^2\Sigma^x$의 world center/covariance 및 RGB/depth/weight 불변성. Mean만 바꿔 covariance가 틀린 경우를 반드시 실패시키는 negative control 포함.
16. **Reallocation invariance:** KF별 양수 $q_k$와 전역 C 재배분 후 canonical C00 geometry·attributes 및 renderer 결과 동일성.
17. **Rigid-only intervention:** C01의 local point·local covariance가 C00과 같고 R/t만 바뀌는지 검사. F의 S factor가 translation을 변경하지 않는지 검사.
18. **Support accounting:** 빈 공통 mask를 0 error로 채우지 않으며, scorable 비율을 전체 등록 뷰로 계산. Camera 간 다른 ray·source-only/target-only subsampling 혼동 방지.
19. **Spatial cross-fit:** A2 fitting/evaluation tile과 guard band의 불교집합, target GT fitting 부재, Sk/Sf Oracle 표시 및 final-test GT 차단.
20. **Reference-vs-renderer:** 동일 reference point의 z-buffer와 Gaussian expected-depth가 서로 다른 관측 모델임을 유지. Sparse unknown 영역을 보간 GT/빈 표면으로 바꾸지 않음.

---

# 16. A0b 이후 실행 일정 — 순차 gate 기준으로 재편

| 시기 | 주된 작업 | 완료 산출물 / Gate |
|---|---|---|
| **완료 이력** | N0/N1/N2, office2 A0, HKairport01 A0b | 완료 기록을 재실행 일정으로 잡지 않음 |
| **묶음 1: U 완료, Q0-HK 미실행** | **A1-U PASS**: 두 기존 map의 좌표·covariance·render 보존. Q0-HK 자료 QA는 별도 진행 예정 | C 등록 준비 가능. UAV reference 미해결은 유지 |
| **묶음 2: C/CZ 완료** | office2 및 HKairport 두 scope의 **A1-C+CZ**, office2 20뷰 covariance QA | local 단독 개선·잔여 interaction. 두 gauge 대조와 full-map/sparsification은 미실행 |
| **다음 묶음 3 (약 2–4작업일)** | **A1-G/M**, 필요 시 F/RT·R-Q 확대 | UAV scope·gauge 의존성, 설명 가설 축소 |
| **묶음 4 (약 2–3작업일)** | 개발 규칙 봉인 후 **V1 office3** 재현 | 결과를 보고 A2/RT/분석 중 다음 한 단계 결정 |
| **묶음 5 (약 3–5작업일, 조건부)** | **A2-S/O**, scalar/field spatial cross-fit 및 RGB loss profile | D/P 진행 자격 또는 관측 한계 보고서 |
| **그 이후 1–2주, GO일 때만** | 한 경로의 가장 단순한 RGB-only 대조군부터 구현 | D4/P3 확대 전 강한 baseline 대비 증분 |
| **규칙 고정 후** | F0 office4; 필요·자원·reference 충족 시 F1 외부 장면 | 실패 포함 최종 평가, 결과에 맞춘 논문 범위 |

기간은 인력·실행량의 예상치이며 완료 약속이나 자동 진행 일정이 아니다. 각 묶음의 산출물이 다음 단계의 조건이다. 보정 출처 확인은 외부 상태에 좌우될 수 있으므로 실내 진단과 분리한다.

**범위 통제:** 기본은 C 네 조건과 CZ 두 조건, 모든 뷰를 한 arm씩 disk-backed map으로 평가한다. F의 8조건·world-covariance 대조·추가 camera 가정은 질문이 남을 때만 고정 subset에서 시작한다. 모든 요인을 한꺼번에 Cartesian product로 실행하지 않는다. 알고리즘 경로를 선택하기 전 새 checkpoint·학습·대규모 장면 다운로드는 필수 범위가 아니다.

**일정 중단 조건:** U 불변성 실패는 구현 수정, reference 부족은 해당 도메인 조건부화, V1 미재현은 결론 축소로 처리한다. RGB-only가 강한 단순 대조군을 넘지 못하면 구현을 계속 확대하지 않는다.

---

# 17. 성공 가능성·실패 위험과 대응

| 주요 위험 | 왜 문제가 되는가 | 조치 |
|---|---|---|
| 두 이미지의 pointmap과 pose가 수학적으로 분리되지 않음 | A10 교체 자체에 relative pose oracle이 섞임 | **self-branch strict primary**와 pair secondary를 분리 |
| 단안 scale ambiguity | meter 오차나 Oracle effect가 잘못 계산될 수 있음 | 단일 global gauge, 별도 scale drift 보고 |
| Local-unit와 KF scale 배분 | A01이 회전·이동 이외의 scale까지 변경 | A1-U의 지도 불변 재표현, C의 rigid-only 개입, F의 별도 S factor |
| 거의 직선인 prefix | 위치 정합의 전역 회전이 불안정해 pose 잔차가 커짐 | 위치/방향 gauge 사전 비교, singular values·불확실성 보고, test fitting 금지 |
| GT calibration/시간동기 오류 | 원인이 없는 geometry error 생성 | 투영 unit test, sensor mask, reprojection sanity |
| HKairport 공개 calibration의 비직교 R·전처리 미확인 | 큰 Oracle 효과가 있어도 physical reference가 확정되지 않음 | Q0-HK, 조건부 표기, 실내 검증과 도메인 gate 분리 |
| GT depth와 estimated coverage 차이 | Oracle만 더 많은 표면을 포함하게 됨 | 공통 valid candidate ID, full map sensitivity 분리 |
| 많은 arm의 target 교집합 붕괴 | 3/5뷰·수십 픽셀의 contrast가 강건한 것처럼 보임 | 비교군별 공통 분모, support gate, 빈 뷰 공개·재현 부족 판정 |
| Shared model bias | 서로 다른 프레임에서도 같은 잘못된 평면을 지지 | RGB parallax/GT diagnostic, 보정 가능성 별도 게이트 |
| Pose·Scale·Depth 상호작용 | 한 요소의 오차가 다른 요소를 바꾸면 효과 착시 | factorial interaction, A1 sensitivity |
| Gaussian center 이동 후 covariance 불일치 | 렌더링/coverage 감소의 원인 혼동 | center-only vs covariance reinit 명확히 구분 |
| 기존 refinery 비활성 상태의 낮은 PSNR | geometry 개선을 appearance 문제로 잘못 해석 | no-refiner vs equal refiner-run sensitivity |
| Dynamic/sky/reflective | static depth GT가 잘 정의되지 않음 | mask 분리, 실패 유형 기록 |
| GPU 8GB 제약 | full scenes/4-arm 메모리 초과 | batch/chunk, subset QA→full, disk-backed map |
| 선행연구와 novelty 중복 | Depth/photo loss나 BA 그 자체는 새롭지 않음 | 원인 분해 계약 + 조건부 보정 순효과를 최소 주장 |
| 신규 scene 부족 | 개발 장면에만 유리한 결론 위험 | seal된 미노출 scene 확보 전 논문 효능 주장 금지 |

---

# 18. 논문 기여도와 연구 종료 기준

## 18.1 결과가 허용하는 잠정 기여 후보

1. **Scale 일관성을 명시한 진단 프로토콜:** 동일 native map을 보존하는 재표현과 raw/effective local·rigid pose·covariance의 개입 계약. 재표현의 대수 자체는 새 알고리즘으로 주장하지 않음.
2. **재현 가능한 실패 조건:** native local/KF scale 배분, gauge, source support, reference 신뢰성에 따라 Oracle 해석이 달라지는지 office3/F0에서 검증. 새로운 실증적 설명을 제공해야 분석 기여 후보가 됨.
3. **조건부 보정 기법:** A1/V1/A2가 지지한 단일 경로에서 RGB-only 보정이 강한 단순 대조군보다 실질적으로 낫다는 증거가 있을 때만 주장.
4. **재현 가능한 체계:** 8GB GPU 환경에서 사용 가능한 평가 도구, 데이터 계약, 단위시험과 negative results.

## 18.2 과장해서는 안 되는 주장

- '모든 Gaussian 이상점은 MASt3R Depth 오차 때문이다.'
- 'GT local geometry oracle 향상 = RGB-only Depth refinement 성능 향상.'
- 'Pose oracle 효과의 전부가 camera translation 오차다.'
- '단독 치환 악화와 joint 개선만으로 실제 오차 상쇄 또는 joint optimizer의 필요성이 입증됐다.'
- 'A1-U의 scale 흡수 자체가 지도를 개선하는 새 보정 알고리즘이다.'
- 'HKairport 보정 공통 후보의 92% 개선 또는 보조 후보의 87% 개선이 전체 native 지도의 개선율이다.'
- 'Gaussian center == GT surface' 또는 'center distance가 rendered geometry 정확도를 증명한다.'
- '단일 Replica/KITTI 개발 구간에서의 개선이 모든 드론 시퀀스로 일반화된다.'
- 'PSNR이 낮으므로 Pointmap이 잘못되었다'(appearance refinement 0의 설정을 무시한 주장).
- '분석만 수행하면 자동으로 새로운 알고리즘 논문으로서 충분하다.' (기존 평가에서 보이지 않은 원인·상호작용·진단법이 실제로 새 지식을 제공해야 함)

## 18.3 가능한 논문 결과 유형

- **Case A:** local Depth가 주원인 + 선택적 보정이 기존 photo/scale보다 성공 → 보정 중심 논문.
- **Case B:** pose/scale drift가 주원인 + 제한적 배치 보정 검증 → pose 중심으로 제목 수정.
- **Case C:** local과 pose의 interaction이 중요하고 실질적인 correction 순효과가 작음 → 엄격한 원인 분해/실패 분석 연구(기여도 추가 점검).
- **Case D:** A0 조차 실험적으로 분리하기 어렵거나 참조 데이터 불충분 → 현재 타당성의 NO-GO, 문제/데이터 재정의.

---

# 19. 실행 체크리스트 — 완료 이력과 다음 실험 구분

## 19.1 완료된 출발점

- [x] 기존 실험의 원본 체크포인트/환경/코드 버전과 추적 가능한 run manifest 보존. (N0)
- [x] **새로운 GT 실내 scene**의 카메라 내부·외부 파라미터, RGB, Depth, 표면 모델 확인. (N2: 첫 A0는 office2, office3 검증, office4 최종 평가 보류)
- [x] Splatt3R-SLAM에서 `raw self-branch pixel uv ↔ candidate_id ↔ Gaussian local mean ↔ anchor frame` 매핑 출력. (office2 A0)
- [x] 추정 Sim(3) pose를 읽어 metric aligned world로 내보내는 테스트 작성. (N1 및 A0)
- [x] `GT depth z`로 pixel unprojection → GT world projection 왕복 오차 확인. (저장된 A11 map 포함)
- [x] 네 A0 Arm 공통 후보 집합과 pose/pointmap 변수 해시 불변 조건 확인.
- [x] Center-only 4-arm map을 작은 장면에서 생성하고 시각화. (local covariance 고정, placement에 따른 world covariance 변환은 유지)
- [x] GT depth/surface metrics를 계산해 $\Delta_L$, $\Delta_P$, interaction 산출. (office2)
- [x] A0 Go/No-Go 회의록에 '현재 확인된 오차'와 '다음 가설'을 구분해 기록. (A0 결과서: REVISE, 단일 장면의 조건부 진단)
- [x] A0b HKairport01의 38개 지도·680 depth-view 평가와 보정/gauge/support 한계를 기록. (조건부 완료, 알고리즘 GO 아님)
- [x] A0b 보조 support 비교의 결과 확인 후 등록 이력과 기존 tracking gate FAIL 보존.

## 19.2 A1-U 완료 및 Q0-HK 미실행 상태

- [x] `configs/a1_unit_reparameterization.json`에 두 기존 map·native mask·pose revision·정밀도·불변성 한도 고정. (검사·smoke·실제 map 변환 전 등록)
- [x] KF별 metric placement $a_k,R_k,t_k$와 native local/covariance의 단위 확인. (32KF 단위 CSV)
- [x] $y=a_kx$, $\Sigma^y=a_k^2\Sigma^x$ 변환 및 역변환, C/seeded KF 배율 재배분 불변성 검사. (전 native-active 후보)
- [x] 원본과 재표현 map의 world mean/covariance·attribute hash, 같은 viewpoint의 RGB/depth/weight 차이 저장. (6 positive map/scene byte-identical, 60 positive render 차이 0)
- [ ] Q0-HK 보정 출처·JPG distortion·Terra/물리 카메라 대응의 확인/미확인 목록 작성. 저자에게 메시지를 자동 발송하지 않음.
- [x] U PASS를 `results/A1_U_scale_reparameterization/2026-10-26/A1_U_contract.json`에 기록. (A1-C/Q0-HK 완료로 간주하지 않음)

## 19.3 그다음 묶음: A1-C → G/M → V1

- [x] office2 C 네 조건+CZ 두 조건, 기존 후보·400뷰·covariance 정책·support gate 등록·평가.
- [x] A00/C00 baseline 불변성, C01 rigid-only, C10 effective-local 정의 확인. (모든 scope C00 SHA 동일)
- [x] HKairport common/wide 각 40뷰 C/CZ 비교 및 공백 전/중/후 층화. (common support 실패, wide 참조는 조건부)
- [x] office2의 20뷰 fixed-world covariance 대조. (해당 대조에서 효과 방향·순위 유지)
- [ ] HKairport full-mixed 및 두 gauge를 A1-G/M에서 추가 대조. Common/wide C는 완료했으며 Q0 미해결 시 conditional 유지.
- [ ] Dense→sparse source-only/target-only 대조와 빈 교집합·추적 공백 층화 포함.
- [ ] 질문이 남을 때만 F/RT/R-Q의 최소 subset을 추가 등록.
- [ ] Office2에서 규칙을 봉인한 뒤 office3 V1 실행. 현재 office3/office4 예측은 미실행.
- [ ] A2 진입 / P 검토 / 추가 진단 / 분석 범위 축소를 판정. D4·joint optimizer·office4를 자동 실행하지 않음.

## 19.4 후속 조건부 작업

- [ ] A2-S spatial cross-fit scalar/field 및 A2-O RGB loss profile 등록·검증.
- [ ] GO일 때만 문헌 중복 점검 후 단순 RGB-only 대조군 구현, 새 방법의 순증분 확인.
- [ ] 방법 또는 분석 가설·metric·mask·판정을 고정한 뒤 F0 office4 한 번 평가.

---

# 20. 참조 자료 및 기존 산출물

## 20.1 실험 근거(이번 계획의 직접 출발점)

- [A0 office2 결과](experiments/A0_office2_factorial_results.md), [설정](../configs/a0_office2_factorial.json), [요약](../configs/a0_results_summary.json): dense GT factorial, C/ray/covariance·full-map 한계.
- [A0b HKairport01 결과](experiments/A0b_HKairport01_factorial_results.md), [설정](../configs/a0b_hkairport01_factorial.json), [요약](../configs/a0b_results_summary.json): sparse LiDAR/reference pose, 보정·gauge·support 및 사후 보조 비교의 한계.
- [A1-U 결과](experiments/A1_U_scale_reparameterization_results.md), [설정](../configs/a1_unit_reparameterization.json), [요약](../configs/a1_u_results_summary.json): 지도 보존 scale 흡수·KF 단위 재배분 및 렌더링 불변성 PASS.
- [A1-C 결과](experiments/A1_C_canonical_factorial_results.md), [설정](../configs/a1_c_canonical_factorial.json), [요약](../configs/a1_c_results_summary.json): effective-local × rigid pose, ray/covariance·동일 픽셀 A/C 비교 완료. A1-G/M·V1은 다음 단계.
- [N1 좌표 계약](experiments/N1_coordinate_contract.md), [N2 데이터 등록](../configs/n2_dataset_registration.json): 후속 구현의 검증 자산과 office2/3/4 역할.
- `surface_guided_gaussian_mapping_experiment_summary.md`, 2026-10-22, §4–§7: E0~E4f 전체 결과·해석·미실행 작업·재사용 가능한 코드/GT 평가 자산.
- `surface_guided_gaussian_mapping_research_plan_v3.md`, 2026-10-14: 동일 후보 풀, source lineage, GT validity, scene-level statistics, 재현성·강한 대조군 원칙. **단, 이전 pruning 가설과 장기 admission 일정은 신규 실행 대상이 아님.**
- 개별 실험 보고서(E0/E1/E2/E3/E4/E4b/E4e/E4f) 및 실행 manifest: 새 실험의 코드·수치 검증에는 이 원자료를 우선 참조.

## 20.2 첨부 논문(기술 배경)

- Wang et al., *DUSt3R: Geometric 3D Vision Made Easy*.
- Leroy et al., *Grounding Image Matching in 3D with MASt3R*.
- Murai et al., *MASt3R-SLAM: Real-Time Dense SLAM with 3D Reconstruction Priors*.
- Smart et al., *Splatt3R: Zero-shot Gaussian Splatting from Uncalibrated Image Pairs*.
- Kerbl et al., *3D Gaussian Splatting for Real-Time Radiance Field Rendering*.
- Zhou et al., *GeoGS-SLAM: Geometry-Only Gaussian Splatting for Dense Monocular SLAM* (2026).
- Gao et al., *GeoGS-SLAM: Online Monocular Reconstruction Using Gaussian Splatting with Geometric Priors* (2026).

**최종 원칙:** 큰 joint Oracle 이득은 **수정 여지에 대한 조건부 증거**다. 단위·scale 배분, reference, gauge, support를 먼저 통제하고 독립 재현과 RGB 관측 가능성에 따라 연구 범위를 선택한다. `Depth를 수정하면 해결된다` 또는 `joint 최적화가 필요하다`는 현재 확정 사실이 아니다. 이전 종료 주제의 Gaussian 제거 가설도 재도입하지 않는다.
