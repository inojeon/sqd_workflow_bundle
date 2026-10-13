#!/usr/bin/env bash
# run_example.py 를 Slurm 작업 하나(1노드 독점) 안에서 세 단계(step)로 실행합니다. 워크플로우의 작업 3개에 해당합니다.
#   A) STEP 1~3  : srun -n 1 -c 32  python run_example.py --only-prepare --save OUT   (에뮬레이터는 안에서 32 rank 로 실행)
#   B) STEP 4 MPI: srun -n 32 -c 1  python run_example.py --mpi --load OUT            (배치 64개를 32 rank 가 나눠 풂)
#   C) STEP 4 비교: srun -n 1 -c 32 python run_example.py --load OUT --threads 32      (같은 32코어, 스레드만. SKIP_S32=1 이면 생략)
# 제출 예(번들 사본이 공유 경로 CODE_DIR 에 있어야 합니다):
#   sudo -u hpcuser env CODE_DIR=$B/code OUT=$B/example EXTRA="--n-atoms 14" \
#     sbatch -p batch -A compute -N 1 --exclusive --mem=0 -w kqsvr04 -t 06:00:00 --export=ALL $B/code/slurm/example.sbatch
set -euo pipefail
: "${CODE_DIR:?}" "${OUT:?}"
. "$CODE_DIR/slurm/site.env"
PY=$VENV/bin/python
export PATH=$MPI_HOME/bin:$PATH LD_LIBRARY_PATH=$MPI_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
unset OMP_PROC_BIND OMP_PLACES GOMP_CPU_AFFINITY OMP_WAIT_POLICY LD_PRELOAD
case "$FABRIC" in verbs) export FI_PROVIDER='verbs;ofi_rxm' ;; tcp) export FI_PROVIDER=tcp FI_TCP_IFACE=ib0 ;; esac
PROP=AS,CORE,CPU,DATA,FSIZE,NOFILE,NPROC,RSS,STACK
R=${RANKS:-32} EXTRA=${EXTRA:-}
cd "$CODE_DIR"; mkdir -p "$OUT"
echo "example job $SLURM_JOB_ID | node $SLURM_JOB_NODELIST | out $OUT | extra [$EXTRA] | $(date -Is)"

echo "== A) STEP 1~3 (rank 1개, 에뮬레이터 $R rank)"
t0=$(date +%s)
srun -N1 -n1 -c 32 --hint=nomultithread --mpi=none env -u SLURM_NTASKS -u PMI_SIZE \
  "$PY" run_example.py --only-prepare --save "$OUT" --ranks "$R" --threads 32 $EXTRA > "$OUT/A_prepare.log" 2>&1
echo "A 끝 $(( $(date +%s) - t0 )) s"; tail -3 "$OUT/A_prepare.log"

echo "== B) STEP 4, MPI $R rank × 1 스레드"
t0=$(date +%s)
srun --mpi=pmi2 -N1 -n "$R" -c 1 --hint=nomultithread --propagate=$PROP --kill-on-bad-exit=1 \
  "$PY" run_example.py --mpi --load "$OUT" --threads 1 $EXTRA > "$OUT/B_step4_mpi.log" 2>&1
echo "B 끝 $(( $(date +%s) - t0 )) s"; grep -A3 '"sqd_energy"' "$OUT/B_step4_mpi.log" | head -4

if [ -z "${SKIP_S32:-}" ]; then
  echo "== C) STEP 4, 단일 프로세스 32 스레드 (비교)"
  t0=$(date +%s)
  srun -N1 -n1 -c 32 --hint=nomultithread --mpi=none env -u SLURM_NTASKS -u PMI_SIZE \
    "$PY" run_example.py --load "$OUT" --threads 32 $EXTRA > "$OUT/C_step4_s32.log" 2>&1
  echo "C 끝 $(( $(date +%s) - t0 )) s"
fi
"$PY" - "$OUT" <<'EOF'
import json, sys, glob
out = sys.argv[1]
for f in sorted(glob.glob(f"{out}/step4_summary_*.json")):
    s = json.load(open(f)); t = s["timing"]
    print(f"{f.split('_')[-1][:-5]:>8}: STEP4 {t['step4_seconds']:8.0f} s  E={s['sqd_energy']:.6f}  err={s['energy_error']:.4f}  D={s['subspace_dimension']}")
EOF
echo "끝 $(date -Is)"
