#!/usr/bin/env bash
# 작업 3098(30큐비트 rank 1·4) 종료 후 counts → 샘플 변환 → 정확 분포 비교. 결과: h30_local30_compare.json, README.txt 추가
B=/home/kq/Workspace/SQD_bench/sqd_workflow_bundle; O=$B/validation/h18_36q/emulator_diag
PY=/data01/hpcuser/sqd/workflow/venv-py311/bin/python; D=/data01/hpcuser/sqd/workflow/runs/diag_h30_local30
until sacct -n -X -j 3099 -o State | grep -qvE "PENDING|RUNNING"; do sleep 60; done
sacct -n -X -j 3099 -o JobID,State,ExitCode,Elapsed -P >> $O/sacct.txt; cp $D/logs/*.out $O/h30_step3.log
cd $B
for np_ in 1 4; do env -u SLURM_NTASKS PYTHONPATH=. $PY run_scaled.py 3 --problem n2_sto6g_16q --workdir $D/np$np_ --sampler emulator > /dev/null 2>&1 || echo "convfail np$np_" >> $O/README.txt; done
env -u SLURM_NTASKS OMP_NUM_THREADS=16 PYTHONPATH=. $PY bench/compare_samples.py $D/np1 $D/np4 --top 200 --out $O/h30_local30_compare.json > /dev/null 2> $O/h30_compare.err
$PY - <<PY >> $O/README.txt
import json
for w, r in json.load(open("$O/h30_local30_compare.json")).items():
    s = r["samples"]; e = r["exact_reference"]
    print("h30_local30_compare.json", w.split('/')[-1], r["qubits"], "q | unique", s["unique"], "xeb %.3f" % s["xeb_ratio"], "p %.3g" % s["top200_pvalue"], "| exact-ref unique", e["unique"])
PY
echo "H30_DONE $(date -Is)" >> $O/README.txt
