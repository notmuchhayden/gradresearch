# A1-G/M 이후 경로 판정

**실행일: 2026-10-26. A1-G와 A1-M 각각 COMPLETE. 방법/지배 오류 GO 보류.**

- **G:** HK wide에서 충분한 동일 target support를 유지해도 rigid pose 효과가 position/orientation gauge에 따라 반전했다. Local 참조 개입은 두 gauge에서 개선됐다.
- **M:** Source-only thinning은 pose 효과 방향을 바꿀 수 있었지만 target-only 측정 희소화는 이번 office2에서 효과 방향을 유지했다. Full mixed와 strict의 정보량은 달라 subset의 큰 이득을 full map 개선율로 해석할 수 없다.
- **한계:** 알려진 두 개발 장면뿐이며 실제 HK reference는 미해결이다. G×모든 density의 전체 조합은 실행하지 않았고 pixels/frames를 독립 반복으로 세지 않는다.

다음은 **office3 V1 진단 재현**이다. [고정된 절차](../../configs/v1_office3_diagnostic_protocol.json)를 저장했지만 office3 예측·평가를 실행하지 않았다. 기존 position을 primary로 유지하고 orientation을 정해진 sensitivity로 모두 보고하며, source/target 희소화를 분리한다. 이 레시피는 아직 구현/실행 완료를 뜻하지 않는다.

V1에서도 규칙·실패·scope 의존성을 먼저 보고한 뒤 A2-S/O 또는 추가 RT/R-Q 진단 여부를 결정한다. 현재 결과로 D4, pose-only 알고리즘, joint optimizer 또는 office4 최종 평가를 자동 시작하지 않는다. Q0-HK의 미해결 상태도 유지한다.

[A1-G 보고서](A1_G_gauge_sensitivity_results.md) · [A1-M 보고서](A1_M_support_sensitivity_results.md)
