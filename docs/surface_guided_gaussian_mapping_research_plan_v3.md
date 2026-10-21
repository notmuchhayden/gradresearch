# 연속 RGB/드론 영상의 Feed-forward 3D Gaussian Map에서 교차관측 기반 이상 후보 편입 제어

## 연구 설계·구현·실험 계획서 v3.0 — GeoGS-SLAM 2026 두 편 검토 반영

- **개정일:** 2026-10-21 — E3b 임시 편입·부분집합 보정 및 새 room1 평가 반영
- **상태:** E0/E0b/E1/E2/E2b/E3/E3b 결과는 개별 보고서에 기록했다. **E3b는 hard DEFER 공백과 부분집합 오거부를 보완했으나, 새 room1 공통 후보에서 B6 대비 추가 우위를 확인하지 못해 REVISE다. E4는 보류하고 동일 관측 자격의 B6/plane 비교(E3c)를 먼저 검토한다.**
- **상위 문서:** `surface_guided_gaussian_mapping_research_plan_v2.md` (2026-10-13)
- **제출 계획서 제목(유지 가능):** 연속 영상 기반 3D Gaussian Splatting에서 이상 Gaussian 감소를 위한 기하 정합성 기반 최적화 연구
- **작업용 제목(권장):** **연속 영상 기반 Feed-forward 3DGS에서 증거 신뢰도를 고려한 Gaussian 편입 및 보류 정책의 실험적 평가**
- **작업용 영문 제목:** *Evidence-Aware Gaussian Admission and Deferral for Feed-Forward 3D Gaussian Mapping from Video*
- **핵심 연구 범위:** pose 및 Gaussian 후보 풀을 고정하고, 새로운 Gaussian을 전역 Map에 **언제/왜 편입·보류·거부할지**를 연구한다. 광범위한 Gaussians 재최적화, 새로운 SLAM backbone, 일반적인 geometry prior 융합은 핵심 기여에서 제외한다.

> **읽기 안내:** 이 문서의 ‘[논문 사실]’은 아래 두 첨부 논문에 직접 기술된 내용이며, ‘[해석/가설]’과 ‘[제안 실험]’은 본 연구를 위한 새 설계다. 논문에 나오지 않은 기능이나 코드를 제공한다고 가정하지 않는다. 본 문서의 결과표 서식은 계획표이며, 측정값은 출처를 연결한 파일럿 경과에만 기재한다.

---

# 0. 결론: 기존 계획의 무엇을 유지하고 무엇을 고치는가

## 0.1. Go / Revise 판정

**판정: 연구 주제를 폐기할 필요는 없지만 v2의 차별화 근거와 대조실험은 수정해야 한다.**

1. **폐기할 독창성 주장:** ‘다중 시점 기하 검증을 도입한다’, ‘PCA로 평면을 추정해 Gaussian 크기·방향을 정한다’, ‘기하·RGB loss를 함께 사용한다’, ‘loop closure에서 통일된 Sim(3) 변환으로 맵을 보정한다’는 주장 자체는 이미 선행연구와 겹친다.
2. **유지할 연구 질문:** Splatt3R 계열 *feed-forward 후보*의 장기 Map 편입 결정에서, 다른 시점 증거와 그 불확실성에 근거한 **candidate-level KEEP / REJECT / DEFER 의사결정**이 실질적으로 유용한가?
3. **강화할 비교:** 기존 v2의 confidence/voxel/uniform/self 기준에 더해 **GeoGS 논문의 다중 시점 검증 방식에서 영감을 얻은 photometric/reprojection 대조군**과 **2026 GeoGS 온라인 논문의 DoG 기반 map expansion을 본뜬 샘플링 대조군**을 *동일한 후보 풀·poses·예산·최적화 조건에서* 구현해 비교한다.
4. **수정할 독립성 주장:** `source pair`가 다른 키프레임도 같은 MASt3R 계열 가중치, pose graph 및 fused pointmap을 공유할 수 있다. 이를 ‘독립 GT’라고 부르지 않는다. **원천 관측 분리(source-disjoint)**, **모델 분리(model-disjoint)**, **별도 RGB 검증**, **외부 GT**를 구별한다.
5. **연구 성공 조건:** 대조군보다 **이상 후보의 선택적 제거 효용**이 있으며 동시에 **정상 구조 coverage, 미관측 영역, 신규 시점 렌더링을 보존**한다는 것을 보여야 한다. 단순한 기하 residual 축소나 Gaussian 수 감소는 충분하지 않다.
6. **선행연구 직접 재현의 한계:** GeoGS-SLAM A의 geometry-only 결과는 일반 RGB 3DGS의 PSNR과 직접 비교할 수 없고, GeoGS-SLAM B의 VGGT 기반 완전 시스템 숫자는 고정 pose/후보 풀 기반 본 실험과 직접적인 알고리즘 비교가 아니다. 대등하지 않은 비교는 별도 **시스템 수준 참고표**로만 둔다.

## 0.2. v2 → v3 핵심 변경 추적

| v2 항목 | v3 판단 | 이유/조치 |
|---|---|---|
| RQ1: self-surface vs cross-view | **유지하되 충분성 기준 강화** | 다중 시점 제약 자체는 GeoGS A에서도 수행. photometric reprojection 및 cross-view prior 대조군 추가 |
| RQ2: matched Gaussian count | **유지·강화** | 자연 편입률과 목표 budget 충족 가능성까지 기록. 강제 무작위 제거로 제안 정책을 포장하지 않음 |
| Local PCA + plane projection | **보조 구현으로 격하** | GeoGS A의 local-plane driven 초기화와 PGSR·SuGaR 계열과 중복 |
| Loop closure/Sim(3) | **정확성 통제 항목으로 유지** | GeoGS A가 coherent map update 명시. 본 논문의 신규 기여로 주장 금지 |
| `source-excluded = independent` 표현 | **전면 수정** | 공통 네트워크·fused map·pose의 상관 bias 존재. independence 계층화 |
| KFs를 모두 모아 cross-view 평가 | **causal online vs retrospective 명확히 분리** | 후보 생성 시점에 존재하지 않던 미래 프레임을 편입 결정에 쓰면 온라인 성능 과장 |
| baseline 구성 | **DoG + reprojection/photometric + prior/normal 정합성 대조군 추가** | 2026년 논문이 수행한 접근의 일부를 공정하게 대응시켜야 함 |
| geometry 평가 | **GT rendered-depth + TSDF/mesh + floaters/coverage로 재구성** | 원래 Gaussian center는 실제 렌더링 표면과 동일하지 않음 |
| Real-time 주장 | **누적 per-KF 지연+latency 분포·queue age 보고** | 비교 논문 B는 keyframe 당 582.1 ms를 보고; ‘실시간’ 의미 구분 필요 |
| 드론 파일럿 | **초기 유지** | 출처 분리, 시점 중첩, rolling shutter, sky, scale 문제를 조기 판정 |

---

# 1. 선행연구 검토의 정확한 범위와 영향

## 1.1. A: GeoGS-SLAM — *Geometry-Only Gaussian Splatting for Dense Monocular SLAM*

**[논문 사실]** Lipu Zhou 외, arXiv:2607.07452v1, 2026-07-08.

- 색상 SH를 제거하고 $G=\{\mu,s\text{(2축)},q,\alpha\}$로 기하만 표현한다(Section IV-A, Eq. 7).
- rendered depth/normal, depth smoothness, ray 상의 depth distortion, monocular depth/normal priors 및 **가림/시야 마스크를 적용한 multi-view RGB reprojection의 L1/SSIM/NCC**를 사용한다(Section IV-C, Eqs. 16–31, Fig. 4).
- KNN/PCA 평면성과 normal을 이용해 Gaussian의 방향과 초기 크기를 조절한다. 낮은 평면성 후보의 초기 scale을 1/10로 낮춘다(Section IV-D, Eq. 32, Fig. 5).
- loop closure/BA 뒤 개별 keyframe 변환이 인접 표면을 찢는 문제를 해결하기 위해 revisit된 Gaussian 묶음에 대해 단일 Sim(3)을 맞춘다(Section V-D, Eqs. 35–37).
- DTU Scan24의 2분 최적화 ablation에서 multi-view loss 제거 시 Chamfer Distance가 **0.53 → 9.04 cm**로 악화된다(Table X). **이 특정 실험 조건의 수치이지, 보편적인 성능 보장은 아니다.**
- Replica에서는 복원 표면을 rendered depth로부터 TSDF fusion해 geometry metrics를 계산한다(Section VI-A).

**[해석]** 위 논문으로 인해 ‘cross-view reprojection/plane alignment/Sim(3) 보존’은 신기법이라고 주장할 수 없다. 그러나 논문 A가 제시한 핵심은 **geometry-only 표현의 기하 최적화**이며, 본 연구가 겨냥하는 **가시성·출처 신뢰도에 따른 feed-forward RGB Gaussian 후보의 장기 Map 편입·보류 결정**과 완전히 같은 문제 정의는 아니다. 후자가 새로운 기여인지에 대한 판단은 다른 Gaussian-pruning/online-admission 선행연구까지 추가 확인해야 한다.

## 1.2. B: GeoGS-SLAM — *Online Monocular Reconstruction Using Gaussian Splatting with Geometric Priors*

**[논문 사실]** Ruilan Gao 외, arXiv:2607.11184v1, 2026-07-13.

