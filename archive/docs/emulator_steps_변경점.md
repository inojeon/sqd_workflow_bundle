# emulator_steps.py: ibm_steps.py와 무엇이 다른가

> **대상:** 이 번들을 처음 보는 사람, 또는 SQD를 워크플로우로 옮기는 사람. **비교 대상:** IBM 소규모 예제를 함수 4개로 나눈 `sqd_workflow/ibm_steps.py` + 실행기 `run_steps.py` 대 양자 에뮬레이터·고전 배치 병렬 예제 `sqd_workflow/emulator_steps.py` + 실행기 `run_example.py`. **한 줄 요약:** 함수 4개의 이름·순서·자료형 규약은 그대로 두고, (1) 분자를 수소 사슬로 바꾸고, (2) STEP 2가 OpenQASM도 내놓고, (3) STEP 3이 Qiskit 샘플러 대신 외부 에뮬레이터를 부르며, (4) STEP 4에 `mpi=True` 스위치를 더했다. STEP 4의 알고리즘 코드는 한 줄도 바꾸지 않았다(`ibm_steps.step4_postprocess`를 그대로 호출). kqdata01 로그인 노드에서 12큐비트로 네 가지 실행 경로를 검증했다.

## 1. 한눈에 보기

| | `ibm_steps.py` (IBM 원문) | `emulator_steps.py` (예제) |
| --- | --- | --- |
| 분자 | N₂, STO-6G, 대칭 D∞h, 코어 2궤도 동결, 16큐비트 | 수소 사슬 H_n(기본 14원자, 1.5 Å), STO-6G, 대칭 없음, 동결 없음, 2n큐비트(기본 28) |
| STEP 1 출력 | `MappedProblem` | **같은** `MappedProblem` |
| STEP 2 출력 | `QuantumCircuit`(ISA) | `OptimizedCircuit` = ISA 회로 + **OpenQASM 2.0 문자열 + 측정 비트 대응표 + 게이트 수** |
| STEP 3 샘플러 | Qiskit `StatevectorSampler`, 10만 shot | 외부 에뮬레이터 `mpi_counts_cli`(MPI 32 rank), 20만 shot. `sampler="statevector"`로 원문 방식도 선택 가능 |
| STEP 3 출력 | `ExecutedCircuit` | **같은** `ExecutedCircuit` + 실행 기록 `EmulatorRun` |
| STEP 4 | `step4_postprocess(mapped, executed, wrap_solver, settings)` | `step4_postprocess(mapped, executed, mpi, settings)` → 안에서 원문 함수를 호출 |
| 실행기 | `run_steps.py`: 인자 없이 1→4 순서 실행 | `run_example.py`: 같은 순서 + 명령행 인자, `--mpi`, `--save/--load`(작업 분리) |
| 외부 프로그램 | 없음 | STEP 3의 에뮬레이터(별도 프로세스) |
| 바뀌지 않은 것 | | 자료형 3개, STEP 4 알고리즘 전체, 난수 규약(`default_rng(seed)` 상태를 STEP 3이 넘기고 STEP 4가 복원) |

## 2. 단계별 변경 내용

### STEP 1 `step1_map`

| 항목 | 원문 | 예제 | 이유 |
| --- | --- | --- | --- |
| 서명 | `step1_map(*, compilation_seed=12345)` | `step1_map(*, n_atoms=14, spacing=1.5, basis="sto-6g", n_reps=2, compute_fci=True, compilation_seed=12345)` | 분자 크기를 인자로 바꿀 수 있게 |
| 분자 | N₂ 고정, `symmetry="Dooh"`, `n_frozen=2` | `h_chain(n_atoms, spacing)`, `symmetry=False`, 동결 없음(활성 공간 = 전체 궤도) | 반 채움 사슬은 분포가 넓어 고전 쪽 D를 키우기 쉽다([쉽게 읽는 설명](쉽게_읽는_SQD_고전계산.md)) |
| FCI 기준값 | 항상 계산 | `compute_fci=False`면 생략(NaN) | 궤도 18개 이상은 FCI가 무겁다 |
| `mol.max_memory` | 기본(4 GB) | 150,000 MB | FCI 차원 10⁷~10⁸에 기본값은 부족 |
| LUCJ 반복 수 | 4 | 2(인자) | 측정 결과 2회가 샘플 다양성이 더 컸다 |
| pass manager·UCJ 연산자 | 원문 코드 인라인 | `scaled._pass_manager`, `scaled._ucj_operator` 호출 | 같은 내용을 `run_scaled.py`와 공유 |
| 반환 | `MappedProblem` | 동일 | |

