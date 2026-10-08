"""문제 크기를 바꿀 수 있는 STEP 1~3. STEP 4는 run_step.py 4를 그대로 씁니다(같은 파일 계약).

    python run_scaled.py 1 --problem n2_ccpvdz_36q --workdir W --threads 32     # 적분·FCI·CCSD·LUCJ 회로
    python run_scaled.py 2 --problem n2_ccpvdz_36q --workdir W                  # ISA 회로 + 에뮬레이터 QASM
    python run_scaled.py 3 --problem n2_ccpvdz_36q --workdir W --sampler ffsim  # 또는 statevector | emulator
    srun ... python run_step.py 4 --workdir W --mpi                             # STEP 4 (MPI 배치 병렬)

--sampler emulator는 에뮬레이터가 쓴 counts JSON(기본 W/step3_emulator_counts.json)을 STEP 3 파일로 바꿉니다.
에뮬레이터 실행은 slurm/scaled_step.sbatch가 합니다. 프리셋과 파일 계약: sqd_workflow/scaled.py.
"""
import argparse
import os
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", type=int, choices=[1, 2, 3])
    ap.add_argument("--problem", required=True, help="프리셋: n2_sto6g_16q(IBM 예제) | n2_ccpvdz_36q | h18_sto6g_36q")
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--norb", type=int, help="활성 궤도 수 덮어쓰기(큐비트 = 2·norb). 작은 크기 검증·시간 측정용")
    ap.add_argument("--n-reps", type=int, help="LUCJ 반복 수 덮어쓰기")
    ap.add_argument("--no-fci", action="store_true", help="STEP 1의 FCI 기준값 계산 생략")
    ap.add_argument("--shots", type=int, help="STEP 3 shot 수 덮어쓰기(기본 100,000)")
    ap.add_argument("--sampler", choices=["statevector", "ffsim", "emulator"], help="STEP 3 샘플러")
    ap.add_argument("--counts", type=Path, help="--sampler emulator: 에뮬레이터 counts JSON")
    ap.add_argument("--threads", type=int, default=1,
                    help="OpenMP 스레드(STEP 1의 FCI·CCSD). STEP 3 ffsim은 BLAS 스레드도 이 값(STEP 1·2의 BLAS는 1)")
    args = ap.parse_args(argv)
    if args.step == 3 and not args.sampler:
        ap.error("STEP 3에는 --sampler가 필요합니다")
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    blas = args.threads if args.step == 3 else 1
    os.environ["OPENBLAS_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = str(blas)

    from pyscf import lib
    from threadpoolctl import threadpool_limits
    from sqd_workflow import scaled

    spec = scaled.get_spec(args.problem, norb=args.norb, n_reps=args.n_reps, shots=args.shots,
                           fci=False if args.no_fci else None)
    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    lib.num_threads(args.threads)
    with threadpool_limits(limits={"openmp": args.threads, "blas": blas}):
        print(f"[STEP {args.step}] {spec.name} workdir={workdir}", flush=True)
        if args.step == 1:
            scaled.stage1(workdir, spec)
        elif args.step == 2:
            scaled.stage2(workdir, spec)
        else:
            scaled.stage3(workdir, spec, sampler=args.sampler, counts_file=args.counts)
    print(f"[STEP {args.step}] 완료", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
