# 독립 전달본 검증 기록

검증일: 2026-10-07.

## 실행 격리

이 폴더의 코드·설치 설정·테스트·고정 원본을 프로젝트 밖의 임시 디렉터리로 복사했습니다. 그 위치에서 `uv sync --locked --extra test --extra docs`로 새 가상환경을 생성했습니다. 상위 프로젝트의 가상환경과 `PYTHONPATH`를 사용하지 않았습니다.

실제로 import한 `sqd_workflow.ibm_steps`가 임시 복사본 경로인지 확인했습니다. 구체적인 경로, Python·플랫폼·주요 패키지 버전은 [environment.json](environment.json)에 있습니다. 기록의 임시 경로는 검증 이력이며 패키지의 실행 의존성이 아닙니다.

## 계산 결과

명령: 가상환경의 `python run_steps.py`.

| 항목 | 결과 |
| --- | --- |
| 종료 코드 | 0 |
| 큐비트 | 16 |
| 최종 총에너지 | −108.59593164616311 Ha |
| FCI 대비 에너지 차이 | 5.5704822926827546e-05 Ha |
| SQD 반복 | 2회 |
| 마지막 반복 배치의 부분공간 차원 | 2,500 |

전체 로그: [execution.log](execution.log).

## 원본 비교 테스트

명령: 가상환경의 `python -m pytest -q`.

**1 passed, 1 warning in 4.47s.** 이 번들에 포함된 통합 테스트 전체의 결과입니다. 원 프로젝트의 48개 전체 테스트 결과와 혼동하지 마세요.

비교 대상은 독립 원본 실행기의 적분, 샘플과 RNG 상태, 총에너지·FCI, 점유수, 반복별 모든 배치의 차원·에너지·점유수입니다. 로그: [tests.log](tests.log).

경고는 해당 macOS PySCF 환경에서 OpenMP를 사용할 수 없어 `omp_threads` 설정이 효과가 없다는 내용입니다. 이 환경의 계산·원본 비교는 통과했습니다. Linux·멀티노드·GPU 성능을 검증한 결과는 아닙니다.

## HTML 확인

격리된 headless Chrome으로 `docs/guide.html`을 로컬 파일로 열었습니다. 1440×1000 및 390×844 화면에서 제목·목차·레이아웃을 확인했으며, 페이지 전체 가로 넘침과 끊어진 내부 앵커, JavaScript 실행 오류가 없었습니다. [browser.json](browser.json).

가이드는 Markdown에서 생성되며 외부 폰트·스크립트가 필요 없습니다. 문서 내부 파일 링크, 복사본 해시와 보존 원본 해시도 확인했습니다.

## 재검증

패키지 루트에서 실행합니다.

```bash
uv sync --locked --extra test
uv run --locked python run_steps.py
uv run --locked --extra test python -m pytest -q
```

코드나 설정을 변경한 후에는 위 결과를 새 검증 로그로 대체해야 합니다. 플랫폼 간 마지막 자릿수 일치나 다른 문제 크기의 성능을 이 기록으로 보장하지 않습니다.

## 2026-10-08 추가 검증: STEP 분리 실행·Slurm·MPI (Linux)

STEP별 실행(`run_step.py`, `sqd_workflow/stages.py`), STEP 4 MPI 배치 병렬(`sqd_workflow/mpi_solver.py`), Slurm 스크립트(`slurm/`)를 추가하면서 검증했습니다. 위의 macOS 기록은 이 변경 이전의 것이며, 변경 후 macOS에서 다시 돌리지는 않았습니다(`ibm_steps.py`의 변경은 기본값이 원문 그대로인 선택 인자 하나입니다).

**환경.** Linux x86_64(Rocky 8, kqdata01·kqsvr04·kqsvr05), Python 3.11.17(uv 관리), `uv.lock` 고정 버전 + mpi4py 4.1.2(MPICH 4.2.0으로 소스 빌드). `slurm/setup_env.sh`가 만든 공유 환경입니다.

**테스트(kqdata01, `mpiexec -launcher fork`).** **4 passed.** [tests_linux.log](tests_linux.log)

| 테스트 | 확인한 것 |
| --- | --- |
| `test_ibm_steps_match_reference` | 기존 원본 비교(한 프로세스) |
| `test_staged_run_matches_reference` | STEP마다 새 프로세스로 실행해도 적분·샘플·RNG·에너지·점유수·반복별 배치가 독립 원본과 1e-8 안에서 같음 |
| `test_mpi_step4_matches_serial[2]`, `[3]` | MPI 2 rank(배치 불균등), 3 rank STEP 4 결과 JSON과 SCIState가 단일 프로세스와 비트 단위로 같음 |

**Slurm 작업 사슬(STEP 1~4 = 작업 4개, afterok).** 모든 작업이 COMPLETED, 종료 코드 0입니다. [slurm_runs.json](slurm_runs.json), 첫 실행의 작업 로그 [slurm_execution.log](slurm_execution.log).

| 실행 | STEP 4 구성 | rank별 호스트 | 총에너지 (Ha) | 첫 실행과 비트 동일 |
| --- | --- | --- | --- | --- |
| wf_20261008-105603 | 1노드, 3 rank × 1 스레드 | kqsvr04 (기록 추가 전) | −108.59592219311702 | 기준 |
| wf_20261008-105648 | 2노드, 3 rank × 2 스레드 | kqsvr04, kqsvr04, kqsvr05 | −108.59592219311702 | 아니오: 점유수 최대 6.7e-16 차이(스레드 수 차이), 에너지는 같음 |
| wf_20261008-105720 | 2노드, 3 rank × 1 스레드 | kqsvr04, kqsvr04, kqsvr05 | −108.59592219311702 | 예 |

**플랫폼 차이.** Linux의 총에너지는 위 macOS 값(−108.59593164616311)과 9.5e-6 Ha 다릅니다. 패키지 버전은 같습니다. 어느 STEP에서 갈라지는지는 분리하지 않았습니다. 같은 Linux 환경에서 독립 원본 실행기와의 비교는 통과합니다.

**성능.** STEP 4 단일 프로세스 대 MPI 배치 병렬 비교는 [bench_step4/README.md](bench_step4/README.md)([HTML](bench_step4/report.html))에 있습니다. 요약: IBM 예제 크기에서는 MPI가 느리고(0.79배), 배치당 D 10⁵·10⁶·4×10⁶에서는 같은 코어 수의 단일 프로세스보다 1.08·1.25·1.44배 빠릅니다.

**하지 않은 것.** 작업 실패 시 뒤 작업 취소(`--kill-on-invalid-dep`)와 rank 예외 시 `Abort` 경로는 일부러 실패시켜 확인하지 않았습니다.
