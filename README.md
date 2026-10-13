# SQD 워크플로우 변환 예제 (IBM 예제 → 에뮬레이터 + MPI)

IBM의 SQD(Sample-based Quantum Diagonalization) 소규모 예제를 **STEP 1~4 함수 4개**로 나눈 뒤, 같은 꼴을 유지하면서 STEP 3을 외부 양자 에뮬레이터로, STEP 4를 MPI 배치 병렬로 바꾼 예제입니다. 워크플로우 엔진으로 옮길 때 함수 하나가 작업(task) 하나가 되도록 만들었습니다.

**읽을 파일은 두 개입니다.**

| 파일 | 역할 | 실행기 |
| --- | --- | --- |
| [`sqd_workflow/ibm_steps.py`](sqd_workflow/ibm_steps.py) | IBM 예제 원문을 STEP 1~4 함수와 dataclass 3개로 나눈 것. N₂/STO-6G 16큐비트 고정, Qiskit `StatevectorSampler`, 단일 프로세스. STEP 4 알고리즘의 원본. | `run_steps.py` |
| [`sqd_workflow/emulator_steps.py`](sqd_workflow/emulator_steps.py) | 같은 함수 4개·자료형 규약을 유지한 변형. 수소 사슬 H_n(크기 조절), STEP 2가 OpenQASM도 생성, STEP 3이 pennylane-lightning-MPI 에뮬레이터를 호출, STEP 4는 `mpi=True`로 배치를 MPI rank에 분배(`ibm_steps.step4_postprocess`를 그대로 호출). | `run_example.py` |

`sqd_workflow/mpi_solver.py`는 STEP 4의 배치 병렬 solver(60줄)로 `emulator_steps.step4_postprocess(mpi=True)`가 사용합니다. 그 밖의 개발·검증 부속물(테스트, 벤치마크, 36큐비트 실험, 문서, IBM 원본 사본)은 모두 [`archive/`](archive/README.md)에 있고 핵심 코드를 읽는 데는 필요하지 않습니다.

## 두 파일의 대응

| | `ibm_steps.py` | `emulator_steps.py` |
| --- | --- | --- |
| STEP 1 `step1_map` | N₂ 고정 → `MappedProblem` | `n_atoms`·`spacing`·`n_reps`·`compute_fci` 인자 → 같은 `MappedProblem` |
| STEP 2 `step2_optimize` | ISA `QuantumCircuit` | `OptimizedCircuit` = ISA 회로 + OpenQASM 2.0 + 측정 비트 대응표 |
| STEP 3 `step3_execute` | `StatevectorSampler` → `ExecutedCircuit` | 에뮬레이터 `mpi_counts_cli`(subprocess, MPI 32 rank) → 같은 `ExecutedCircuit` + `EmulatorRun`. `sampler="statevector"`면 원문 방식 |
| STEP 4 `step4_postprocess` | SQD 복구·대각화 반복(원본) | `mpi=True`면 `mpi_solver.batch_parallel`을 `wrap_solver`로 넘겨 원본 함수 호출 |
| 함수 사이 값 | 메모리 | 메모리 또는 pickle 파일(`run_example.py --save/--load`) |
| 외부 프로그램 | 없음 | STEP 3의 에뮬레이터만 |

STEP 4의 알고리즘 코드는 바꾸지 않았습니다. 난수 규약(`default_rng(seed)` 상태를 STEP 3이 넘기고 STEP 4가 복원)도 같습니다. 자세한 항목별 비교는 [`archive/docs/emulator_steps_변경점.md`](archive/docs/emulator_steps_변경점.md)에 있습니다.

## 설치

Python 3.11과 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비하고 이 폴더 안에서 실행합니다.

```bash
uv sync --locked                   # 기본(단일 프로세스)
uv sync --locked --extra mpi       # STEP 4 MPI까지. mpi4py 는 사이트 MPI 로 소스 빌드(slurm/setup_env.sh 참고)
```

uv 없이: `python3.11 -m venv .venv && source .venv/bin/activate && pip install .`

## 실행

### 1) IBM 원문 (`ibm_steps.py`)

```bash
uv run python run_steps.py
```

N₂ 16큐비트, 10만 shot, 배치 3개, `max_dim=50`. 노트북 1~2분. 총에너지 약 −108.5959 Ha, SQD 반복 2회.

### 2) 에뮬레이터 + MPI 예제 (`emulator_steps.py`)

