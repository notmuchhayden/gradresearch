# N1: 좌표계·단위·후보 계약 및 개입 독립성 검증

- **수행일:** 2026-10-26 (Asia/Seoul)
- **판정:** **PASS — 개발 장면에서 A0 구현을 위한 좌표·단위 계약 검증 완료**
- **입력:** [N0](N0_asset_audit_results.md)의 새 `office0` RGB-only 실행 `results/N0_asset_audit/2026-10-26/fresh_baseline/`.
- **최종 출력:** `results/N1_coordinate_contract/2026-10-26-verified/`
- **설정:** [n1_coordinate_contract.json](../../configs/n1_coordinate_contract.json)
- **범위:** 기존 개발 장면에서 후보·좌표·단위·mask·4군 불변 조건을 검증했다. 새 장면의 A0 오류 지표·효과·interaction이나 보정 효능은 산출하지 않았다.

## 1. 실제 검증 결과

| 항목 | 결과 |
|---|---|
| 합성·오염 주입 시험 | 12개 PASS |
| Raw source와 KF dump | mean·scale·quaternion·SH·opacity·confidence 정확히 일치 |
| Audit journal 재생 | 246 events, 60 raw events, 5 snapshots, PASS |
| 최종 pose revision | 62; dump와 최종 audit snapshot의 pose 정확히 일치 |
| Fused ancestry | 별도 audit metadata에서 2 KF 모두 `traced`; unknown 0 |
| Native active ↔ PLY | 286,208개, upstream GPU 준비 결과의 후보·순서와 일치 |
| 공통 GT 유효 후보 | 258,718개 |
| 고정 stratified 표본 | 1,429개; 동일 입력·seed 재선택 일치 |
| A0 4군 계약 검사 | ID·mask·속성·local covariance 공통, local/placement 개입 독립성 PASS |
| 입력 보존 | 333개 파일을 실행 전후 재해시, 변경 없음 |

N0에 등록된 주요 산출물 13개의 hash도 먼저 확인했다. 검증 과정에서 mapper·학습·native filter 정책을 바꾸거나 N0 산출물을 덮어쓰지 않았다.

## 2. 후보·픽셀·branch·pose 연결

| 항목 | KF0 | KF1 | 합계 |
|---|---:|---:|---:|
| 입력 / 원본 frame | 0 / 0 | 41 / 82 | |
| Raw self-branch 후보 | 147,456 | 147,456 | 294,912 |
| Native active | 142,432 | 143,776 | 286,208 |
| GT valid (범위 내, edge 제외 전) | 147,231 | 147,204 | 294,435 |
| 공통 후보 | 128,026 | 130,692 | 258,718 |
| 고정 표본 | 733 | 696 | 1,429 |
| Calibration prefix 내 anchor | 예 | 아니오 | |

후보의 canonical ID는 `<prediction_event_id>:self:<row-major-pixel-index>`다. 해상도는 512×288이며, 인덱스 $j$의 픽셀은 $u=j\bmod512$, $v=\lfloor j/512\rfloor$다. `candidate_registry.csv.gz`에는 전체 raw 후보의 ID·픽셀·anchor·원본 frame·active/valid/edge/common 여부·최종 revision을 저장했다.

확정한 좌표 규약:

- Pose 텐서는 `[tx, ty, tz, qx, qy, qz, qw, scale]`의 **camera-to-world Sim(3)**다.
- Raw pair의 `outputs[0]`는 첫 source/anchor 카메라의 self-branch다. KF dump의 모든 Gaussian 속성은 같은 raw 출력과 정확히 일치했다.
- `outputs[1]`는 두 번째 이미지의 픽셀을 나타내지만 점은 **첫 source/anchor 카메라 좌표**에 있다. 검사한 두 KF의 두 branch 모두 `means == pts3d`였다.
- Cross-branch GT 대체에는 source-camera → anchor-camera 상대 Pose가 필요하다. 실제 source depth 표본에서도 상대 변환 후 world 좌표가 source GT world 좌표와 일치함을 검사했다. 이 경로는 **GT relative Pose가 들어가는 secondary oracle**로만 사용한다.
- Primary 후보에는 raw self-branch만 사용한다. Fused pointmap을 raw local geometry로 사용하지 않는다.

