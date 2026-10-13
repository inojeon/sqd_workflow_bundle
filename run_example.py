"""에뮬레이터 + 고전 배치 병렬 예제의 STEP 1~4 를 순서대로 실행합니다(run_steps.py 와 같은 꼴).

단일 프로세스(스레드만):
    python run_example.py                                   # H14 28큐비트, 에뮬레이터 32 rank, STEP 4 D=10⁶ 배치 64 반복 3
    python run_example.py --n-atoms 6 --sampler statevector --shots 5000 --set num_batches=4 --set samples_per_batch=1000 \
                          --set max_dim=50 --set max_iterations=2          # 12큐비트 로컬 검증
MPI 배치 병렬(STEP 4 를 R rank 로; STEP 1~3 은 rank 0 이 하고 결과를 broadcast):
    srun --mpi=pmi2 -n 32 -c 1 python run_example.py --mpi --threads 1
계산 본문: sqd_workflow/emulator_steps.py (STEP 1~3), sqd_workflow/ibm_steps.py (STEP 4)
"""
import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-atoms", type=int, default=14, help="수소 원자 수 = 궤도 수(큐비트 = 2배). 기본 14 = 28큐비트")
    ap.add_argument("--spacing", type=float, default=1.5, help="원자 간격 Å(늘릴수록 분포가 넓어져 D 가 커짐)")
    ap.add_argument("--n-reps", type=int, default=2)
    ap.add_argument("--no-fci", action="store_true", help="STEP 1 의 FCI 기준값 생략(궤도 18 이상)")
    ap.add_argument("--sampler", choices=["emulator", "statevector"], default="emulator")
    ap.add_argument("--shots", type=int, default=200_000)
    ap.add_argument("--ranks", type=int, default=32, help="에뮬레이터 MPI rank 수(2의 거듭제곱, 한 노드)")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--mpi", action="store_true", help="STEP 4 배치 병렬. srun/mpiexec 로 띄운 모든 rank 가 함께 실행")
    ap.add_argument("--threads", type=int, default=1, help="프로세스(rank)당 OpenMP 스레드 수")
    ap.add_argument("--set", action="append", default=[], metavar="이름=값",
                    help="STEP 4 설정. 기본: num_batches=64 samples_per_batch=50000 max_dim=1000 max_iterations=3")
    ap.add_argument("--save", type=Path, help="단계별 결과를 이 폴더에 pickle/json 으로 저장(워크플로우 작업 분리용)")
    ap.add_argument("--only-prepare", action="store_true", help="STEP 1~3 만 실행하고 --save 폴더에 저장한 뒤 끝냄")
    ap.add_argument("--load", type=Path, help="STEP 1~3 결과를 이 폴더(--save 로 만든)에서 읽고 STEP 4 만 실행")
    args = ap.parse_args(argv)
    if args.only_prepare and not args.save:
        ap.error("--only-prepare 에는 --save 폴더가 필요합니다")

    settings = {"num_batches": 64, "samples_per_batch": 50_000, "max_dim": 1000, "max_iterations": 3}
    for item in args.set:
        name, _, value = item.partition("=")
        settings[name] = float(value) if name.endswith("_tol") else int(value)

    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    from pyscf import lib
    from threadpoolctl import threadpool_limits
    lib.num_threads(args.threads)

    comm, rank = None, 0
    if args.mpi:
        from mpi4py import MPI
        comm = MPI.COMM_WORLD
        rank = comm.Get_rank()
        if rank != 0:
            sys.stdout = open(os.devnull, "w")       # STEP 4 안의 원문 print 가 rank 수만큼 겹치지 않게
    elif any(v in os.environ for v in ("SLURM_NTASKS", "PMI_SIZE", "OMPI_COMM_WORLD_SIZE")) and \
            int(os.environ.get("SLURM_NTASKS", os.environ.get("PMI_SIZE", "1"))) > 1:
        raise SystemExit("MPI 환경(rank 여러 개)에서 실행 중입니다. --mpi 를 주거나 rank 1개로 실행하세요.")

    from sqd_workflow import emulator_steps as es
    timing = {}
    with threadpool_limits(limits={"openmp": args.threads, "blas": 1}):
        payload = None
        if rank == 0 and args.load:
            print(f"[STEP 1~3] loaded from {args.load}", flush=True)
            payload = (pickle.loads((args.load / "step1_mapped.pkl").read_bytes()),
                       pickle.loads((args.load / "step3_executed.pkl").read_bytes()))
        elif rank == 0:
            t0 = time.perf_counter()
            print("[STEP 1/4] Map: H-chain → integrals, FCI reference, LUCJ circuit", flush=True)
            mapped = es.step1_map(n_atoms=args.n_atoms, spacing=args.spacing, n_reps=args.n_reps,
                                  compute_fci=not args.no_fci, compilation_seed=args.seed)
            timing["step1_seconds"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            print("[STEP 2/4] Optimize: ISA circuit → OpenQASM for the emulator", flush=True)
            optimized = es.step2_optimize(mapped)
            timing["step2_seconds"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            print(f"[STEP 3/4] Execute: {args.sampler}, {args.shots} shots", flush=True)
            executed, run = es.step3_execute(optimized, shots=args.shots, n_ranks=args.ranks, seed=args.seed,
                                             sampler=args.sampler, workdir=args.save)
            timing["step3_seconds"] = time.perf_counter() - t0
            payload = (es.strip_for_transfer(mapped), executed)
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                (args.save / "step1_mapped.pkl").write_bytes(pickle.dumps(payload[0]))
                (args.save / "step2_circuit.qasm").write_text(optimized.qasm)
                (args.save / "step2_measure_map.json").write_text(json.dumps(optimized.measure_map))
                (args.save / "step3_executed.pkl").write_bytes(pickle.dumps(executed))
                (args.save / "step3_run.json").write_text(json.dumps(run.__dict__, indent=2))
                (args.save / "step13_timing.json").write_text(json.dumps(timing, indent=2))
            if args.only_prepare:
                print(json.dumps(timing, indent=2))
                return 0
        if comm is not None:
            mapped, executed = comm.bcast(payload, root=0)      # 모든 rank 가 같은 입력으로 STEP 4 를 부른다
        else:
            mapped, executed = payload

        t0 = time.perf_counter()
        print(f"[STEP 4/4] Post-process: SQD, settings {settings}, mpi={args.mpi}, threads={args.threads}", flush=True)
        result = es.step4_postprocess(mapped, executed, mpi=args.mpi, settings=settings)
        timing["step4_seconds"] = time.perf_counter() - t0

    if rank != 0:
        return 0
    summary = {"qubits": 2 * mapped.norb, "nelec": list(mapped.nelec), "fci_energy": mapped.reference_energy,
               "sqd_energy": result.final_energy, "energy_error": result.energy_error,
               "iterations": len(result.result_history),
               "subspace_dimension": int(result.result.sci_state.amplitudes.size),
               "settings": settings, "sampler": args.sampler, "shots": args.shots, "emulator_ranks": args.ranks,
               "mpi": args.mpi, "mpi_ranks": comm.Get_size() if comm else 1, "threads": args.threads, "timing": timing}
    print(json.dumps(summary, indent=2))
    out = args.save or args.load
    if out:
        tag = f"M{summary['mpi_ranks']}x{args.threads}" if args.mpi else f"S{args.threads}"
        (out / f"step4_summary_{tag}.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
