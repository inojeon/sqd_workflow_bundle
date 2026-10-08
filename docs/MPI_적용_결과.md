# SQD 워크플로우 STEP 4 MPI 적용 결과

> **정리일:** 2026-10-08. **대상:** `sqd_workflow_bundle`(IBM SQD 예제 STEP 1~4). **실행 환경:** kqsvr04·kqsvr05(Slurm, 노드당 2소켓 × 16코어), Python 3.11.17, MPICH 4.2.0. **한 줄 요약:** STEP 4의 고전 후처리를 MPI로 배치 병렬화해 Slurm에서 1·2노드로 돌렸고, 결과는 IBM 원본과 같았습니다. 배치당 부분공간이 클 때(D ≥ 10⁵)만 빨라집니다.

## 1. 요약

- **무엇을 했나:** STEP 1~4를 별도 Slurm 작업 4개로 나눠 돌릴 수 있게 했습니다. STEP 4(SQD 구성 복구·대각화 반복)는 MPI rank에 배치를 나눠 풉니다.
- **정확성:** IBM 원본 실행기와 1e-8 Ha 안에서 같습니다. rank당 1스레드일 때 MPI 결과는 단일 프로세스와 비트 단위로 같습니다. 테스트 4개, Slurm 작업 사슬 4회, 동등성 검사 112건이 모두 통과했습니다.
- **성능:** IBM 예제 크기(16큐비트, 배치당 D ≤ 2,500)에서는 MPI가 오히려 느립니다(0.79배). 32큐비트 N₂/6-31G에서 배치당 D를 키우면 결과가 달라집니다. 같은 코어 수의 단일 프로세스보다 D 10⁵에서 1.08배, 10⁶에서 1.25배, 4×10⁶에서 1.44배 빠릅니다. 2노드(48코어)에서는 1.46배·1.83배이고, 기존 실행(1코어) 대비로는 최대 15.8배입니다.
- **한계:** 배치 수(기본 3)까지만 나눠집니다. rank 0만 하는 구성 복구(순수 Python) 약 35초는 줄지 않습니다.

## 2. 무엇을 바꿨나

### 2.1 설계 결정

| 결정 | 이유 |
| --- | --- |
| STEP 4 MPI는 **PySCF 배치 병렬**만 사용 | 다른 폴더(sqd_perf)의 SBD 경로도 시험했습니다. 하지만 SBD는 `spin_sq`를 지원하지 않아 IBM 원본(`spin_sq=0.0`)보다 1.6e-7 Ha 낮은 값을 냅니다. IBM 원본과 같은 결과를 유지하려고 SBD는 넣지 않았습니다 |
| SDK 공개 API의 MPI 규약을 그대로 사용 | qiskit-addon-sqd 0.13.1의 `diagonalize_fermionic_hamiltonian`은 SPMD를 지원합니다. CI 문자열 준비·결과 처리는 rank 0이 하고, `sci_solver`만 모든 rank가 부릅니다. 번들은 solver 하나만 감싸면 됩니다 |
| STEP 1~3은 MPI 없이 단일 프로세스 | 사용자 요구(STEP별 별도 Slurm 작업)입니다. 이 단계에는 MPI가 필요 없습니다 |
| STEP 4 환경은 Python 3.11로 새로 빌드 | 번들 고정 버전(`uv.lock`)을 그대로 쓰고 mpi4py 4.1.2만 사이트 MPICH로 빌드해 추가했습니다 |

### 2.2 코드

| 파일 | 내용 |
| --- | --- |
| `sqd_workflow/ibm_steps.py` | `step4_postprocess`에 선택 인자 두 개를 추가했습니다. `wrap_solver`는 solver 감싸기, `settings`는 성능 측정용 크기 변경입니다. 기본값은 원문 그대로입니다 |
| `sqd_workflow/mpi_solver.py` | 새 파일. 배치 k를 rank k % size가 풀고 rank 0으로 모읍니다. SDK의 MPI 감지 확인, 한 rank가 실패하면 전체 중단 기능도 있습니다 |
| `sqd_workflow/stages.py`, `run_step.py` | 새 파일. STEP 하나씩 실행합니다. STEP 사이 파일은 적분 npz, 추상 회로 pickle, ISA 회로 qpy, 샘플 npz, 난수 상태 json입니다. `stepN.json`에 해시·버전·시간이 기록됩니다 |
| `slurm/` | 새 폴더. `site.env`(사이트 설정), `setup_env.sh`(공유 환경 빌드), `step.sbatch`, `submit_chain.sh`(STEP 1~4를 `afterok`로 제출) |
| `bench/` | 새 폴더. STEP 4 성능 비교 도구(사다리 데이터 변환, 측정 작업, 요약) |
| `tests/test_stages.py` | 새 파일. STEP 분리 실행 = IBM 원본, MPI STEP 4 = 단일 프로세스(2·3 rank) |

pass manager는 직렬화할 수 없어서 STEP 2가 같은 seed로 다시 만듭니다. 이 부분은 qiskit의 제약입니다.

## 3. 어떻게 돌렸나

```bash
slurm/setup_env.sh                                  # 공유 환경: /data01/hpcuser/sqd/workflow/venv-py311
slurm/submit_chain.sh -w kqsvr04 -n 3 -c 1          # STEP 1~4 = 작업 4개, STEP 4는 3 rank
slurm/submit_chain.sh -w kqsvr04,kqsvr05 -N 2 -n 3  # STEP 4를 2노드로
```

STEP 4 안에서는 `srun --mpi=pmi2 --hint=nomultithread … python run_step.py 4 --workdir W --mpi`가 실행됩니다.

