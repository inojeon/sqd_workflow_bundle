"""성능 측정용: sqd_perf 사다리 데이터(Zenodo 15324153 변환본)를 STEP 1·3 출력 형식으로 바꿉니다.

    python bench/import_ladder.py --integrals R_16_1.00.npz --samples R_1.00.npz --fci -109.10... --out W

STEP 4는 이 파일만 읽습니다(step1_problem.npz, step3_samples.npz, step3_rng.json). 회로 STEP 1~3은 실행하지 않습니다.
데이터의 샘플은 (고유 비트열, 가중치)입니다. STEP 3 형식(측정 shot 배열)에 맞추려고 가중치 비율대로
--shots 개를 다항분포로 뽑습니다(seed 고정). 난수 상태는 default_rng(--seed)의 처음 상태입니다.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--integrals", type=Path, required=True, help="h1·eri·ecore·norb·nelec npz")
    ap.add_argument("--samples", type=Path, required=True, help="bitstrings(packbits)·counts·num_bits npz")
    ap.add_argument("--fci", type=float, default=float("nan"), help="기준 총에너지(Ha). 없으면 NaN")
    ap.add_argument("--shots", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=False)

    ints = np.load(args.integrals)
    norb, nelec = int(ints["norb"]), np.asarray(ints["nelec"], dtype=int)
    np.savez(args.out / "step1_problem.npz", norb=norb, nelec=nelec, hcore=ints["h1"], eri=ints["eri"],
             nuclear_repulsion_energy=float(ints["ecore"]), reference_energy=args.fci)

    smp = np.load(args.samples)
    num_bits = int(smp["num_bits"])
    if num_bits != 2 * norb:
        raise ValueError(f"비트 수 {num_bits} != 2·norb {2 * norb}")
    unique = np.unpackbits(smp["bitstrings"], axis=1)[:, :num_bits].astype(bool)   # 열 0 = 가장 왼쪽 비트
    weights = np.asarray(smp["counts"], dtype=np.float64)
    rng = np.random.default_rng(args.seed)
    counts = rng.multinomial(args.shots, weights / weights.sum())
    shots = np.repeat(unique, counts, axis=0)
    shots = shots[rng.permutation(len(shots))]
    np.savez(args.out / "step3_samples.npz", shots=shots, num_bits=num_bits)
    (args.out / "step3_rng.json").write_text(json.dumps(np.random.default_rng(args.seed).bit_generator.state) + "\n")

    source = {"integrals": str(args.integrals), "integrals_sha256": hashlib.sha256(args.integrals.read_bytes()).hexdigest(),
              "samples": str(args.samples), "samples_sha256": hashlib.sha256(args.samples.read_bytes()).hexdigest(),
              "norb": norb, "nelec": nelec.tolist(), "fci_energy_hartree": args.fci, "shots": args.shots, "seed": args.seed,
              "unique_in_data": int(len(unique)), "unique_in_shots": int((counts > 0).sum())}
    (args.out / "source.json").write_text(json.dumps(source, indent=2) + "\n")
    print(json.dumps(source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