- VGGT sliding window에서 pose·intrinsics·depth·confidence를 추정하고 window 간 공유 KF로 scale을 맞춘다(Section III-B).
- map expansion은 입력 RGB의 **DoG 위치 확률**과 현재 렌더의 **DoG occupancy 확률** 차이로 중복 생성을 억제한다(Section III-C, Eqs. 6–7).
- 새 Gaussian은 RGB 색상과 예측 point prior로 초기화하고, map/pose를 photometric L1+SSIM 및 predicted-depth L1로 **공동 최적화**한다(Section III-D, Eqs. 8–10).
- MegaLoc 기반 loop detection → VGGT 상대 pose 제약 → pose-graph 최적화 → keyframe 연관 Gaussian 보정(Section III-E).
- Replica/TUM RGB-D/Waymo에서 PSNR·SSIM·LPIPS 및 ATE를 제시하지만 **GT geometry의 outlier detection precision/recall이나 후보별 admission 오류를 평가하지 않는다**(Section IV의 metrics).
- RTX 4090 평균 per-keyframe 처리시간 총 **582.1 ms**, 그중 joint optimization **480.6 ms**를 보고한다(Table III). 이는 **평균 keyframe 비용**이지 전체 입력 프레임 FPS와 동일한 지표가 아니다.

**[해석]** 온라인 맵에 새 Gaussian을 선택적으로 추가한다는 *넓은 발상*은 이미 B에 존재한다. 그러나 B의 주된 기준은 DoG 기반 생성 위치/중복 억제와 RGB·depth joint refinement로서, 제안하는 **cross-view source-disjoint evidence + 보류/거절의 개별 후보 판정**과 직접적으로 동일하다고 단정할 자료는 없다. 최소한 DoG map-expansion을 본뜬 대조군이 필요하다.

## 1.3. 서로의 결과 수치 직접 비교 금지

- A는 geometry-only primitive이므로 RGB NVS PSNR을 동일 과제로 평가한 결과가 아니다.
- B는 VGGT backbone과 joint pose/map refinement를 함께 바꾸므로 성능 상승을 **Gaussian 편입 알고리즘만의 효과**로 분리할 수 없다.
- 본 연구는 두 시스템 전체를 복제해 SOTA와 경쟁하는 것을 16주 MVP 필수 요건으로 두지 않는다. 대신 논문에 등장한 **연산 요소를 동일 baseline 상에서 구현한 대조 실험**을 수행한다. 구현이 해당 논문의 충실한 재현이 아닌 경우 결과표에 반드시 `proxy/inspired baseline`이라고 쓴다.

---

# 2. 새 연구 문제·가설·성공 조건

## 2.1. 문제 정의

> **같은 연속 RGB 입력과 고정된 feed-forward Gaussian 후보 풀에서, source-disjoint 다중 관측·가시성·원본 RGB 재투영의 확인 가능한 증거를 사용해 후보 Gaussian의 KEEP/REJECT/DEFER를 결정하면, 단순 confidence/voxel thinning뿐 아니라 기존 multi-view reprojection 및 DoG 기반 삽입 정책보다 정상 장면 coverage를 적게 잃으면서 실제 geometric outlier를 더 효율적으로 줄일 수 있는가?**

이 질문은 ‘새로운 multi-view consistency 최적화’를 주장하는 것이 아니다. **온라인 편입 의사결정과 증거 부족의 처리 정책**을 연구한다.

## 2.2. 핵심 연구 질문

| ID | 질문 | 필요한 증거 |
|---|---|---|
| RQ1 | source-disjoint geometric support가 후보별 GT outlier 분류를 개선하는가? | raw/fused/self vs source-disjoint vs model-disjoint의 PR, FPR 및 평가 가능 후보 비율 |
| **RQ2 (핵심)** | candidate-level evidence-aware admission이 **multi-view photometric/reprojection, DoG, confidence** 대조군보다 같거나 낮은 map budget에서 geometry·coverage·novel-view 품질의 trade-off를 개선하는가? | 동일 후보 풀/pose/학습/후처리 조건의 Pareto, paired scene 결과 |
| RQ3 | **DEFER(새 관측 시 재판정)**가 즉시 KEEP 또는 즉시 REJECT보다 정상 구조의 오삭제와 온라인 지연 사이에서 유리한가? | false reject / deferral delay / peak queue memory / coverage |
| RQ4 | 학습된 모델의 공유 bias가 있을 때 source-disjoint signal이 유효한가, 언제 실패하는가? | 합성 공통 bias, 별도 model-depth, RGB reprojection, GT 비교 |
| RQ5 | 원래 RGB Gaussian을 유지하면서 online 비용·실제 map compactness에 이득이 있는가? | per-KF p95 latency, resident VRAM, serialized MB, FPS 별도 |

## 2.3. 가설 및 반증 기준

- **H1:** self-prediction보다 source-disjoint 검증의 GT 판별력 개선이 있다. 단, 공유 모델 bias에서도 개선된다고 미리 가정하지 않는다.
- **H2:** DoG/reprojection/confidence 각각과 비교해, 동일한 **실효 budget**에서 geometric accuracy 또는 outlier precision의 개선이 있고 coverage·렌더링 손실이 사전 정의된 허용 범위 내이다.
- **H3:** DEFER는 evidence-absent 후보의 잘못된 삭제를 줄이지만 평균/꼬리 지연과 RAM 사용량을 증가시킬 수 있다.
- **H4:** 공통 systematic geometry bias가 지배적이면 기하 검증만으로 해결할 수 없으며, 원본 RGB 신호 및 별도 predictor가 추가로 유효한지 결정한다.

**성공의 필요조건:** 정확도가 소폭 개선돼도 기존 GeoGS-inspired baseline 대비 추가 이익을 확인할 수 없으면 알고리즘 novelty 주장은 **보류**한다. ‘선행연구보다 좋다’가 아니라 '**고정된 공통 pipeline에서 해당 설계요소를 추가했을 때 어느 상황에서 유익한가**'로 제한한다.

---

# 3. 불변 실험 계약: 혼합 비교 방지

## 3.1. 시스템 데이터 흐름

```text
연속 RGB 프레임 t
  ├── [고정] MASt3R-SLAM: pose/scale/keyframe/pointmap/track
  ├── [고정] Splatt3R(-SLAM) predictor: Gaussian 후보, source_pair IDs
  │                   │
  │                   └── candidate pool C_t (재현 가능한 frozen dump)
  └── [읽기 전용] RGB/keyframe records + 출처 ancestry + (선택) 다른 prior
                       │
                evidence construction
             ├─ 자기 관측/다른 출처 Pointmap
             ├─ 가시성 확인·깊이 경계/occlusion
             ├─ local surface quality (PCA는 기존 요소)
             └─ optional masked photometric reprojection
                       │
          admission: KEEP / REJECT / DEFER / BYPASS
                       │
                frozen-parameter Gaussian map
                       │
       동일 candidate/pose/renderer로 정량 평가
```

**Stage 1:** Gaussian 새 학습·미분최적화 **없음**, 고정된 후보 집합으로 실험. **Stage 2(선택):** 모든 방법에 동일 Gaussian refiner/optimization iteration을 적용하고 동일 poses를 유지한다. **Stage 3(선택):** 실제 온라인 insertion으로 이전 맵의 렌더링에 영향을 주는 조건을 검사한다. **SLAM tracking과 mapping을 동시에 바꾸는 통합 시스템 비교는 본 연구의 핵심 검증이 아니다.**

## 3.2. 실행 전 필수 확인 사항(E0)

1. Splatt3R-SLAM repo commit, 실제 runner, weight, 3D Gaussian output/head, keyframe selection, pair source 연결 관계. 문서에 적힌 CLI flag의 존재와 적용 범위를 코드/실행으로 검증.
2. `candidate_id`, `source_frame_ids`, `source_pair_ids`, `anchor_keyframe_id`, 생성 시점, world/local 좌표계, $\mu,q,s,\mathrm{SH},\alpha,\mathrm{confidence}$ 추출. 같은 KF의 중복 후보 생성 여부 조사.
3. `MASt3R-SLAM`의 raw per-pair pointmap, fused map, confidence, pose revision, raw ancestry 역추적이 가능한가. fused 출력을 ‘독립 관측’으로 오기재하지 않는다.
4. `Sim(3)` 스케일과 covariance: $\mu_w=sR\mu_k+t$, $\Sigma_w=s^2R\Sigma_kR^\top$ 왕복 검사; 단, pose 저장 방향은 실제 코드 기반 검증.
5. 카메라 모델: calibrated pinhole은 투영식 사용, distortion/unknown camera일 경우 기존 ray map 또는 pointmap matching 사용. pinhole을 기본으로 가정한 결과를 arbitrary-camera 재현으로 확대 해석하지 않음.
6. online map 갱신 전후 상태를 **동일한 주기**로 저장; refiner 전후를 섞지 않는다.
7. GT reference는 실험 구현시 접근하지 않도록 분리; validation에서만 hyperparameter 선택.

## 3.3. 오차의 원인을 분해한 통제

- **Pose-fixed arm**: 모든 방법이 같은 저장된 SLAM pose 사용 → mapping 정책 효과.
- **GT-pose diagnostic arm**: 가능한 GT pose로 지도/관측 정렬 → tracking bias에 대한 민감도. 실제 제품 성능으로 주장하지 않음.
- **Refiner-on/off arm**: 각각 동일 iteration/optimizer 및 동일 후보 입력조건. 관측과 refiner 설정을 동시에 바꾸지 않음.
- **Loop correction arm**: 같은 pose update를 사용하고 cache 및 정합성만 검증. GeoGS A의 coherent map update를 신규 기여로 주장하지 않음.

---

# 4. 가장 중요한 수정: ‘독립 교차관측’의 정의와 온라인 인과성

## 4.1. 증거 계층

| 레벨 | 기술적 정의 | 논문에서 허용할 표현 |
|---|---|---|
| E0 self | 동일 후보 predictor에서 나온 pointmap/offset | 자기 일관성 검사 (GT 증거 아님) |
| E1 cross-view / source-overlap | 다른 KF이나 동일 원본 이미지가 pointmap 학습/융합 입력에 포함 | 공유 출처 관측 |
| **E2 source-disjoint** | candidate 생성에 참여한 원본 이미지·pair와 검증 입력 이미지들이 직접 겹치지 않음; ancestry 미확인 시 별도 | **원천 이미지 분리** 관측; 통계적 독립 아님 |
| E3 model-disjoint | 별도 사전학습 모델에서 예측한 geometry로 검증; 동일 RGB·scene 입력은 유지 | 모델 구조가 다른 보조 기하 검증, 여전히 GT 아님 |
| E4 photo | raw RGB 간 occlusion-aware reprojection과 공간 정합 확인 | 영상 관측 기반 보조 증거; 반사/조명/동적 장면 취약 |
| **E5 external GT** | 실제 depth/mesh/reference pose 또는 독립 고정밀 reference | **평가용** 독립 참조. map 편입 결정에는 절대 사용하지 않음 |

**E2만으로 ‘독립된 정답 표면’을 얻었다고 주장하는 것을 금지한다.** 핵심 실험은 E0/E1/E2의 비교, E4 추가의 순증분, (선택) E3가 E2의 shared-model failure를 개선하는지를 분리한다.

## 4.2. Online causality

후보 $G_i$가 생성된 키프레임 시각을 $t_i$라 하면, **온라인 결정에 이용하는 관측은** $t_j \le t_{\mathrm{decision}}$이어야 한다. $t_{\mathrm{decision}}$은 해당 후보가 결정되거나 재평가되는 순간이다.

- **Past-only arm(주효과):** 현재 시간까지 도착한 *후보 생성 출처와 분리된* 이전 KF 관측으로 판단. 충분하지 않으면 `DEFER/BYPASS`.
- **Deferred arm(주효과):** 이후 **실제로 새 KF가 들어올 때만** 업데이트해 재평가. queue age와 보류 중 렌더링 처리 명시.
- **Future-aware oracle arm(진단용):** 전체 sequence 완료 후 미래 프레임까지 이용하여 실현 가능한 최대 분류력을 파악. **온라인 실험 결과표와 절대 혼합하지 않음.**
- Loop closure로 과거 pose가 갱신되면 revision에 맞게 cache 재계산; 평가 시 `revision-at-decision`과 `final-revision`을 혼동하지 않는다.

### 최소 lineage 기록

`candidate_id, source_images, source_pairs, source_model, anchor_kf, created_at_kf, evidence_kfs, evidence_images, shared_images_count, fused_ancestry_status, pose_revision_at_decision, decision_at_kf`.

---

# 5. 관측 연결/가시성/기하 support 계산

## 5.1. 어떤 관측이 실제로 Gaussian을 반박할 수 있는가

1. 후보가 타 KF의 시야 안에 있는지 확인.
2. 픽셀/레이가 실제 측정된 표면에 대응하는지 확인. 단순 3D 최근접점만으로는 벽의 반대 면이나 이중 표면을 잘못 연결할 수 있음.
3. **가려짐을 음성 증거로 사용하지 않음.** 후보가 target surface 뒤에 있으면 `NOT_VISIBLE/UNKNOWN` 처리.
4. 후보가 추정 표면보다 카메라에 더 가까운 free-space 영역에 있고 2개 이상 유효 관측이 반복해서 동일 충돌을 보이면 **potential false-positive**로 기록. 얇은 구조/반투명/동적 물체에서는 예외.
5. RGB 재투영 증거는 L1/SSIM 또는 NCC를 조합하되 자동 노출·반사·움직임·textureless 영역에서 신뢰도를 낮춤.
6. 타 관측의 ‘없음’을 `REJECT`로 변환하지 않는다.

## 5.2. 표면 patch (신규라고 주장하지 않음)

- 후보 target pixel의 2D depth 연속 구간과 bounded 3D neighborhood를 결합해 KNN/PCA.
- 중심 $\bar p_j$, 법선 $n_j$, 측정 간격 $h_j$, 샘플 개수/평면성/분포 비율/깊이 엣지/가시성 지표 기록.
- weighted covariance에서 $\lambda_1\ge\lambda_2\ge\lambda_3$. surface fit 잔차와 $\lambda_2/(\lambda_1+\varepsilon)$를 함께 검사해 **직선형 분포($\lambda_2\approx 0$)**를 평면으로 오인하지 않는다.
- PCA 기반 initialization, normal alignment, flattening은 GeoGS A와 공유하는 **known technique**으로 처리; 본 실험의 필수 신규 모듈이 아님.

다음 후보-관측 잔차는 설명 가능한 **feature**로 사용하되 한 개 수식만으로 분류 결론을 내리지 않는다.

$$
r_{ij}^{plane}=\frac{|n_j^\top(\mu_i-\bar p_j)|}{h_j+\varepsilon}, \qquad
r_{ij}^{depth}=\frac{z_j(\mu_i)-D_j(u_j)}{\max(D_j(u_j),\varepsilon)}.
$$

$r_{\mathrm{depth}}$는 signed 값이다. **관측 표면보다 앞에 있는지(가상의 장애물), 뒤에 있는지(가림 가능성)**를 분리한다. $z_j(\mu_i)$를 target ray에 맞춰 확인하는 projection, camera calibration, depth uncertainty는 검사해야 하며, pose가 틀릴 때 오판할 수 있다.

## 5.3. Feature vector와 관측 자격

`support_count`, `source_disjoint_count`, `baseline_angle`, `visibility_state`, `signed_depth_conflict_count`, `median_plane_residual`, `MAD`, `patch_fit`, `planarity/spread`, `point_confidence`, `opacity`, `projected_area`, `optional_rgb_residual`.

- support_count는 **관측 프레임 개수**와 **서로 다른 독립 기반의 증거 개수**를 별도 저장한다.
- `source-disjoint`라도 시점 baseline이 거의 0이면 실질적인 depth disambiguation이 약하다. parallax/angular diversity를 별도 covariate로 보고한다.
- 예측 confidence는 calibration된 오류 확률이 아닐 수 있다. 값의 분포/장면 간 보정 실험 전 임의 softmax/확률 해석 금지.

---

# 6. 핵심 알고리즘: Conservative Evidence-Aware Admission

## 6.1. 본 연구에서 실제 비교할 정책

| 상태 | 발생 조건 | 온라인 동작 | 평가상 의미 |
|---|---|---|---|
| **KEEP** | 보존 충분 또는 기존 표면 표현에 유용 | 렌더러 Map 편입 | 정상 보존만으로 성공 아님 |
| **REJECT** | **반복적으로 가시성 확인된 기하 충돌** + 충분한 근거 | 편입하지 않음; 로그 복원 가능 | outlier precision·false reject로 평가 |
| **DEFER** | source 분리 불가/시점 부족/불확실 | deferred queue로 이동; 신규 관측 시 재평가 | 온라인 지연·coverage 손실 측정 |
| **BYPASS** | 안전 baseline에서 미판정 후보를 그대로 유지 | immediate map 편입 + `unknown` 표시 | DEFER와 별도의 실험 정책 |

**주의:** 기존 v2의 `DEFER/BYPASS`를 혼합된 하나의 상태처럼 표시하지 않고 두 개의 명시적 운영 정책으로 비교한다. `DEFER`는 관측할 때까지 미삽입한 시간 동안 hole을 만들 수 있다.

## 6.2. 분류 규칙의 안전한 시작점

```text
admit(candidate G, evidence available by now):
  1. if same source/fusion ancestry and no eligible independent-source views:
       return DEFER (policy D) or BYPASS (policy B)
  2. evaluate visibility + valid parallax + depth-edge + patch reliability
  3. if evidence cannot adjudicate candidate: return DEFER/BYPASS
  4. if repeated, validated front-of-surface/free-space contradictions:
       return REJECT only if safety limits are satisfied
  5. if coherent multi-view support: return KEEP
  6. else return DEFER/BYPASS
```

**Threshold의 수치**는 development/validation에서만 정해 test 전에 봉인한다. Surface quality와 candidate consistency를 하나의 비보정 곱셈 score로 합치지 않는다. 점수 구조의 고도화는 rule-based baseline의 순이익을 입증한 이후다.

## 6.3. 분류 목적과 예산 목적 분리

- **Primary:** false rejection을 제어하며 bad Gaussian을 식별하는 *selective classification*.
- **Secondary:** 같은 Gaussian budget에서 품질/geometry Pareto가 실제로 좋아지는가.
- 심각한 문제: 보수적 게이트가 전체 map의 3%만 REJECT할 수 있는데, 30% budget을 맞추려고 추가 27%를 random prune하면 그 결과를 **순수 admission 효과로 주장할 수 없다.**
- 해결: (a) 정책 자체의 자연 작동점, (b) evidence score에 기초한 budget-constrained ranker, (c) 전 방법에 동일한 **공통 fallback**을 붙인 arm을 각각 명시. 도달 불가능한 budget은 결과가 ‘미정의/도달 불가’라고 기록.