N0의 KF dump에는 여전히 `final_snapshot_unversioned`·`unknown` 문자열이 들어 있다. 이를 원본에서 수정하지 않고, 별도 audit journal의 최종 snapshot을 연결해 revision 62·ancestry를 복원했다. Audit의 fused pointmap 수치 재생 최대 오차는 `1.66893e-06`이었다.

## 3. 카메라·깊이 계약

Raw 카메라는 1200×680 pinhole이며 왜곡/remap을 적용하지 않는다. Mapper는 `use_calib=false`였으므로 GT 카메라를 추론에 넣은 결과가 아니다. GT는 기존 E0/E1 evaluator와 동일한 resize/crop 규약으로 평가한다.

- RGB resize: 512×290.
- Center crop: top 1, left 0, output 512×288.
- Depth: `uint16 / 6553.5`, **카메라 Z-depth**, nearest 보간 후 같은 crop.
- 아래 $K$를 upstream `resize_img(..., return_transformation=True)`가 반환한 변환과 대조했고, depth resize도 upstream evaluator와 정확히 일치했다.

$$
K = \begin{bmatrix}
256 & 0 & 255.786666667 \\
0 & 255.882352941 & 143.786764706 \\
0 & 0 & 1
\end{bmatrix}.
$$

GT 로컬 점은 같은 source 픽셀에서 다음처럼 만든다.

$$
X^{\mathrm{GT}}(u)=D^{\mathrm{GT}}(u)K^{-1}[u_x,u_y,1]^T.
$$

GT unprojection → projection 및 GT local → world → local → projection 왕복을 `1e-9` 허용 오차로 확인했다. 합성 평면 시험에서는 Z-depth 2인 비중심 광선의 Euclidean range가 $\sqrt{8}$임을 확인해 Z-depth와 range를 구별했다.

픽셀 중심은 기존 evaluator의 $c'_x=s_xc_x-\mathrm{left}$, $c'_y=s_yc_y-\mathrm{top}$ 규약을 고정했다. 별도의 half-pixel offset을 추가하지 않았다. 이는 기존 코드와의 일관성 계약이며, resampling의 연속 좌표 해석까지 독립적으로 검증했다는 뜻은 아니다. 다른 픽셀 중심 규약을 검토할 경우 전체 arm에 같은 변경을 적용하는 개발 sensitivity로 구분해야 한다.

### 중요한 해석 제한: GT local oracle은 순수 depth 교체가 아니다

Raw 점을 위 GT $K$로 투영한 픽셀과 원래 source 픽셀 간 차이는 다음과 같다. 공통 후보만으로 계산했다.

| Anchor | Median (pixel) | p95 (pixel) |
|---|---:|---:|
| KF0 | 2.500 | 4.673 |
| KF1 | 1.045 | 1.920 |

따라서 GT depth를 GT ray로 backproject해 넣는 A10은 **Z-depth와 광선 방향을 함께 바꾸는 local geometry oracle**이다. 이 차이에는 예측 ray와 GT 카메라 모델·좌표 규약의 불일치가 포함될 수 있다. A10의 이득을 전부 Z-depth 보정의 효과로 해석하면 안 된다. 후속 연구에서 depth-only 원인을 따로 주장하려면 predicted ray를 유지하는 보조 실험이 필요하다.

## 4. 고정 단위와 global gauge

기존 E0 validation/calibration 구간인 **원본 frame `[0,40)`의 mapping pose 20개**만으로 한 번의 global Sim(3) $A=[aQ,b]$를 fit했다. KF/frame별 GT scale fit은 수행하지 않는다.

- Global scale $a = 1.199338529008951$ m / raw-world-unit.
- Calibration 위치 RMSE: **0.010875045 m**.
- Calibration 중심화 위치의 singular values: `[0.212764259, 0.144943416, 0.021821435]`.
- 모든 post-prefix GT 위치를 크게 바꿔도 정렬이 정확히 같은지 검사했다.
- 이 정렬의 입력 pose는 **최종 backend revision**이다. Calibration GT만 사용했지만 추정 pose에는 후속 RGB/backend 정보가 들어갈 수 있으므로 **offline 진단**이다.

Raw local 단위를 metric local로 옮기는 상수는 최초 KF의 scale을 기준으로 정했다.

$$
C=a s_0=1.199338529008951,\qquad X^m=C X^{\mathrm{raw}}.
$$