원문의 `print("norb=…")`류 출력은 한 줄로 합쳤다. 늘린 사슬(1.5 Å)에서는 CCSD가 "not converged"를 내지만 LUCJ 초기 진폭으로 그대로 쓴다(원문도 CCSD 수렴 여부를 확인하지 않는다).

### STEP 2 `step2_optimize`

| 항목 | 원문 | 예제 |
| --- | --- | --- |
| 하는 일 | `pass_manager.run(circuit)` | 같은 호출 + `scaled.to_emulator_qasm(isa)` |
| 반환 | `QuantumCircuit` | `OptimizedCircuit(isa_circuit, qasm, measure_map, gate_counts)` |

에뮬레이터는 Qiskit 회로 객체를 못 읽고 OpenQASM 2.0만 받으며, 지원 게이트가 `h x y z rx ry rz cx cz swap cp`뿐이라 ISA 회로(`xx_plus_yy`, `p` 포함)를 이 게이트들로 다시 transpile한다. `measure_map[c]`는 고전 비트 c가 측정하는 물리 큐비트로, STEP 3이 counts 문자열을 Qiskit 비트 순서로 되돌릴 때 쓴다. 파라미터는 `repr(float)`로 쓴다(에뮬레이터 파서가 `pi` 식을 못 읽음).

### STEP 3 `step3_execute`

| 항목 | 원문 | 예제 |
| --- | --- | --- |
| 서명 | `step3_execute(isa_circuit)` | `step3_execute(optimized, *, shots=200_000, n_ranks=32, seed=12345, sampler="emulator", emulator_cli, mpi_home, workdir=None)` |
| 샘플러 | `StatevectorSampler(seed=rng)`, 10만 shot | `mpiexec -launcher fork -np 32 mpi_counts_cli --qasm … --shots … --fuse all` 를 `subprocess.run`으로 실행, 표준출력의 counts JSON을 받음 |
| 비트열 변환 | 없음(Qiskit이 `BitArray` 제공) | `scaled.convert_emulator_counts(counts, measure_map, rng)` → bool 행렬 → `BitArray.from_bool_array` |
| 난수 | `rng = default_rng(12345)`로 샘플링, 그 뒤 상태를 `ExecutedCircuit.rng_state`에 저장 | `rng = default_rng(seed)`를 만들어 **샘플링 전 상태**를 `rng_state`로 저장하고, 같은 seed를 에뮬레이터 `PLMPI_SEED`에도 준다 |
| 반환 | `ExecutedCircuit(pub_result, rng_state)` | `(ExecutedCircuit, EmulatorRun)` — `EmulatorRun`은 cli·rank 수·shot·seed·벽시계·고유 비트열 수 |

난수 규약의 차이에 주의: 원문은 StatevectorSampler가 rng를 소비한 **뒤**의 상태를 넘기지만, 에뮬레이터는 Python rng를 쓰지 않으므로 예제는 `default_rng(seed)` **초기 상태**를 넘긴다. 어느 쪽이든 STEP 4는 받은 상태에서 시작하므로 재현성은 같다. 다만 같은 seed라도 원문과 예제의 STEP 4 난수열은 다르다.