## 6.4. Optional extensions: 선행연구와 충돌하지 않도록 분리

- **Soft projection:** high-confidence patch에 한정하고 GT before/after 평가. 기존 surface-alignment 기술의 새 발명이라고 주장하지 않음.
- **Local-scale/normal adjustment:** GeoGS A와 겹치므로 첫 16주의 주요 기여에서 제외.
- **Surface-aware keep-best dedup:** DoG/voxel baseline 우회 여부가 관측된 경우에만 확장.
- **Coherent Sim(3) map update:** GeoGS A에 명시되어 있으므로 시스템 통제/정확성 검증으로만 유지.

---

# 7. Baseline: 2026 연구를 반영한 공정 비교군

**공통사항:** 동일 장면·키프레임·pose·source 후보 풀·SH/color·렌더러/마스크·test view·(선택 시) refinement budget. 원 논문 전체 알고리즘과 혼동하지 않도록 영감받은 축소 구현에 `proxy` 접미어를 붙인다.

| ID | 정책 | 변경하는 변수 | 상태 |
|---|---|---|---|
| B0 | MASt3R-SLAM tracking/pointmap only | 입력 tracking/geometry 검사 | 진단용; RGB 렌더 baseline 아님 |
| B1 | Frozen original Splatt3R-SLAM Map | 변경 없음 | 필수 원본 |
| B2 | Point/opacity confidence gate | confidence 신호만 | 필수 |
| B3 | Uniform/random thinning | 숫자 예산만 | 필수, 다중 seed |
| B4 | Voxel proximity/dedup | 거리/중복만 | 필수 |
| B5 | Self-surface residual | candidate와 동일 source prediction | 필수 |
| **B6** | **Source-disjoint depth reprojection conflict (GeoGS-A-inspired geometric proxy)** | masked cross-view depth/occlusion | **필수 강화군** |
| **B7** | **Masked cross-view RGB photometric reprojection (GeoGS-A-inspired photometric proxy)** | multi-view L1/SSIM 또는 NCC | **필수 강화군**; 사전 GT 아닌 RGB |
| **B8** | **DoG input-vs-render occupancy (GeoGS-B-inspired insertion proxy)** | map redundancy/생성 필요성 | **필수 강화군**, 동일 후보 풀에서 mask 적용 |
| B9 | Depth/normal prior match or simple dist/smoothness proxy | geometry prior & surface regularization | 시간 허용 시 진단용; GeoGS-A full model 아님 |
| **P1** | E2 source-disjoint plane/ray support | 후보별 provenance, valid support | 주 제안 최소판 |
| **P2** | P1 + reliability/occlusion + DEFER | 후보별 신뢰도·보류 | 주 제안 완성판 |
| **P3** | P2 + RGB reprojection evidence | image evidence 융합 | 필수 ablation 또는 강한 대안; B7 순증분 검증 |
| P4 | P2 + soft projection | 위치 보정 | 선택 확장 |

**반드시 분리할 두 실험 조건:**

1. **Common-pre-map score diagnostic:** 원본 baseline에서 저장한 동일한 *후보 편입 직전* Gaussian Map snapshot에 모든 점수 계산법을 적용한다. 이는 점수의 식별력만 비교한다. 특히 DoG의 P2(렌더된 occupancy)를 **전체 시퀀스가 끝난 final map**에서 계산하면 미래 정보가 유입되므로 금지한다.
2. **Policy-specific causal replay:** 동일한 시간순 후보들을 각 정책에 순차적으로 넣고, DoG의 P2는 **해당 정책이 그 순간까지 실제로 보유한 Map**에서 매번 다시 계산한다. 이때 각 정책의 map 상태가 달라지는 것은 방법 고유의 경로의존성(path-dependence)이므로 숨기지 않으며, fixed-pool score 결과와 하나의 수치로 섞지 않는다.

또한 B7의 RGB 재투영 오차는 대체로 *픽셀/영역 단위* 신호이므로 특정 Gaussian 후보의 탓으로 바로 돌릴 수 없다. 후보의 가시적 투영 영역·깊이·실제 기여도 등을 통해 픽셀→후보 attribution을 명시한다. attribution이 불안정하다면 B7은 **영역 수준 비교군**으로 보고하고 Gaussian 단위 oracle 판정처럼 사용하지 않는다.

**비교 해석의 제한:**

- B6/B7은 GeoGS-A가 제안한 **optimization loss 전체를 재현한 결과가 아니라**, 해당 재투영·가림 요소를 후보 편입 결정용 점수로 변형한 `inspired proxy`다. 실제 GeoGS-A 수치와 직접 순위를 매기지 않는다.
- B8도 B의 VGGT/geometric prior + RGB/pose joint optimizer 전체가 아니라 **DoG 기반 insertion selection**을 동일 후보에 적용한 proxy다.
- B6 vs P1은 **cross-view 자체**의 효과가 아니라 *candidate-level 보수적 admission / 수용·보류 로직*의 순이익을 검증한다.
- P3가 B7과 P2 양쪽보다 못하면 RGB 융합을 성능 개선 기여라고 주장하지 않는다.

---

# 8. 단계별 실험 매트릭스 (사전등록)

| 실험 | 최소 비교 | 핵심 평가 | 다음 단계로 넘어갈 조건 |
|---|---|---|---|
| **E0: Reproducibility + feasibility** | B0/B1 | pose, candidate pool/lineage 추출, active/resident, GT 분할, VRAM | 재현 가능하고 GT 기반 평가가 작동 |
| **E0b: Ancestry/causality audit** | self/E1/E2 | source disjoint 가능 후보 비율, parallax, temporal delay, fused contamination | source-분리 관측이 의미 있는 양 존재하거나 pivot |
| **E1: Error taxonomy** | B1 | GT depth/mesh vs candidate center/ellipsoid/rasterized depth, floaters/duplicates/missing | 실제 outlier가 유의미하게 존재해야 함 |
| **E2: Signal discriminability** | B2/B5/B6/B7/B8/P1 | GT bad-candidate PR-AUC, high-inlier-recall precision, coverage of evaluable candidates, false rejection | P1이 교차시점 약한 baseline에 유용한 증가분을 보이는지 |
| **E2b: Repeated observations & threshold transfer** | B2/B6/B7/B8/P1, 기존 점수 vs 개발 구간에서 정한 정규화 | 동시 2+ 유효 관측 coverage, 첫 반복 관측까지 지연, 분리된 개발·평가 구간의 정상 보존율·bad recall·정밀도 | 반복 관측과 봉인된 임계값의 유효 거부 운영점을 모두 확보해야 E3 검증 진행 (§8.1) |
| **E3: Admission decision — 실행 완료·REVISE** | B6/B7/B8/P1/P2/P3 | GT error, inlier retention, DEFER delay, policy support/unknown | hard DEFER의 coverage 손실 및 부분집합 오거부로 개선 주장 보류 (§8.2) |
| **E3b: Provisional admission — 실행 완료·REVISE** | legacy vs 부분집합 보정 B6/B7/B8/P, 시간 지속성 | 정상 active/finite/common 보존, bad recall, 실제 맵 coverage, 새 room1 전이 | 보존·coverage 보완 통과, 공통 후보 B6 대비 추가 우위 미확인 (§8.3); E4 보류 |
| **E4: Matched budget** | B1~B8/P1~P3 | active/resident/sh/MB, PSNR/SSIM/LPIPS, TSDF accuracy/completion | 적어도 사전 정의된 효과 기준에서 비열등/개선 |
| **E5: Shared-bias synthetic stress** | E0/E2/P2, optional model-disjoint | 공통 depth offset, scale bias, pose error, occlusion, textureless | failure envelope 정량화 |
| **E6: Causal online replay** | B8/P2/P3, DEFER vs BYPASS | real-time availability, queue age/size, time-to-admit, temporary holes | offline oracle 이득이 online에서도 유지되는지 |
| **E7: Refinement sensitivity** | baseline/proposed + **동일** optimizer steps | map repair로 필터 이득이 소멸하는가, online budget | 추가 구현 가치 결정 |
| **E8: Long sequence and loop closure** | B1/B8/P2 | revision correctness, map tearing controls, resident VRAM vs revisit | 시간/메모리 측정이 가능 |
| **E9: Drone pilot/domain shift** | B1/B8/P2 | geometry failure taxonomy, held-out view, scale & rolling shutter | 결과는 정성 또는 독립 GT 가능 시 정량 |
| **E10 (선택): correction/dedup** | matched controls | soft projection, keep-best, compact VRAM | E4 성공 후 선택 |

**우선순위:** E0 → E0b → E1 → E2 → **E2b → Go/Revise/No-Go** → E3 → E3b → 동일 관측 자격 보완(E3c) → 조건 충족 후 E4 → E5/E6 → E7/E8/E9. 첫 8주를 목표로 강한 baseline 대비 가설의 효용 여부를 판단하되, 앞 단계 기준 미달 시 이후 효능 검증을 앞당기지 않고 일정을 재조정한다.

## 8.1. E2b: 반복 유효 관측 확보 및 임계값 전이 검증

**상태: 실행 완료(2026-10-20), GO for E3 validation.** 상세 절차와 지표·판정 정의는 [E2b 실험 보고서](experiments/E2b_repeated_observations_threshold_transfer.md)에 둔다. §4의 증거 등급 `E2 source-disjoint`와 이 절의 실험 ID `E2b`를 구별한다.

