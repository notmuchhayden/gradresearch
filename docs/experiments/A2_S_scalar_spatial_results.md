# A2-S: Scalar bias와 공간적 depth deformation 진단

**상태: COMPLETE_DIAGNOSTIC** · 실행일: 2026-10-27 (Asia/Seoul) · [프로토콜](../../configs/a2_s_scalar_spatial_protocol.json) · [실행 manifest](../../results/A2_S_scalar_spatial/2026-10-27/execution_manifest.json) · [기계 판독 요약](../../configs/a2_s_results_summary.json)

## 범위와 실행 상태

고정된 A2-S 절차에 따라 구현과 합성 검사를 마친 뒤 preflight/등록, office2 fit/build/evaluate/analyze/verify, office2 개발 결과 봉인, office3 고정 validation 순으로 실행했다. 합성·단위 검사는 13개 모두 통과했다. 두 장면 모두 등록된 strict 후보를 그대로 유지하고, gauge/fold/method별 400개 heldout target view를 평가했다. 모든 post-prefix KF/fold에서 source 지원 기준을 통과했고, 각 장면의 네 gauge/fold 조건 모두 target 지원 기준을 통과했다. S0는 기존 저장 뷰 5개와 정확히 재현됐다. Covered mask 불일치는 0개, 공통 covered depth의 최대 차이는 0.000m였다. 별도의 cache 기반 검증기가 두 장면의 primary common3 MAE, support gate, 판정 label을 독립 재계산해 통과했다. [독립 검증 기록](../../results/A2_S_scalar_spatial/2026-10-27/independent_verification.json)을 참조한다.

`Sk`, `SkH`, `Sf`는 source GT를 사용하는 oracle 진단이다. RGB-only 보정 방법이 아니다. Office3는 이미 사용된 validation 장면이다. Office4, HKairport, A2-O, 보정 알고리즘, D/P 방법, joint optimizer는 실행하지 않았다.

## 동일 mask의 주 target 결과

`E0`, `Ek`, `Ef`는 같은 S0+Sk+Sf interior common-covered 픽셀에서 계산한 view별 MAE의 동등 가중 평균이다. Target 지원 조건은 400개 view 중 80% 이상에서 common pixel이 1,000개 이상이고, 그 수가 해당 view interior reference의 50% 이상인 것이다. Scalar 충분성 판정에는 여기에 source KF와 strict 후보 지원율 각각 80% 이상, fixed-field 이득 10% 이상, coverage 보전, scalar/field 이득 비율 0.90 이상 조건이 추가된다.

| 장면 | Gauge | Fold | E0 S0 (m) | Ek Sk (m) | Ef Sf (m) | (E0−Ek)/(E0−Ef) | 지원 target view | 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| office2 | position | 0 | 0.12341 | 0.09400 | 0.09035 | 0.890 | 400/400 | `RESIDUAL_FIELD_OPPORTUNITY` |
| office2 | position | 1 | 0.12348 | 0.09403 | 0.09122 | 0.913 | 400/400 | `SCALAR_SUFFICIENT_RELATIVE_TO_FIXED_FIELD` |
| office2 | orientation | 0 | 0.14015 | 0.09174 | 0.08463 | 0.872 | 400/400 | `RESIDUAL_FIELD_OPPORTUNITY` |
| office2 | orientation | 1 | 0.14019 | 0.09256 | 0.08464 | 0.857 | 400/400 | `RESIDUAL_FIELD_OPPORTUNITY` |
| office3 | position | 0 | 0.06712 | 0.08356 | 0.06871 | null | 400/400 | `FIELD_GAIN_NOT_ESTABLISHED` |
| office3 | position | 1 | 0.06708 | 0.08453 | 0.06955 | null | 400/400 | `FIELD_GAIN_NOT_ESTABLISHED` |
| office3 | orientation | 0 | 0.06441 | 0.08154 | 0.06744 | null | 400/400 | `FIELD_GAIN_NOT_ESTABLISHED` |
| office3 | orientation | 1 | 0.06436 | 0.08236 | 0.06906 | null | 400/400 | `FIELD_GAIN_NOT_ESTABLISHED` |