로컬 검증(에뮬레이터 없이 Qiskit 샘플러, 12큐비트, 1분 이내):

```bash
uv run python run_example.py --n-atoms 6 --sampler statevector --shots 5000 \
    --set num_batches=4 --set samples_per_batch=1000 --set max_dim=50 --set max_iterations=2
```

실제 크기(H₁₄ 28큐비트, 에뮬레이터 32 rank, STEP 4 D=10⁶ 배치 64 반복 3), 클러스터 노드에서:

```bash
python run_example.py                                   # 단일 프로세스(STEP 4 스레드만)
srun --mpi=pmi2 -n 32 -c 1 python run_example.py --mpi  # STEP 4 를 32 rank 배치 병렬
```

`--mpi`일 때 rank 0이 STEP 1~3을 수행해 결과를 broadcast하고 모든 rank가 `step4_postprocess(mpi=True)`를 부릅니다(SPMD). STEP 1~3과 STEP 4를 별도 작업으로 나누려면 `--only-prepare --save DIR` 뒤에 `--mpi --load DIR`을 씁니다. 전체 옵션은 `python run_example.py -h`.

Slurm 작업 하나로 세 단계(A: STEP 1~3, B: STEP 4 MPI 32 rank, C: STEP 4 32 스레드 비교)를 돌리는 스크립트가 [`slurm/example.sbatch`](slurm/example.sbatch)입니다. 클러스터 경로·계정·MPI 위치는 [`slurm/site.env`](slurm/site.env)에서, 공유 가상환경 생성은 `slurm/setup_env.sh`로 합니다. 에뮬레이터·MPI 경로 기본값은 `emulator_steps.py` 상단의 `SQD_EMULATOR_CLI`, `SQD_MPI_HOME` 환경변수로 바꿉니다.

## 구성

```text
sqd_workflow_bundle/
├── sqd_workflow/
│   ├── ibm_steps.py        # [핵심 1] IBM 원문 STEP 1~4 함수 + dataclass 3개
│   ├── emulator_steps.py   # [핵심 2] 에뮬레이터·MPI 변형 (같은 함수 4개 + 보조 함수)
│   ├── mpi_solver.py       # STEP 4 배치 병렬 sci_solver (emulator_steps 가 사용)
│   └── __init__.py
├── run_steps.py            # ibm_steps 실행기 (인자 없음)
├── run_example.py          # emulator_steps 실행기 (--mpi, --save/--load, --set ...)
├── slurm/                  # example.sbatch(MPI 테스트 작업), site.env, setup_env.sh
├── pyproject.toml, uv.lock # 고정 의존성 (qiskit 2.5.2, qiskit-addon-sqd 0.13.1, ffsim, pyscf, mpi4py[extra])
├── NOTICE.md               # IBM 원본 출처·라이선스·수정 내역
└── archive/                # 개발·검증 부속물 (README 참고). 실행 유지 대상 아님
```

## 워크플로우로 옮길 때

- 작업 경계 = 함수 경계. 함수 사이 값은 모두 pickle 가능합니다(`MappedProblem`은 `strip_for_transfer`로 pass manager를 뺀 뒤).
- STEP 3만 외부 명령을 부릅니다. 다른 에뮬레이터나 QPU로 바꾸려면 "OpenQASM 입력 → counts 출력" 부분과 `convert_emulator_counts`만 갈아 끼우면 됩니다.
- STEP 4 MPI는 모든 rank가 같은 입력으로 `step4_postprocess(mpi=True)`를 부르는 SPMD 규약입니다. 배치 k는 rank k % size가 풀고 rank 0만 결과를 받습니다. 병렬도는 배치 수까지입니다.
- 자원: STEP 1은 FCI 때문에 코어 여러 개(H₁₄ 32코어 약 1분), STEP 3은 노드 코어 전부(에뮬레이터), STEP 4는 rank당 메모리(D=10⁶ 0.3 GB, 10⁷ 3 GB, 10⁸ 30 GB).
- MPI는 배치당 부분공간이 클 때(D 10⁵ 이상)만 이득입니다. IBM 예제 크기에서는 단일 프로세스가 더 빠릅니다.

## 출처

IBM 코드는 Apache-2.0이며 출처·수정 내역은 [`NOTICE.md`](NOTICE.md), 원본 사본과 라이선스는 `archive/references/n2_small_scale/`에 있습니다.
