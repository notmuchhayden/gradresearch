# 실험 노트: E0_baseline_reproduction

## 목적

- 날짜: 2026-10-15 (Asia/Seoul)
- 상태: **E0 파일럿 완료** — RTX 5060에서 고정 입력 60프레임 기준선 종료, 후보·관측·pose 저장 및 GT rendered-depth / held-out RGB 평가 통과. Fused ancestry·온라인 pose revision·source-disjoint 가용성 감사는 다음 E0b에 남음
- 계획서: [연구·실험 계획서 v3](../surface_guided_gaussian_mapping_research_plan_v3.md), §3.2 및 §8의 E0
- 대응 실험 / 연구 질문: E0 (Reproducibility + feasibility); RQ1–RQ5 공통 실험 기반
- 검증할 사항: Replica 한 장면에서 원본 기준선을 재현하고, 고정 후보 풀·pose·관측 출처를 저장해 GT 기반 평가에 연결할 수 있는가?
- 대조군 대비 변경한 항목: 원본 admission·tracking 기준과 가중치를 사용했다. 하드웨어 호환·메모리 관리·export 변경은 patch로 보관했다. 8GB 실행에서는 프레임 미리보기를 끄고 최종 맵을 별도 프로세스에서 평가했다. 원본 논문의 수치나 처리속도를 재현했다고 주장하지 않는다.
- 사전 정의한 완료 기준:
  - [x] 환경·가중치·입력·설정·실행 명령을 고정하여 기준선을 재실행할 수 있다. (성공 실행 1회; 반복 실행 간 결정성은 아직 미검증)
  - [x] Gaussian 후보 풀과 pose를 저장·재로딩하고, 원래 local 후보로 복원한 맵과 PLY의 렌더링 차이를 확인한다.
  - [x] 후보 생성 이미지/pair 및 raw/fused pointmap 출처의 추적 가능 여부를 확인한다. Fused ancestry는 `unknown`으로 기록한다.
  - [x] mean/covariance의 Sim(3) 왕복 변환 및 pose·quaternion 규약을 검증한다.
  - [x] GT rendered-depth 기반 평가가 동작하고, GT가 후보 생성·편입 경로와 분리되어 있다. (TSDF/mesh 지표는 미구현)

## 재현 정보