Raw pose $T_k^{\mathrm{raw}}(X)=s_kR_kX+t_k$의 metric placement는 다음과 같다.

$$
\hat{T}_k^m(X^m)=\frac{a s_k}{C}QR_kX^m+aQt_k+b.
$$

따라서 A00은 원래 월드 배치에 같은 global gauge를 적용한 결과를 보존한다.

$$
\hat{T}_k^m(C X_k^{\mathrm{raw}})=A\bigl(T_k^{\mathrm{raw}}(X_k^{\mathrm{raw}})\bigr).
$$

Covariance도 $\Sigma_k^m=C^2\Sigma_k^{\mathrm{raw}}$로 한 번 환산하고, placement의 선형 블록으로 world covariance를 만든다. 평균·covariance·역변환 검사 모두 통과했으며, 실제 표본의 A00 평균 재표현 최대 오차는 `8.88e-16 m`였다.

추정 metric placement scale은 KF0 **1**, KF1 **1.089996337890625**이며 기존 상대 scale 변화가 남는다. GT pose arm은 metric SE(3)이므로 scale은 **1**이다. N0 재현에 사용했던 전체 trajectory scale 1.067586563을 재사용하지 않는다.

### C에 조건부인 분해

$C$를 0.8배·1배·1.25배로 바꿔도 A00의 world mean/covariance는 보존됐다. 반면 A01의 점 위치는 바뀐다. 예를 들어 0.8배에서 A01 위치 변화의 중앙값은 KF0 약 **0.528 m**, KF1 약 **0.543 m**였다.

이는 GT 오류 개선량이 아니라 **동일 raw 데이터의 단위 배분에 대한 민감도**다. Local과 placement의 효과는 이 gauge 계약에 조건부이며, 수학적으로 유일한 원인 기여율이 아니다. 신규 장면 A0에서도 고정 gauge 규칙과 sensitivity를 함께 보고해야 한다.

## 5. Native mask·공통 mask·속성 계약

Native filter는 원래 raw 예측에 한 번만 적용했다.

- $z>0.05$, 해당 positive-depth 집합의 98 percentile 이하.
- raw Gaussian max scale $<1$, confidence $\ge1.5$, opacity $>0.3$.
- spatial stride 1, 추가 scale inflation 없음.

CPU에서 만든 후보 mask를 upstream GPU `prepare_gaussians_local`의 결과와 정확히 대조했다. KF 순서·픽셀 순서로 연결한 286,208개 후보를 PLY에 매핑했고 mean·covariance·RGB·opacity를 대조했다. PLY mean 최대 차이는 **0**이었다.

PLY parity는 기존 TF32 on 경로를 사용했다. 별도의 TF32 off GPU bake와 float64 좌표 계약도 비교했으며, mean 최대 차이는 KF0 0, KF1 `5.26114e-07`이었다. 좌표 계약의 수학적 동등성과 기존 float32/TF32 재현을 구분했다.

공통 mask는 **원본 native active ∩ 유효 GT depth ∩ 비경계 영역**이다. GT 유효 범위는 `[0.1,10] m`, edge 기준은 인접 깊이 차이 `max(0.05 m, 2%)`, dilation radius 2이며 기존 `depth_masks`의 경계 처리도 적용했다.

Replica의 static scene이라는 조건을 사용했으며 별도 sky·동적 semantic mask는 생성하지 않았다. 이 mask는 **source-view GT 유효성·경계 배제**만 뜻한다. Target view의 모든 arm에서 가시적인지를 보장하지 않으며, 변형 후 target 가시성으로 후보를 다시 선택하지 않는다.

고정 표본은 8×8 공간 cell, 예측 metric depth bin `[1,2,4] m`, cell/bin당 최대 8개, KF별 seed `0+kf_idx`로 선택했다. GT 오류 크기나 Oracle 이득으로 표본을 고르지 않았다.

각 arm은 다음 항목을 같은 값·dtype·shape의 hash로 유지한다.

- 후보 ID, common mask, 후보 수.
- Raw scale·rotation·SH·opacity·confidence.
- 한 번 환산한 **local covariance**.
- A00/A10의 placement, A01/A11의 GT placement.
- A00/A01의 추정 local points, A10/A11의 GT local points.

