"""bench_step4.sbatch 결과 요약: 구성별 중앙값 시간, 기존 실행(S:1) 대비 속도, 결과 동등성.

    python bench/summarize.py BENCH_DIR [--out BENCH_DIR/summary]

동등성 기준
- 스레드 1개: MPI(M:R:1)의 step4_result.json 전체가 단일 프로세스(S:1)와 비트 단위로 같아야 합니다.
- 그 밖: 반복별 배치 부분공간 차원이 S:1과 같고 |ΔE| ≤ 1e-8 Ha여야 합니다. PySCF 커널은 스레드가 2개 이상이면
  실행마다 마지막 자리(1e-14 수준)가 달라질 수 있어 비트 동일을 요구하지 않습니다(sqd_perf X35와 같은 현상).
"""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def cores(cfg: str) -> int:
    parts = cfg.split(":")
    return int(parts[1]) if parts[0] == "S" else int(parts[1]) * int(parts[2])


def threads(cfg: str) -> int:
    return int(cfg.split(":")[-1])


def dims(result: dict) -> list:
    return [[b["subspace_dimension"] for b in it] for it in result["history"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench_dir", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    out = args.out or args.bench_dir / "summary"
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for tsv in sorted(args.bench_dir.glob("runs_*.tsv")):
        with open(tsv) as f:
            rows += list(csv.DictReader(f, delimiter="\t"))
    runs = defaultdict(list)         # (case, hint, config, nodes) → 회차 기록. hint 열이 없는 초기 기록은 cpu-bind=cores
    failures = []
    for r in rows:
        run = Path(r["run_dir"])
        if r["exit"] != "0" or not (run / "step4.json").exists():
            failures.append(r)
            continue
        meta = json.loads((run / "step4.json").read_text())
        result = json.loads((run / "step4_result.json").read_text())
        t = meta["timing"]
        runs[(r["case"], r.get("hint") or "cpu-bind=cores", r["config"], int(r["nodes"]))].append({
            "round": int(r["round"]), "wall": float(r["wall_seconds"]), "postprocess": t["postprocess_seconds"],
            "solve": t["solve_seconds"], "load": t["load_seconds"], "hosts": meta["mpi_hosts"], "result": result,
            "max_D": max(max(it) for it in dims(result)), "n_iter": result["n_iterations"]})

    table, checks = [], []
    for case, hint in sorted({k[:2] for k in runs}):
        keys = sorted((k for k in runs if k[:2] == (case, hint)), key=lambda k: (k[3], k[2][0] != "S", cores(k[2]), k[2]))
        base_name = "S:1"
        base = runs.get((case, hint, "S:1", 1))
        if not base:                      # S:1 이 없는 case(큰 D)는 가장 느린 단일 프로세스 구성을 기준으로
            singles = [k for k in keys if k[2].startswith("S:")]
            if singles:
                base_name = max(singles, key=lambda k: statistics.median(x["postprocess"] for x in runs[k]))[2]
                base = runs[(case, hint, base_name, 1)]
        base_post = statistics.median(x["postprocess"] for x in base) if base else None
        ref = base[0]["result"] if base else None
        for key in keys:
            rs = runs[key]
            med = {m: statistics.median(x[m] for x in rs) for m in ("wall", "postprocess", "solve", "load")}
            table.append({"case": case, "hint": hint, "config": key[2], "nodes": key[3], "cores": cores(key[2]), "rounds": len(rs),
                          "max_D": rs[0]["max_D"], "n_iterations": rs[0]["n_iter"],
                          "wall_s": med["wall"], "step4_s": med["postprocess"], "solve_s": med["solve"],
                          "other_s": med["postprocess"] - med["solve"],
                          "spread_step4": (max(x["postprocess"] for x in rs) - min(x["postprocess"] for x in rs)) / med["postprocess"],
                          "baseline": base_name if base_post else None,
                          "speedup_vs_S1": base_post / med["postprocess"] if base_post else None,
                          "energy": rs[0]["result"]["total_energy_hartree"]})
            same_t = runs.get((case, hint, f"S:{threads(key[2])}", 1))
            for x in rs:
                if same_t and threads(key[2]) == 1 and key[2] != "S:1":
                    checks.append({"case": case, "hint": hint, "config": key[2], "nodes": key[3], "round": x["round"],
                                   "against": f"S:{threads(key[2])}", "kind": "bit-identical",
                                   "ok": x["result"] == same_t[0]["result"]})
                if ref is not None:
                    dE = abs(x["result"]["total_energy_hartree"] - ref["total_energy_hartree"])
                    checks.append({"case": case, "hint": hint, "config": key[2], "nodes": key[3], "round": x["round"], "against": "S:1",
                                   "kind": "same D trajectory, |dE|<=1e-8", "dE": dE,
                                   "ok": dims(x["result"]) == dims(ref) and dE <= 1e-8})

    summary = {"table": table, "checks_failed": [c for c in checks if not c["ok"]], "n_checks": len(checks),
               "failures": failures}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    lines = ["| case | CPU 배정 | 구성 | 노드 | CPU | 회차 | D 최대 | 반복 | STEP 4 (s) | 대각화 (s) | 나머지 (s) | 기준 대비 | 실행 전체 (s) |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for t in table:
        sp = f"{t['speedup_vs_S1']:.2f}× ({t['baseline']})" if t["speedup_vs_S1"] else "—"
        lines.append(f"| {t['case']} | {t['hint']} | {t['config']} | {t['nodes']} | {t['cores']} | {t['rounds']} | {t['max_D']:,} | "
                     f"{t['n_iterations']} | {t['step4_s']:.2f} | {t['solve_s']:.2f} | {t['other_s']:.2f} | {sp} | {t['wall_s']:.2f} |")
    lines.append("")
    lines.append(f"동등성 검사 {len(checks)}건, 실패 {len(summary['checks_failed'])}건. 실행 실패 {len(failures)}건.")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
