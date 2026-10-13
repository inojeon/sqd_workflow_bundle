#!/usr/bin/env bash
# STEP 하나를 실행하는 Slurm 작업. submit_chain.sh 가 STEP·RUN_DIR 을 넘겨 제출합니다.
# STEP 1~3: 1 task 단일 프로세스. STEP 4: srun 으로 SLURM_NTASKS 개 rank(배치 k → rank k % ntasks).
set -euo pipefail
: "${STEP:?STEP 필요}" "${RUN_DIR:?RUN_DIR 필요}"
. "$RUN_DIR/code/slurm/site.env"
PY=$VENV/bin/python
cd "$RUN_DIR/code"
echo "STEP $STEP | job $SLURM_JOB_ID | nodes $SLURM_JOB_NODELIST | ntasks ${SLURM_NTASKS:-1} | cpus/task ${SLURM_CPUS_PER_TASK:-1} | $(date -Is)"

if [ "$STEP" != 4 ]; then
  # SDK(qiskit_addon_sqd)는 import 시 이 변수들로 MPI 를 감지합니다. 단일 프로세스 STEP 에서는 지웁니다.
  env -u SLURM_NTASKS -u PMI_SIZE -u OMPI_COMM_WORLD_SIZE -u MPI_LOCALNRANKS \
    "$PY" run_step.py "$STEP" --workdir "$RUN_DIR/work"
  exit
fi

THREADS=${SLURM_CPUS_PER_TASK:-1}
export PATH=$MPI_HOME/bin:$PATH
export LD_LIBRARY_PATH=$MPI_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
unset OMP_PROC_BIND OMP_PLACES GOMP_CPU_AFFINITY OMP_WAIT_POLICY LD_PRELOAD
case "$FABRIC" in
  verbs) export FI_PROVIDER='verbs;ofi_rxm' ;;
  tcp) export FI_PROVIDER=tcp FI_TCP_IFACE=ib0 ;;
  *) echo "오류: FABRIC=$FABRIC (verbs|tcp)"; exit 2 ;;
esac
# --propagate 에서 MEMLOCK 을 빼 로그인 노드의 memlock 64 KB 가 verbs 등록을 막지 않게 합니다(sqd_perf X40).
# --hint=nomultithread: -c T 가 물리 코어 T개(코어당 스레드 1개에 고정)입니다. 없으면 하이퍼스레드 노드에서 rank 둘이
# 한 코어를 나눠 쓸 수 있습니다. --cpu-bind 를 함께 주면 --hint 가 무시되므로 넣지 않습니다(Slurm 24.11).
srun --mpi=pmi2 --ntasks="$SLURM_NTASKS" --cpus-per-task="$THREADS" --hint=nomultithread \
  --propagate=AS,CORE,CPU,DATA,FSIZE,NOFILE,NPROC,RSS,STACK --kill-on-bad-exit=1 \
  "$PY" run_step.py 4 --workdir "$RUN_DIR/work" --mpi --threads "$THREADS"