에뮬레이터 실행 환경 처리:
- 바깥이 이미 MPI(srun) 안이어도 안쪽 MPI가 새로 뜨도록 `PMI_*`, `SLURM_STEP*`, `MPI_LOCAL*` 환경변수를 지운다.
- `-launcher fork`는 한 노드에서 프로세스를 fork로 띄우므로 Slurm 안팎에서 같은 명령이 돈다. rank 수는 2의 거듭제곱이어야 한다(아니면 결과가 조용히 틀린다. 코드에서 검사).
- 자식 프로세스는 `sched_setaffinity`로 코어 묶임을 풀어, srun이 rank 0을 코어 1개에 묶어도 에뮬레이터가 노드 코어를 모두 쓴다.
- 경로 기본값은 kqdata01 것이며 `SQD_EMULATOR_CLI`, `SQD_MPI_HOME` 환경변수로 바꾼다.
- `sampler="statevector"`면 원문과 같은 Qiskit 샘플러를 써서 같은 자료형을 만든다(20큐비트 이하 검증용).

### STEP 4 `step4_postprocess`

| 항목 | 원문 | 예제 |
| --- | --- | --- |
| 서명 | `(mapped, executed, *, wrap_solver=None, settings=None)` | `(mapped, executed, *, mpi=False, settings=None)` |
| 본문 | 측정 통계, 구성 복구·대각화 반복, FCI 오차 | **원문 함수를 그대로 호출**. `mpi=True`면 `wrap_solver=lambda s: mpi_solver.batch_parallel(s, comm)`를 넘기고, 예외 시 전체 중단(`abort_on_error`)·SDK MPI 감지 확인(`check_sdk_mpi`)을 먼저 한다 |

즉 예제의 STEP 4는 원문의 얇은 포장이다. 배치 병렬의 구현(`mpi_solver.batch_parallel`, 배치 k → rank k % size, 결과를 rank 0으로 gather)은 [MPI 적용 결과](MPI_적용_결과.md)에 설명되어 있다.

### 자료형

| 자료형 | 출처 | 비고 |
| --- | --- | --- |
| `MappedProblem`, `ExecutedCircuit`, `PostprocessedResult` | `ibm_steps` 그대로 import | STEP 1·3·4 출력 |
| `OptimizedCircuit` | 예제에서 추가 | STEP 2 출력(에뮬레이터 입력 포함) |
| `EmulatorRun` | 예제에서 추가 | STEP 3 실행 기록 |
| `strip_for_transfer(mapped)` | 예제에서 추가 | 회로·pass manager를 뺀 `MappedProblem` 사본. pass manager는 pickle이 안 되므로 파일·broadcast로 넘길 때 사용 |

## 3. 실행기: `run_steps.py` 대 `run_example.py`

| 항목 | `run_steps.py` | `run_example.py` |
| --- | --- | --- |
| 실행 | `python run_steps.py` | `python run_example.py [옵션]` |
| 스레드 | 항상 1 | `--threads T` |
| 문제 크기 | 고정 | `--n-atoms`, `--spacing`, `--n-reps`, `--no-fci`, `--shots`, `--ranks`(에뮬레이터), `--sampler`, `--seed`, `--set 이름=값`(STEP 4 설정; 기본 `num_batches=64 samples_per_batch=50000 max_dim=1000 max_iterations=3`) |
| MPI | 없음 | `--mpi`: rank 0이 STEP 1~3을 하고 `(strip_for_transfer(mapped), executed)`를 `comm.bcast`, 모든 rank가 STEP 4. rank 0 외 표준 출력은 끔 |
| 작업 분리 | 없음 | `--only-prepare --save DIR`: STEP 1~3만 하고 저장(`step1_mapped.pkl`, `step2_circuit.qasm`, `step2_measure_map.json`, `step3_executed.pkl`, `step3_run.json`, `step13_timing.json`). `--load DIR`: 그 파일을 읽어 STEP 4만 |
| 결과 | 반복 수·궤도 점유수 출력 | 위 출력 + JSON 요약(큐비트, FCI, SQD 에너지, 오차, 반복, D, 설정, 시간) → `step4_summary_<S32|M32x1>.json` |
| MPI 환경 오검출 | — | `--mpi` 없이 rank 여러 개 환경이면 중단(SDK가 rank마다 전체 루프를 따로 도는 사고 방지) |

