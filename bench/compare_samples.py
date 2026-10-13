"""STEP 3 샘플(에뮬레이터 등)이 LUCJ 상태의 정확한 분포(ffsim)에서 나온 것과 맞는지 검사합니다. 36큐비트에서도 동작합니다.

    python bench/compare_samples.py W [W2 ...] [--top 200] [--out result.json]

W: run_scaled.py STEP 1~3을 마친 폴더(step1_ucj.pkl, step1.json, step3_samples.npz). 지표
- valid: 전자 수(α, β)가 맞는 shot 비율. 이상적 회로는 1입니다.
- xeb_ratio: 샘플 비트열의 정확한 확률 평균 ÷ Σp². 같은 분포에서 뽑았으면 1 근처입니다(무작위 샘플이면 1/Σp²·평균 ≪ 1).
- top-K χ²: 정확한 확률 상위 K개 비트열의 관측 개수와 기대 개수(shots·p)의 χ²(자유도 K, 나머지는 한 칸으로 묶음).
  p-value가 아주 작으면(예: < 1e-3) 분포가 다르다고 봅니다.
같은 지표를 정확한 분포에서 직접 뽑은 대조 샘플(seed 고정)로도 계산해 함께 적습니다.
"""
import argparse
import json
import math
import pickle
from pathlib import Path

import numpy as np


def exact_state(workdir: Path):
    import ffsim
    meta = json.loads((workdir / "step1.json").read_text())
    norb, nelec = meta["norb"], tuple(meta["nelec"])
    ucj_op = pickle.loads((workdir / "step1_ucj.pkl").read_bytes())
    vec = ffsim.apply_unitary(ffsim.hartree_fock_state(norb, nelec), ucj_op, norb=norb, nelec=nelec)
    return norb, nelec, np.abs(vec) ** 2


def addresses(shots: np.ndarray, norb: int, nelec):
    """shot bool 행렬(Qiskit 순서) → (ffsim 주소, 전자 수가 맞는지)."""
    import ffsim
    n = shots.shape[1]
    weights = (1 << np.arange(n - 1, -1, -1, dtype=np.int64))
    ints = shots.astype(np.int64) @ weights                       # 문자열 s_b s_a 의 정수값
    a = ints & ((1 << norb) - 1)
    b = ints >> norb
    pop = lambda x: np.array([bin(int(v)).count("1") for v in x])  # noqa: E731
    ok = (pop(a) == nelec[0]) & (pop(b) == nelec[1])
    addr = np.full(len(ints), -1, dtype=np.int64)
    if ok.any():
        addr[ok] = ffsim.strings_to_addresses(ints[ok], norb, nelec)
    return addr, ok


def metrics(addr: np.ndarray, ok: np.ndarray, probs: np.ndarray, top: int) -> dict:
    from scipy.stats import chi2
    shots = len(addr)
    p_sum2 = float(np.sum(probs ** 2))
    p_samp = np.where(ok, probs[np.clip(addr, 0, None)], 0.0)
    order = np.argsort(probs)[::-1][:top]
    counts = np.bincount(addr[ok], minlength=len(probs))
    obs = np.append(counts[order], shots - counts[order].sum())
    exp = np.append(probs[order] * shots, shots * (1 - probs[order].sum()))
    stat = float(np.sum((obs - exp) ** 2 / exp))
    return {"shots": shots, "valid": float(ok.mean()), "unique": int(len(np.unique(addr[ok]))),
            "xeb_ratio": float(p_samp.mean() / p_sum2), f"top{top}_chi2": stat,
            f"top{top}_pvalue": float(chi2.sf(stat, top)), f"top{top}_exact_mass": float(probs[order].sum())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdirs", type=Path, nargs="+")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    report = {}
    for w in args.workdirs:
        norb, nelec, probs = exact_state(w)
        shots = np.load(w / "step3_samples.npz")["shots"]
        sampler = json.loads((w / "step3.json").read_text()).get("sampler")
        addr, ok = addresses(shots, norb, nelec)
        rng = np.random.default_rng(2026)
        ref = rng.choice(len(probs), size=len(shots), p=probs / probs.sum())
        report[str(w)] = {"qubits": 2 * norb, "fci_dimension": len(probs), "norm": float(probs.sum()), "sampler": sampler,
                          "samples": metrics(addr, ok, probs, args.top),
                          "exact_reference": metrics(ref, np.ones(len(ref), bool), probs, args.top)}
        print(json.dumps({w.name: report[str(w)]}, indent=1, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
