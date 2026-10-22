# E4c A2 — 표면 footprint 구현 수정

**2026-10-22, A1 개발 결과 확인 후·새 장면 미노출.**

A1의 분할·두께 네 조합·반복 수·시차·source 분리·표본 기준은 유지한다. A1의 `view_geometry`가 support용 수선점 convex-hull 조건을 모든 충돌 관측의 공통 자격에도 적용한 문제를 수정한다. 카메라 광선이 patch 내부의 표면을 만나더라도 그 앞 후보의 수선점은 patch 밖에 있을 수 있다. 이 조건으로 앞쪽 충돌을 무효화하면 계획의 ray/depth 충돌을 표현하지 못한다.

V2는 support에는 수선점 hull 검사를 유지하고, 공통 관측 자격에는 **후보 광선과 patch 평면의 교점이 양의 ray 거리에서 inlier hull 안에 있는지**를 사용한다. 가림·signed 잔차·Gaussian 3σ·앞쪽 band·두 KF 시선 다양성은 그대로다. audit 평가기에도 같은 유효 표면 범위 정의를 적용한다.

이를 검증하는 고정 fixture는 앞쪽 후보의 수선점은 hull 밖이지만 ray–plane 교점은 hull 안인 경우다. support는 false, 유효한 앞쪽 충돌 잔차는 finite여야 한다. 수정은 등록·테스트 후 별도 `results/E4c_surface_consistency_pruning/v2/`에서 처음부터 재계산한다. A1 코드·배열·보정 실패 결과는 덮어쓰지 않는다. V2는 개발 수정 버전으로 기록하며 두 실행 중 유리한 결과만 고르지 않는다.
