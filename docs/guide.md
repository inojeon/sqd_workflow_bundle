# run_steps.py로 이해하는 SQD 워크플로우

IBM small-scale simulator 예제의 계산을 네 단계로 실행하고, 이후 워크플로우 SDK에 연결하기 위한 개발자·연구자 가이드입니다. 정리일: 2026-10-07. 갱신: 2026-10-08(STEP별 Slurm 작업, STEP 4 MPI 배치 병렬).

> 이 폴더는 **SDK 연결 직전의 독립 실행 패키지**입니다. 실행 코드는 기존 계산을 그대로 복사했으며, 파일 배치·설치 설정·검증·설명 문서를 함께 제공합니다.

[TOC]

## 1. 무엇을 실행하는가

질소 분자 N₂의 바닥상태 에너지를 SQD(sample-based quantum diagonalization)로 추정합니다. 양자 회로에서 전자 배치를 샘플링하고, 고전 컴퓨터에서 선택된 부분공간의 Hamiltonian을 대각화합니다. 본 실행에서는 QPU 대신 Qiskit의 이상적인 `StatevectorSampler`를 사용합니다.

| 항목 | 기본 설정 |
| --- | --- |
| 분자·기저 | N₂, N–N 거리 1.0 Å, STO-6G |
| 활성 공간 | 공간 궤도 8개, 전자 10개: α=5, β=5 |
| 큐비트 | 16개: 공간 궤도당 스핀 궤도 2개 |
| 회로 | Hartree–Fock 상태 + LUCJ, 반복 4회 |
| 샘플링 | StatevectorSampler, 100,000 shots, seed=12345 |
| SQD | 배치 3개, 배치당 샘플 1,000개, `max_dim=50` |
| 수렴 조건 | 에너지·점유수 허용오차 각각 1e-3, 최대 SQD 반복 5회 |
| 대각화 | `solve_sci_batch`, `spin_sq=0.0`, `max_cycle=200` |
| 비교값 | STEP 1에서 계산한 활성 공간 FCI 총에너지 |

`GenericBackendV2`는 회로 변환의 대상 연결 구조와 게이트 집합을 제공합니다. 이것을 사용했다고 실제 QPU나 잡음 모델에서 실행한 것은 아닙니다. 현재 샘플링은 이상적인 상태벡터 계산입니다.

## 2. 설치와 첫 실행

폴더 전체를 원하는 위치에 복사합니다. 이후 아래 명령은 `run_steps.py`와 `pyproject.toml`이 있는 폴더에서 실행합니다.

```bash
cd sqd_workflow_bundle
uv sync --locked --extra test
uv run --locked python run_steps.py
```

