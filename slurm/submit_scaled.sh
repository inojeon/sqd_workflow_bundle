#!/usr/bin/env bash
# 큰 문제(run_scaled.py)의 STEP 1~4 를 Slurm 작업 4개로 제출합니다(afterok).
#   slurm/submit_scaled.sh -p n2_ccpvdz_36q [-a "--norb 14 --no-fci"] [-s emulator|ffsim|statevector]
#                          [-N STEP3_노드=3] [-P 에뮬레이터_rank=64] [-w STEP3_노드목록] [-f STEP1_코어=32]
#                          [-n STEP4_rank=3] [-c STEP4_rank당_코어=10] [-x "STEP4 인자(예: --set max_dim=1000)"]
#                          [-T STEP3_시간=04:00:00] [-F STEP1_시간=04:00:00]
# 36큐비트 에뮬레이터는 3노드 64 rank(노드당 약 400 GiB)가 필요합니다. 에뮬레이터 rank 수는 2의 거듭제곱이어야 합니다.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }
usage() { sed -n '2,8p' "$0"; exit 1; }

PROBLEM="" SARGS="" SAMPLER=emulator N3=3 NP=64 W3="" C1=32 R4=3 C4=10 S4="" T3=04:00:00 T1=04:00:00
while getopts "p:a:s:N:P:w:f:n:c:x:T:F:h" o; do
  case $o in p) PROBLEM=$OPTARG ;; a) SARGS=$OPTARG ;; s) SAMPLER=$OPTARG ;; N) N3=$OPTARG ;; P) NP=$OPTARG ;; w) W3=$OPTARG ;;
    f) C1=$OPTARG ;; n) R4=$OPTARG ;; c) C4=$OPTARG ;; x) S4=$OPTARG ;; T) T3=$OPTARG ;; F) T1=$OPTARG ;; *) usage ;; esac
done
[ -n "$PROBLEM" ] || usage
if (( NP & (NP - 1) )); then echo "오류: 에뮬레이터 rank 수 $NP 는 2의 거듭제곱이어야 합니다(아니면 결과가 조용히 틀립니다)"; exit 1; fi
as test -x "$VENV/bin/python" || { echo "오류: $VENV 없음. 해결: slurm/setup_env.sh"; exit 1; }

TAG=$(echo "$SARGS" | sed -n 's/.*--norb \([0-9]*\).*/_norb\1/p')
RUN_ID=sc_${PROBLEM}${TAG}_$(date +%Y%m%d-%H%M%S)_$$        # 같은 초에 여러 번 제출해도 겹치지 않게
RUN_DIR=$RUNS/$RUN_ID
as test ! -e "$RUN_DIR" || { echo "오류: $RUN_DIR 이 이미 있습니다"; exit 1; }
as mkdir -p "$RUN_DIR/code" "$RUN_DIR/work" "$RUN_DIR/logs"
tar -C "$HERE/.." --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -cf - . | as tar -C "$RUN_DIR/code" -xf -
EXPORT="ALL,RUN_DIR=$RUN_DIR,PROBLEM=$PROBLEM,SCALED_ARGS=$SARGS,SAMPLER=$SAMPLER,EMU_NP=$NP,STEP4_ARGS=$S4"
COMMON=(--parsable -p "$PARTITION" -A "$ACCOUNT" --kill-on-invalid-dep=yes)
submit() { local step=$1 dep=$2; shift 2
  as sbatch "${COMMON[@]}" ${dep:+--dependency=afterok:$dep} -J "sc-step$step" -o "$RUN_DIR/logs/step$step-%j.out" \
    --export="$EXPORT,STEP=$step" "$@" "$RUN_DIR/code/slurm/scaled_step.sbatch"; }
j1=$(submit 1 "" -N 1 -n 1 -c "$C1" --hint=nomultithread --mem=200G -t "$T1")
j2=$(submit 2 "$j1" -N 1 -n 1 -c 1 -t 00:30:00)
if [ "$SAMPLER" = emulator ]; then
  j3=$(submit 3 "$j2" -N "$N3" --exclusive --mem=0 --ntasks-per-node=1 --cpus-per-task=64 ${W3:+-w "$W3"} -t "$T3")
else
  j3=$(submit 3 "$j2" -N 1 -n 1 -c 4 --mem=100G -t "$T3")
fi
j4=$(submit 4 "$j3" -N 1 -n "$R4" -c "$C4" --hint=nomultithread --mem=0 -t 04:00:00)
printf 'run_id %s\nproblem %s %s\nsampler %s (np %s, nodes %s)\nstep1 %s\nstep2 %s\nstep3 %s\nstep4 %s (%s x %s) %s\n' \
  "$RUN_ID" "$PROBLEM" "$SARGS" "$SAMPLER" "$NP" "$N3" "$j1" "$j2" "$j3" "$j4" "$R4" "$C4" "$S4" | as tee "$RUN_DIR/chain.txt"
echo "결과: $RUN_DIR/work/   로그: $RUN_DIR/logs/"
