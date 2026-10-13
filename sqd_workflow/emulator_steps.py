"""양자 에뮬레이터 + 고전 배치 병렬 예제의 STEP 1~4. ibm_steps.py와 같은 꼴(함수 4개, 자료형 3개)입니다.

STEP 1 Map      : 수소 사슬 H_n(기본 14원자 = 28큐비트) → 적분·FCI 기준값·CCSD·LUCJ 회로
STEP 2 Optimize : ISA 회로 → 에뮬레이터용 OpenQASM 2.0 + 측정 비트 대응표
STEP 3 Execute  : 에뮬레이터 mpi_counts_cli(MPI P rank)로 shot 측정 → ExecutedCircuit (ibm_steps와 같은 자료형)
STEP 4 Post-process : ibm_steps.step4_postprocess 그대로. mpi=True면 배치를 MPI rank에 나눠 풉니다(mpi_solver.batch_parallel).

워크플로우로 옮길 때는 각 함수가 작업(task) 하나입니다. 함수 사이에 오가는 값은 모두 pickle 가능하므로
파일로 저장하거나(run_example.py --save) 메모리로 넘길 수 있습니다. STEP 3만 외부 프로그램(에뮬레이터)을 부릅니다.
"""
from dataclasses import dataclass, asdict, replace
import copy
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister

from sqd_workflow import ibm_steps
from sqd_workflow.ibm_steps import MappedProblem, ExecutedCircuit, PostprocessedResult, STEP4_SETTINGS
from sqd_workflow.scaled import _pass_manager, _ucj_operator, h_chain, to_emulator_qasm, convert_emulator_counts

# 사이트 기본값(slurm/site.env 와 같은 값). 다른 클러스터에서는 환경변수로 바꿉니다.
EMULATOR_CLI = os.environ.get(
    "SQD_EMULATOR_CLI", "/data01/hpcuser/qc-cloud/pennylane-mpi/pennylane-lightning-MPI-v3/build-v3/mpi_counts_cli")
MPI_HOME = os.environ.get("SQD_MPI_HOME", "/data01/hpcuser/qc-cloud/sw/mpich-4.2.0")


@dataclass
class OptimizedCircuit:
    """STEP 2 출력. 에뮬레이터는 OpenQASM 문자열을 읽고, measure_map[c] = 고전 비트 c가 측정한 물리 큐비트."""
    isa_circuit: QuantumCircuit
    qasm: str
    measure_map: list[int]
    gate_counts: dict


@dataclass
class EmulatorRun:
    """STEP 3 실행 기록(시간 측정·재현용)."""
    cli: str
    n_ranks: int
    shots: int
    seed: int
    wall_seconds: float
    unique_bitstrings: int


