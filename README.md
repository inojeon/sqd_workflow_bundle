# IBM SQD 워크플로우 실행 패키지

`run_steps.py`를 중심으로 IBM 소규모 시뮬레이터 예제의 STEP 1~4를 실행하는 독립 폴더입니다. 이 폴더 전체를 다른 위치에 복사해 사용할 수 있습니다.

**먼저 읽기:** [HTML 가이드](docs/guide.html) · [Markdown 가이드](docs/guide.md)

**MPI 적용 결과(2026-10-08):** [정리 문서](docs/MPI_적용_결과.md) · [HTML](docs/MPI_적용_결과.html)

## 설치와 실행

Python 3.11과 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비하고 **이 폴더 안에서** 실행합니다. 최초 설치에는 인터넷이 필요합니다.

```bash
uv sync --locked --extra test
uv run --locked python run_steps.py
uv run --locked --extra test python -m pytest -q
```

uv를 사용하지 않는 경우:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install '.[test]'
python run_steps.py
python -m pytest -q
```

### STEP별 실행과 Slurm

STEP 1~4를 각각 별도 프로세스(별도 Slurm 작업)로 돌릴 수 있습니다. STEP 사이는 `--workdir` 폴더의 파일로 이어지고, STEP 4만 MPI로 배치를 나눠 풉니다. 자세한 파일 계약과 동등성 조건은 [가이드](docs/guide.md) 6.1절에 있습니다.

```bash
python run_step.py 1 --workdir W     # STEP 1~3: 단일 프로세스
python run_step.py 2 --workdir W
python run_step.py 3 --workdir W
srun --mpi=pmi2 -n 3 python run_step.py 4 --workdir W --mpi   # 배치 k → rank k % 3

slurm/setup_env.sh                          # 클러스터 공유 환경(Python 3.11 + uv.lock + mpi4py), 최초 1회
slurm/submit_chain.sh -w kqsvr04 -n 3       # STEP 1~4 작업 4개를 afterok로 제출
```

MPI는 배치당 부분공간이 클 때(D 10⁵ 이상)만 이득입니다. IBM 예제 크기에서는 단일 프로세스가 더 빠릅니다([성능 비교](validation/bench_step4/README.md)).

사이트 값(공유 경로, 제출 계정, MPI 경로, 파티션)은 `slurm/site.env`에서 바꿉니다. MPI 설치는 `uv sync --locked --extra mpi`이고, mpi4py는 사이트 MPI로 소스 빌드합니다(`setup_env.sh` 참고).

pip 경로는 직접 의존성 버전을 고정하지만 전이 의존성은 `uv.lock`과 다를 수 있습니다. 재현 비교에는 uv 경로를 권장합니다. 검증 대상은 macOS arm64 / Python 3.11이며 다른 OS·CPU의 수치와 설치 가능 여부는 별도로 확인해야 합니다.

## 구성

```text
sqd_workflow_bundle/
├── run_steps.py                 # 네 단계를 연결하는 실행 진입점
├── run_step.py                  # STEP 하나만 실행(STEP별 Slurm 작업용)
├── sqd_workflow/
│   ├── __init__.py
│   ├── ibm_steps.py             # 계산 함수 4개와 입출력 dataclass
│   ├── stages.py                # STEP 사이 파일 계약(npz·qpy·json)
│   └── mpi_solver.py            # STEP 4 MPI 배치 병렬 sci_solver
├── slurm/                       # site.env·setup_env.sh·step.sbatch·submit_chain.sh
├── pyproject.toml              # 설치·테스트·문서 의존성
├── uv.lock                     # 전이 의존성까지 고정
├── docs/guide.md                # 가이드 원본
├── docs/guide.html              # 브라우저용 가이드
├── tools/build_guide.py         # Markdown → HTML 재생성
├── references/n2_small_scale/   # IBM 고정 원본·독립 실행기·라이선스
├── tests/                      # 원본과 단계별 결과 비교, STEP 분리·MPI 동등성
├── bench/                      # STEP 4 성능 비교 도구(단일 프로세스 대 MPI)
├── validation/                 # 분리된 환경에서 실행한 검증 기록
├── COPY_MANIFEST.json           # 복사본의 출처와 SHA-256
└── NOTICE.md                   # 라이선스·수정 내역
```

## 기본 계산

N₂ / STO-6G / 활성 공간 8궤도·10전자 / **16큐비트** / LUCJ 4회 / 100,000 shots / 배치 3개 / `max_dim=50`입니다. 검증 환경의 총에너지는 약 **−108.59593164616311 Ha**, SQD 반복은 2회였습니다. 더 자세한 근거는 [검증 기록](validation/README.md)을 참고하세요.

## 제공 범위

SDK 연결 직전의 Python 워크플로우입니다. STEP 4 안에서 SQD 복구·대각화 반복을 수행합니다. 한 프로세스 실행(`run_steps.py`)과 STEP별 Slurm 작업 실행(`run_step.py`, `slurm/`)을 모두 제공하며, STEP 4는 MPI rank에 배치를 나눠 풀 수 있습니다(PySCF, IBM 원본과 같은 `spin_sq=0.0`). 실제 QPU 제출, 한 배치 내부의 분산 대각화(SBD 등), GPU 솔버는 후속 구현 대상입니다. STEP 1에 FCI 기준값 계산이 있으므로 분자 크기를 바로 키우기 전에 해당 경로를 분리해야 합니다.

## 문서 갱신

```bash
uv sync --locked --extra test --extra docs
uv run --locked --extra docs python tools/build_guide.py
```

`docs/guide.md`를 편집한 후 재생성합니다. HTML에는 현재 `run_steps.py` 전체 코드도 자동 삽입됩니다. 외부 폰트·스크립트 없이 열리며 브라우저 인쇄로 PDF를 저장할 수 있습니다.