| 실행 | 작업 번호 | STEP 4 구성 | 결과 |
| --- | --- | --- | --- |
| wf_20261008-105603 | 2982–2985 | 1노드, 3 rank × 1 | 4개 성공, −108.59592219311702 Ha |
| wf_20261008-105648 | 2986–2989 | 2노드, 3 rank × 2 | 4개 성공, 에너지 동일(점유수 6.7e-16 차이, 스레드 수 차이) |
| wf_20261008-105720 | 2990–2993 | 2노드, 3 rank × 1 | 4개 성공, 첫 실행과 비트 동일 |
| wf_20261008-131809 | 3025–3028 | 1노드, 3 rank × 2 (`--hint` 반영 후) | 4개 성공, 에너지 동일 |

## 4. 정확성 검증

- **테스트(kqdata01): 4 passed.** 내용은 다음과 같습니다.
  - 기존 원본 비교
  - STEP마다 새 프로세스로 실행해도 IBM 독립 원본과 적분·샘플·RNG·에너지·점유수·반복별 배치가 1e-8 안에서 같음
  - MPI 2·3 rank STEP 4가 단일 프로세스와 비트 단위로 같음
- **Slurm 작업 사슬:** 1노드와 2노드에서 모두 같은 에너지가 나왔습니다(위 표).
- **성능 측정의 동등성 검사 112건:** 모든 구성에서 반복별 부분공간 차원이 같고 |ΔE| ≤ 1e-8입니다. rank당 1스레드면 비트 단위로도 같습니다.
- **플랫폼 차이:** Linux 총에너지(−108.59592219311702)는 번들의 macOS 검증값과 9.5e-6 Ha 다릅니다. 패키지 버전이 같으므로 플랫폼 차이입니다. 같은 플랫폼에서 IBM 원본과는 일치합니다.

## 5. 성능

STEP 4만 쟀습니다. STEP 1~3은 미리 만든 파일을 썼고, 32큐비트는 공개 데이터의 적분과 하드웨어 샘플을 STEP 4 입력으로 바꿔 썼습니다. 모두 물리 코어 배정 조건입니다. S:1은 기존 실행(1코어), S:30은 단일 프로세스 30코어, M:R:T는 MPI R rank × rank당 T코어입니다.

| 문제 | 배치당 D | S:1 | S:30 | M:3:10 (1노드) | M:3:16 (2노드) | MPI ÷ S:30 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IBM 예제, 16큐비트 | 2,500 | 0.48 s | — | M:3:1 0.61 s | — | 0.79배 |
| N₂/6-31G, 32큐비트 | 10⁵ | 96.6 s | 41.9 s | 38.8 s | — | 1.08배 |
| N₂/6-31G, 32큐비트 | 10⁶ | 490.7 s | 79.2 s | 63.1 s | 54.4 s | 1.25배 (2노드 1.46배) |
| N₂/6-31G, 32큐비트 | 4×10⁶ | 1,534 s | 176.9 s | 123.0 s | 96.9 s | 1.44배 (2노드 1.83배) |

- **대각화는 rank 수에 비례해 줄어듭니다.** rank당 1코어에서 rank 3개가 2.96배입니다. 같은 30코어 안에서는 배치마다 rank 하나(3×10)가 한 프로세스 30스레드보다 대각화를 1.62–1.84배 빨리 끝냅니다.
- **줄지 않는 약 35초:** 구성 복구 등 rank 0만 하는 부분입니다. 이 때문에 문제가 클수록 MPI 효과가 커집니다.
- **하이퍼스레드 배정 문제를 고쳤습니다.** `--cpu-bind=cores`로는 rank 3개가 물리 코어 약 1.5개를 나눠 써서 1.5배에 그쳤습니다. `--hint=nomultithread`로 바꿔 Slurm 스크립트에 반영했습니다.

자세한 표·방법·원자료: [validation/bench_step4](../validation/bench_step4/README.md).

## 6. 한계와 다음 단계

- **병렬도:** 배치 수(3)까지입니다. 배치를 늘리면 IBM 설정과 결과가 달라집니다.
- **rank 0 구간(약 35초):** sqd_perf의 X38(구성 복구 C 구현, 비트 동일)을 붙이면 반복당 약 12초가 0.1초 아래로 줄 것으로 예상합니다. 아직 적용하지 않았습니다.
- **배치 하나는 한 노드 안에서 풉니다.** 노드 메모리를 넘는 D에는 배치 내부 분산 대각화(SBD 등)가 필요합니다. 다만 SBD는 `spin_sq`를 지원하지 않습니다.
- **36큐비트 STEP 1~4 전체 실행:** 번들의 STEP 1(분자 고정)과 STEP 3(상태벡터 샘플러)은 32큐비트 이상을 다루지 못합니다. 문제 정의와 대규모 에뮬레이터 연결이 필요하며, 별도 작업으로 진행합니다.

## 7. 파일 위치

| 무엇 | 어디 |
| --- | --- |
| 코드 | `sqd_workflow_bundle/` (`sqd_workflow/`, `run_step.py`, `slurm/`, `bench/`) |
| 사용법 | [README](../README.md), [가이드 6.1절](guide.md) |
| 검증 기록 | [validation/README.md](../validation/README.md), `validation/tests_linux.log`, `slurm_runs.json`, `slurm_execution.log` |
| 성능 보고서 | [validation/bench_step4/README.md](../validation/bench_step4/README.md), `report.html` |
| 클러스터 실행 결과 | `/data01/hpcuser/sqd/workflow/runs/`, `/data01/hpcuser/sqd/workflow/bench/b_20261008-112145/` |