**측정 경과:** office0 개발 / room0 평가를 각각 원본 1,000프레임·짝수 500입력으로 실행했다. 인과적 재평가 후 동시 2+ 관측 coverage는 **20.58% / 16.14%**였다. 개발에서 선택한 relative 정규화·반대 증거 보호 규칙과 임계값 **0.03581599**를 고정 적용한 room0 결과는 **GT bad 거부 판정 1,107개, normal 오거부 80개, 판정불명 거부 40개**, 전체/2+ 관측 normal 보존 **99.9887% / 99.9444%**, 전체/2+ 관측 bad recall **3.3742% / 31.8286%**로 사전 기준을 충족했다. 실제 Map 삭제는 수행하지 않았다. 유한 점수 normal 집합의 보존율은 **98.53%**이며 공통 집합에서 B6/confidence 대비 일관된 우위는 없어, **E3에서 부분집합 위험과 강한 대조군 대비 정책 순이익을 검증**한다. 연구 전체 GO로 확대하지 않는다.

**추가 근거:** [E2 단일 장면 파일럿](experiments/E2_signal_discriminability.md)은 좁은 공통 집합의 제한적 AP 기준을 통과했지만, 동시 2+ 유효 plane 관측 후보가 0개였고 개발 임계값을 평가 구간에 적용한 P1 bad recall도 0%였다. E2b는 이 결과를 실패로 소급 재판정하지 않고, **반복 증거를 이용한 유효 거부 운영점을 새 분할에서 검증**한다.

1. **관측 확보:** 더 긴 연속 구간·재방문 시퀀스를 우선 사용한다. 원본 KF 선택·후보 생성·tracking은 유지하며, 별도 raw 관측 풀 확장은 분리된 arm으로 기록한다. 후보 출처와 분리되고 시차·가시성·깊이 경계·평면 신뢰도 조건을 만족하는 **서로 다른 관측 2개 이상이 같은 판단 snapshot에 존재**해야 한다. 과거와 미래 snapshot의 유효 관측 수를 합산하지 않는다. 관측 간 공유 이미지·모델 bias도 별도 기록한다.
2. **개발·평가 분리:** 기존 office0/E2는 개발·실패 분석용이다. 주 전이 검증은 개발과 평가를 서로 다른 장면으로 나누고, 후보·관측의 원본 이미지/pair가 분할을 가로지르지 않게 한다. 같은 장면의 시간 분할만 가능하면 보조 파일럿으로 명시한다. 입력 RGB는 인과적으로 관측에 사용할 수 있지만 GT와 NVS held-out RGB는 편입 증거로 쓰지 않는다.
3. **점수·임계값 봉인:** 기존 E2 점수를 기준으로 두고, 정규화 수정은 개발 구간에서만 선택한다. 정상 보존 목표 99%가 주 운영점, 95%는 민감도 분석이다. 관측 자격·최소 시차·patch 조건·정규화·집계·재판정 시점·임계값을 평가 전에 설정/코드 hash와 함께 봉인한다. 평가 결과에 맞춘 수정은 새 개발 iteration이며 새 평가 분할이 필요하다.
4. **인과적 거부 진단:** 새 KF가 도착할 때만 재평가하고 동일 revision에서 2개 이상 관측의 front/free-space 충돌이 각각 봉인된 기준을 넘을 때만 `would_reject`를 기록한다. 관측 부재·가림·상충 증거는 `UNKNOWN/DEFER`이며 정상·불량으로 치환하지 않는다. E2b는 고정 후보에 대한 거부 가능성 진단이고, 정책별 Map 갱신·실제 DEFER queue·삭제 후 품질 검증은 E3 이후에 수행한다.
5. **비교·진행 기준:** B2/B6/B7/B8/P1을 동일 후보 공통 집합과 각 방법의 전체 적용 범위에서 비교한다. **계획값**으로 평가 장면별 2+ 관측 coverage ≥1%, 해당 GT-labeled 후보 bad/normal 각각 ≥100개를 요구한다. P1 반복 충돌 운영점은 **전체 및 관측 가능한 normal 보존율 각각 ≥99%, 전체 bad recall ≥1%, 관측 가능한 bad recall ≥5%, GT bad 거부 판정 ≥30개**를 모두 만족해야 한다. 아무것도 거부하지 않는 운영점은 통과가 아니다. 수치는 E2 결과에서 달성한 값이 아니며 새 평가를 열기 전에 봉인한다.

**E3 진행 판단:** 위 관측·운영점·누설 방지 조건을 충족하면 **E3 검증을 위한 GO**로 기록한다. Confidence/B6/B7 대비 추가 이익은 동일 정상 보존 제약과 공통 후보에서 보고하고, 아직 확인되지 않으면 E3의 필수 비교 가설로 유지한다. 이는 연구 전체 GO, 장면 일반화, 실제 Map 품질 개선의 입증이 아니다. 관측 부족 또는 높은 정상 손실/무효한 bad recall이면 **REVISE**, 추가 장면이 없어 시간 분할만 수행했다면 **파일럿 결과만 보고**한다. 평가 장면 중 기준 미달 장면을 제외해 통과시키지 않는다.

---

## 8.2. E3: 실제 admission·DEFER 정책 비교 결과

**상태: 실행 완료(2026-10-21), REVISE.** [E3 실험 보고서](experiments/E3_admission_decision.md)에 정책 정의·봉인·원본 active 후보 범위·결과·재현 명령을 기록했다. 기존 office0 개발 / room0 평가를 재사용했으므로 새 독립 test로 해석하지 않는다. E3 당시 샌드박스에서 GPU가 보이지 않아 개발 장면의 CUDA 저장 RGB pre-map 대조(PSNR 54.7–60.7 dB)를 통과한 CPU 수치 적응 렌더러로 모든 정책을 동일하게 비교했다. 후속 E3b에서 샌드박스 밖 GPU 접근을 확인했다. E3의 GPU latency/VRAM 개선과 E6 온라인 시스템 통과를 주장하지 않는다.

room0 원본 active **1,008,252개**에서 B1/B2/B6/B7/B8/P1 및 DEFER/BYPASS ablation을 포함한 **10개 정책**을 실행하고 실제 membership의 compact map을 렌더했다. E2b office0 개발 전용 **active** 임계값을 유지했으며, P2의 반복 relative 임계값은 **0.0359322727**이다. E2b raw 전체의 임계값·분모와 구별한다.

| 정책 | GT bad / normal 거부 | 정상 active 보존 | 전체 bad recall | GT 깊이 L1 | held-out 깊이 coverage |
|---|---:|---:|---:|---:|---:|
| B1 원본 | 0 / 0 | 100% | 0% | 0.09419 m | 93.8234% |
| B6 depth proxy | 2,844 / 621 | 99.9103% | 9.1353% | 0.08877 m | 93.8163% |
| P2 즉시 BYPASS 후 재검사 | 1,105 / 79 | 99.9886% | 3.5494% | 0.09111 m | 93.8234% |
| P2 DEFER, 2-KF timeout | 1,105 / 79 | 77.5857% | 3.5494% | 0.10729 m | 73.9651% |
| P3 DEFER + RGB AND | 6 / 0 | 77.5971% | 0.0193% | 0.11053 m | 73.9651% |

P2는 종료 시 **282,890개**가 미판정 queue에 남았다. 정상 후보를 거부하지 않은 비율 99.9886%와 실제 맵에 표현한 비율 77.5857%는 다르다. 동일 기하 gate의 DEFER/BYPASS는 같은 후보를 같은 시점에 거부했으므로 이번 fixed-raw 조건에서 DEFER 자체의 추가 불량 제거 이득은 없었다. 무제한 DEFER는 정상 active 보존 20.07%, 깊이 coverage 26.40%로 더 악화됐다.

P2의 유한 점수 normal 비거부율은 **98.5489%**, 모든 신호 공통 후보의 normal 비거부율은 **96.6483%**로 99% 부분집합 보호 기준도 충족하지 않았다. 공통 후보에서 P2 정밀도 77.56%는 B6 83.13%, B7 86.96%보다 낮았다. 자연 작동점에서는 P2의 낮은 오거부와 B6의 높은 bad recall 사이 trade-off가 있으며 지배적 우위가 아니다. P3는 과도하게 보수적인 회수율을 보였다. 이 결과에 맞춰 임계값이나 timeout을 이동시키지 않았다.

**후속 조치:** hard DEFER와 RGB AND의 개선 주장을 보류하고, provisional/BYPASS 편입 뒤 재검사·보류 대상 축소를 개발 단계에서 검토한다. E4 matched-budget·TSDF·NVS 및 새 장면 검증은 별도다. 이번 결과를 연구 전체 GO 또는 알고리즘의 보편적 무효로 확대하지 않는다.

---

## 8.3. E3b: 임시 편입·부분집합 보정 및 새 장면 평가

**상태: 실행 완료(2026-10-21), REVISE / E4 보류.** [E3b 실험 보고서](experiments/E3b_provisional_admission.md)에 11개 정책의 개발·회귀·새 장면 결과, 봉인, 후보별 무결성 검증과 재현 명령을 기록했다. GPU 접근 문제는 샌드박스 밖에서 해결해, 동일 RTX 5060·backbone·weights·설정으로 아직 평가하지 않은 **room1 원본 1,000프레임/500입력·10-KF** 기준선을 새로 생성했다. office0 개발 / room0 회귀 / room1 새 평가를 구분하며 room1 결과에 맞춰 정책을 다시 조정하지 않았다.

