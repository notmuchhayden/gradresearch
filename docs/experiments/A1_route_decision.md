# A1 및 V1 이후 경로 판정

**2026-10-26 (Asia/Seoul). A1-U/C/G/M 및 office3 V1 실행 완료. 다음 한 단계는 A2-S 진단. 보정 알고리즘 GO는 보류.**

새 validation office3에서 유효 local 참조 치환의 개선 여지가 재현됐다. 주 position strict의 C00/C10/C01/C11 공통 깊이 MAE는 **0.065526/0.043293/0.062524/0.036682m**이며 local 단독은 **33.93%** 개선됐다. 400/400뷰가 dense support gate를 통과했다. Correct coverage는 interior 분모에서 **71.199→79.631%**, 관측영역 TSDF Chamfer는 **0.084048→0.058834m**로 개선됐다. Predicted ray를 유지한 CZ10도 같은 6군 픽셀에서 **0.065349→0.042553m**로 개선돼, calibrated ray로 바꾸는 개입만으로 생긴 이득은 아니었다.

같은 position/orientation 8군 픽셀에서도 local 단독 MAE는 **0.065399→0.043233m**, **0.062552→0.037151m**였다. Covariance fixed-world 20뷰 대조에서도 개선 방향이 유지됐다. Full mixed와 source 10%에서도 local 개선 방향은 유지됐지만, source 1%와 target 1%는 등록한 support gate를 통과하지 못했으므로 그 범위의 robustness를 주장하지 않는다. 특히 target 1% uniform은 314/400뷰(78.5%)로 80% 기준에 미달했으며 임계값을 완화하지 않았다.

재현된 사항과 재현되지 않은 사항을 구분한다.

- **재현:** 원 A 표현의 단독 악화·joint 개선과 scale 흡수 후 local 효과 방향 변경. 같은 A+C 8군 픽셀에서 원 A00/A10/A01/A11은 **0.064631/0.214983/0.305159/0.034356m**, C00/C10/C01/C11은 **0.064631/0.042855/0.061644/0.036286m**였다. 같은 baseline 지도에서도 factor 정의에 따라 해석이 달라졌다. Native-map 불변성과 covariance·ID 계약을 함께 검증한 결과다.
- **일반화되지 않음:** Office2 C 표현의 rigid pose 단독 악화 및 큰 잔여 interaction이 office3 strict에서 같은 크기로 재현되지는 않았다. Office3 strict pose 효과는 **+0.003002m(+4.58%)**, interaction은 **−0.003608m**다. Orientation pose 효과는 **+0.000158m(+0.25%)**에 그쳤다. 둘 다 최소 10% 효과 기준에 미달하므로 효과 비율을 만들어 local/pose의 고유 우세나 기여율을 선언하지 않는다.
- **남은 조건 의존성:** 같은 strict/full 8군 픽셀에서 rigid 효과는 strict **+0.003002m**, full mixed **−0.011496m**로 부호가 바뀌었다. Full mixed는 prefix 포함 1,136,762개 중 local 참조가 있는 967,994개(85.154%)만 교체한 지도다. Scope 간 서로 다른 정보량·미관측 local 예측·가림이 개입되므로 이 차이를 순수한 물리 pose 오류로 귀속하지 않는다. 두 효과 모두 10% 기준을 넘는 material sign flip은 아니다.
- **미검증:** RGB로 이 local 잔차를 구별·수정할 수 있는지, KF scalar가 충분한지, 공간 field가 추가로 필요한지, 독립 최종 장면/도메인 성능. Q0-HK reference도 미해결이다.

따라서 다음은 **A2-S: scalar bias와 spatial deformation의 교차 검증 진단** 하나다. Office2 개발에서 tile split·guard band·최소 표본 수·field regularization·unsupported 처리·동일 후보/covariance 및 target 공통 분모를 먼저 고정한다. S0/Sg/Sk-oracle/Sf-oracle를 두 spatial fold와 heldout target에서 비교하고, source fit 오차 감소를 일반화로 보고하지 않는다. Office3의 추가 사용은 이미 본 validation이라는 사실과 변경 이력을 남긴다. Scalar 충분성은 계획서의 90%·최소 효과·coverage 조건으로 판단한다.

