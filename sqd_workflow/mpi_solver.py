"""STEP 4의 MPI 배치 병렬 sci_solver.

qiskit-addon-sqd 0.13.1의 diagonalize_fermionic_hamiltonian은 MPI SPMD로 실행할 수 있습니다.
CI 문자열 준비와 결과 처리는 제어 프로세스(rank 0)가 하고, sci_solver만 모든 rank가 함께 부릅니다.
여기서는 배치 k를 rank k % size가 원문의 sci_solver(spin_sq=0.0, max_cycle=200)로 풀고 결과를 rank 0으로 모읍니다.
SDK의 solve_sci_batch는 배치마다 solve_sci를 독립 호출하므로, 같은 스레드 수에서는 단일 프로세스 결과와 같습니다.
병렬도는 배치 수(기본 3)까지입니다. 배치 하나를 여러 rank가 나눠 풀지는 않습니다.

출처: sqd_perf/sqdperf/drivers/ladder_sqd_sbd.py의 --solver pyscf 모드(그룹당 1 rank, 배치 k → 그룹 k % G)를
SDK 공개 API 위로 옮겼습니다. SBD는 spin_sq를 지원하지 않아 포함하지 않았습니다.
"""
from __future__ import annotations

import sys
from typing import Callable


def batch_parallel(sci_solver: Callable, comm=None) -> Callable:
    """sci_solver를 배치 단위로 MPI rank에 나누는 solver로 감쌉니다.

    rank 0은 배치 순서대로 결과 목록을, 다른 rank는 None 목록을 돌려줍니다.
    SDK는 제어 프로세스의 결과만 사용합니다(callback·결과 처리·broadcast).
    """
    if comm is None:
        from mpi4py import MPI
        comm = MPI.COMM_WORLD
    rank, size = comm.Get_rank(), comm.Get_size()

    def solver(ci_strings, one_body_tensor, two_body_tensor, norb, nelec):
        n = len(ci_strings)
        local = {k: sci_solver([ci_strings[k]], one_body_tensor, two_body_tensor, norb, nelec)[0]
                 for k in range(rank, n, size)}
        gathered = comm.gather(local, root=0)
        if rank != 0:
            return [None] * n
        merged = {k: r for part in gathered for k, r in part.items()}
        return [merged[k] for k in range(n)]

    return solver


def check_sdk_mpi(comm) -> None:
    """SDK가 MPI를 감지했는지 확인합니다. 감지하지 못하면 rank마다 루프 전체를 따로 돌립니다."""
    from qiskit_addon_sqd.processes import process_count
    if process_count() != comm.Get_size():
        raise RuntimeError(f"SDK가 MPI를 감지하지 못했습니다(process_count={process_count()}, "
                           f"MPI size={comm.Get_size()}). srun/mpiexec로 실행했는지 확인하세요.")


def abort_on_error(comm) -> None:
    """한 rank의 예외가 다른 rank를 MPI 대기에 남기지 않도록 전체 작업을 끝냅니다."""
    hook = sys.excepthook

    def _hook(*exc_info):
        hook(*exc_info)
        sys.stderr.flush()
        if comm.Get_size() > 1:
            comm.Abort(3)

    sys.excepthook = _hook