미관측 후보를 렌더 가능한 `PROVISIONAL`로 즉시 편입하고 실제 KF 도착 시 재검사한다. queue는 0개다. 개발 normal의 자체 유한 점수·모든 신호 공통·충분한 anchor KF별 정상 보존 99% 임계값 중 최댓값을 고정했다. 주 정책의 반복 relative 임계값은 **0.0560654998**이다. 이 방식은 검증 전 차단보다 임시 편입 뒤 사후 제거에 가까우며, 확인 전 불량의 노출 위험을 제거하지 않는다.

| 장면 / 주 정책 | GT bad / normal 제거 | 유한 normal 보존 | 공통 normal 보존 | 전체 bad recall | 깊이 coverage |
|---|---:|---:|---:|---:|---:|
| room0 회귀, P_safe | 823 / 6 | 99.8898% | 99.7454% | 2.6436% | 93.8234% — 원본과 동일 |
| room1 새 평가, P_safe | 5,104 / 0 | 100% | 100% | 1.5354% | 87.8749% — 원본과 동일 |

room1 원본 active 후보는 **1,399,108개**다. P_safe의 유한 점수 후보는 **63,081개(4.51%)**이며 미판정 후보를 정상으로 인증한 것이 아니다. 두 연속 KF 충돌을 요구하는 P_persist는 room0 부분집합 정상 보존에 실패했고 room1은 bad 4,845개·normal 0개를 제거했다. 별도 개발 보정으로 임계값도 달라, 시간 지속성만의 단일 변수 효과로 해석하지 않는다.

**보완 목표와 추가 우위를 구별한다.** 주 정책은 두 장면에서 정상 보존·bad recall·coverage 기준을 통과했다. 그러나 room1 모든 신호 공통 후보에서 **B6_safe도 정밀도 100%**로 bad **4,966개**를 제거했고 P_safe는 **4,338개**를 제거했다. “모든 강한 대조군보다 정밀도 +2pp”라는 봉인 기준은 충족하지 못했다. B6가 100%일 때 수학적으로 달성 불가능한 조건이지만, 결과를 보고 기준을 바꾸어 GO로 기록하지 않는다. 같은 공통 집합에서 B6의 회수량도 더 많아 추가 정책의 순이익은 아직 입증되지 않았다.

**다음 조치:** E4로 바로 진행하지 않고 **E3c에서 B6와 plane에 동일한 시점별 관측 자격·support veto·위험 보정을 적용**해 점수 자체의 추가 가치를 분리한다. 고정된 공통 후보 진단과 실제 인과적 자격 gate를 혼동하지 않는다. room1을 사후 재튜닝 test로 써 이번 실행을 성공으로 소급하지 않으며, 이후 진행 조건과 새 평가 분할은 별도 봉인한다. 다장면 일반화·통계적 유의성·메모리 또는 실시간 개선·논문 novelty의 입증은 아니다.

---

# 9. 평가 데이터·분할·출력 정의

## 9.1. 정량 평가 데이터

- **Replica(우선):** RGB/GT pose/dense mesh가 있는 시퀀스로 outlier/GT rendered depth·TSDF geometry·NVS 테스트를 구성. A와 B가 공통으로 사용하므로 비교 문헌과의 맥락 설명이 수월하나 직접 수치 우열은 금지.
- **ScanNet++(우선 두 번째):** GT mesh/pose 및 실제 실내 RGB. GeoGS-A에서 4개 시퀀스 geometry를 평가하므로 별도 domain 확인. 각 capture 조건 및 제공되는 데이터 사용 범위를 확인.
- **TUM RGB-D(보조):** RGB-only 입력으로 제한하며 depth는 validation/evaluation reference로만. trajectory-only 아닌 GT depth의 coverage/mask 점검.
- **DTU(선택, offline geometry probe):** A의 2분 예산 실험 맥락에서 geometry-only 참고 가능. **순차 비디오 SLAM과 입력/목적이 달라 main online table에 섞지 않음.**
- **드론 RGB:** 1~2개 짧은 scene을 1~4주차에 확보. GT mesh/depth가 없다면 정확도 수치 대신 held-out RGB, off-axis holes, 실패 유형, tracking diagnostics만 제시.

## 9.2. 엄격한 데이터 누설 관리

- 지도 후보 생성에 사용된 frame/pair, admission evidence frame, validation/test frame, GT 평가 장면을 기록한다.
- GT mesh/depth가 불완전하거나 실제 스캔 범위 밖이면 GT 미기록 공간을 **빈 공간 또는 outlier label**로 취급하지 않는다. 분류용 유효 영역 마스크와 depth sensing range를 명시한다.
- Held-out RGB를 **어떤 방식의 map update, 후보 결정, threshold 조정, optimization에도 사용하지 않는다.**
- 단순 ‘인접 프레임을 test로 빼놓았다’만으로 독립적인 novel view가 되지 않을 수 있으므로 (i) temporal gap, (ii) viewpoint angular gap, (iii) overlap region을 보고한다.
- 평가를 scene 단위로 집계한다. keyframe 수를 독립 반복 시행으로 간주한 유의성 과장은 금지한다.

## 9.3. 기하 및 outlier 지표

**일반 Gaussian의 중심만으로 물리적 표면을 정의하지 않는다.** 결과 보고는 다음 3수준으로 분리한다.

1. **Center proxy:** $d(\mu_i, S_{\mathrm{GT}})$에 대한 후보별 탐색성/PR-AUC. 이 값은 GT floater의 엄밀한 정의가 아니라 기하 proxy임을 표기.
2. **Projected Gaussian contribution:** 각 후보의 $\mathrm{opacity} \times \text{screen-space footprint}$가 **GT depth보다 앞선 free-space에 불필요한 density를 생성하는 정도**, 가림/경계/얇은 물체 마스크. 먼저 synthetic unit-test로 타당성 점검.
3. **Rendered geometry:** 고정 GT-aligned/estimated poses에서 rendered depth/normal 비교, **동일 절차의 TSDF depth fusion**으로 Accuracy, Completeness, completeness ratio, Chamfer. A가 사용한 rendered-depth→TSDF 평가 취지를 반영한다.

반드시 같이 기록할 보호 지표:

- **Inlier retention**, **false rejection** (GT로 유효하다고 분류된 후보의 손실)
- **Reconstructable surface coverage / completeness**, thin structures and depth-boundary recall
- **Outlier PR-AUC/precision-recall**은 *eval 가능한 후보 집합*과 전체 후보 집합에서의 eligible fraction을 함께 표기
- **DEFER / BYPASS** 후보 개수 및 deferred 후보의 시간에 따른 표현 공백
- per-scene variance, 실패 사례(무텍스처·반사·식생·sky·dynamic·large baseline·좁은 baseline)

## 9.4. RGB 지표

PSNR/SSIM/LPIPS(held-out). 영상은 동일 pose·해상도·노출보정·배경처리·마스크와 geometry cutoff를 사용. 입력 시점 사이와 **위/측면 off-axis view**를 구분하고 정량화는 실제 reference RGB가 있을 때만 수행. B의 높은 PSNR 숫자만으로 geometric outlier가 적다고 해석하지 않는다.

## 9.5. 예산 및 비용 지표

- **예산 1:** $N_{\mathrm{active}}$로 정렬 (기본)
- **예산 2:** **serialized bytes** / GPU **$N_{\mathrm{resident}}$, allocated VRAM** (별도; SH와 Gaussian parameter 수가 달라질 때 특히 중요)
- **예산 3:** cost-matched (preprocess/matching/PCA/refiner 포함 총 GPU seconds 또는 ms/KF)
- `DEFER`로 GPU map을 줄인 경우 CPU queue 메모리와 가용 시점 지연을 반드시 포함.
- active mask는 GPU memory saving이 아니다. physical compact buffer 적용 전후를 측정.
- system input FPS, tracking FPS, per-KF mapping latency(mean/median/p95), rendering FPS, total wall-clock speed를 **각각** 보고.

---

# 10. 핵심 Go / Revise / No-Go 파일럿 (4~8주차)

## 10.1. 준비물

Replica 1개 + ScanNet++ 1개(확보 가능한 경우), 드론 짧은 시퀀스 1개. 공통 tracker/후보 export, GT mesh/depth evaluator, lineage checker, masked reprojection baseline.

## 10.2. 실험 절차

1. 고정 baseline run에서 Gaussian 후보와 source ancestry를 저장; end-to-end timestamp 및 pose revision 기록.
2. 후보를 `real geometry outlier / redundant-but-valid / well-placed / unobserved-or-ambiguous`로 분리하고 내부 outlier 정의의 라벨 품질을 점검. 이는 GT에서 명확히 구분 가능한 범위에만 적용.
3. E0/E1/E2/E4 evidence grade별 eligible candidate 비율과 평가 가능한 면적·시차 분포를 계산.
4. 공통 후보에서 confidence/self/B6 depth/B7 photometric/B8 DoG/P1 후보 score를 모두 추출 (가능한 후보에 한정).
5. GT outlier PR-AUC, fixed-inlier-retention에서의 outlier 제거율, false reject, coverage/geometry와의 상관을 비교.
   - **E2b 보완 단계:** §8.1에 따라 반복 관측을 확보하고 개발·평가 분할을 봉인한 뒤, 정상 보존과 유효 bad recall을 동시에 검증한다. E2의 AP 개선만으로 E3 진행을 확정하지 않는다.
