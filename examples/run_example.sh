#!/usr/bin/env bash
# 예제: 양자 에뮬레이터(28큐비트, 1노드) + 고전 STEP 4 배치 병렬(MPI rank 사다리)을 Slurm 작업 체인 하나로 돌립니다.
#   examples/run_example.sh [-p h14_sto6g_28q] [-w 노드] [-P 에뮬레이터_rank=32] [-C "S:32 M:8:4 M:16:2 M:32:1"]
#                           [-x "num_batches=64;samples_per_batch=50000;max_dim=1000;max_iterations=3"] [-T 사다리_시간=08:00:00]
# 작업 4개(afterok 의존):
#   STEP 1: FCI 기준값·CCSD·LUCJ 회로 (1노드 32코어)      STEP 2: ISA 회로 → OpenQASM
#   STEP 3: 에뮬레이터 mpi_counts_cli(1노드 P rank) → 샘플 파일
#   tail  : 샘플 검사(bench/compare_samples.py, 정확 분포와 비교) → STEP 4 사다리(bench/bench_step4.sbatch) → 집계(bench/summarize.py)
# 결과: <RUNS>/sc_<problem>_<stamp>/work (STEP 1~3), <WF_ROOT>/bench/ex_<problem>_<stamp>/ (sample_check.json, runs_*.tsv, summary/summary.md)
# 세 노드 중 하나는 항상 비워 둡니다(qc-cloud 카나리).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../slurm/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }
usage() { sed -n '2,9p' "$0"; exit 1; }
PROBLEM=h14_sto6g_28q W="" NP=32 CONFIGS="S:32 M:8:4 M:16:2 M:32:1" T=08:00:00
SETS="num_batches=64;samples_per_batch=50000;max_dim=1000;max_iterations=3"
while getopts "p:w:P:C:x:T:h" o; do
  case $o in p) PROBLEM=$OPTARG ;; w) W=$OPTARG ;; P) NP=$OPTARG ;; C) CONFIGS=$OPTARG ;; x) SETS=$OPTARG ;; T) T=$OPTARG ;; *) usage ;; esac
done
if (( NP & (NP - 1) )); then echo "오류: 에뮬레이터 rank 수 $NP 는 2의 거듭제곱이어야 합니다"; exit 1; fi

# STEP 1~3 (에뮬레이터, 1노드). STEP 4는 아래 사다리가 대신하므로 -K.
chain=$("$HERE/../slurm/submit_scaled.sh" -p "$PROBLEM" -s emulator -N 1 -P "$NP" -K ${W:+-W "$W" -w "$W"} -F 02:00:00 -T 02:00:00)
echo "$chain"
RUN=$RUNS/$(echo "$chain" | sed -n 's/^run_id //p')
j3=$(echo "$chain" | sed -n 's/^step3 //p')
B=$WF_ROOT/bench/ex_${PROBLEM}_$(date +%Y%m%d-%H%M%S)_$$
as mkdir -p "$B/code"
tar -C "$HERE/.." --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=validation --exclude=docs -cf - . | as tar -C "$B/code" -xf -

# tail: 샘플 검사 → 사다리 → 집계 (1노드 독점)
jt=$(as sbatch --parsable -p "$PARTITION" -A "$ACCOUNT" --dependency=afterok:$j3 --kill-on-invalid-dep=yes -N 1 --exclusive --mem=0 \
  ${W:+-w "$W"} -t "$T" -J ex-tail -o "$B/tail-%j.out" \
  --export="ALL,RUN=$RUN,B=$B,SETS=$SETS,CONFIGS=$CONFIGS,CASE=$PROBLEM" "$B/code/examples/example_tail.sbatch")
printf 'run %s\nbench %s\nstep3 %s\ntail %s\n' "$RUN" "$B" "$j3" "$jt" | as tee "$B/chain.txt"
echo "진행: squeue -u $RUN_USER   결과: $B/summary/summary.md"