Slurm에서는 `slurm/example.sbatch`가 이 두 모드를 작업 하나 안에서 A(STEP 1~3, 1 task 32코어) → B(STEP 4, 32 rank) → C(STEP 4, 32스레드 비교) 세 단계로 돌린다. 워크플로우 엔진에서는 A를 작업 1개(또는 함수 3개), B를 MPI 작업 1개로 보면 된다.

## 4. kqdata01에서 한 검증

로그인 노드(kqdata01)에서 H₆(12큐비트, 궤도 6·전자 3+3) 작은 문제로 네 경로를 돌렸다. 설정 `--shots 5000 --set num_batches=4 --set samples_per_batch=1000 --set max_dim=50 --set max_iterations=2`.

| 경로 | 명령 | SQD 에너지 (Ha) | 비고 |
| --- | --- | --- | --- |
| 단일 프로세스, Qiskit 샘플러 | `python run_example.py --sampler statevector …` | −2.951098 | 원문 방식 |
| 단일 프로세스, 에뮬레이터 2 rank | `python run_example.py --sampler emulator --ranks 2 …` | −2.951098 | 에뮬레이터 0.2초, 고유 비트열 83 |
| MPI 2 rank, Qiskit 샘플러 | `mpiexec -launcher fork -n 2 python run_example.py --mpi …` | −2.951098 | STEP 1~3 broadcast 경로 |
| 저장 후 재적재, MPI 2 rank | `--only-prepare --save D` 뒤 `mpiexec … --mpi --load D` | −2.951098 | 작업 분리 경로 |

FCI는 −3.020198 Ha(오차 69 mHa는 D=144로 작은 부분공간 탓). 네 경로의 에너지가 같은 것은 이 크기에서 부분공간이 포화되어 같은 표를 풀기 때문이며, 경로 간 자료형·난수 규약이 어긋나지 않았음을 뜻한다.

28큐비트 실제 크기(H₁₄, 에뮬레이터 32 rank, D=10⁶ 배치 64 반복 3)는 `slurm/example.sbatch`로 kqsvr04에 제출했다(작업 3295). 결과는 [H₁₆ MPI 확장성](H16_MPI_확장성.md)의 예제 절에 기록한다.

## 5. 워크플로우로 옮길 때 참고

- 작업 경계는 함수 경계와 같다. 함수 사이 값은 모두 pickle 가능(`strip_for_transfer` 적용 후)하므로 파일이나 객체 저장소 어느 쪽으로도 넘길 수 있다.
- STEP 3만 외부 명령을 부른다. 다른 에뮬레이터나 실제 QPU로 바꾸려면 "OpenQASM 입력 → counts 출력" 명령과 `convert_emulator_counts`만 갈아 끼우면 된다.
- STEP 4의 MPI는 "같은 스크립트를 rank 수만큼 띄우고 모두가 `step4_postprocess(mpi=True)`를 부른다"는 SPMD 규약이다. 입력은 모든 rank에서 같아야 하므로 rank 0이 읽어 broadcast하거나 모든 rank가 같은 파일을 읽는다.
- 자원 요구: STEP 1은 FCI 때문에 코어 여러 개(32코어 H₁₄ 1분, H₁₆ 22분), STEP 3은 노드 코어 전부(에뮬레이터), STEP 4는 rank당 메모리(D=10⁶ 0.3 GB, 10⁷ 3 GB, 10⁸ 30 GB).