def step1_map(*, n_atoms: int = 14, spacing: float = 1.5, basis: str = "sto-6g", n_reps: int = 2,
              compute_fci: bool = True, compilation_seed: int = 12345) -> MappedProblem:
    """수소 사슬 H_n(간격 spacing Å)의 적분·FCI 기준값·CCSD·LUCJ 회로·pass manager.

    기본 H14/STO-6G: 궤도 14, 전자 (7,7), 28큐비트, FCI 차원 3,432² = 1.18×10⁷(32코어 약 1분).
    늘린 사슬(1.5 Å)은 강상관이라 CCSD가 수렴하지 않을 수 있지만 LUCJ 초기 진폭으로는 그대로 씁니다.
    """
    import ffsim
    import pyscf
    import pyscf.cc
    import pyscf.mcscf
    mol = pyscf.gto.Mole()
    mol.build(atom=[[a, xyz] for a, xyz in h_chain(n_atoms, spacing)], basis=basis, symmetry=False)
    mol.max_memory = 150_000                       # MB. FCI 차원 10⁷~10⁸에 기본 4 GB 는 부족
    scf = pyscf.scf.RHF(mol).run()
    norb = mol.nao_nr()
    n_electrons = int(sum(scf.mo_occ))
    nelec = ((n_electrons + mol.spin) // 2, (n_electrons - mol.spin) // 2)
    cas = pyscf.mcscf.CASCI(scf, norb, nelec)
    mo = cas.sort_mo(range(norb), base=0)
    hcore, ecore = cas.get_h1cas(mo)
    eri = pyscf.ao2mo.restore(1, cas.get_h2cas(mo), norb)
    reference_energy = float(cas.run().e_tot) if compute_fci else float("nan")
    print(f"norb = {norb}, nelec = {nelec}, qubits = {2 * norb}, FCI = {reference_energy}")

    ccsd = pyscf.cc.CCSD(scf).run()
    pass_manager, pairs_ab = _pass_manager(norb, compilation_seed)
    ucj_op = _ucj_operator(norb, ccsd, n_reps, pairs_ab)
    qubits = QuantumRegister(2 * norb, name="q")
    circuit = QuantumCircuit(qubits)
    circuit.append(ffsim.qiskit.PrepareHartreeFockJW(norb, nelec), qubits)
    circuit.append(ffsim.qiskit.UCJOpSpinBalancedJW(ucj_op), qubits)
    circuit.measure_all()
    return MappedProblem(norb, nelec, hcore, eri, float(ecore), reference_energy, circuit, pass_manager)


def step2_optimize(mapped: MappedProblem) -> OptimizedCircuit:
    """ISA 회로를 만들고 에뮬레이터가 읽는 OpenQASM 2.0(게이트 h x y z rx ry rz cx cz swap cp)으로 바꿉니다."""
    isa_circuit = mapped.pass_manager.run(mapped.circuit)
    qasm, measure_map, gate_counts = to_emulator_qasm(isa_circuit)
    print(f"Gate counts: {dict(isa_circuit.count_ops())} → emulator {gate_counts}")
    return OptimizedCircuit(isa_circuit, qasm, measure_map, gate_counts)


def step3_execute(optimized: OptimizedCircuit, *, shots: int = 200_000, n_ranks: int = 32, seed: int = 12345,
                  sampler: str = "emulator", emulator_cli: str = EMULATOR_CLI, mpi_home: str = MPI_HOME,
                  workdir: Path | None = None) -> tuple[ExecutedCircuit, EmulatorRun]:
    """에뮬레이터로 shot 측정. ibm_steps.step3_execute 와 같은 ExecutedCircuit 을 돌려줍니다.

    sampler="emulator": mpi_counts_cli 를 mpiexec(-launcher fork, 한 노드) n_ranks(2의 거듭제곱)로 띄웁니다.
        Slurm 작업 안에서 부르면 그 노드의 코어를 씁니다. 28큐비트는 32 rank 로 약 2분.
    sampler="statevector": 작은 크기 검증용(Qiskit StatevectorSampler, 20큐비트 이하).
    seed 는 에뮬레이터 난수(PLMPI_SEED)와 STEP 4 의 SQD 난수 시작 상태(default_rng(seed))에 함께 씁니다.
    """
    from qiskit.primitives import BitArray, DataBin, SamplerPubResult
    rng = np.random.default_rng(seed)
    rng_state = copy.deepcopy(rng.bit_generator.state)     # STEP 4 는 이 상태에서 시작 (ibm_steps 와 같은 규약)
    t0 = time.perf_counter()
    if sampler == "statevector":
        from qiskit.primitives import StatevectorSampler
        result = StatevectorSampler(seed=np.random.default_rng(seed)).run([optimized.isa_circuit], shots=shots).result()[0]
        meas = result.data.meas
        run = EmulatorRun("statevector", 1, shots, seed, time.perf_counter() - t0, int(len(meas.get_counts())))
        return ExecutedCircuit(SamplerPubResult(DataBin(meas=meas)), rng_state), run
    if sampler != "emulator":
        raise ValueError(f"알 수 없는 샘플러: {sampler}")
    if n_ranks & (n_ranks - 1):
        raise ValueError(f"에뮬레이터 rank 수 {n_ranks} 는 2의 거듭제곱이어야 합니다(아니면 결과가 조용히 틀립니다)")
    if workdir is not None:
        Path(workdir).mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="sqd_emulator_", dir=workdir))
    qasm_file = tmp / "circuit.qasm"
    qasm_file.write_text(optimized.qasm)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PMI_", "SLURM_STEP", "MPI_LOCAL"))}  # 안쪽 MPI 를 새로 띄움
    env["PATH"] = f"{mpi_home}/bin:" + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = f"{mpi_home}/lib:" + env.get("LD_LIBRARY_PATH", "")
    env["PLMPI_SEED"] = str(seed)
    env["OMP_NUM_THREADS"] = "1"
    cmd = [f"{mpi_home}/bin/mpiexec", "-launcher", "fork", "-np", str(n_ranks),
           emulator_cli, "--qasm", str(qasm_file), "--shots", str(shots), "--fuse", "all"]
    def widen_affinity():                            # srun 이 rank 0 을 코어 1개에 묶어도 에뮬레이터는 노드 코어를 다 쓰게
        try:
            os.sched_setaffinity(0, range(os.cpu_count()))
        except OSError:
            pass
    counts = json.loads(subprocess.run(cmd, env=env, check=True, capture_output=True, text=True,
                                       preexec_fn=widen_affinity).stdout)
    shutil.rmtree(tmp, ignore_errors=True)
    shots_bool = convert_emulator_counts(counts, optimized.measure_map, rng)
    meas = BitArray.from_bool_array(shots_bool)
    run = EmulatorRun(emulator_cli, n_ranks, shots, seed, time.perf_counter() - t0, len(counts))
    print(f"emulator: {n_ranks} ranks, {shots} shots, {run.wall_seconds:.1f} s, {run.unique_bitstrings} unique bitstrings")
    return ExecutedCircuit(SamplerPubResult(DataBin(meas=meas)), rng_state), run


def step4_postprocess(mapped: MappedProblem, executed: ExecutedCircuit, *, mpi: bool = False,
                      settings: dict | None = None) -> PostprocessedResult:
    """ibm_steps.step4_postprocess 그대로. mpi=True 면 모든 MPI rank 가 함께 불러야 하고, 배치 k 는 rank k % size 가 풉니다.

    settings 예: {"num_batches": 64, "samples_per_batch": 50000, "max_dim": 1000, "max_iterations": 3} (D = max_dim²).
    rank 0 만 의미 있는 결과를 받습니다(다른 rank 는 None 이 섞인 결과).
    """
    wrap = None
    if mpi:
        from mpi4py import MPI
        from sqd_workflow import mpi_solver
        comm = MPI.COMM_WORLD
        mpi_solver.abort_on_error(comm)
        mpi_solver.check_sdk_mpi(comm)
        wrap = lambda solver: mpi_solver.batch_parallel(solver, comm)      # noqa: E731
    return ibm_steps.step4_postprocess(mapped, executed, wrap_solver=wrap, settings=settings)


# ---- 함수 사이 값을 파일로 넘길 때(워크플로우 작업 분리) ----

def strip_for_transfer(mapped: MappedProblem) -> MappedProblem:
    """STEP 4 에 필요한 값만 남긴 사본(pass manager 는 pickle 이 안 될 수 있음)."""
    return replace(mapped, circuit=None, pass_manager=None)
