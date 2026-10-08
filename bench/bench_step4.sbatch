#!/usr/bin/env bash
# STEP 4 성능 비교: 같은 입력에 대해 단일 프로세스(기존)와 MPI 배치 병렬 구성을 번갈아(회차마다 무작위 순서) 실행합니다.
# 환경변수(sbatch --export 로 넘김)
#   BENCH_DIR  결과 폴더(공유 경로). 그 안의 inputs/<case>/ 에 STEP 1·3 파일이 있어야 합니다
#   CODE_DIR   번들 사본(run_step.py 가 있는 곳)
#   CASES      "case:설정;설정 case2:설정..." 예) "ibm: n2_d1e6:max_dim=1000;samples_per_batch=10000"
#   CONFIGS    S:T(단일 프로세스, T 스레드) | M:R:T(MPI R rank × T 스레드). 예) "S:1 S:10 M:3:1 M:3:10"
#   ROUNDS     회차 수(기본 3)   NODES_MPI  MPI 구성의 노드 수(기본 1)
#   HINT       nomultithread(기본: -c T = 물리 코어 T개) | multithread(-c T = 논리 CPU T개, 하이퍼스레드 짝을 함께 씀)
set -euo pipefail
: "${BENCH_DIR:?}" "${CODE_DIR:?}" "${CASES:?}" "${CONFIGS:?}"
ROUNDS=${ROUNDS:-3} NODES_MPI=${NODES_MPI:-1} HINT=${HINT:-nomultithread}
. "$CODE_DIR/slurm/site.env"
PY=$VENV/bin/python
export PATH=$MPI_HOME/bin:$PATH LD_LIBRARY_PATH=$MPI_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
unset OMP_PROC_BIND OMP_PLACES GOMP_CPU_AFFINITY OMP_WAIT_POLICY LD_PRELOAD
case "$FABRIC" in verbs) export FI_PROVIDER='verbs;ofi_rxm' ;; tcp) export FI_PROVIDER=tcp FI_TCP_IFACE=ib0 ;; esac
PROP=AS,CORE,CPU,DATA,FSIZE,NOFILE,NPROC,RSS,STACK
LOG=$BENCH_DIR/runs_${SLURM_JOB_ID}.tsv
echo -e "job\tcase\tconfig\tround\tnodes\thint\twall_seconds\texit\trun_dir" > "$LOG"
echo "bench job $SLURM_JOB_ID | nodes $SLURM_JOB_NODELIST | cases [$CASES] | configs [$CONFIGS] | rounds $ROUNDS | hint $HINT | $(date -Is)"
cd "$CODE_DIR"
# CPU 배치 확인: rank별로 허용된 CPU 목록(같은 물리 코어의 하이퍼스레드 짝이 겹치면 안 됨)
for probe in "1 1" "3 1" "3 10"; do
  set -- $probe
  echo "probe -n$1 -c$2 hint=$HINT:"; srun -N1 -n "$1" -c "$2" --hint="$HINT" --mpi=none bash -c 'echo "  task $SLURM_PROCID $(grep Cpus_allowed_list /proc/self/status | cut -f2)"' | sort
done

for case_spec in $CASES; do
  case_name=${case_spec%%:*} sets=${case_spec#*:}
  SET_ARGS=()
  IFS=';' read -ra kv <<< "$sets"
  for x in "${kv[@]}"; do [ -n "$x" ] && SET_ARGS+=(--set "$x"); done
  for round in $(seq 1 "$ROUNDS"); do
    for cfg in $(printf '%s\n' $CONFIGS | shuf --random-source=<(yes "$round$case_name")); do
      run=$BENCH_DIR/runs/$case_name/${cfg//:/_}_n${NODES_MPI}_${HINT}_r$round
      mkdir -p "$run"
      ln -sf "$BENCH_DIR/inputs/$case_name/"{step1_problem.npz,step3_samples.npz,step3_rng.json} "$run/"
      IFS=: read -r kind a b <<< "$cfg"
      t0=$(date +%s.%N); rc=0
      if [ "$kind" = S ]; then
        nodes=1
        srun -N1 -n1 -c "$a" --hint="$HINT" --mpi=none \
          env -u SLURM_NTASKS -u PMI_SIZE "$PY" run_step.py 4 --workdir "$run" --threads "$a" "${SET_ARGS[@]}" \
          > "$run/log.txt" 2>&1 || rc=$?
      else
        nodes=$NODES_MPI
        srun -N "$nodes" -n "$a" -c "$b" --hint="$HINT" --mpi=pmi2 --propagate=$PROP --kill-on-bad-exit=1 \
          "$PY" run_step.py 4 --workdir "$run" --mpi --threads "$b" "${SET_ARGS[@]}" \
          > "$run/log.txt" 2>&1 || rc=$?
      fi
      t1=$(date +%s.%N)
      wall=$(echo "$t1 - $t0" | bc)
      echo -e "$SLURM_JOB_ID\t$case_name\t$cfg\t$round\t$nodes\t$HINT\t$wall\t$rc\t$run" >> "$LOG"
      echo "$(date +%T) $case_name $cfg r$round nodes=$nodes wall=${wall}s exit=$rc"
    done
  done
done
echo "끝 $(date -Is)"