6. 동일한 naturally achieved budget과 사전등록된 budget-constrained ranking을 **구분해서** 비교. 삽입 수·runtime·queue memory·temporary hole을 기록.
7. **상관 bias 합성 실험**: 같은 방향으로 모든 pointmap과 Gaussian을 0.1–0.3m 등 다양한 크기로 이동시켜(Eval scale에 맞춘 별도 범위 포함), cross-view consensus가 참이라고 오판하는 조건을 확인. 같은 위치로 pose도 함께 바뀌는 설정과 geometry-only bias를 분리.
8. 과거 관측만 존재할 때 결과와 미래 관측 허용 oracle 결과를 분리.

## 10.3. 판정 매트릭스

| 관측 결과 | 판정 | 조치 |
|---|---|---|
| E2에서 제한적 ranking 개선은 있으나 2+ 유효 관측 또는 전이된 거부 운영점이 없음 | **REVISE → E2b** | 반복 관측 확보·개발/평가 분리·정규화/임계값 전이를 먼저 검증 |
| E2b의 관측·정상 보존·bad recall 기준을 봉인된 장면 분할에서 충족 | **GO for E3 validation** | 실제 admission 비교 진행; 연구 전체 GO와 구별 |
| E2b 관측·전이 조건을 충족하고 E3/E4에서 P2/P3가 B6/B7/B8보다 false reject·coverage 제약 하에서 outlier 정밀도를 개선 | **GO** | candidate admission 연구 진행, online replay 통과 시 제목 확정 |
| E2는 유용하나 B7과 차이가 없어 photo-only가 사실상 충분 | **REVISE** | 복잡한 PCA/ancestry gate 축소; ‘언제 교차 기하 추가가 필요한가’ 실패 조건 연구로 전환 |
| B8만으로 중복/메모리 문제가 해결되고 outlier 문제는 작음 | **PIVOT** | outlier 감소로 novelty 주장 중단; admission에서 redundancy 보호/계층화 과제로 수정 |
| source-disjoint가 불가하거나 공유 bias로 E2가 무력 | **NO-GO for independence claim** | 별도 predictor/원본 RGB 교차검증 또는 문제 범위 변경. 정량 독립성 주장하지 않음 |
| offline-oracle에서만 좋은데 causal replay가 비용·보류로 무력 | **NO-GO for online claim** | offline postfilter 평가로 제한하거나 지연 허용 정책 재설계 |
| GT geometry와 coverage 이득이 없거나 false rejects가 중대 | **NO-GO for improvement claim** | 실패 분석만 결과로 보관; 결과를 ‘개선’으로 포장하지 않음 |

정량 Go 기준(허용 완료율 감소, 렌더링 저하 폭, 최소 detectable gain, target Gaussian budget, 최소 eligible fraction)은 **pilot 전 validation 구성/허용 위험에 따라 문서화**하고 test 결과를 본 뒤 이동시키지 않는다. 예시 임계값은 성능을 선약하는 방식으로 기재하지 않는다.

---

# 11. 절차적 대조실험 및 ablation 세부 항목

## 11.1. Source independence ablation

- self prediction → 다른 프레임이나 source overlap → raw source-disjoint → independent model prior(선택) → RGB reprojection add-on.
- 공유 model error, 같은 overlap frame이 두 pair에 포함된 경우, global fused geometry로 인한 contamination을 개별 계수.
- 이미지쌍 분리를 유지하면서 baseline angle만 증가할 때 깊이 분류 성능이 어떻게 변하는지 plot.

## 11.2. Candidate gate ablation

- Distance only; Distance+depth ordering; +occlusion; +source eligibility; +surface fit; +DEFER; +RGB.
- 각각 변경 **한 개 변수**, 같은 threshold-tuning budget 유지.
- $\text{NO\_SURFACE} \rightarrow \text{REJECT}$는 금지, $\text{NO\_SURFACE} \rightarrow \text{KEEP}$/`DEFER` 결과를 모두 측정.

## 11.3. Strong baseline ablation

- DoG (B8)만 적용한 경우와 DoG+proposed gate를 비교하여 **DoG 이후 남은 Gaussian의 geometry**가 개선되는지 평가.
- GeoGS-A-inspired masked reprojection (B6/B7)을 score/ranker로 만든 경우와 P2/P3를 비교해 source-trace·uncertainty의 순이익을 분석.
- 공통 refiner에서 같은 gradient steps, keyframe schedule, loss weights를 적용한 다음에도 편입 정책 차이가 남는지 검사.
- A의 Coherent map update와 본 연구의 anchor-local cache 방식을 섞지 않으며 동일 map의 pose revision correctness만 단위 테스트.

## 11.4. Budget curve 및 group-by reporting

- 타깃 budget 예: validation에서 사전 선택한 3~5개 fraction; 모든 방법 동일 map 시점에서 결과.
- 중복 많은 벽/바닥, 반복 방문, single-view edge, vegetation, 얇은 구조를 나누어 보고.
- 자연적 reject 비율이 서로 다르면 **서로 다른 실제 작동점**을 먼저 보여주고 예산 강제 맞춤은 2차 분석으로 표시.
- 랜덤 thinning은 적어도 3 seed, 가능하면 5 seed로 변동성 보고.

---

# 12. 구현 계획 및 데이터 모델

## 12.1. 권장 모듈

```text
research/
  export/
    candidate_dump.py            # t/source/pose/mean/q/scale/opacity/sh/conf
    pointmap_raw_and_fused.py    # raw vs fused provenance
    pose_revision.py
  observations/
    lineage_graph.py            # candidate→source images/pairs, shared ancestry
    causal_registry.py          # available-by-t only
    projective_matching.py      # pinhole or ray-map matching
    visibility_and_free_space.py
  features/
    surface_patch.py            # PCA (baseline-derived), visibility, residuals
    photometric_reprojection.py # GeoGS-A-inspired B7
    dog_occupancy.py            # GeoGS-B-inspired B8
    gaussian_confidence.py
  admission/
    baseline_scores.py
    gate.py                     # KEEP/REJECT/DEFER/BYPASS
    deferred_queue.py           # age/status/CPU+GPU memory
    decision_log.py
  map/
    frozen_candidate_pool.py
    sim3.py
    cache_revision.py
    compact.py
  evaluation/
    gt_geometry.py              # GT rendered depth; TSDF meshes
    rendered_rgb.py
    selective_metrics.py        # eligible coverage, GT precision/recall
    budget_cost.py
    online_replay.py
    failure_taxonomy.py
  experiments/
    E0_exports.py
    E1_error_taxonomy.py
    E2_score_ablation.py
    E2b_observation_threshold_transfer.py
    E3_decision_ablation.py
    E4_matched_budget.py
    E5_correlated_bias.py
    E6_causal_replay.py
    E7_refiner.py
  configs/  results/  tests/
```

위 디렉터리와 인터페이스는 제안 구조다. E0–E2에서 확인한 실제 CLI·tensor·구현 경로는 각 실험 보고서와 실행 manifest를 따른다. E2b 항목은 추가할 모듈의 역할을 나타내며 구현 완료를 뜻하지 않는다.

## 12.2. 기록 자료구조(최소 계약)

```python
@dataclass
class Candidate:
    candidate_id: int
    timestamp: float
    anchor_kf: int
    source_image_ids: tuple[int, ...]
    source_pair_ids: tuple[int, ...]
    source_model_id: str
    pose_revision: int
    mean_local: object
    scale_local: object
    quat_local: object
    opacity: float
    sh: object
    confidence_raw: float

@dataclass
class Evidence:
    candidate_id: int
    observation_kf: int
    observed_by_time: int
    eligible_source_disjoint: bool
    ancestry_verified: bool
    same_model: bool
    visibility_state: str   # VISIBLE / OCCLUDED / OUT_OF_VIEW / UNKNOWN
    parallax: float | None
    signed_depth_residual: float | None
    plane_residual: float | None
    rgb_reprojection_residual: float | None
    surface_reliability: float | None
    pose_revision: int

@dataclass
class Decision:
    candidate_id: int
    decided_at_kf: int
    action: str             # KEEP / REJECT / DEFER / BYPASS
    reason: str
    eligible_view_count: int
    unverified_ancestry: bool
    threshold_config_id: str
    pose_revision: int
```

## 12.3. 필수 unit / synthetic tests

1. flat plane, curved surface, line-shaped neighbor, two adjacent surfaces, tiny thin structure, strong depth edge.
2. front-of-surface fake Gaussian과 **behind-surface occluded valid Gaussian**의 행동을 구별.
3. source pair overlap, shared fused ancestry, model-shared but source-disjoint, future-only support의 `independent/eligible` 처리.
4. same-geometry bias 및 scale drift; GT relative correctness와 내부 residual divergence.
5. Sim(3) round-trip for mean/covariance, quaternion convention, cache invalidation after BA.
6. masked cross-view RGB reprojection with moving objects/illumination/sky.
7. Gaussian count vs buffer residency vs memory bytes/physical compaction.
8. deterministic budget acceptance and fail-to-reach-budget reporting.

---

# 13. 16주 일정(신규 강한 baseline을 우선하도록 조정)