Python 3.11을 사용합니다. 최초 의존성 설치에는 네트워크가 필요하지만 실행에는 IBM 계정·API 키가 필요하지 않습니다. [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 참고하세요. pip 설치 명령은 [README](../README.md)에 있습니다.

화면에는 분자 계산 결과, 단계 이름, 회로 게이트 수, 샘플 유효 비율, 반복별 배치 에너지, 최종 에너지와 점유수가 출력됩니다. 로그를 보관하려면 다음처럼 실행합니다.

```bash
mkdir -p runs
uv run --locked python run_steps.py > runs/execution.log 2>&1
```

드라이버는 결과 파일을 자동 생성하지 않습니다. 마지막 결과는 `main()`의 반환값으로 받을 수 있습니다.

```python
from run_steps import main

result = main()
print(result.final_energy)
print(result.energy_error)
print(len(result.result_history))
```

## 3. 파일을 읽는 순서

| 파일 | 역할 | 읽는 시점 |
| --- | --- | --- |
| [run_steps.py](../run_steps.py) | 네 함수의 호출 순서와 데이터 연결 | 가장 먼저 |
| [sqd_workflow/ibm_steps.py](../sqd_workflow/ibm_steps.py) | 계산 본문·반환 자료형 | 단계별 상세를 볼 때 |
| [pyproject.toml](../pyproject.toml) / [uv.lock](../uv.lock) | 직접·전이 의존성 | 환경을 재현할 때 |
| [원본 코드](../references/n2_small_scale/original.py) | IBM 예제 코드 셀 보존본 | 과학 코드 출처를 비교할 때 |
| [독립 원본 실행기](../references/n2_small_scale/run_reference.py) | 원본 실행·중간 데이터 저장 | 재현 검증할 때 |
| [비교 테스트](../tests/test_ibm_steps.py) | 적분·샘플·에너지·점유수·이력 비교 | 변경 후 검증할 때 |
| [run_step.py](../run_step.py) / [sqd_workflow/stages.py](../sqd_workflow/stages.py) | STEP 하나만 실행, STEP 사이 파일 계약 | STEP별 Slurm 작업으로 돌릴 때 |
| [sqd_workflow/mpi_solver.py](../sqd_workflow/mpi_solver.py) | STEP 4 MPI 배치 병렬 sci_solver | STEP 4를 여러 rank로 돌릴 때 |
| [slurm/](../slurm/site.env) | 사이트 설정·공유 환경 빌드·작업 사슬 제출 | 클러스터에서 실행할 때 |
| [sqd_workflow/scaled.py](../sqd_workflow/scaled.py) / [run_scaled.py](../run_scaled.py) | 문제 크기 일반화(36큐비트), 에뮬레이터 QASM·샘플러 | 큰 문제를 돌릴 때 |
| [분리 실행 테스트](../tests/test_stages.py) | STEP별 프로세스 실행 = 원본, MPI STEP 4 = 단일 프로세스 | 변경 후 검증할 때 |
| [COPY_MANIFEST.json](../COPY_MANIFEST.json) | 원 프로젝트 복사 출처와 해시 | 전달 이력을 확인할 때 |
| [NOTICE](../NOTICE.md) | IBM 라이선스와 수정 내역 | 재배포할 때 |

원 프로젝트의 다른 계산 경로인 `prepare/sample/postprocess/solve`, CLI, MPI 코드는 이 폴더의 실행 의존성이 아닙니다. 이 패키지에는 `run_steps.py`가 실제 사용하는 코드와, 같은 계산을 STEP별 작업으로 나눠 돌리는 코드(`run_step.py`, `stages.py`, `mpi_solver.py`, `slurm/`)만 담았습니다.

## 4. 네 단계와 의존 관계

```text
STEP 1: step1_map()
    │ mapped: 분자 정보 + 적분 + 회로 + pass manager + FCI 기준값
    ├──────────────────────────────────────────┐
    ▼                                          │
STEP 2: step2_optimize(mapped)                  │
    │ isa_circuit: 최적화된 측정 회로           │
    ▼                                          │
STEP 3: step3_execute(isa_circuit)              │
    │ executed: 측정 결과 + 난수 상태           │
    ▼                                          ▼
STEP 4: step4_postprocess(mapped, executed)
    └─ 유효 비율 확인 → 구성 복구·부분공간 대각화 반복 → 총에너지
```

STEP 4에는 STEP 3의 샘플 외에 **STEP 1의 적분과 분자 정보가 직접 필요**합니다. 단순히 마지막 작업의 출력만 다음 작업으로 넘기는 선형 체인으로 구현하면 이 의존성을 놓치게 됩니다.

| IBM 공식 단계 이름 | 함수 | 입력 → 출력 | 기본 실행 자원 |
| --- | --- | --- | --- |
| STEP 1: Map classical inputs to a quantum problem | `step1_map()` | 기본 분자 설정 → `MappedProblem` | 로컬 CPU |
| STEP 2: Optimize for quantum hardware execution | `step2_optimize(mapped)` | `MappedProblem` → `QuantumCircuit` | 로컬 CPU |
| STEP 3: Execute using Qiskit primitives | `step3_execute(isa_circuit)` | 회로 → `ExecutedCircuit` | 로컬 상태벡터 시뮬레이션 |
| STEP 4: Post-process and return result in desired classical format | `step4_postprocess(mapped, executed)` | 분자·측정 결과 → `PostprocessedResult` | 로컬 CPU |

이 단계는 IBM의 알고리즘 설명 기준입니다. 각 단계를 Slurm CPU 노드 하나, QPU, MPI 노드 여러 개와 일대일로 고정한 자원 분할은 아닙니다.

### STEP 1 — 분자 문제와 회로 구성

PySCF로 RHF 계산을 수행하고 활성 공간 적분을 구합니다. 작은 문제의 정확한 비교값을 얻기 위해 CASCI/FCI를 실행합니다. CCSD의 t1·t2 진폭으로 LUCJ 회로를 초기화하고, Hartree–Fock 준비 회로와 측정을 붙입니다.

원본처럼 이 단계에서 LUCJ 전용 pass manager도 만듭니다. **pass manager 적용은 STEP 2에서 수행**하므로 STEP 1의 회로에는 추상적인 ffsim 연산이 남아 있습니다.

`compilation_seed=12345`가 기본값입니다. `step1_map(compilation_seed=None)`은 원문처럼 backend/transpiler seed를 고정하지 않는 동작이며, 이때 샘플 단위 동일성을 기대하면 안 됩니다.

### STEP 2 — 회로 최적화

`mapped.pass_manager.run(mapped.circuit)`로 회로를 변환합니다. 반환값은 `isa_circuit`이며 게이트 수를 출력합니다. 실제 QPU로 바꾸려면 장치의 target과 연결 구조에 맞는 최적화·매핑을 별도로 검증해야 합니다.

### STEP 3 — 측정 샘플 획득

NumPy 난수 생성기를 seed=12345로 만들고 `StatevectorSampler`로 100,000회 측정합니다. `pub_result.data.meas`에는 측정 비트 배열이 있습니다. 샘플링 직후의 난수 상태도 복사해 반환합니다.

이는 IBM 원본에서 sampling과 SQD에 동일한 난수 생성기를 이어 쓰는 동작을 단계 분리 후에도 재현하기 위한 장치입니다. STEP 4에서 seed=12345로 새로 시작하는 것과는 다릅니다.

### STEP 4 — SQD 반복과 결과 해석

먼저 전자 수를 만족하는 샘플의 비율을 출력합니다. 이 과정은 통계 계산이며, 잘못된 전자 수를 가진 샘플을 모두 삭제해 넘기는 전처리가 아닙니다. 원본 측정 배열을 `diagonalize_fermionic_hamiltonian`에 넘겨 configuration recovery와 대각화 반복을 수행합니다.

`callback`은 각 SQD 반복의 배치별 에너지·상태를 `result_history`에 보관합니다. SQD 반복 안에 배치별 고유값 솔버 반복이 있으므로 `max_iterations`와 `max_cycle`은 서로 다른 제한입니다. 여기서 반복한다고 STEP 3의 회로를 다시 실행하는 것은 아닙니다.

최종 총에너지는 `result.energy + mapped.nuclear_repulsion_energy`입니다. 이 변수 이름은 원본을 따르지만 `CASCI.get_h1cas()`가 반환한 상수항이므로 **핵 반발뿐 아니라 동결된 코어의 기여도 포함할 수 있습니다.** SDK 어댑터에서 이 상수를 두 번 더하지 않도록 해야 합니다.

## 5. 단계 사이의 데이터 계약

| 객체·필드 | 의미 | 후속 사용 |
| --- | --- | --- |
| `MappedProblem.norb`, `.nelec` | 활성 공간 궤도 수와 스핀별 전자 수 | STEP 4의 배치·전자 수 제약 |
| `.hcore`, `.eri` | 1전자·2전자 적분, NumPy 배열 | 부분공간 Hamiltonian |
| `.nuclear_repulsion_energy`, `.reference_energy` | 에너지 상수와 FCI 총에너지 | 총에너지·오차 계산 |
| `.circuit`, `.pass_manager` | 추상 회로와 LUCJ 변환 도구 | STEP 2 |
| `ExecutedCircuit.pub_result` | Qiskit primitive 측정 결과 | `.data.meas`를 SQD에 전달 |
| `.rng_state` | 샘플링 직후 NumPy RNG 상태의 사본 | STEP 4의 난수 진행 재현 |
| `PostprocessedResult.result` | `SCIResult`: 전자 에너지·상태·점유수 | 과학 결과 분석 |
| `.result_history` | 반복마다 배치 결과 목록 | 수렴·배치 비교 |
| `.final_energy`, `.energy_error` | 상수 포함 총에너지, FCI 대비 차이 | 결과 보고 |
| `.valid_fraction`, `.expected_fraction_random` | 실제·균등 무작위 샘플의 유효 비율 | 측정 통계 |

세 자료형은 **메모리 내 Python 객체 계약**입니다. JSON으로 그대로 직렬화할 수 있는 형식이 아니며 pass manager, QuantumCircuit, PubResult, SCIResult에는 별도의 변환이 필요합니다.

## 6. SDK·Slurm 워크플로우로 옮기는 방법

현재 드라이버의 실제 호출 관계는 다음과 같습니다.

```python
mapped = step1_map()
isa_circuit = step2_optimize(mapped)
executed = step3_execute(isa_circuit)
result = step4_postprocess(mapped, executed)
```

향후 SDK에서는 각 함수를 task로 감싸고 위 입력 의존성을 선언합니다. CPU 작업·시뮬레이터·QPU·MPI 배치는 미들웨어의 실행 어댑터가 결정합니다. 다음은 **추가 구현 사항**입니다.

| 연결 지점 | 추가 구현과 검증 |
| --- | --- |
| 서로 다른 프로세스/노드 | **구현됨**(아래 6.1). 적분 NPZ, RNG·메타데이터 JSON, ISA 회로 QPY. schema/version 정의는 남음 |
| STEP 1 → STEP 2 | **구현됨**. 추상 회로는 pickle(같은 환경 전용), pass manager는 같은 seed로 재구성 |
| STEP 3 → STEP 4 | **구현됨**. 측정 bool 배열 → `BitArray`로 재구성. 실제 QPU의 레지스터명·layout 매핑은 남음 |
| 실제 QPU 제출 | 인증·job ID·재시도·결과 수집 및 실제 장치용 transpilation 구현 |
| Slurm | **구현됨**(작업별 자원, afterok 실패 전파, 실행 폴더). 재시작·캐시 규칙은 남음 |
| MPI/GPU SQD | **배치 분산 구현됨**(PySCF, 6.1). 한 배치 내부의 분산 대각화(SBD 등)와 GPU는 남음 |

Python 객체에 대한 무조건적인 pickle 전송이나 `mpirun python run_steps.py`만으로 분산 워크플로우가 완성되는 것은 아닙니다. 후자는 MPI 통신 로직이 없으므로 동일 계산을 여러 번 독립 실행하게 됩니다.

IBM의 STEP 1~4 구분을 유지한 채 실행 자원을 붙일 수 있습니다. 특히 STEP 4의 SQD 반복과 configuration recovery를 서로 다른 작업으로 더 쪼개려면 반복 상태·장애 복구·동기화 계약을 추가해야 합니다.

### 6.1 STEP별 Slurm 작업과 STEP 4 MPI 배치 병렬 (구현)

STEP 하나를 한 프로세스로 실행하는 `run_step.py`와, 네 STEP을 Slurm 작업 4개로 제출하는 `slurm/`을 추가했습니다. 계산 본문은 `ibm_steps.py`의 네 함수 그대로입니다.

```bash
python run_step.py 1 --workdir W        # STEP 1~3: 단일 프로세스, MPI 없음
python run_step.py 2 --workdir W
python run_step.py 3 --workdir W
srun --mpi=pmi2 -n 3 python run_step.py 4 --workdir W --mpi   # STEP 4: 배치 k → rank k % 3
```

| STEP | 읽는 파일 | 쓰는 파일 |
| --- | --- | --- |
| 1 | - | `step1_problem.npz`(norb·nelec·적분·상수·FCI), `step1_circuit.pkl`(추상 회로), `step1.json` |
| 2 | `step1_circuit.pkl`, `step1.json` | `step2_isa.qpy`, `step2.json` |
| 3 | `step2_isa.qpy` | `step3_samples.npz`(측정 bool 배열), `step3_rng.json`(측정 직후 난수 상태), `step3.json` |
| 4 | `step1_problem.npz`, `step3_samples.npz`, `step3_rng.json` | `step4_result.json`(총에너지·점유수·반복별 배치), `step4_state.npz`(SCIState), `step4.json` |

`stepN.json`에는 입력·출력 SHA-256, Python·패키지 버전, 호스트, 소요 시간이 남습니다. STEP 4의 `step4.json`에는 MPI rank 수와 rank별 호스트도 기록됩니다.

- **pass manager:** qiskit의 pass manager는 pickle할 수 없습니다(HLSConfig 안의 lambda). STEP 2가 `step1.json`의 `compilation_seed`로 같은 backend·pass manager를 다시 만듭니다. 그래서 `compilation_seed=None`(원문의 비결정적 컴파일)은 분리 실행에서 지원하지 않습니다.
- **추상 회로:** ffsim 사용자 정의 게이트가 있어 pickle로 넘깁니다. 같은 환경의 STEP 1이 쓴 파일만 읽으세요. ISA 회로는 표준 게이트라 QPY로 넘깁니다.
- **STEP 4 MPI:** SDK의 `diagonalize_fermionic_hamiltonian`은 MPI SPMD를 지원합니다. CI 문자열 준비와 결과 처리는 rank 0이 하고, `sci_solver`만 모든 rank가 함께 부릅니다. `mpi_solver.batch_parallel`이 원문의 solver(`spin_sq=0.0`, `max_cycle=200`)를 감싸 배치 k를 rank k % size에 맡기고 결과를 rank 0으로 모읍니다. `step4_postprocess`의 새 인자 `wrap_solver`로 넘기며, 기본값 None은 원문 그대로입니다.
- **동등성:** SDK의 `solve_sci_batch`는 배치마다 `solve_sci`를 독립 호출합니다. 그래서 rank당 스레드 수가 같으면 단일 프로세스와 **비트 단위로 같은** 결과가 나옵니다. 스레드 수를 바꾸면 점유수 마지막 자리(1e-16 수준)가 달라질 수 있습니다.
- **성능:** IBM 예제 크기(배치당 D ≤ 2,500)에서는 MPI 시작 비용 때문에 오히려 느립니다(0.79배). 배치당 D 10⁵·10⁶·4×10⁶에서는 같은 코어 수의 단일 프로세스보다 1.08·1.25·1.44배 빠릅니다. 구성 복구 등 rank 0만 하는 약 35초는 줄지 않습니다. 측정 방법과 전체 결과: [validation/bench_step4](../validation/bench_step4/README.md). 측정 도구: [bench/](../bench/README.md). 하이퍼스레드 노드에서는 `--hint=nomultithread`로 rank마다 물리 코어를 줍니다(`slurm/`에 반영).
- **병렬도의 한계:** 배치 수(기본 3)까지만 나눠집니다. rank를 배치 수보다 많이 주면 남는 rank는 놉니다. 배치 하나의 대각화를 여러 rank가 나눠 풀지는 않으므로, 배치 하나는 노드 하나의 메모리 안에 들어가야 합니다.
- **SBD를 넣지 않은 이유:** SBD(sbd-eigensolver)는 `spin_sq`를 지원하지 않습니다. N₂ 예제에서 IBM 원본(`spin_sq=0.0`)보다 1.6e-7 Ha 낮은 값(= PySCF `spin_sq=None`)을 냅니다. IBM 원본과 같은 결과를 유지하기 위해 PySCF만 씁니다.
- **실패 처리:** 한 rank에서 예외가 나면 `comm.Abort`로 전체 작업을 끝냅니다(다른 rank가 MPI 대기에 남지 않게). SDK가 MPI를 감지하지 못하면 STEP 4가 바로 실패합니다.

**클러스터 실행.** 사이트 값은 `slurm/site.env` 하나에 모았습니다(공유 경로, 제출 계정, MPI 경로, 파티션, 패브릭).

```bash
slurm/setup_env.sh                                  # 최초 1회(uv.lock이 바뀌면 다시): Python 3.11 + uv.lock + mpi4py(사이트 MPI로 빌드)
slurm/submit_chain.sh -w kqsvr04 -n 3 -c 1          # 1노드, STEP 4 3 rank
slurm/submit_chain.sh -w kqsvr04,kqsvr05 -N 2 -n 3  # STEP 4 2노드 (STEP 1~3은 첫 노드)
```

`submit_chain.sh`는 실행 폴더 `runs/<run_id>/`에 번들 사본(`code/`)을 만들고, STEP 1~4를 `--dependency=afterok`로 이어 제출합니다. 앞 작업이 실패하면 뒤 작업은 취소됩니다(`--kill-on-invalid-dep=yes`). STEP 1~3 작업은 SDK의 MPI 자동 감지 변수(`SLURM_NTASKS` 등)를 지우고 실행합니다. STEP 4는 `srun --mpi=pmi2`로 rank를 띄우고, `--propagate`에서 MEMLOCK을 빼 verbs 패브릭이 로그인 노드의 memlock 한도에 걸리지 않게 합니다(sqd_perf X40에서 확인한 설정).

### 6.2 큰 문제(36큐비트)와 MPI 에뮬레이터 (구현)

`ibm_steps.py`는 IBM 예제(16큐비트) 원문 그대로 두고, 같은 계산을 문제 정의로 일반화한 `sqd_workflow/scaled.py`와 `run_scaled.py`를 추가했습니다. 파일 계약이 같아서 STEP 4는 `run_step.py 4`(MPI 배치 병렬)를 그대로 씁니다.

| 프리셋 | 분자·기저 | 활성 공간 | 큐비트 | LUCJ | 비고 |
| --- | --- | --- | ---: | ---: | --- |
| `n2_sto6g_16q` | N₂ 1.0 Å, STO-6G | 8궤도, 전자 10 | 16 | 4회 | IBM 예제와 같은 적분·회로·샘플(테스트로 확인) |
| `n2_ccpvdz_36q` | N₂ 1.0 Å, cc-pVDZ | 18궤도, 전자 10 (코어 2 동결) | 36 | 1회 | FCI 차원 7.3×10⁷. `--norb`로 같은 계열의 작은 크기 |
| `h18_sto6g_36q` | H₁₈ 사슬 1.0 Å, STO-6G | 18궤도, 전자 (9,9) | 36 | 4회(시험은 2회) | 반 채움, D 상한 2.4×10⁹. FCI 대신 CCSD(T). [최대 규모 시험](최대규모_H18_36큐비트.md) |

STEP 3 샘플러는 세 가지입니다.

- `statevector`: Qiskit 상태벡터. 30큐비트 근처까지.
- `ffsim`: 전자 수 보존 공간에서 LUCJ 상태를 정확히 계산해 샘플링. 36큐비트도 1.2 GB.
- `emulator`: pennylane-lightning-MPI `mpi_counts_cli`(v3)로 2³⁶ 상태벡터를 3노드 64 rank에 나눠 계산해 샘플링.

STEP 2는 ISA 회로를 에뮬레이터 게이트(h x y z rx ry rz cx cz swap cp)로 바꾼 OpenQASM(`step2_emulator.qasm`)과, 고전 비트 → 물리 큐비트 대응표(`step2_measure_map.json`)를 함께 씁니다. 에뮬레이터는 모든 물리 큐비트를 문자열 왼쪽부터 q0 순서로 내므로, STEP 3이 이 대응표로 Qiskit 순서로 되돌립니다.

```bash
python run_scaled.py 1 --problem n2_ccpvdz_36q --workdir W --threads 32   # 적분·FCI·CCSD·LUCJ
python run_scaled.py 2 --problem n2_ccpvdz_36q --workdir W                # ISA + 에뮬레이터 QASM
python run_scaled.py 3 --problem n2_ccpvdz_36q --workdir W --sampler ffsim
slurm/submit_scaled.sh -p n2_ccpvdz_36q -s emulator -N 3 -P 64 -T 08:00:00   # STEP 1~4 Slurm 사슬
slurm/submit_scaled.sh -p n2_ccpvdz_36q -a "--norb 14 --no-fci"           # 28큐비트(같은 계열)
python bench/compare_samples.py W                                          # 샘플 ↔ 정확한 분포 검사
```

- **에뮬레이터 rank 수는 2의 거듭제곱이어야 합니다.** 아니면 결과가 조용히 틀립니다. `submit_scaled.sh`가 확인합니다.
- **정확성 확인:** 16큐비트 QASM의 분포가 ffsim 정확 분포와 TVD 2×10⁻¹⁴로 같습니다. 16·28·32·34큐비트 에뮬레이터 샘플도 정확한 분포와 통계적으로 구별되지 않습니다.
- **STEP 4 설정:** IBM 설정(`max_dim=50`)이면 큐비트가 늘어도 배치당 D가 2,500에 머물러 에너지가 CCSD보다 높습니다. 큰 문제에는 `-x "--set max_dim=1000 --set samples_per_batch=10000"`처럼 키웁니다.
- 실행 결과: [36큐비트 실행 결과](36큐비트_실행.md), [최대 규모 시험(H₁₈, D 10⁸)](최대규모_H18_36큐비트.md). 끝난 실행에 STEP 4만 다른 설정으로 다시 돌리려면 `slurm/submit_step4.sh`를 씁니다.

## 7. 원본과 같은 계산인지 확인

```bash
uv run --locked --extra test python -m pytest -q
```

테스트는 별도 프로세스에서 보존된 `original.py`를 독립 실행하고 다음을 비교합니다.

- STEP 1과 STEP 2 사이의 추상 회로 연산 분리.
- 분자 적분과 16비트 측정 배열.
- 샘플 순서·값과 샘플링 이후 RNG 상태의 일치.
- 총에너지·FCI 값·궤도 점유수.
- 반복마다 모든 배치의 차원·에너지·점유수.
- STEP 4를 호출해도 입력 RNG 상태가 바뀌지 않는지.
- (`test_stages.py`) STEP마다 새 프로세스로 `run_step.py`를 실행해도 위 비교가 모두 같은지.
- (`test_stages.py`, `mpi` 표시) STEP 4를 MPI 2·3 rank로 돌린 결과가 단일 프로세스 STEP 4와 비트 단위로 같은지. mpi4py와 `mpiexec`(또는 `SQD_MPIEXEC` 환경변수의 실행 명령)가 없으면 건너뜁니다.

비교 테스트의 에너지 허용오차는 1e-8 Ha입니다. 물리적 SQD 수렴 허용오차 1e-3 Ha와 목적이 다릅니다. 전자는 같은 알고리즘을 분리해도 같은 계산을 하는지 검사하고, 후자는 반복 종료를 결정합니다.

독립 원본 결과를 직접 저장하려면 아직 존재하지 않는 출력 경로를 사용합니다.

```bash
uv run --locked python references/n2_small_scale/run_reference.py --output runs/reference-new
```

원본 실행기는 `hamiltonian.npz`, `samples.npz`, `circuit.qpy`, `rng.json`, `history.json`, `result.json` 등을 저장합니다. 계산은 현재 모듈을 호출하지 않고 보존 원본 셀에서 실행합니다. 불필요한 QPU·plot import를 제외하고 backend/transpiler seed를 고정하며 결과 저장을 추가한 실행 어댑터입니다.

기존 검증 환경의 결과는 총에너지 약 −108.59593164616311 Ha, FCI 대비 차이 약 5.57e-5 Ha, SQD 반복 2회였습니다. 이 패키지의 분리 실행 결과·환경은 [검증 기록](../validation/README.md)에서 확인합니다. OS·라이브러리·BLAS 차이로 마지막 자릿수나 선택 경로가 달라질 수 있습니다. 실제로 Linux x86_64(kqsvr04·kqdata01, 같은 패키지 버전)에서는 총에너지가 −108.59592219311702 Ha로 macOS arm64 값과 9.5e-6 Ha 다릅니다. 어느 STEP에서 갈라지는지는 분리하지 않았습니다. 같은 플랫폼에서 독립 원본 실행기와 비교하면 1e-8 Ha 안에서 같으므로, 플랫폼 간 비교에는 이 테스트를 각 플랫폼에서 다시 돌리세요.

## 8. 변경할 설정과 흔한 문제

| 목적/증상 | 확인 위치와 조치 |
| --- | --- |
| shots 변경 | `step3_execute()`의 `shots=100_000`. 원본 동일성 검증 조건도 바뀜 |
| 배치·부분공간 크기 변경 | `step4_postprocess()`의 `num_batches`, `samples_per_batch`, `max_dim` |
| 반복·수렴 조절 | `max_iterations`, `energy_tol`, `occupancies_tol`; 솔버 내부 반복은 `max_cycle` |
| 분자·큐비트 변경 | `step1_map()`의 분자·기저·활성 공간·전자 수. 이 번들은 소규모 재현용으로 고정됨 |
| `ModuleNotFoundError` | 이 폴더에서 설치했는지 확인하고 `uv run --locked ...` 사용 |
| 원본 출력 폴더가 이미 존재 | 새 `--output` 경로 지정. 원본 실행기는 덮어쓰지 않음 |
| OpenMP 관련 경고 | 현재 플랫폼의 PySCF/BLAS 지원 확인. 경고가 수치 검증 실패를 의미하는지 실행 결과와 함께 판단 |
| 큰 문제에서 메모리·시간 급증 | FCI 기준 계산, 상태벡터 시뮬레이션, SQD 대각화를 각각 측정 |

`max_dim`을 늘리는 것과 큐비트를 늘리는 것은 다릅니다. 현재 솔버의 tensor-product 부분공간은 선택된 α·β 문자열 개수의 곱으로 커집니다. 샘플 다양성이 부족하면 상한을 높여도 실제 차원이 증가하지 않을 수 있습니다.

현재 STEP 1에는 FCI 비교 계산이 포함됩니다. 20~30큐비트로 확장할 때는 이 기준 계산의 비용을 먼저 검토하고 분리해야 합니다. SDK 이식, 큰 분자 실험, MPI/GPU 연결은 원본 재현 확인 이후의 별도 변경으로 관리하는 것을 권장합니다.

## 9. 레퍼런스와 출처

- [IBM SQD 공식 튜토리얼 — small-scale simulator example](https://quantum.cloud.ibm.com/docs/en/tutorials/sample-based-quantum-diagonalization#small-scale-simulator-example): 단계 이름과 계산 예제의 기준.
- [고정 notebook revision](https://github.com/Qiskit/documentation/blob/64fbdc210b4379f9079e3d8f8e2ee8877cbc3ba2/docs/tutorials/sample-based-quantum-diagonalization.ipynb): 이 패키지에서 사용한 원본 snapshot.
- [qiskit-addon-sqd 공개 구현](https://github.com/Qiskit/qiskit-addon-sqd): recovery·부분공간 대각화 구현.
- [SQD API 문서](https://qiskit.github.io/qiskit-addon-sqd/): `SCIResult`, `diagonalize_fermionic_hamiltonian`, `solve_sci_batch` 참고. 최신 웹 문서와 고정 설치 버전의 차이에 주의.
- [ffsim 공개 구현](https://github.com/qiskit-community/ffsim): LUCJ 회로와 fermionic simulation 도구.
- [PySCF 문서](https://pyscf.org/): RHF·CCSD·CASCI·적분 계산.
- [원본 출처 정보](../references/n2_small_scale/source.json), [Apache-2.0 라이선스](../references/n2_small_scale/LICENSE), [수정 내역](../NOTICE.md).

원본의 과학 계산은 유지하고 함수 경계·반환 객체·RNG snapshot을 추가했습니다. SDK decorator나 Slurm 명령을 IBM 예제의 일부인 것처럼 섞지 않았습니다.

## 10. 문서와 전달본 관리

이 문서의 원본은 `docs/guide.md`입니다. HTML은 아래 명령으로 갱신하며, 현재 `run_steps.py` 전체 코드도 자동 첨부됩니다.

```bash
uv sync --locked --extra test --extra docs
uv run --locked --extra docs python tools/build_guide.py
```

HTML은 오프라인 열람과 브라우저 인쇄를 지원합니다. 폴더를 전달할 때 소스·문서·lockfile·레퍼런스·라이선스·검증 기록을 함께 전달하고 `.venv`, 캐시, 대규모 실행 결과는 제외합니다.

작업에는 `find-skills`로 탐색한 뒤 이미 설치된 `documentation-and-adrs`(독자별 안내·출처·제약), `incremental-implementation`(독립 패키지 실행 후 문서화) 지침을 적용했습니다. 코드 의존성 탐색에는 프로젝트의 `graphify` 지침을 사용했습니다. 외부 스킬을 새로 설치할 필요는 없었습니다.