V1은 A2-S의 **진단 자격**을 지지하며 D4·pose-only 방법·joint optimizer 개발의 GO를 발행하지 않는다. A2-O RGB 관측 가능성, 필요한 문헌 중복 검토와 강한 대조군을 거치기 전 실제 보정 경로를 확정하지 않는다. 이번 요청에서는 A2 실험을 시작하지 않았다. Office4 최종 평가는 계속 보류한다.

[V1 상세 보고서](V1_office3_replication.md) · [V1 수치 요약](../../configs/v1_office3_results_summary.json) · [G/M 당시 판정](A1_GM_route_decision.md) · [연구 계획](../pointmap_pose_error_decomposition_research_plan_v1.md)

---

## A2-S 이후 경로 판정

**2026-10-27 (Asia/Seoul). A2-S 진단 실행 완료. Scalar 충분성은 scene-wide로 성립하지 않았고 RGB-only 보정 GO는 발행하지 않는다.**

Office2에서 fixed 16-node field는 같은 S0+Sk+Sf common-mask MAE를 네 gauge/fold context 모두 낮췄다. 그러나 scalar/field gain ratio는 position fold 0과 두 orientation fold에서 0.90 미만이었고, 0.90 이상은 position fold 1 하나뿐이었다. 계획상 두 folds 모두 통과해야 하므로 office2 scalar 충분성은 성립하지 않는다. Common4에서 Sf는 Sk와 SkH보다 모두 낮았고 opposite-tile source Z error도 낮았다. GT-depth TSDF에서는 Sf가 scalar보다 나은 결과를 보였지만 이건 관측영역 geometry 진단이다.

Office3에서는 Sk가 target MAE를 악화시켰고 Sf도 S0 대비 10% target 이득을 만들지 못했다. Opposite-tile source residual은 개선됐지만 target에서는 개선되지 않아 source/target mismatch로 기록한다. 이 결과는 source fit field가 validation target 성능을 보장하지 않음을 보여준다.

따라서 **단순 scalar가 충분하다는 결론은 보류**하고, 이 고정 field에서 office2의 잔여 공간 이득이 관측됐다 하더라도 그것을 두 scene에 일반화하지 않는다. 다음 후보는 **별도 등록할 A2-O RGB 관측 가능성 진단**이다. A2-S는 전부 GT-oracle fit이므로 RGB-only 보정 가설을 시험하지 않았다. D/P 알고리즘, joint optimizer, office4는 실행하지 않으며 HKairport reference는 미해결로 남긴다.

[A2-S 상세 결과](A2_S_scalar_spatial_results.md) · [protocol](../../configs/a2_s_scalar_spatial_protocol.json) · [수치 요약](../../configs/a2_s_results_summary.json) · [execution manifest](../../results/A2_S_scalar_spatial/2026-10-27/execution_manifest.json)

---

## A2-O-M 이후 경로 종료

**2026-10-27 (Asia/Seoul). 마지막 mask/support 진단을 실행하고 `STOP_INSUFFICIENT_SUPPORT`로 종료했다.** 기존 A2-O의 fit 160개 레코드에서 eligible 최대 171개·common retained 0개를 재현했다. 사전 고정한 R1(stride2, RGB mask의 symmetric depth agreement 제거)은 fit 6/160개 pair의 지원을 회복했지만 audit는 0/128개였고, 양 gauge·양 fold 모두 KF 지원율은 0/10이었다. 합성 필수 대조 36개와 전체 기대 판정 검사 77개, 저장소 unittest 190개 및 cache 기반 mask/support 검증 1,152건을 통과했다.

RGB 계수는 선택되지 않았고 source GT·target geometry·office3 새 평가는 gate 실패로 실행하지 않았다. **현재 데이터·표현·scalar 후보·고정 RGB objective에 대한 보정 개발 경로를 종료한다.** 이는 RGB 관측 불가능성이나 모든 field/pose 보정의 실패 증명이 아니다. Field·D/P·joint optimizer·office4로 확대하지 않는다. A2-S의 GT-oracle 결과와 office3 source/target 불일치는 그대로 유지한다.

[A2-O-M 결과](A2_O_M_results.md) · [고정 계획](A2_O_M_execution_plan.md) · [수치 요약](../../configs/a2_o_m_results_summary.json)
