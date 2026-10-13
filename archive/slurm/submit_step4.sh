#!/usr/bin/env bash
# 끝난 실행(STEP 1~3 파일)에 STEP 4만 다른 설정으로 다시 돌립니다. 입력을 새 폴더 <run>_step4_<tag>/ 에 복사합니다.
#   slurm/submit_step4.sh -r RUN_DIR -t TAG -x "--set max_dim=3162 --set samples_per_batch=1000000"
#                         [-N 노드=1] [-n rank=3] [-c rank당_코어=10] [-w 노드목록] [-T 시간=08:00:00] [-s 앞쪽_shot_수만_사용]
# 배치는 rank k % n 에 나뉘므로, 노드마다 배치 하나(L2)는 -N 3 -n 3 -c 32 입니다.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }
usage() { sed -n '2,5p' "$0"; exit 1; }
RUN="" TAG="" S4="" N=1 R=3 C=10 W="" T=08:00:00 SHOTS=""
while getopts "r:t:x:N:n:c:w:T:s:h" o; do
  case $o in r) RUN=$OPTARG ;; t) TAG=$OPTARG ;; x) S4=$OPTARG ;; N) N=$OPTARG ;; n) R=$OPTARG ;; c) C=$OPTARG ;; w) W=$OPTARG ;; T) T=$OPTARG ;; s) SHOTS=$OPTARG ;; *) usage ;; esac
done
[ -n "$RUN" ] && [ -n "$TAG" ] || usage
as test -f "$RUN/work/step3_samples.npz" || { echo "오류: $RUN/work 에 STEP 3 결과가 없습니다"; exit 1; }
V=${RUN%/}_step4_$TAG
as test ! -e "$V" || { echo "오류: $V 가 이미 있습니다"; exit 1; }
as mkdir -p "$V/work" "$V/logs"
as ln -s "$RUN/code" "$V/code"
for f in step1.json step1_problem.npz step3_samples.npz step3_rng.json; do as cp "$RUN/work/$f" "$V/work/"; done
if [ -n "$SHOTS" ]; then   # shot 순서는 이미 무작위라 앞쪽 SHOTS 개 = 같은 분포의 작은 표본
  as "$VENV/bin/python" -c "import numpy as np; z=np.load('$V/work/step3_samples.npz'); np.savez('$V/work/step3_samples.npz', shots=z['shots'][:$SHOTS], num_bits=z['num_bits'])"
fi
PROBLEM=$(as "$VENV/bin/python" -c "import json;print(json.load(open('$RUN/work/step1.json'))['spec']['name'])")
j=$(as sbatch --parsable -p "$PARTITION" -A "$ACCOUNT" -N "$N" -n "$R" -c "$C" --hint=nomultithread --mem=0 ${W:+-w "$W"} -t "$T" \
  -J sc-step4-$TAG -o "$V/logs/step4-%j.out" --export="ALL,STEP=4,RUN_DIR=$V,PROBLEM=$PROBLEM,STEP4_ARGS=$S4" "$RUN/code/slurm/scaled_step.sbatch")
echo "step4 $j  $V  ($N 노드, $R rank x $C, $S4${SHOTS:+, shots $SHOTS})" | as tee "$V/chain.txt"