Local 요인을 바꿀 때 covariance를 재초기화하지 않는다. World covariance는 placement에 따라 달라지며, 이를 local 속성 불변과 혼동하지 않는다. 저장한 SH는 raw residual이므로 향후 A0 렌더러에서 원본 source RGB를 한 번 결합해 색을 준비한 뒤 모든 arm에 고정해야 한다. 중심 교체 후 native filter를 재실행해서는 안 된다.

저장된 NPZ를 다시 읽어 각 arm의 배열 dtype·shape·payload bytes가 같음도 확인했다. KF0는 arm당 **285,265 bytes**, KF1은 **270,872 bytes**다. 이는 ID 문자열·mask·local/world 좌표·covariance를 포함한 검증 배열의 압축 전 payload이며 실제 Gaussian resident VRAM이나 압축 파일 크기가 아니다. 결과는 `resource_contract.json`에 보존했다.

## 6. 시험과 재실행

합성시험 12개는 알려진 평면·Z-depth/range, xyzw·Sim(3) 왕복·covariance scale 제곱, reflection/shear 거부, prefix 이후 GT 오염 격리, 단위 재표현, cross-branch 상대 Pose, depth/pose 단일 오류, interaction 부호, ID·mask·속성·covariance 오염 거부, 유효 Pose를 사용한 상관 개입 거부, stratified 표본 재현을 검사했다.

```bash
.venv/bin/python -m unittest discover -s tests -p test_pointmap_contract.py -v
.venv/bin/python scripts/run_n1_contract.py --gpu \
  --output results/N1_coordinate_contract/2026-10-26-verified
```

실제 GPU 검증은 GPU가 보이는 호스트 실행 환경에서 수행했다. 출력 경로가 이미 있으면 덮어쓰지 않는다. 재실행 시 새 output 경로를 지정한다. `--gpu`를 생략하면 PLY 대조가 빠지므로 전체 판정은 `INCOMPLETE`다. 다운로드·재추론은 수행하지 않는다.

- [검증 결과](../../results/N1_coordinate_contract/2026-10-26-verified/result.json), [시험 로그](../../results/N1_coordinate_contract/2026-10-26-verified/unit_tests.log)
- [후보 manifest](../../results/N1_coordinate_contract/2026-10-26-verified/candidate_manifest.json), [전체 후보 CSV](../../results/N1_coordinate_contract/2026-10-26-verified/candidate_registry.csv.gz)
- [정렬·단위 manifest](../../results/N1_coordinate_contract/2026-10-26-verified/alignment_manifest.json), [카메라 manifest](../../results/N1_coordinate_contract/2026-10-26-verified/camera_manifest.json)
- [4군 불변 조건](../../results/N1_coordinate_contract/2026-10-26-verified/arm_invariants.json), [고정 표본](../../results/N1_coordinate_contract/2026-10-26-verified/sample_manifest.json)
- [Audit 재생](../../results/N1_coordinate_contract/2026-10-26-verified/journal_checks.json), [GPU·PLY 대조](../../results/N1_coordinate_contract/2026-10-26-verified/gpu_parity.json)
- [Gauge sensitivity](../../results/N1_coordinate_contract/2026-10-26-verified/gauge_sensitivity.json), [입력 보존](../../results/N1_coordinate_contract/2026-10-26-verified/preservation.json)
- [4군 배열 자원 계약](../../results/N1_coordinate_contract/2026-10-26-verified/resource_contract.json)
- [소스 고정](../../results/N1_coordinate_contract/2026-10-26-verified/source_manifest.json), [추적용 요약](../../configs/n1_results_summary.json)
- KF별 full registry·mask는 `kfNNNN_registry.npz`, 표본의 4군 좌표·covariance·속성은 `kfNNNN_Axx_contract.npz`다.

## 7. 다음 A0의 착수 조건

구현에 사용할 좌표·단위·후보 계약은 확보했다. 다음 작업은 **미사용 GT 실내 장면을 확보하고 calibration/evaluation 구간·공통 후보·평가 규칙을 등록한 뒤**, 같은 검사를 통과시켜 full-map 4군의 기하·coverage를 평가하는 것이다.

이번 `office0`에는 prefix 밖 KF가 하나뿐이다. 이 장면의 4군 QA 배열을 신규 장면 A0 결과나 Depth/Pose 우세의 증거로 사용하지 않는다. 최종 보정 경로는 아직 결정하지 않았다.
