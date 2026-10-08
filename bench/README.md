# STEP 4 성능 비교 (단일 프로세스 대 MPI 배치 병렬)

같은 STEP 4 입력을 기존 실행(단일 프로세스, `run_step.py 4`)과 MPI 배치 병렬(`run_step.py 4 --mpi`)로 번갈아 돌려 시간을 비교합니다. 결과가 같은지도 함께 확인합니다.

| 파일 | 역할 |
| --- | --- |
| `import_ladder.py` | sqd_perf 사다리 데이터(적분 + 고유 비트열·가중치)를 STEP 1·3 출력 파일로 변환. 가중치대로 shot을 다항분포로 뽑습니다 |
| `bench_step4.sbatch` | 한 노드(또는 MPI 구성만 2노드)를 독점하고 구성 × 회차를 무작위 순서로 실행. `runs_<job>.tsv`에 벽시계 시간 기록 |
| `compare_samples.py` | STEP 3 샘플(에뮬레이터 등)이 LUCJ 정확 분포(ffsim)와 맞는지: 전자 수, xeb 비율, 상위 K개 χ². 36큐비트에서도 동작 |
| `summarize.py` | 구성별 중앙값, 기존 실행(S:1) 대비 속도, 동등성 검사 → `summary/summary.md`·`summary.json` |

## 구성 표기

- `S:T`: 단일 프로세스, OpenMP T 스레드. `S:1`이 번들의 기존 실행 조건입니다(`run_steps.py`와 같은 1 스레드).
- `M:R:T`: MPI R rank × rank당 T 스레드. 배치 k를 rank k % R이 풉니다. 배치가 3개라 R은 최대 3이 의미 있습니다.

## 시간 항목 (`step4.json`의 `timing`)

| 항목 | 내용 |
| --- | --- |
| STEP 4 (`postprocess_seconds`) | `step4_postprocess` 전체. 비교의 기준 |
| 대각화 (`solve_seconds`) | `sci_solver` 호출 합(rank 0 기준, 결과 수집 대기 포함). MPI로 나눠지는 부분 |
| 나머지 | 유효 비율 계산, 구성 복구(`recover_configurations`, 순수 Python), 결과 처리. rank 0만 하며 MPI로 줄지 않습니다 |
| 실행 전체 (`wall_seconds`) | srun 시작부터 끝까지. Python 기동·import·입력 읽기 포함 |

## 실행 예

```bash
B=/data01/hpcuser/sqd/workflow/bench/b_<stamp>      # 공유 경로. code/(번들 사본), inputs/<case>/ 준비
python bench/import_ladder.py --integrals <data>/N2_6-31G/integrals/R_16_1.00.npz \
    --samples <data>/N2_6-31G/samples/R_1.00.npz --fci -109.10288938 --out $B/inputs/n2_d1e6
sudo -u hpcuser env BENCH_DIR=$B CODE_DIR=$B/code CASES="n2_d1e6:max_dim=1000;samples_per_batch=10000" \
    CONFIGS="S:1 S:10 S:30 M:3:1 M:3:10 M:3:20" ROUNDS=2 \
    sbatch -p batch -A compute -N1 --exclusive --mem=0 -w kqsvr04 -t 02:00:00 --export=ALL $B/code/bench/bench_step4.sbatch
python bench/summarize.py $B
```

`CASES`의 `case:설정;설정`은 `run_step.py 4 --set`으로 넘어갑니다(`ibm:`처럼 비우면 IBM 원문 설정).