- 자체 코드 기준 commit (노트 생성 전): `72d34e401c3c6bc25e3923e0226763b1337748dd`
- 자체 코드 미커밋 변경: E0용 scripts·src·configs·노트·patch를 추가했다. 실행한 소스 파일 SHA-256은 `configs/e0_code_manifest.json`에 기록했다. 별도 commit은 만들지 않았다.
- 외부 저장소 URL: https://github.com/Looong01/Splatt3R-SLAM.git
- 외부 저장소 경로: `thirdparty/Splatt3R-SLAM/`
- 외부 저장소 commit: `74ffc37454dfa7560c9531b1534825c54c36a89e`
- 외부 저장소 적용 patch: 노트 생성 당시 수정 없음. 이번 진행의 변경은 `docs/patches/e0_upstream.patch`로 보관하며 `src/e0_export.py`를 함께 사용한다.
- 환경 명세 파일: `configs/e0_environment.yml`, `configs/e0_environment_resolved.json`, `configs/e0_pip_freeze.txt`, `configs/e0_conda_linux64.explicit.txt` (최종 환경 기록 완료)
- GPU / VRAM / 드라이버 / CUDA toolkit: GeForce RTX 5060 / 8,151 MiB / 595.99.02 / 시스템 toolkit 13.4 (`nvcc V13.4.92`), 프로젝트 toolkit 13.2 (`nvcc V13.2.78`), compute capability 12.0. 샌드박스 밖 조회 성공
- Python / PyTorch / 주요 라이브러리 버전: 프로젝트 `.venv`의 Python 3.11.17, `torch 2.13.0+cu132`, `torchvision 0.28.0+cu132`, NumPy 2.4.6. 시스템 Python과 분리
- Pretrained weights 출처 / SHA-256: `configs/e0_weights_manifest.json`. MASt3R retrieval 자산 2개, 원본 Splatt3R checkpoint 3,231,028,127 bytes, upstream loss 모듈 및 평가 LPIPS에 사용하는 AlexNet backbone을 포함한다. README의 checkpoint 크기 설명 대신 실제 파일 크기·hash를 기준으로 기록한다.
- Dataset 출처 / version / sequence / split 명세: NICE-SLAM rendered Replica `office0`, 원본 프레임 `[0, 120)`. 입력 짝수 60개, validation 홀수 `[0, 40)` 20개, held-out test 홀수 `[40, 120)` 40개. `configs/e0_replica_split.json` 참조. 242개 파일 다운로드·CRC/SHA-256 기록 완료, RGB/depth 120쌍과 trajectory 형식 검사 통과
- Config 경로: `configs/e0_replica_office0.yaml`
- Dataset 배포 근거: [NICE-SLAM 공식 다운로드 스크립트](https://github.com/cvg/nice-slam/blob/master/scripts/download_replica.sh). 실제 URL·archive ETag·개별 파일 hash는 `configs/e0_replica_download_manifest.json` 참조
- Random seed: 0 (실행 wrapper의 `E0_SEED`로 Python·NumPy·PyTorch에 적용; 비동기/CUDA 연산의 결정성 보장은 별도)
- 결과 경로: `results/E0_baseline_reproduction/`

실제로 실행한 확인 명령 (프로젝트 루트 기준):

```bash
git rev-parse HEAD
git status --short
git -C thirdparty/Splatt3R-SLAM rev-parse HEAD
git -C thirdparty/Splatt3R-SLAM remote -v
git -C thirdparty/Splatt3R-SLAM status --short
```

설치·기준선 실행·export·평가 명령 (각 단계의 실제 완료 여부는 체크리스트와 결과 절 참조):

```bash
bash scripts/bootstrap_e0_environment.sh
bash scripts/install_e0_dependencies.sh
bash scripts/download_e0_weights.sh
python3 scripts/download_e0_replica.py --frames 120
bash scripts/build_e0_extensions.sh
# PTX 호환 오류 후 프로젝트 CUDA 13.2로 다시 빌드하는 보조 명령:
bash scripts/build_e0_cuda_wheels.sh
bash scripts/build_e0_backend.sh
# 성공한 기준선 / 검증·평가:
bash scripts/run_e0_baseline.sh
bash scripts/evaluate_e0.sh
# 통과한 export 검사를 재실행하지 않고 평가 코드만 이어간 실제 명령:
bash scripts/evaluate_e0.sh --metrics-only
.venv/bin/python scripts/capture_e0_environment.py
```

최종 실행의 모든 CLI·환경 변수는 `scripts/run_e0_baseline.sh`에 고정했다. CUDA wheel을 보조 스크립트로 만든 경우 생성된 wheel은 `pip install --no-deps --force-reinstall`로 설치했다. 신규 환경은 전체 설치 순서와 `docs/patches/e0_upstream.patch`, `src/e0_export.py`를 함께 적용해야 한다.

## 최초 환경 및 설치 사전 점검 (2026-10-15, 과거 기록)

확인 범위는 현재 도구 실행 세션에서 보이는 시스템·PATH·Python이다. 다른 서버나 PATH에 없는 별도 가상환경의 설치 상태까지 확인한 것은 아니다. 패키지 설치, 드라이버 변경, submodule 초기화, CUDA 확장 빌드는 수행하지 않았다.

### GPU 및 시스템

| 항목 | 확인 결과 | 준비 상태 / 해석 |
|---|---|---|
| OS / 커널 | Ubuntu 26.04.1 LTS / Linux 7.0.0-38-generic, x86_64 | README의 Ubuntu 20.04+ 조건에 해당; 이 조합에서 빌드·실행은 미검증 |
| GPU 장치 | `lspci`: NVIDIA GB206 [GeForce RTX 5060], PCI `02:00.0`, ID `10de:2d05` | PCI 장치 식별 완료 |
| GPU 런타임 | `nvidia-smi` 드라이버 연결 실패. 샌드박스 밖 재확인도 같은 오류, exit code 9 | 현재 세션에서 NVIDIA GPU 실행 불가; 단순 샌드박스 제한으로 결론내릴 수 없음 |
| VRAM / 드라이버 버전 / compute capability | 조회 실패 | 추정값으로 채우지 않음; 드라이버 연결 복구 후 조회 |
| 드라이버 관측 | `/dev/nvidia*`, `/proc/driver/nvidia/version` 없음. `lsmod`에 NVIDIA GPU 드라이버 모듈 없음. `lspci -nnk`에 `Kernel driver in use` 표시 없음 | 드라이버 미연결 상태의 근거. 원인·설치 여부·복구 방법은 추가 진단 필요 |
| CUDA toolkit | `nvcc`: release 13.4, V13.4.92. `/usr/local/cuda`의 실제 경로는 `/usr/local/cuda-13.4` | 컴파일러 존재 확인; toolkit 설치만으로 GPU 런타임 가용성이 보장되지는 않음 |
| C/C++ 컴파일러 | GCC / G++ 15.2.0 | 설치 확인; CUDA 확장과의 실제 빌드 호환성 미검증 |
| 빌드 도구 | CMake 4.2.3, GNU Make 4.4.1 | `ninja`, `swig`는 현재 PATH에서 발견되지 않음 |
| Python | `/usr/bin/python3`, 3.14.4 | README의 Python 3.11 환경과 다름. `python` 명령은 현재 PATH에 없음 |
| 환경 관리자 | `conda`, `mamba`, `micromamba`, `uv`는 현재 PATH에서 발견되지 않음 | README의 Conda 환경 준비 단계 미수행 |
| 활성 환경 | `CONDA_PREFIX`, `VIRTUAL_ENV`, `CUDA_HOME`, `CUDA_PATH`, `CUDA_VISIBLE_DEVICES` 미설정 | 별도 실험 환경 활성화 확인되지 않음 |

`nvidia-smi` 오류 원문:

```text
NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver. Make sure that the latest NVIDIA driver is installed and running.
```

### 해당 commit의 설치 안내 및 의존성

검토한 파일: [README 설치 절](../../thirdparty/Splatt3R-SLAM/README.md#installation), [pyproject.toml](../../thirdparty/Splatt3R-SLAM/pyproject.toml), [requirements.txt](../../thirdparty/Splatt3R-SLAM/requirements.txt), [setup.py](../../thirdparty/Splatt3R-SLAM/setup.py) 및 vendored 패키지의 빌드 설정. 아래 버전은 해당 commit의 문서·코드에 적힌 값이며, 다운로드 가능 여부나 실제 설치 성공을 검증한 값은 아니다.

- README 요구사항: NVIDIA GPU compute capability ≥ 7.5, CUDA 13.x, Conda/Miniconda. 개발 환경은 RTX A6000 (`sm_86`), CUDA 13.3으로 기재되어 있다.
- README 기본 설치 경로: Python 3.11 → CUDA 13.2용 PyTorch wheel. 개발 버전은 `torch 2.13.0+cu132`, `torchvision 0.28.0+cu132`로 기재되어 있다. 현재 toolkit 13.4와의 조합은 빌드·실행 검증 전이다.
- README 설치 순서: PyTorch → `cmake ninja swig mkl-devel` → `requirements.txt` → vendored `in3d` → `asmk` → GPU faiss 소스 빌드 → `lietorch` → Gaussian rasterizer → 본체 editable 설치 → 선택적 RoPE2D 커널 빌드.
- `pyproject.toml`의 build-system은 `setuptools==70.0.0`과 `torch`를 요구한다. README는 CUDA 확장과 본체를 `--no-build-isolation`으로 설치한다. 현재 시스템 setuptools는 78.1.1이며 실험 환경의 버전은 아직 정하지 않았다.
- 직접 의존성에는 `numpy>=2.0`, `scipy>=1.13`, `einops`, `evo`, `natsort`, `plyfile`, 영상·시각화 라이브러리, `lightning`, `lpips`, `omegaconf`, `huggingface_hub`, `gitpython`, `peft` 등이 있다. `requirements.txt`만으로는 본체의 전체 의존성과 CUDA 확장 설치가 끝나지 않는다.
- 현재 Python의 배포 메타데이터에서 본체 직접 의존성 중 Pillow 12.1.1, PyYAML 6.0.3만 확인됐다. 나머지 직접 의존성 및 `torch`, `torchvision`, `in3d`, `lietorch`, Gaussian rasterizer, 본체는 설치가 확인되지 않았다. `torch`는 모듈 검색에서도 발견되지 않았다.
- `in3d`는 로컬 pyimgui를 설치하며 `moderngl==5.12.0`, `moderngl-window==2.4.6`을 지정한다. `asmk`는 vendored GPU faiss를 전제로 한다. faiss는 README에 따라 소스 빌드하며 별도 PyPI faiss 패키지와 혼용하지 않는다.
- `torchcodec`은 선택 사항이다. `pyrealsense2`는 런타임에서 RealSense 입력용이지만 본체 설치 메타데이터에는 직접 의존성으로 포함되어 있다.

빌드 전에 해결·확인할 사항:

1. NVIDIA 드라이버 연결을 복구하고 `nvidia-smi`에서 VRAM·드라이버 버전·compute capability를 확인한다.
2. 별도 Python 3.11 환경과 CUDA 대응 PyTorch를 준비해 `torch.cuda.is_available()`이 참인지 확인한다. 현재는 PyTorch가 없어 이 검사를 실행하지 못했다.
3. 본체 `setup.py`는 `torch.cuda.is_available()`이 거짓이면 CUDA backend 확장 생성을 생략한다. GPU가 연결되지 않은 상태에서의 설치 성공만으로 준비 완료를 판단하지 않는다.
4. 본체 CUDA 빌드 타깃은 `sm_75/80/86/89/90`으로 고정되어 있다. 실제 RTX 5060의 compute capability와 대조해 타깃 조정 필요 여부를 확인한다. faiss는 `CMAKE_CUDA_ARCHITECTURES=native`를 기본값으로 사용한다.
5. GPU 연결 및 Python 환경 준비 후 GCC 15.2·CUDA 13.4·PyTorch 조합에서 각 확장의 빌드와 작은 CUDA 실행을 확인한다. 이 점검에서는 코드나 시스템 설정을 변경하지 않았다.

### Submodule 및 포함된 외부 소스

- `git submodule status --recursive`: exit code 0, 출력 없음.
- Git index의 mode `160000` (gitlink) 항목: **0개**. 저장소 루트 `.gitmodules`: 없음.
- 해당 commit의 README는 외부 코드를 vendored 형태로 포함하고 submodule을 사용하지 않는다고 명시한다. 따라서 이 commit에서는 `git submodule update --init --recursive`가 설치 선행 작업이 아니다.
- `thirdparty/`의 `asmk`, `diff-gaussian-rasterization-modified`, `eigen`, `faiss`, `in3d`, `lietorch` 디렉터리와 주요 setup/CMake/header 파일이 존재한다. 하위 pyimgui·glm 및 CroCo RoPE2D 빌드 파일도 존재를 확인했다. 이는 소스 존재 확인이며 빌드 성공 검증은 아니다.
- `splatt3r_core/src/mast3r_src/dust3r/.gitmodules`에는 과거 CroCo submodule 선언이 남아 있다. 현재 Git index에는 gitlink가 없고 해당 CroCo 소스 파일이 포함되어 있어, 이를 미초기화 submodule로 판단하지 않는다.
- 점검 후 외부 저장소 `git status --short`: 출력 없음. 원본 코드는 수정하지 않았다.

주요 확인 명령 (프로젝트 루트 기준):

```bash
nvidia-smi
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader
nvcc --version
uname -srmo
cat /etc/os-release
python3 --version
gcc --version
g++ --version
cmake --version
make --version
lspci -nnk -s 02:00.0
ls -l /dev/nvidia* /proc/driver/nvidia/version /usr/local/cuda
lsmod
git -C thirdparty/Splatt3R-SLAM submodule status --recursive
```

Python 패키지 버전은 현재 `/usr/bin/python3`의 `importlib.metadata.version()`으로, 명령의 존재는 `shutil.which()`로 확인했다. Git index는 `git ls-files --stage`를 읽어 mode `160000` 항목 수를 집계했다. GPU 조회는 기본 샌드박스 실행과 승인된 샌드박스 밖 실행 모두 실패했다.

## GPU 복구 후 진행 (2026-10-15)

- 사용자 보고 후 재확인: 기본 샌드박스의 `nvidia-smi`는 여전히 실패하지만, 승인된 샌드박스 밖에서는 RTX 5060 / 8,151 MiB / 드라이버 595.99.02 / capability 12.0으로 정상 조회된다. 따라서 최초 점검의 실패를 현재 호스트 드라이버 장애로 계속 간주하지 않는다.
- 프로젝트 내부에 micromamba 2.9.0과 `.venv` Python 3.11.17을 준비했다. 시스템 Python·드라이버·CUDA toolkit은 변경하지 않았다.
- README 개발 버전인 PyTorch 2.13.0+cu132, torchvision 0.28.0+cu132를 설치했다. `torch.cuda.is_available()`이 참이고 CUDA 행렬곱 결과가 finite인 것을 확인했다. PyTorch 빌드의 지원 목록에 `sm_120`이 있다.
- CMake 4.4.4, Ninja 1.13.2, SWIG 4.5.1 및 MKL 개발 라이브러리를 전용 환경에 준비했다. GPU faiss, lietorch, rasterizer, SLAM backend, RoPE2D 빌드·설치가 완료됐다.
- 의존성 충돌 수정: vendored `in3d`의 `moderngl-window==2.4.6`은 NumPy <2를 요구하여 본체의 NumPy ≥2와 충돌했다. `moderngl-window>=3.1,<4`로 변경하고 실제 3.1.1 / NumPy 2.4.6으로 설치했다. 현재 Python 의존성의 `pip check`는 통과했다. GUI 동작은 아직 미검증이다.
- Build-system 메타데이터의 setuptools 70.0.0과 달리 PyTorch 2.13은 setuptools ≥77.0.3을 요구한다. README의 `--no-build-isolation` 경로를 사용하며 전용 환경의 setuptools는 84.0.0이다.
- 하드웨어 대응: 본체 `setup.py`가 명시적인 `TORCH_CUDA_ARCH_LIST`를 따르도록 수정했다. 빌드 타깃은 `12.0`, faiss는 `CMAKE_CUDA_ARCHITECTURES=120`으로 지정한다.
- 8GB 파일럿 대응: 기존 고정 512개 keyframe 사전 할당을 CLI `--keyframe-buffer`로 조절할 수 있게 하고 16을 사용했다. 후보 필터나 keyframe 선택 기준은 변경하지 않았다. 용량 초과 시 추가 조정·기록이 필요하다.
- 선택적 export: `E0_EXPORT_DIR`이 있을 때 raw per-pair pointmap·confidence·Gaussian 파라미터와 생성 이미지/pair를 기록한다. 마지막 keyframe dump에는 fused pointmap·누적 confidence·최종 pose를 추가한다. Fused ancestry와 명시적 pose revision 추적은 아직 `unknown`/미버전 상태이며 E0b에서 강화한다.
- GT 분리: 실행 wrapper의 `E0_DISABLE_GT=1`로 Replica loader의 GT trajectory 변환을 건너뛴다. GT depth·trajectory는 사후 evaluator에서만 읽으며 후보 편입에는 사용하지 않는다.
- 재현 스크립트: `scripts/bootstrap_e0_environment.sh` → `scripts/install_e0_dependencies.sh` → `scripts/build_e0_extensions.sh`; 가중치는 `scripts/download_e0_weights.sh`, 데이터는 `scripts/download_e0_replica.py --frames 120`, 실행은 `scripts/run_e0_baseline.sh`, 검증·평가는 `scripts/evaluate_e0.sh`를 사용한다.
- 로그: `results/E0_baseline_reproduction/setup/`의 `bootstrap.log`, `dependencies.log`, `extensions.log`, `weights.log`.

### 첫 실행 실패 및 호환성 조정

- 첫 기준선 실행은 성공한 결과가 아니다. 실패 artifact는 `results/E0_baseline_reproduction/attempts/attempt01/`에 보존했다.
- Retrieval backend: GPU faiss의 codebook 추가 중 메모리 부족. ASMK에서 선택적으로 faiss scratch-memory를 제한하도록 수정하고 재설치했다. 파일럿은 `E0_FAISS_TEMP_MB=64`를 사용한다. 검색 알고리즘·codebook은 그대로 유지한다.
- Rasterizer: 한 Gaussian을 렌더링하는 최소 재현에서도 약 131,000 GiB의 비정상 버퍼 할당 요청이 발생했다. CUB 상태를 초기화하고 size-query 오류를 검사한 결과 실제 오류는 `the provided PTX was compiled with an unsupported toolchain`이었다. 단순히 map 크기가 커서 생긴 OOM으로 분류하지 않는다.
- 시스템 toolkit을 교체하지 않고 NVIDIA wheel `cuda-toolkit[nvcc,cccl]==13.2.1`을 프로젝트 `.venv`에 설치했다. 작은 확장들과 SLAM backend·RoPE2D를 PyTorch와 같은 CUDA 13.2로 다시 빌드했다. 최소 GPU add/search·Sim(3)·렌더링 검사가 모두 통과했다. faiss는 시스템 13.4로 빌드한 버전이며 나머지 확장과 컴파일러가 다르므로 이 조합을 명세에 남겼다.
- NumPy 교체 전 헤더 경로가 남아 발생했던 faiss Python 바인딩 빌드 오류는 CMake에 실제 NumPy 2 include 경로를 명시하여 해결했다. faiss 1.14.3 설치 및 전체 환경의 `pip check`가 통과했다.
- 기존 upstream PLY round-trip 검사: 10,000개 synthetic Gaussian, covariance 상대 오차 `4.601e-08`, mean 최대 오차 `0`, RGB `4.266e-08`, opacity `3.099e-08`, PASS. 이는 실제 맵의 재렌더링 검사를 대신하지 않는다.
- 두 번째 실행은 PTX 오류 해결 후에도 두 GPU 프로세스의 메모리 중첩으로 실패했다. `attempts/attempt02/`에 보존했다. 성공 실행은 `E0_LOW_VRAM=1`로 미사용 CUDA 캐시를 반환하고 INIT의 첫 backend 처리를 기다리며, `--no-render-gaussians`로 프레임 미리보기를 끈다. 최종 맵 렌더링은 모델 종료 후 별도 평가 프로세스에서 수행했다. 이 메모리 관리 비용과 export 비용을 포함한 시간을 기록하며 논문의 원래 속도와 직접 비교하지 않는다.

### 코드 경로 확인

| 항목 | 코드 경로 / 확인된 동작 |
|---|---|
| 실행 진입점 | `main.py`: 입력·config·checkpoint 로드, tracker/backend, 종료 시 trajectory·Gaussian map 저장 |
| 후보 생성 | `splatt3r_slam/splatt3r_utils.py`: `splatt3r_inference_mono`는 같은 이미지를 두 번 입력, `splatt3r_match_asymmetric`는 현재 프레임과 참조 KF 쌍으로 후보를 생성 |
| Map에 보관하는 후보 | `SharedKeyframes.__setitem__`는 `gaussian_pred` (self branch)를 저장. Cross branch는 해당 프레임의 렌더링에 쓰이지만 동일한 방식으로 map buffer에 추가되는 것은 아님 |
| Raw / fused 분리 | `splatt3r_asymmetric_inference`의 decoder 출력은 raw per-pair. `Frame.update_pointmap`은 기본 `weighted_pointmap` 규칙으로 관측을 누적하므로 최종 `X_canon`을 raw 관측으로 간주하면 안 됨 |
| 후보 출처 | 선택적 export가 예측 시 이미지 쌍과 event ID를 저장하고, KF 삽입 시 같은 event ID를 연결. 최종 2개 KF의 후보 mean이 해당 raw 출력과 정확히 일치함을 검사 |
| Pose / scale | `T_WC`는 camera-to-world Sim(3). `_sim3_to_4x4`가 회전 블록에 scale을 포함하고 `bake_gaussians_world`가 mean과 covariance를 변환 |
| Quaternion | 로컬 Gaussian covariance 계산은 `(x,y,z,w)`. 표준 3DGS PLY 저장 quaternion은 `(w,x,y,z)`. 실제 회전·scale이 있는 synthetic 검사 통과 |
| 최종 snapshot | `save_keyframe_gaussians`는 종료 시 local Gaussian·현재 pose를 저장. Raw 관측 및 생성 시점과 달리 pose는 최종 상태이며 온라인 revision-at-decision 증거로 사용할 수 없음 |
| 원본 필터 | 최종 Gaussian map은 depth percentile 0.98, max scale 1.0, min confidence 1.5, 기본 min opacity 0.3을 적용. Export한 raw 후보 풀과 map의 active 후보 수를 구분 |
| Replica 평가 | RGB/depth 원해상도 1200×680, `cam_params.json`의 depth scale 6553.5 사용. 기존 upstream `eval_map_geometry.py`는 TUM depth scale 및 파일 형식 전용이므로 `scripts/evaluate_e0.py`에서 Replica 입력과 명시적 held-out split을 처리 |

## 비교 조건

- 입력 해상도 / stride / Keyframe 선택: 원본 1200×680 → 실제 512×288, input subsample 2, Gaussian spatial stride 1, 원본 tracking 선택 기준. 최종 KF는 input index 0 / 41, 원본 frame 0 / 82
- Pose 출처 / 좌표계 / scale 정렬: 원본 SLAM camera-to-world Sim(3), final anchor revision에 맞춘 60개 tracked pose 저장. 평가에서만 GT와 단일 Umeyama Sim(3) 정렬; scale 1.06758656, ATE RMSE 0.01562678 m. 온라인 decision-time pose revision은 미추적
- 후보 및 검증 관측의 출처 분리 규칙: 생성 이미지/pair와 검증 이미지의 교집합을 추적한다. Fused ancestry가 미확인인 관측은 source-disjoint로 간주하지 않는다.
- Confidence / admission threshold 및 선정 근거: 원본 confidence 1.5, depth max percentile 0.98, max scale 1.0, 기본 min opacity 0.3. 자체 gate나 threshold 탐색 없음
- Gaussian budget / 실제 active count: raw 최종 KF 후보 294,912 → active 286,208. `--max-gaussians=16777216`은 upstream viewer의 render 예산이며 headless 최종 PLY 개수의 강제 상한으로 취급하지 않는다. 이 실행에서는 matched-budget 비교를 하지 않음
- Refiner 사용 여부 및 전체 설정: refiner 없음, head/LoRA 없음, refiner conf-fade 0 명시. 포즈 backend 최적화·loop closure는 원본 설정으로 켜고, 종료 시 queue drain 후 최종 snapshot 저장
- GT 사용 범위 / held-out view 선정: mapper의 GT 변환을 비활성화했다. 평가 시 raw pinhole intrinsics에 동일 resize/crop을 적용하고, GT depth는 nearest 보간·6553.5 scale을 사용한다. 원본 홀수 프레임은 predictor/tracker에 입력하지 않음
- 저장 주기: 모든 입력의 mono/asymmetric raw 추론을 기록 (60개 event), KF 후보 생성 시 출처·삽입 pose 저장. Fused map 및 전체 pose는 종료 시 1회 저장. Per-KF 전체 map snapshot 및 명시적 pose revision은 E0b에서 보강

## 준비 및 실행 체크리스트

- [x] Splatt3R-SLAM을 git clone으로 준비했다. (사용자 수행)
- [x] 외부 저장소 URL·commit·작업 트리 상태를 확인했다.
- [x] GPU 환경과 해당 commit의 설치 안내·의존성·submodule 상태를 확인한다. (GPU 복구 후 샌드박스 밖 조회와 PyTorch CUDA 연산도 확인)
- [x] 별도 실행 환경과 가중치를 준비하고 버전·hash를 기록한다.
- [x] Replica 한 장면의 입력·평가 구간 및 설정을 고정한다.
- [x] 원본 runner로 짧은 구간을 실행하고 로그·최종 맵 렌더링·시간·샘플링 GPU 메모리를 저장한다.
- [x] Gaussian 생성/head, source pair 연결, keyframe 선택 및 raw/fused pointmap 경로를 확인한다.
- [x] 후보·관측·pose export를 구현하고 재로딩 및 좌표 변환을 검증한다. (Fused ancestry는 미확인으로 명시)
- [x] GT evaluator를 실행하고 결과·누락 지표·실패 사례를 기록한다.

Export 확인 대상:

- 후보: `candidate_id`, source image/pair IDs, anchor keyframe, 생성 시점, mean, scale, quaternion, opacity, SH, confidence
- 관측: raw per-pair pointmap, fused pointmap, confidence, 원본 이미지 ancestry 및 추적 불가 여부
- 좌표/상태: local/world 규약, pose, scale, pose revision, map/refiner 저장 시점

Source-disjoint 관측의 확보율·시차·도착 지연과 미래 관측 누출에 대한 정량 감사는 다음 E0b에서 수행한다.

## 결과

성공한 파일럿 실행 1회의 결과다. 새로운 admission 정책과의 비교나 알고리즘 효능의 증거가 아니다.

| Method / Scene / Split | Frames | Active #G | PSNR (dB) | SSIM | LPIPS Alex ↓ | GT rendered-depth L1 (m) ↓ | GT depth coverage ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 원본 admission / office0 / validation | 20 | 286,208 | 18.3498 | 0.56935 | 0.33671 | 0.108294 | 97.0995% |
| 원본 admission / office0 / held-out test | 40 | 286,208 | 15.4674 | 0.41440 | 0.43224 | 0.110685 | 79.9698% |

- 지표 정의: depth는 alpha-weighted expected rendered depth, compositing weight >1e-3인 픽셀을 coverage 후보로 본다. 유효 GT depth 중 렌더링된 양의 finite depth 픽셀에서 L1·AbsRel을 계산하며, coverage 분모는 전체 유효 GT 픽셀이다. 표는 프레임별 지표의 단순 평균이다.
- RGB는 frame 0에 고정한 원본 exposure normalization을 사용한다. 평가 intrinsics는 실제 resize/crop을 적용한 raw GT pinhole camera다. Scale 정렬에는 입력으로 사용한 짝수 프레임의 추정 pose만 사용하고, 홀수 GT pose는 평가 viewpoint에 사용한다.
- 보류 지표: TSDF/mesh accuracy·completion, 후보별 outlier precision/recall 및 오류 taxonomy는 아직 없다. 이 depth L1/coverage를 해당 지표로 바꿔 부르지 않는다.

| 실행·비용 항목 | 측정값 / 범위 |
|---|---|
| Raw 최종 KF 후보 / active | 294,912 / 286,208 |
| Resident map buffer | 2,359,296개 사전 할당 슬롯 (`16 × 288 × 512`). 유효 Gaussian 수와 다르며 transient 예측까지 포함한 전체 resident 개수는 미측정 |
| Gaussian PLY / local KF dump | 20,321,244 bytes (20.321 MB) / 25,959,223 bytes (25.959 MB) |
| GPU 사용량 | 1초 간격 device-wide 관측 최대 6,247 MiB. 프로세스 allocator의 정확한 peak VRAM과 다름 |
| 전체 실행 wall time | 26초, 모델 로딩·저장 포함. 환경 설치·사후 평가는 제외 |
| Tracking frame iteration | 59개 TRACKING row, mean 173.539 ms, median 157.876 ms, p95 186.602 ms. INIT row 없음; export·CPU 저장·backend 대기 포함 |
| Tracking 계산만 | mean 143.924 ms, median 137.342 ms, p95 142.953 ms. Per-KF mapping 지연이나 전체 시스템 실시간 FPS를 뜻하지 않음 |

검증 결과:

- Raw pair event 60개 및 최종 KF 2개의 후보 출처 연결: PASS. KF0은 source input `[0]`, KF1은 `[0, 41]` (원본 frame `[0, 82]`). Frozen 후보 ID는 prediction event ID + self branch + row-major pixel index로 구성한다.
- Sim(3) mean·covariance·scale 제곱·inverse 및 quaternion convention: PASS. 기하 대수 검사는 TF32를 끄고 수행했으며, 실제 맵 복원은 원본의 TF32 설정을 사용했다.
- 원래 local 후보를 다시 bake한 맵 vs 저장 PLY의 렌더링: mean absolute difference `3.50924e-08`, max `0.00102586` (RGB 0–1). PLY를 두 번 재로딩한 렌더링 차이는 0.
- Mapper 종료는 exit code 0. 종료 시 upstream CUDA IPC lifetime 경고가 남았지만 snapshot·후보 대조·재렌더링 검사는 통과했다. 장기 실행의 자원 정리 검증은 별도 과제로 남긴다.
- Matched-budget 충족 여부: 해당 없음; E0는 재현·추출·평가 가능성 확인 단계.

Artifact:

- [기하·RGB 평가 원자료](../../results/E0_baseline_reproduction/evaluation/metrics.json), [export 검증](../../results/E0_baseline_reproduction/export_checks.json), [실행 통계](../../results/E0_baseline_reproduction/run_stats.json)
- [기준선 로그](../../results/E0_baseline_reproduction/logs/baseline.log), [프레임별 시간](../../results/E0_baseline_reproduction/timing.csv), [GPU 메모리 샘플](../../results/E0_baseline_reproduction/device_memory.csv)
- `map/office0_kfgauss.pt`: local 후보·fused pointmap·confidence·최종 pose, `map/office0_gaussians.ply`: active world map, `map/office0_frames.txt`: 60개 tracked pose
- `exports/raw_pairs/*.pt`: raw pointmap·confidence·Gaussian·source pair, `exports/candidate_sources/*.json`: KF 삽입 event 연결
- 육안 확인 예: [frame 81 target](../../results/E0_baseline_reproduction/evaluation/render/frame000081_target.png), [frame 81 render](../../results/E0_baseline_reproduction/evaluation/render/frame000081_render.png). 문·의자 경계와 화면 외곽의 빈 영역 및 흐려짐이 보인다. 이 관찰만으로 floater/duplicate 비율을 확정하지 않는다.

## 관찰 및 다음 판단

- 확인된 사항: RTX 5060에서 메모리 관리를 적용한 원본 admission 기준선과 raw export·GT 평가를 실행할 수 있다. 시스템 환경 변경 없이 별도 환경을 고정했다.
- 성공 / 실패 사례: 초기 두 번의 실패와 해결 조건을 보존했다. 성공 실행은 60/60 tracked pose, KF 2개, active Gaussian 286,208개를 저장했다.
- 정상 표면 손실 / coverage 변화: 제안 필터에 의한 손실은 아직 측정하지 않았다. 원본 맵 자체에서 held-out coverage 평균 79.97%, 마지막 frame 119는 54.54%다. 낮은 residual만으로 좋은 맵이라고 판단하면 안 된다.
- Source-disjoint 관측 확보율 및 공유 오차의 한계: 최종 두 KF의 후보 source가 frame 0을 공유한다. 아직 충분한 source-disjoint 증거가 있다고 결론낼 수 없다. Fused ancestry·공유 모델 bias 및 과거 시점에 이용 가능한 관측 비율은 E0b에서 평가한다.
- Tracking 실패 / 비용 / 메모리 병목: 최종 실행에서 tracking failure 보고 없이 종료했다. GPU 8GB에서 preview·캐시·retrieval의 동시 메모리가 병목이므로 현재 low-VRAM 조건을 모든 비교군에 동일하게 적용해야 한다.
- 가설을 지지하거나 반박하는 결과: 아직 없음. E0는 파이프라인 작동 확인이며 제안 admission의 효능이나 novelty 판정이 아니다.
- 다음 판단: **E0 통과, E0b 진행.** 원본 논문 수치 재현·전체 16주 연구의 GO 판정과 구분한다.
- 바로 다음 작업: source ancestry/causality 감사를 구현하고, 이번 2-KF 구간에 더해 추가 KF가 확보되는 구간을 별도 config로 준비한다. Source-disjoint 가용 후보 비율·관측 도착 지연·시차를 확인한 뒤 E1 오류 taxonomy로 진행한다.