Office2에서 fixed field는 주 target MAE를 Sk보다 position gauge에서 약 0.0037m, orientation gauge에서 약 0.0071m 낮췄다. 네 조건 모두 S0 대비 field 이득이 10%를 넘었지만 scalar 충분성은 한 fold에서만 통과했다. Office3의 Sf는 S0보다 target MAE를 낮추지 못했고 Sk는 오히려 MAE를 높였다. 따라서 field 이득 gate가 성립하지 않았다. 두 장면 모두 scene-wide scalar 충분성 주장을 뒷받침하지 않는다.

Common4 loss 대조에서도 office2의 모든 fold에서 같은 순서가 나왔다. Sf의 MAE는 0.09035–0.09122m, SkH는 0.09393–0.09425m, Sk는 0.09393–0.09402m였다. Office3에서는 common4에서 Sf가 두 scalar 조건보다 나빴다. Gauge를 함께 비교한 paired common6 결과는 [gauge_pairs.csv](../../results/A2_S_scalar_spatial/2026-10-27/gauge_pairs.csv)에 저장했다.

## 교차검증 source 잔차

모든 post-prefix source KF/fold가 지원 조건을 통과했다. Office2는 10/10 KF, strict 후보 1,200,827/1,200,827개였고 office3는 7/7 KF, 855,796/855,796개였다. 최소 fit/evaluation pixel 수, 4×4 field 각 구역의 최소 표본 수, design rank 및 eigenvalue ratio 조건도 모두 통과했다. Prefix `Sg`는 기존 frame-0 KF의 guard 내부 reference-valid 픽셀만 사용했다. Fold와 무관하게 동일한 alpha를 적용했다.

지원 post-prefix KF에 대한 반대 tile Z MAE의 KF별 동등 가중 평균(m):

| 장면 | Gauge | Fold | S0 | Sg | Sk | SkH | Sf |
|---|---|---:|---:|---:|---:|---:|---:|
| office2 | position/orientation | 0 | 0.0595 | 0.1148 | 0.0279 | 0.0287 | 0.0179 |
| office2 | position/orientation | 1 | 0.0621 | 0.1179 | 0.0302 | 0.0315 | 0.0203 |
| office3 | position/orientation | 0 | 0.0547 | 0.0537 | 0.0408 | 0.0417 | 0.0259 |
| office3 | position/orientation | 1 | 0.0549 | 0.0539 | 0.0411 | 0.0419 | 0.0284 |

두 장면 모두 반대 tile source 오차에서는 Sf가 두 scalar 조건보다 낮았다. 하지만 office3 target 점수는 개선되지 않았다. 이는 source/target mismatch이므로 source field fit 이득을 target 일반화로 해석하지 않는다. KF별 Z/AbsRel/log-residual/3D 오차와 분모는 각 scene의 `analysis/source_spatial_residuals.csv`, fold별 정확한 pixel index와 hash는 `fits/source_folds.csv`에 있다.

## Coverage, 표면, 보조 RGB

Office2에서 Sk와 Sf의 interior coverage는 S0 이상이었다. 주 비교 네 조건 모두에서 interior correct coverage도 S0보다 낮지 않았다. Office3의 Sk와 Sf는 S0보다 interior correct coverage가 낮았지만, field 이득 gate부터 통과하지 못했다. View별 own-covered 지표, 전체 reference 분모의 correct coverage, depth-bin 지표는 `evaluation/target_methods.csv` 및 `evaluation/target_coverage_bins.csv`에 저장했다.

Position gauge TSDF는 고정된 20개 GT-interior view, voxel 4cm, truncation 12cm, 최대 depth 10m, seed 고정 100,000개 표면 표본, 5cm 허용오차로 계산했다. 등록된 GT-depth TSDF reference에 대해 office2 Sf chamfer는 약 0.096m로 Sk의 0.101m보다 낮았다. Office3 Sf는 0.077–0.078m, Sk는 0.089–0.090m였지만 Sf는 office3 target depth MAE를 개선하지 못했다. 이는 관측영역 TSDF 비교이며 장면 전체 completeness 주장이 아니다. 지표와 reference hash는 `evaluation/surface_metrics.csv`에 기록했다.

고정 RGB view 5개의 렌더 지표와 prediction/target/absolute-error 배열도 보조 산출물로 저장했다. 이 값은 RGB가 GT fit 보정을 추론하거나 적용할 수 있는지를 시험하지 않는다.

## 해석과 제한

- **Office2:** 이번에 고정한 16-node field 기준으로 네 gauge/fold 중 세 조건에서 잔여 공간 이득이 관측됐다. Scalar 기준을 통과한 fold는 하나뿐이다. Scene 판정은 두 fold와 두 gauge 모두 통과해야 하므로 scene-wide 결론은 낼 수 없다.
- **Office3:** Scalar 보정은 target depth를 악화했고 fixed field도 target 이득을 입증하지 못했다. 반대 tile source 잔차는 개선됐지만 target 결과로 이어지지 않아 target geometry 결론은 조건부·미결정이다.
- **장면 간 해석:** 결과 방향이 일치하지 않는다. Fixed field는 사전등록한 loss와 regularization을 쓰는 하나의 진단 basis이며 공간 오차의 수학적 상한이 아니다. Office3에 공간 deformation이 없다고 결론 낼 수도, RGB-only 보정을 지지할 수도 없다.
- Pixel과 view를 독립 실험 단위로 간주한 p-value나 scene confidence interval은 계산하지 않았다.

## Amendment 및 구현 실패

1. `AMENDMENT_A1`: 첫 구현은 fold별 fit parity만 모아 `Sg` alpha가 fold마다 달라졌다. 해당 office2 fit/build 산출물은 `amendments/attempt1`에 보존했다. Guard 내부 prefix 전체를 pooling하도록 고쳐 office2를 다시 실행했다. 잘못된 map으로 target 지표를 계산하지 않았다.
2. `AMENDMENT_A2`: 첫 renderer는 map에 이미 반영된 global alignment를 target camera pose에도 적용해 정렬을 중복했다. 고정 5뷰 replay에서 mask 불일치가 19,450–104,314개 발생했다. 잘못된 출력은 `amendments/attempt2`에 보존했다. Raw GT target pose를 사용하도록 고친 뒤 5개 S0 뷰의 mask와 depth가 모두 정확히 일치했다. 실패 renderer의 중간 소스는 수정 전에 보관되지 않았으며, 이 provenance 제한을 amendment에 공개했다.
3. `AMENDMENT_A3`: office2 seal 이후 보조 surface/RGB 및 보고 도구를 추가했다. 첫 TSDF 비교는 등록된 GT-depth reference 대신 S0 rendered surface를 참조했다. 잘못된 지표와 manifest는 `amendments/attempt3`에 보존하고 제외했다. 두 장면 모두 GT-depth TSDF reference로 다시 계산했다. Fit 계수, map 중심, primary target 배열, protocol 값, 판정 threshold는 바꾸지 않았다.

## 다음 진단 후보

A2-S 결과는 D/P 보정이나 joint optimizer 실행을 승인하지 않는다. 다음 후보는 A2-S source 결과를 참고해 질문을 고정하고, 강한 scalar/simple 대조군을 포함해 별도 사전등록할 A2-O RGB 관측 가능성 진단이다. 이번 실행에서는 시작하지 않았다. Office4는 계속 봉인 상태이며 HKairport reference는 미해결이다.