| 기간 | 할 일 | 종료 조건 |
|---|---|---|
| **1–2주** | repo/weight/환경 고정, candidate+raw/fused exports, Replica GT evaluator | E0, A/B 논문 주장 구분표, candidate provenance 1개 장면 검증 |
| **3–4주** | drone 1–2 short pilots, source disjoint 추적, simulated visibility test, basic DoG B8 | 독립성 계층표·source availability·B8 preview |
| **5–6주** | geometric depth/reprojection B6, masked RGB reprojection B7, confidence/self baselines | B1–B8 공정 baseline score, GT precision/coverage |
| **7–8주** | E1/E2 결과 점검, E2b 긴/재방문 시퀀스·분리된 개발/평가·반복 관측·임계값 전이 | **E2b Go/Revise/No-Go** 결정; 정상 보존과 유효 bad recall 동시 검증 |
| **9–10주** | E2b 통과 후 E3 admission/DEFER vs BYPASS, E4 matched-budget + GT rendered depth/TSDF geometry/held-out NVS | strong baseline 대비 정책/Pareto 결과·paired scenes; E2b 미달 시 보완 우선 및 일정 재조정 |
| **11–12주** | shared-bias synthetic, causal replay, optional E3 model-disjoint | online-eligibility/queue harm, failure envelope |
| **13주** | 동일 refiner/no refiner/pose revision & compaction | 외생 최적화 영향·resident VRAM 결과 |
| **14주** | drone extrapolation/viewpoint coverage, long sequences | domain failure/latency 결과 |
| **15주** | re-run validation/test 봉인 protocol, figure/table/scene statistics | reproducibility report, final comparison |
| **16주 이후** | 논문 집필; 효과 없으면 novelty/제목 축소 | 자료·부정적 결과 포함 최종 본문 |

**우선순위 제약:** B6/B7/B8가 아직 없다면 projection/advanced dedup을 먼저 개발하지 않는다. 이전 v2에서 선택확장에 썼던 시간을 **GeoGS-inspired 강한 baseline과 causal validation**에 재배분한다.

---

# 14. 결과표 서식 (숫자는 실험 후)

## 14.1. Primary: online policy, fixed candidate pool, no refiner

| Method | GT outlier precision ↑ | Outlier recall ↑ | Inlier retention ↑ | Eligible candidates % ↑ | Deferred age p95 ↓ | GT accuracy ↓ | GT completion ↑ | PSNR ↑ | LPIPS ↓ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B1 original | | | | | | | | | |
| B2 confidence | | | | | | | | | |
| B4 voxel | | | | | | | | | |
| B6 masked-depth reproj (proxy) | | | | | | | | | |
| B7 masked-RGB reproj (proxy) | | | | | | | | | |
| B8 DoG occupancy (proxy) | | | | | | | | | |
| P1 source-disjoint | | | | | | | | | |
| P2 + reliability/defer | | | | | | | | | |
| P3 + RGB | | | | | | | | | |

## 14.2. Budget and hardware

| Method | Natural $N_{\mathrm{active}}$ | Target $N_{\mathrm{active}}$ | Budget reachable? | $N_{\mathrm{resident}}$ | Serialized MB | peak VRAM | CPU queue MB | Mapping ms/KF median/p95 |
|---|---:|---:|:---:|---:|---:|---:|---:|---:|
| Original | | | | | | | | |
| DoG proxy | | | | | | | | |
| Reprojection proxy | | | | | | | | |
| Evidence-aware | | | | | | | | |

## 14.3. Causal vs hindsight 결과

| Policy | Past-only completed decisions % | Mean/p95 DEFER frames | Temporary hole rate | Final GT accuracy | Final completeness | Future-aware oracle upper bound (separate) |
|---|---:|---:|---:|---:|---:|---:|
| Immediate keep | | | | | | |
| Immediate reject | | | | | | |
| DEFER/recheck | | | | | | |

---

# 15. 논문 기여 및 한계: 사후에만 확정

## 15.1. 실험이 실제로 뒷받침할 경우에만 주장할 항목

1. **영상 출처·가시성·surface reliability를 분리하는 feed-forward Gaussian candidate admission 정책**의 재현 가능한 구현과 그 유효 범위.
2. **Evidence-absent 상태를 명시적 보류로 처리하는 정책**이 즉시 삭제/유지 대비 제공하는 quality–delay–memory trade-off.
3. **동일 후보·tracking·budget 조건에서** confidence, DoG, simple reprojection, raw source filtering과 비교한 outlier/geometry/rendering 결과.
4. Shared-model bias, small-baseline, occlusion 및 drone domain shift에서의 실패 조건과 검출 신호의 한계.

## 15.2. 반드시 피해야 하는 주장

- ‘교차시점으로 기하를 맞추는 최초의 방법’, ‘Local PCA로 plane을 사용한 최초의 Gaussian SLAM’, ‘loop-closure coherent Sim(3)의 신규 방법’, ‘geometry prior+RGB 3DGS의 최초 결합’.
- GT pose를 사용한 진단 결과를 실제 RGB-only 온라인 tracking 성능이라고 기술.
- geometry-only A의 bytes/accuracy와 appearance-bearing 본 연구의 PSNR/count를 같은 표에서 동등 조건인 것처럼 비교.
- 후보의 pointmap 근접도를 **검증된 정확도**로 둔갑시키거나 false rejection/coverage를 누락.
- masked score만 구현하고 GeoGS 논문 자체를 '재현했다'고 서술.
- 미래 관측을 사용한 retrospective 성능을 online admission 성능으로 서술.

## 15.3. 연구 방향 변경 기준

- **P2/P3가 B6/B7/B8보다 의미 있는 개선이 없다면:** 상관 bias/시점 부족/coverage 손실의 학술적 실패 분석 및 독립 signal의 정보가치 실험으로 범위를 축소. 성능 개선 알고리즘이라고 주장하지 않는다.
- **DoG가 대부분 해결한다면:** 중복 Gaussian 문제를 독창성으로 주장하지 말고, *DoG가 실패하는 free-space floater 분류/오인*에만 집중하거나 주제 교체.
- **지도 geometry의 대부분이 공통적으로 잘못 추정된 경우:** 더 많은 동일 predictor 관측만으로 해결하려는 접근에서 후퇴. 별도 geometric predictor 또는 RGB photo evidence의 유효성을 확인하는 설계로 pivot; 추가 모델이 더 효과적이라면 연구 제목을 신뢰도/오류 탐지로 재정의.
- **온라인에서는 DEFER가 실용적이지 않다면:** 별도 throughput/latency 제약을 명시한 후 offline quality-control 단계로 목표 축소.

---

# 16. 핵심 자료 및 읽어야 할 위치

**첨부 논문 A**
- Zhou et al., *GeoGS-SLAM: Geometry-Only Gaussian Splatting for Dense Monocular SLAM*, arXiv:2607.07452v1 (2026-07-08).
- Section IV-C (single/multi-view losses), IV-D (PCA local-plane initialization), V-D (coherent Sim(3) map update), Section VI-A (TSDF geometry eval), Table VIII (coherent update ablation), Table X (multi-view-loss ablation).

**첨부 논문 B**
- Gao et al., *GeoGS-SLAM: Online Monocular Reconstruction Using Gaussian Splatting with Geometric Priors*, arXiv:2607.11184v1 (2026-07-13).
- Section III-B (VGGT sliding window), III-C Eqs. 6–7 (DoG map expansion), III-D Eqs. 8–10 (RGB+depth joint optimization), III-E (online loop closure), Section IV and Tables I–IV (RGB/ATE/runtime/ablation).

**기존 v2 재사용 부분**
- v2 Sections 4/10/11: 실제 export 계약·Sim(3) 변환·active/resident/VRAM 분리. v3에서 순서와 주장만 수정.
- v2 Sections 16–18: drone early pilot·GT/held-out 분할·geometry/coverage 지표. v3의 GT rendered depth/TSDF 및 online causality 조건을 우선 적용.
- v2 Sections 21–22: PCA/edge/occlusion/compaction unit tests 및 debug viewer. v3에서는 provenance·DoG/reprojection·future leakage checker를 추가.

---

# 17. 지금 바로 착수할 8개 체크리스트

- [ ] Splatt3R-SLAM에서 **source image/pair 및 un-fused pointmap 추출 가능 여부** 확인.
- [ ] 최소 Replica 1개에서 **GT rendered depth/GT mesh 비교 코드** 먼저 실행.
- [ ] Gaussian 오류를 **floating / duplicate / missing / valid**로 분해해 각각의 비율 확인.
- [ ] source-disjoint KF를 몇 개나 확보할 수 있는지, temporal delay와 baseline angle을 로그로 산출.
- [ ] **DoG B8** (source RGB vs current rendered RGB) 구현 또는 원래 논문과의 기능 차이를 문서화.
- [ ] **Masked multi-view reprojection B6/B7** baseline을 먼저 구현하고 동일 후보 풀에서 score 기록.
- [ ] P1/P2의 KEEP/REJECT/DEFER decisions를 **과거 관측만으로** 생성하고, future-aware와 구분.
- [ ] 8주차 Go/Revise/No-Go: **강한 baseline 대비 outlier/coverage/latency의 추가 이득**이 있는지 확인.

**최종 규칙:** 새로운 기법의 성공을 미리 약속하지 않는다. 연구의 학술적 가치는 다중 시점 정합성의 존재 자체가 아니라, **이미 알려진 기하·영상 신호가 실제 feed-forward Gaussian map의 어떤 후보를 언제 안전하게 제거할 수 있는지**, 그리고 **그 선택이 단순 샘플링/정합성 baseline에 비해 얼마나 유효한지**를 통제된 실험으로 밝히는 데서 판정한다.
