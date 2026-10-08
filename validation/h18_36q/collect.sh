#!/usr/bin/env bash
# H18 36큐비트 최대 규모 시험의 결과 수집기(세션과 분리해 실행: setsid nohup ... &). Slurm 3091 이 끝나면 요약을 씁니다.
O=/home/kq/Workspace/SQD_bench/sqd_workflow_bundle/validation/h18_36q
RUNS=/data01/hpcuser/sqd/workflow/runs
FF=$RUNS/sc_h18_sto6g_36q_20261008-180057_2339410          # ffsim LUCJ2 1e7 shot (STEP 1~3)
EMU=$RUNS/sc_h18_sto6g_36q_20261008-182038_2357625        # 에뮬레이터 LUCJ2 1e5 shot (STEP 1~3)
until sacct -n -X -j 3091 -o State | grep -qvE "PENDING|RUNNING"; do sleep 60; done
sacct -n -j 3074,3075,3079,3091 -o JobID%14,JobName%16,State,ExitCode,Elapsed,MaxRSS,NodeList -P > $O/sacct.txt
/data01/hpcuser/sqd/workflow/venv-py311/bin/python - <<PY > $O/summary.json
import json, os
out = {"step1_ffsim": json.load(open("$FF/work/step1.json")), "step3_ffsim": json.load(open("$FF/work/step3.json")),
       "step2_emulator": json.load(open("$EMU/work/step2.json")), "step3_emulator": json.load(open("$EMU/work/step3.json")),
       "emulator": json.load(open("$EMU/work/step3_emulator.json")), "step4": {}}
for tag in ("d1e6", "d1e7", "d1e8"):
    w = "$FF" + "_step4_" + tag + "/work"
    if os.path.exists(w + "/step4_result.json"):
        r = json.load(open(w + "/step4_result.json")); m = json.load(open(w + "/step4.json"))
        out["step4"][tag] = {"energy": r["total_energy_hartree"], "iterations": r["n_iterations"],
            "D": [[b["subspace_dimension"] for b in it] for it in r["history"]], "mpi_size": m["mpi_size"], "hosts": m["mpi_hosts"],
            "threads_per_rank": m["threads_per_rank"], "settings": m["settings"], "timing": m["timing"]}
    else:
        out["step4"][tag] = "missing"
print(json.dumps(out, indent=2, default=str))
PY
for t in d1e6 d1e7 d1e8; do cat $FF"_step4_"$t/logs/*.out; done > $O/step4_logs.txt 2>/dev/null
echo "COLLECTED $(date -Is)" >> $O/collect.log
