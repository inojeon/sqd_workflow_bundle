#!/usr/bin/env bash
# 큰 문제(run_scaled.py) STEP 하나를 실행하는 Slurm 작업. submit_scaled.sh 가 변수를 넘겨 제출합니다.
#   STEP, RUN_DIR, PROBLEM, SCALED_ARGS(예: "--norb 14 --no-fci"), SAMPLER(STEP 3), STEP4_ARGS(예: "--set max_dim=1000")
#   STEP 3 + SAMPLER=emulator: 할당된 노드 전체에 EMU_NP rank(2의 거듭제곱)로 mpi_counts_cli 를 띄웁니다.
set -euo pipefail
: "${STEP:?}" "${RUN_DIR:?}" "${PROBLEM:?}"
. "$RUN_DIR/code/slurm/site.env"
PY=$VENV/bin/python
W=$RUN_DIR/work
cd "$RUN_DIR/code"
NO_MPI=(env -u SLURM_NTASKS -u PMI_SIZE -u OMPI_COMM_WORLD_SIZE -u MPI_LOCALNRANKS)
echo "STEP $STEP | $PROBLEM ${SCALED_ARGS:-} | job $SLURM_JOB_ID | nodes $SLURM_JOB_NODELIST | $(date -Is)"
read -ra SARGS <<< "${SCALED_ARGS:-}"

case "$STEP" in
1|2)
  "${NO_MPI[@]}" "$PY" run_scaled.py "$STEP" --problem "$PROBLEM" --workdir "$W" --threads "${SLURM_CPUS_PER_TASK:-1}" "${SARGS[@]}" ;;
3)
  if [ "${SAMPLER:?}" = emulator ]; then
    : "${EMU_NP:?}"
    export PATH=$MPI_HOME/bin:$PATH LD_LIBRARY_PATH=$MPI_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
    export SRUN_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-64}   # hydra 프록시가 cgroup 1코어에 갇히지 않게(qc-cloud env-mpi.sh)
    SHOTS=$("$PY" -c "import json;print(json.load(open('$W/step1.json'))['spec']['shots'])")
    [ -n "${SHOTS_OVERRIDE:-}" ] && SHOTS=$SHOTS_OVERRIDE
    mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST")
    HF=$W/step3_hostfile; : > "$HF"
    nn=${#NODES[@]}; base=$((EMU_NP / nn)); extra=$((EMU_NP % nn))
    for i in "${!NODES[@]}"; do echo "${NODES[$i]}:$((base + (i < extra ? 1 : 0)))" >> "$HF"; done
    echo "에뮬레이터 $EMU_CLI | np $EMU_NP | shots $SHOTS | fuse ${EMU_FUSE:-all} | seed ${EMU_SEED:-12345}"; cat "$HF"
    t0=$(date +%s.%N)
    PLMPI_SEED=${EMU_SEED:-12345} mpirun -f "$HF" -np "$EMU_NP" -genv OMP_NUM_THREADS 1 -genv PLMPI_SEED "${EMU_SEED:-12345}" \
      "$EMU_CLI" --qasm "$W/step2_emulator.qasm" --shots "$SHOTS" --fuse "${EMU_FUSE:-all}" > "$W/step3_emulator_counts.json"
    t1=$(date +%s.%N)
    "$PY" -c "import json,sys; json.dump({'cli':'$EMU_CLI','np':$EMU_NP,'nodes':'$SLURM_JOB_NODELIST','hostfile':open('$HF').read().split(),
      'shots':$SHOTS,'fuse':'${EMU_FUSE:-all}','seed':${EMU_SEED:-12345},'wall_seconds':$t1-$t0,'slurm_job':'$SLURM_JOB_ID'},
      open('$W/step3_emulator.json','w'), indent=2)"
    echo "에뮬레이터 wall $(echo "$t1 - $t0" | bc) s"
  fi
  "${NO_MPI[@]}" "$PY" run_scaled.py 3 --problem "$PROBLEM" --workdir "$W" --sampler "$SAMPLER" \
    --threads "${SLURM_CPUS_PER_TASK:-1}" "${SARGS[@]}" ;;
4)
  THREADS=${SLURM_CPUS_PER_TASK:-1}
  export PATH=$MPI_HOME/bin:$PATH LD_LIBRARY_PATH=$MPI_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
  unset OMP_PROC_BIND OMP_PLACES GOMP_CPU_AFFINITY OMP_WAIT_POLICY LD_PRELOAD
  case "$FABRIC" in verbs) export FI_PROVIDER='verbs;ofi_rxm' ;; tcp) export FI_PROVIDER=tcp FI_TCP_IFACE=ib0 ;; esac
  read -ra S4 <<< "${STEP4_ARGS:-}"
  srun --mpi=pmi2 --ntasks="$SLURM_NTASKS" --cpus-per-task="$THREADS" --hint=nomultithread \
    --propagate=AS,CORE,CPU,DATA,FSIZE,NOFILE,NPROC,RSS,STACK --kill-on-bad-exit=1 \
    "$PY" run_step.py 4 --workdir "$W" --mpi --threads "$THREADS" "${S4[@]}" ;;
esac
echo "끝 $(date -Is)"
