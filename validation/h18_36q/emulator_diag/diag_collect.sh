#!/usr/bin/env bash
# 에뮬레이터 진단: 3노드 64 rank(22/21/21)로 돌린 H14(28q)·H16(32q)를 정확 분포와 비교. Slurm 3094·3095 종료 후 실행.
B=/home/kq/Workspace/SQD_bench/sqd_workflow_bundle; O=$B/validation/h18_36q/emulator_diag
PY=/data01/hpcuser/sqd/workflow/venv-py311/bin/python; RUNS=/data01/hpcuser/sqd/workflow/runs
until sacct -n -X -j 3094,3095 -o State | grep -qvE "PENDING|RUNNING" && ! sacct -n -X -j 3094,3095 -o State | grep -qE "PENDING|RUNNING"; do sleep 60; done
sacct -n -X -j 3094,3095 -o JobID,JobName,State,ExitCode,Elapsed,NodeList -P > $O/sacct.txt
cd $B
for t in h14 h16; do
  W=$RUNS/diag_${t}_emu3node/work; cp $RUNS/diag_${t}_emu3node/logs/*.out $O/${t}_step3.log 2>/dev/null
  env -u SLURM_NTASKS OMP_NUM_THREADS=16 PYTHONPATH=. $PY bench/compare_samples.py $W --top 200 --out $O/${t}_3node_compare.json > /dev/null 2> $O/${t}_compare.err
done
# 같은 H14 회로의 1노드 결과(np16·np64, kqdata01)도 보관
cp /tmp/claude-1001/-home-kq-Workspace-SQD-bench/5a8bf7d1-dce8-4a9c-b5ba-8a6348e908b3/scratchpad/h14_cmp.json $O/h14_1node_np16_np64_compare.json 2>/dev/null
$PY - <<PY > $O/README.txt
import json, glob
for f in sorted(glob.glob("$O/*compare.json")):
    for w, r in json.load(open(f)).items():
        s = r["samples"]; e = r["exact_reference"]
        print(f.split('/')[-1], w.split('/')[-1], r["qubits"], "q", r.get("sampler"), "| unique", s["unique"], "xeb %.3f" % s["xeb_ratio"],
              "p %.3g" % s["top200_pvalue"], "| exact-ref unique", e["unique"], "xeb %.3f" % e["xeb_ratio"])
PY
echo "DIAG_DONE $(date -Is)" >> $O/README.txt
