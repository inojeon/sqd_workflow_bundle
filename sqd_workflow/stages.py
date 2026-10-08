"""STEP 1~4를 별도 프로세스(별도 Slurm 작업)로 실행하기 위한 파일 경계.

각 STEP은 workdir에서 앞 STEP의 파일을 읽고 자기 결과를 씁니다. 계산 본문은 ibm_steps.py의 함수 그대로입니다.

| STEP | 읽는 파일 | 쓰는 파일 |
| 1 | - | step1_problem.npz(적분·FCI), step1_circuit.pkl(추상 회로), step1.json |
| 2 | step1_circuit.pkl, step1.json | step2_isa.qpy, step2.json |
| 3 | step2_isa.qpy | step3_samples.npz(측정 비트열), step3_rng.json(측정 직후 난수 상태), step3.json |
| 4 | step1_problem.npz, step3_samples.npz, step3_rng.json | step4_result.json, step4_state.npz |

pass manager는 직렬화할 수 없어(qiskit HLSConfig의 lambda) STEP 2에서 같은 seed로 다시 만듭니다.
그래서 compilation_seed=None(원문의 비결정적 컴파일)은 STEP 분리 실행에서 지원하지 않습니다.
step1_circuit.pkl은 pickle입니다. 같은 환경의 STEP 1이 쓴 파일만 읽으세요.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import platform
import sys
import time
from importlib import metadata
from pathlib import Path

import numpy as np

from sqd_workflow import ibm_steps

PACKAGES = ("qiskit", "qiskit-addon-sqd", "ffsim", "pyscf", "numpy", "scipy", "mpi4py")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version.split()[0], "executable": sys.executable,
            "platform": platform.platform(), "host": platform.node(), "packages": versions}


def _write_meta(workdir: Path, step: int, outputs: list[str], inputs: list[str], started: float, **extra) -> None:
    meta = {"step": step, "elapsed_seconds": time.perf_counter() - started, "environment": _environment(),
            "inputs": {name: _sha256(workdir / name) for name in inputs},
            "outputs": {name: _sha256(workdir / name) for name in outputs}, **extra}
    (workdir / f"step{step}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def _require(workdir: Path, *names: str) -> None:
    missing = [n for n in names if not (workdir / n).exists()]
    if missing:
        raise FileNotFoundError(f"{workdir}에 앞 STEP의 파일이 없습니다: {', '.join(missing)}")


def lucj_pass_manager(norb: int, compilation_seed: int):
    """step1_map과 같은 backend·pass manager를 다시 만듭니다(같은 seed면 같은 ISA 회로)."""
    import ffsim
    from qiskit.providers.fake_provider import GenericBackendV2
    from qiskit.transpiler import CouplingMap
    pairs_aa = [(p, p + 1) for p in range(norb - 1)]
    coupling_map = CouplingMap.from_grid(norb, 2)
    backend = GenericBackendV2(coupling_map.size(), coupling_map=coupling_map, seed=compilation_seed,
                               basis_gates=["cp", "xx_plus_yy", "p", "x", "swap"])
    pass_manager, _ = ffsim.qiskit.generate_lucj_pass_manager(
        backend=backend, norb=norb, connectivity="square", interaction_pairs=(pairs_aa, None),
        optimization_level=3, seed_transpiler=compilation_seed)
    return pass_manager


def stage1(workdir: Path, *, compilation_seed: int = 12345) -> None:
    started = time.perf_counter()
    mapped = ibm_steps.step1_map(compilation_seed=compilation_seed)
    np.savez(workdir / "step1_problem.npz", norb=mapped.norb, nelec=np.array(mapped.nelec), hcore=mapped.hcore,
             eri=mapped.eri, nuclear_repulsion_energy=mapped.nuclear_repulsion_energy,
             reference_energy=mapped.reference_energy)
    (workdir / "step1_circuit.pkl").write_bytes(pickle.dumps(mapped.circuit))
    _write_meta(workdir, 1, ["step1_problem.npz", "step1_circuit.pkl"], [], started,
                compilation_seed=compilation_seed, norb=mapped.norb, nelec=list(mapped.nelec),
                reference_energy=mapped.reference_energy)


def stage2(workdir: Path) -> None:
    from types import SimpleNamespace
    from qiskit import qpy
    _require(workdir, "step1.json", "step1_circuit.pkl")
    started = time.perf_counter()
    meta1 = json.loads((workdir / "step1.json").read_text())
    if meta1["compilation_seed"] is None:
        raise ValueError("compilation_seed=None은 STEP 분리 실행에서 pass manager를 재현할 수 없습니다.")
    circuit = pickle.loads((workdir / "step1_circuit.pkl").read_bytes())
    pass_manager = lucj_pass_manager(meta1["norb"], meta1["compilation_seed"])
    isa_circuit = ibm_steps.step2_optimize(SimpleNamespace(circuit=circuit, pass_manager=pass_manager))
    with open(workdir / "step2_isa.qpy", "wb") as f:
        qpy.dump(isa_circuit, f)
    _write_meta(workdir, 2, ["step2_isa.qpy"], ["step1_circuit.pkl"], started,
                gate_counts=dict(isa_circuit.count_ops()))


def stage3(workdir: Path) -> None:
    from qiskit import qpy
    _require(workdir, "step2_isa.qpy")
    started = time.perf_counter()
    with open(workdir / "step2_isa.qpy", "rb") as f:
        isa_circuit = qpy.load(f)[0]
    executed = ibm_steps.step3_execute(isa_circuit)
    meas = executed.pub_result.data.meas
    np.savez(workdir / "step3_samples.npz", shots=meas.to_bool_array(), num_bits=meas.num_bits)
    (workdir / "step3_rng.json").write_text(json.dumps(executed.rng_state) + "\n")
    _write_meta(workdir, 3, ["step3_samples.npz", "step3_rng.json"], ["step2_isa.qpy"], started,
                num_shots=meas.num_shots)


def load_step4_inputs(workdir: Path) -> tuple[ibm_steps.MappedProblem, ibm_steps.ExecutedCircuit]:
    """STEP 4가 쓰는 값만 복원합니다(회로·pass manager는 None)."""
    from qiskit.primitives import BitArray, DataBin, SamplerPubResult
    _require(workdir, "step1_problem.npz", "step3_samples.npz", "step3_rng.json")
    p = np.load(workdir / "step1_problem.npz")
    mapped = ibm_steps.MappedProblem(
        norb=int(p["norb"]), nelec=tuple(int(x) for x in p["nelec"]), hcore=p["hcore"], eri=p["eri"],
        nuclear_repulsion_energy=float(p["nuclear_repulsion_energy"]),
        reference_energy=float(p["reference_energy"]), circuit=None, pass_manager=None)
    s = np.load(workdir / "step3_samples.npz")
    meas = BitArray.from_bool_array(s["shots"])
    if meas.num_bits != int(s["num_bits"]):
        raise ValueError(f"비트 수 불일치: {meas.num_bits} != {int(s['num_bits'])}")
    executed = ibm_steps.ExecutedCircuit(SamplerPubResult(DataBin(meas=meas)),
                                         json.loads((workdir / "step3_rng.json").read_text()))
    return mapped, executed


def _timed(solver, calls: list):
    """sci_solver 호출마다 벽시계 시간을 calls에 남깁니다(MPI면 rank 0 기준, 결과 수집 대기 포함)."""
    def timed(ci_strings, *args):
        t0 = time.perf_counter()
        out = solver(ci_strings, *args)
        calls.append({"seconds": time.perf_counter() - t0,
                      "subspace_dimensions": [int(len(a) * len(b)) for a, b in ci_strings]})
        return out
    return timed


def stage4(workdir: Path, *, mpi: bool = False, settings: dict | None = None,
           threads: int = 1) -> ibm_steps.PostprocessedResult:
    """mpi=True면 srun/mpiexec의 모든 rank가 함께 호출합니다. 파일은 rank 0만 씁니다.

    settings: ibm_steps.STEP4_SETTINGS 중 바꿀 값(None = IBM 원문 설정). threads는 기록용입니다.
    step4.json의 timing: load(입력 읽기), postprocess(step4_postprocess 전체), solve(sci_solver 호출 합).
    postprocess − solve는 유효 비율 계산·구성 복구·결과 처리처럼 rank 0만 하는(병렬화되지 않는) 부분입니다.
    """
    from qiskit_addon_sqd.processes import process_count
    started = time.perf_counter()
    rank, size, wrap, hosts = 0, 1, None, [platform.node()]
    if mpi:
        from mpi4py import MPI
        from sqd_workflow import mpi_solver
        comm = MPI.COMM_WORLD
        rank, size = comm.Get_rank(), comm.Get_size()
        mpi_solver.abort_on_error(comm)
        mpi_solver.check_sdk_mpi(comm)
        hosts = comm.gather(platform.node(), root=0)
    elif process_count() > 1:
        raise RuntimeError("MPI 환경에서 실행 중입니다. STEP 4를 여러 rank로 돌리려면 --mpi를 주세요.")
    calls: list[dict] = []

    def wrap(solver):
        if mpi:
            solver = mpi_solver.batch_parallel(solver, comm)
        return _timed(solver, calls)

    mapped, executed = load_step4_inputs(workdir)
    loaded = time.perf_counter()
    result = ibm_steps.step4_postprocess(mapped, executed, wrap_solver=wrap, settings=settings)
    done = time.perf_counter()
    if rank != 0:
        return result
    ecore = mapped.nuclear_repulsion_energy
    history = [[{"energy_hartree": float(b.energy + ecore), "subspace_dimension": int(b.sci_state.amplitudes.size),
                 "occupancies": [o.tolist() for o in b.orbital_occupancies]} for b in batches]
               for batches in result.result_history]
    summary = {"total_energy_hartree": result.final_energy, "fci_energy_hartree": mapped.reference_energy,
               "energy_error_hartree": result.energy_error, "valid_fraction": result.valid_fraction,
               "expected_fraction_random": result.expected_fraction_random,
               "occupancies": [o.tolist() for o in result.result.orbital_occupancies],
               "n_iterations": len(history), "history": history}
    (workdir / "step4_result.json").write_text(json.dumps(summary, indent=2) + "\n")
    result.result.sci_state.save(workdir / "step4_state.npz")
    _write_meta(workdir, 4, ["step4_result.json", "step4_state.npz"],
                ["step1_problem.npz", "step3_samples.npz", "step3_rng.json"], started,
                mpi_size=size, mpi_hosts=hosts, threads_per_rank=threads, settings=settings or {},
                solver="qiskit_addon_sqd solve_sci_batch(spin_sq=0.0)"
                + (", MPI 배치 병렬(배치 k → rank k % size)" if mpi else ""),
                timing={"load_seconds": loaded - started, "postprocess_seconds": done - loaded,
                        "solve_seconds": sum(c["seconds"] for c in calls), "solver_calls": calls},
                total_energy_hartree=result.final_energy)
    return result


STAGES = {1: stage1, 2: stage2, 3: stage3, 4: stage4}
