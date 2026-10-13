"""STEP 하나만 실행합니다. STEP 1~4를 별도 Slurm 작업으로 나눌 때 씁니다.

    python run_step.py 1 --workdir W
    python run_step.py 2 --workdir W
    python run_step.py 3 --workdir W
    srun --mpi=pmi2 -n 3 python run_step.py 4 --workdir W --mpi     # 배치 k → rank k % 3
    python run_step.py 4 --workdir W --set max_dim=1000 --set samples_per_batch=10000   # 성능 측정용 크기 변경

파일 경계와 형식: sqd_workflow/stages.py. 한 프로세스에서 네 STEP을 잇는 실행은 run_steps.py입니다.
--threads는 OpenMP(PySCF) 스레드 수이고 BLAS는 1로 고정합니다. 기본 1은 run_steps.py와 같은 조건입니다.
"""
import argparse
import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--workdir", type=Path, required=True, help="STEP 사이에 파일을 주고받는 폴더(노드 간 공유 경로)")
    ap.add_argument("--mpi", action="store_true", help="STEP 4만: MPI rank에 배치를 나눠 풉니다")
    ap.add_argument("--threads", type=int, default=1, help="rank당 OpenMP 스레드 수(기본 1)")
    ap.add_argument("--set", action="append", default=[], metavar="이름=값",
                    help="STEP 4만: IBM 원문 설정 바꾸기(예: --set max_dim=1000). 성능 측정용, 기본은 원문 그대로")
    args = ap.parse_args(argv)
    if (args.mpi or args.set) and args.step != 4:
        ap.error("--mpi·--set은 STEP 4에서만 씁니다")
    settings = {}
    for item in args.set:
        name, _, value = item.partition("=")
        settings[name] = float(value) if name.endswith("_tol") else int(value)
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)

    # 수치 라이브러리는 스레드 환경변수를 정한 뒤 import합니다.
    from pyscf import lib
    from threadpoolctl import threadpool_limits
    from sqd_workflow.stages import STAGES

    rank = 0
    if args.mpi:
        from mpi4py import MPI
        rank = MPI.COMM_WORLD.Get_rank()
        if rank != 0:                       # STEP 4 안의 원문 print가 rank 수만큼 겹치지 않게
            sys.stdout = open(os.devnull, "w")
    workdir = args.workdir.resolve()
    if rank == 0:
        workdir.mkdir(parents=True, exist_ok=True)
    lib.num_threads(args.threads)
    with threadpool_limits(limits={"openmp": args.threads, "blas": 1}):
        print(f"[STEP {args.step}] workdir={workdir}", flush=True)
        kwargs = {"mpi": args.mpi, "settings": settings or None, "threads": args.threads} if args.step == 4 else {}
        STAGES[args.step](workdir, **kwargs)
    print(f"[STEP {args.step}] 완료", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
