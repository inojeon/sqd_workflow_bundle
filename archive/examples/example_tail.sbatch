#!/usr/bin/env bash
# run_example.sh 의 뒷부분: 샘플 검사 → STEP 4 사다리 → 집계. 1노드를 독점한 작업 안에서 차례로 실행합니다.
#   환경변수: RUN(STEP 1~3 실행 폴더), B(bench 폴더, code/ 포함), SETS, CONFIGS, CASE
set -euo pipefail
: "${RUN:?}" "${B:?}" "${SETS:?}" "${CONFIGS:?}"
CASE=${CASE:-example}
. "$B/code/slurm/site.env"
PY=$VENV/bin/python
cd "$B/code"
echo "예제 tail | job $SLURM_JOB_ID | node $SLURM_JOB_NODELIST | $(date -Is)"

mkdir -p "$B/inputs/$CASE"
for f in step1_problem.npz step3_samples.npz step3_rng.json step1.json step3.json step3_emulator.json; do
  [ -f "$RUN/work/$f" ] && cp "$RUN/work/$f" "$B/inputs/$CASE/"
done
echo "$RUN" > "$B/inputs/$CASE/source_run.txt"

echo "== 샘플 검사 (에뮬레이터 샘플 vs ffsim 정확 분포)"
env -u SLURM_NTASKS -u PMI_SIZE OMP_NUM_THREADS=16 "$PY" bench/compare_samples.py "$RUN/work" --out "$B/sample_check.json"
"$PY" - "$B/sample_check.json" <<'EOF'
import json, sys
r = next(iter(json.load(open(sys.argv[1])).values()))
s, e = r["samples"], r["exact_reference"]
k = [x for x in s if x.endswith("_pvalue")][0]
print(f"valid {s['valid']:.4f}  xeb {s['xeb_ratio']:.3f} (정확 대조 {e['xeb_ratio']:.3f})  {k} {s[k]:.3g} (대조 {e[k]:.3g})  unique {s['unique']}")
if s["valid"] < 0.999 or s[k] < 1e-6:
    print("경고: 에뮬레이터 샘플이 정확 분포와 다릅니다. STEP 4 결과 해석에 주의(사다리는 계속 진행).")
EOF

echo "== STEP 4 사다리: $CONFIGS  [$SETS]"
BENCH_DIR=$B CODE_DIR=$B/code CASES="$CASE:$SETS" CONFIGS="$CONFIGS" ROUNDS=1 NODES_MPI=1 bash bench/bench_step4.sbatch

echo "== 집계"
"$PY" bench/summarize.py "$B" --out "$B/summary"
echo "끝 $(date -Is)"
