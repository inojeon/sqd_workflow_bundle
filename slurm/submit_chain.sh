#!/usr/bin/env bash
# STEP 1~4 를 별도 Slurm 작업 4개로 제출합니다. 앞 작업이 성공해야 다음 작업이 시작합니다(afterok).
#   slurm/submit_chain.sh [-w STEP4_노드목록] [-n STEP4_rank수=3] [-c rank당_물리코어=1] [-N STEP4_노드수=1] [-t STEP4_시간=00:30:00]
# 실행 폴더 RUNS/<run_id>: code/(번들 사본) work/(STEP 사이 파일) logs/(작업 로그) chain.txt(작업 번호)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }
usage() { sed -n '2,4p' "$0"; exit 1; }

NODELIST="" RANKS=3 CPUS=1 NODES=1 TIME4=00:30:00
while getopts "w:n:c:N:t:h" opt; do
  case $opt in w) NODELIST=$OPTARG ;; n) RANKS=$OPTARG ;; c) CPUS=$OPTARG ;; N) NODES=$OPTARG ;; t) TIME4=$OPTARG ;; *) usage ;; esac
done
as test -x "$VENV/bin/python" || { echo "오류: $VENV 없음. 해결: slurm/setup_env.sh 먼저 실행"; exit 1; }
if ! cmp -s "$HERE/../uv.lock" <(as cat "$WF_ROOT/env-src/uv.lock"); then
  echo "오류: uv.lock 이 공유 환경을 만든 것과 다릅니다. 해결: slurm/setup_env.sh 다시 실행"; exit 1
fi

RUN_ID=wf_$(date +%Y%m%d-%H%M%S)
RUN_DIR=$RUNS/$RUN_ID
as mkdir -p "$RUN_DIR/code" "$RUN_DIR/work" "$RUN_DIR/logs"
tar -C "$HERE/.." --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -cf - . | as tar -C "$RUN_DIR/code" -xf -

COMMON=(--parsable -p "$PARTITION" -A "$ACCOUNT" --kill-on-invalid-dep=yes)
W1=() W4=()      # -w: STEP 4 는 목록 전체, STEP 1~3(1노드)은 목록의 첫 노드
if [ -n "$NODELIST" ]; then
  W1=(-w "$(scontrol show hostnames "$NODELIST" | head -1)") W4=(-w "$NODELIST")
fi
submit() {  # submit <step> <의존 job 또는 빈 값> <sbatch 옵션...>
  local step=$1 dep=$2; shift 2
  as sbatch "${COMMON[@]}" ${dep:+--dependency=afterok:$dep} -J "wf-step$step" -o "$RUN_DIR/logs/step$step-%j.out" \
    --export=ALL,STEP=$step,RUN_DIR=$RUN_DIR "$@" "$RUN_DIR/code/slurm/step.sbatch"
}
j1=$(submit 1 "" "${W1[@]}" -N 1 -n 1 -c 1 -t 00:30:00)
j2=$(submit 2 "$j1" "${W1[@]}" -N 1 -n 1 -c 1 -t 00:30:00)
j3=$(submit 3 "$j2" "${W1[@]}" -N 1 -n 1 -c 1 -t 00:30:00)
j4=$(submit 4 "$j3" "${W4[@]}" -N "$NODES" -n "$RANKS" -c "$CPUS" --hint=nomultithread -t "$TIME4")
printf 'run_id %s\nstep1 %s\nstep2 %s\nstep3 %s\nstep4 %s (ranks %s, cpus/task %s, nodes %s)\n' \
  "$RUN_ID" "$j1" "$j2" "$j3" "$j4" "$RANKS" "$CPUS" "$NODES" | as tee "$RUN_DIR/chain.txt"
echo "결과: $RUN_DIR/work/step4_result.json   로그: $RUN_DIR/logs/"
