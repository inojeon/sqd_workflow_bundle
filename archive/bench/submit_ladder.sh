#!/usr/bin/env bash
# 끝난 실행(STEP 1~3 파일)을 입력으로 STEP 4 rank 사다리(bench_step4.sbatch)를 제출합니다.
#   bench/submit_ladder.sh -r RUN_DIR -B BENCH_DIR -k CASE "설정;설정" -C "S:1 S:32 M:32:1" [-N 노드=1] [-w 노드] [-R 회차=1] [-T 시간=08:00:00] [-d 앞작업ID(afterany)]
# 예) bench/submit_ladder.sh -r $RUNS/sc_h16_... -B $WF_ROOT/bench/b_h16 -k h16_d1e6 \
#       "num_batches=64;samples_per_batch=50000;max_dim=1000;max_iterations=3" -C "S:1 S:32 M:4:8 M:8:4 M:16:2 M:32:1" -w kqsvr05
# BENCH_DIR/code 가 없으면 번들 사본을 만듭니다. 노드는 --exclusive 로 잡으므로 3노드 전부를 쓰지 않습니다(qc-cloud 카나리 자리).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../slurm/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }
usage() { sed -n '2,5p' "$0"; exit 1; }
RUN="" B="" CASE="" SETS="" CONFIGS="" N=1 W="" ROUNDS=1 T=08:00:00 DEP=""
while getopts "r:B:k:C:N:w:R:T:d:h" o; do
  case $o in r) RUN=$OPTARG ;; B) B=$OPTARG ;; k) CASE=$OPTARG; SETS=${!OPTIND}; OPTIND=$((OPTIND + 1)) ;; C) CONFIGS=$OPTARG ;;
    N) N=$OPTARG ;; w) W=$OPTARG ;; R) ROUNDS=$OPTARG ;; T) T=$OPTARG ;; d) DEP=$OPTARG ;; *) usage ;; esac
done
[ -n "$RUN" ] && [ -n "$B" ] && [ -n "$CASE" ] && [ -n "$CONFIGS" ] || usage
as test -f "$RUN/work/step3_samples.npz" || { echo "오류: $RUN/work 에 STEP 3 결과가 없습니다"; exit 1; }
if ! as test -f "$B/code/run_step.py"; then
  as mkdir -p "$B/code"
  tar -C "$HERE/.." --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=validation --exclude=docs -cf - . | as tar -C "$B/code" -xf -
fi
as mkdir -p "$B/inputs/$CASE"
for f in step1_problem.npz step3_samples.npz step3_rng.json step1.json step3.json; do
  as test -f "$RUN/work/$f" && as cp "$RUN/work/$f" "$B/inputs/$CASE/" || true
done
echo "$RUN" | as tee "$B/inputs/$CASE/source_run.txt" > /dev/null
j=$(as env BENCH_DIR="$B" CODE_DIR="$B/code" CASES="$CASE:$SETS" CONFIGS="$CONFIGS" ROUNDS="$ROUNDS" NODES_MPI="$N" \
  sbatch --parsable -p "$PARTITION" -A "$ACCOUNT" -N "$N" --exclusive --mem=0 ${W:+-w "$W"} -t "$T" ${DEP:+--dependency=afterany:$DEP} \
    -J "ladder-$CASE" -o "$B/ladder_${CASE}_%j.out" --export=ALL "$B/code/bench/bench_step4.sbatch")
echo "$(date -Is) job $j case $CASE [$SETS] configs [$CONFIGS] nodes $N${W:+ ($W)} rounds $ROUNDS" | as tee -a "$B/jobs.log"
