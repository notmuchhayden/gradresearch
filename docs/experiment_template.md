# 실험 노트: <experiment_id>

## 목적

- 날짜:
- 대응 실험 / 연구 질문: E0–E7 / RQ1–RQ5
- 검증할 가설:
- 대조군 대비 변경한 항목:
- 사전 정의한 평가 및 판정 기준:

## 재현 정보

- 자체 코드 commit 및 미커밋 변경:
- 외부 저장소 URL / commit 및 적용 patch:
- 환경 명세 파일:
- GPU / VRAM / 드라이버 / CUDA toolkit:
- Python / PyTorch / 주요 라이브러리 버전:
- Pretrained weights 출처 / SHA-256:
- Dataset 출처 / version / sequence / split 명세:
- Config 경로:
- Random seed:
- 결과 경로: `results/<experiment_id>/`

정확한 실행 명령:

```bash
# 실제 실행한 명령을 작성
```

## 비교 조건

- 입력 해상도 / stride / Keyframe 선택:
- Pose 출처 / 좌표계 / scale 정렬:
- 후보 및 검증 관측의 출처 분리 규칙:
- Confidence / admission threshold 및 선정 근거:
- Gaussian budget / 실제 active count:
- Refiner 사용 여부 및 전체 설정:
- GT 사용 범위 / held-out view 선정:

## 결과

| Method / Scene | Active #G | Resident #G | PSNR | SSIM | LPIPS | GT Accuracy | GT Completion | Peak VRAM | 처리시간 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| | | | | | | | | | | |

각 지표의 정의·단위·집계 방식과 matched-budget 충족 여부를 기록합니다. 미측정 값은 `N/A`로 표시합니다.

## 관찰 및 다음 판단

- 성공 / 실패 사례와 artifact 경로:
- 정상 표면 손실 / coverage 변화:
- 독립 관측 확보율 및 공유 오차의 한계:
- Tracking 실패 / 비용 / 메모리 병목:
- 가설을 지지하거나 반박하는 결과:
- 다음 판단: GO / REVISE / NO-GO
- 다음 실험에서 변경할 항목과 이유:

