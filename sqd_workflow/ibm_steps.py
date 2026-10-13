# Adapted from IBM/Qiskit documentation code snippets, Apache-2.0.
# Source revision and license: archive/references/n2_small_scale/{source.json,LICENSE}.
# Changes: four explicit functions, typed outputs, RNG snapshot/restore,
# optional deterministic compilation seeds, Korean boundary comments,
# optional STEP 4 sci_solver wrapper (MPI batch parallelism) and settings override.
"""IBM small-scale simulator example의 STEP 1~4를 그대로 나눈 계산 모듈.

STEP 1 Map classical inputs to a quantum problem
STEP 2 Optimize for quantum hardware execution
STEP 3 Execute using Qiskit primitives
STEP 4 Post-process and return result in desired classical format

기존 prepare/sample/postprocess/solve의 자원별 단계와 구분합니다.
함수는 SDK와 파일 I/O에 의존하지 않습니다. 기본값은 소규모 N₂ 전용이며
STEP 1에 원본의 FCI 비교 계산도 포함되므로 대규모 설정으로 바꾸지 마세요.
"""
from dataclasses import dataclass
import copy
from typing import Any, Callable
import math

import ffsim
import numpy as np
import pyscf
import pyscf.cc
import pyscf.mcscf
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.primitives import StatevectorSampler
from qiskit.providers.fake_provider import GenericBackendV2
from qiskit.transpiler import CouplingMap
from functools import partial
from qiskit_addon_sqd.fermion import SCIResult, diagonalize_fermionic_hamiltonian, solve_sci_batch


@dataclass
class MappedProblem:
    """STEP 1의 출력. 회로 외에 STEP 4용 적분과 FCI 기준값을 함께 보관합니다."""
    norb: int
    nelec: tuple[int, int]
    hcore: np.ndarray
    eri: np.ndarray
    nuclear_repulsion_energy: float
    reference_energy: float
    circuit: QuantumCircuit
    pass_manager: Any


@dataclass
class ExecutedCircuit:
    """STEP 3의 측정 결과와 측정 직후 난수 상태. STEP 4에서 이어 사용합니다."""
    pub_result: Any
    rng_state: dict


@dataclass
class PostprocessedResult:
    """STEP 4의 최저 에너지 상태, 반복 이력과 정확도 비교값입니다."""
    result: SCIResult
    result_history: list[list[SCIResult]]
    final_energy: float
    energy_error: float
    valid_fraction: float
    expected_fraction_random: float


def step1_map(*, compilation_seed: int | None = 12345) -> MappedProblem:
    """분자·적분·FCI·CCSD·LUCJ 회로와 pass manager 생성. 아직 transpile하지 않습니다.

    compilation_seed=None이면 원문처럼 backend/transpiler seed를 고정하지 않습니다.
    기본 12345는 프로젝트 독립 원본 실행기와 재현 조건을 맞춥니다.
    """
    # Specify molecule properties
    spin_sq = 0

    # Build N2 molecule
    mol = pyscf.gto.Mole()
    mol.build(
        atom=[["N", (0, 0, -0.5)], ["N", (0, 0, 0.5)]],
        basis="sto-6g",
        symmetry="Dooh",
    )

    # Define active space
    n_frozen = 2
    active_space = range(n_frozen, mol.nao_nr())

    # Get molecular integrals
    scf = pyscf.scf.RHF(mol).run()
    norb = len(active_space)
    n_electrons = int(sum(scf.mo_occ[active_space]))
    n_alpha = (n_electrons + mol.spin) // 2
    n_beta = (n_electrons - mol.spin) // 2
    nelec = (n_alpha, n_beta)
    cas = pyscf.mcscf.CASCI(scf, norb, nelec)
    mo = cas.sort_mo(active_space, base=0)
    hcore, nuclear_repulsion_energy = cas.get_h1cas(mo)
    eri = pyscf.ao2mo.restore(1, cas.get_h2cas(mo), norb)

    # Compute exact energy using FCI
    reference_energy = cas.run().e_tot

    print(f"norb = {norb}")
    print(f"nelec = {nelec}")

    # Get CCSD t2 amplitudes for initializing the ansatz
    ccsd = pyscf.cc.CCSD(
        scf, frozen=[i for i in range(mol.nao_nr()) if i not in active_space]
    ).run()
    t1 = ccsd.t1
    t2 = ccsd.t2

    # Set ansatz properties
    n_reps = 4
    pairs_aa = [(p, p + 1) for p in range(norb - 1)]

    # Let generate_lucj_pass_manager determine the alpha-beta interactions
    pairs_ab = None

    # Initialize backend
    coupling_map = CouplingMap.from_grid(norb, 2)
    backend = GenericBackendV2(
        coupling_map.size(),
        coupling_map=coupling_map,
        seed=compilation_seed,
        basis_gates=["cp", "xx_plus_yy", "p", "x", "swap"],
    )

    # Create pass manager
    pass_manager, pairs_ab = ffsim.qiskit.generate_lucj_pass_manager(
        backend=backend,
        norb=norb,
        connectivity="square",
        interaction_pairs=(pairs_aa, pairs_ab),
        optimization_level=3,
        seed_transpiler=compilation_seed,
    )

    # Create the LUCJ ansatz operator
    ucj_op = ffsim.UCJOpSpinBalanced.from_t_amplitudes(
        t2=t2,
        t1=t1,
        n_reps=n_reps,
        interaction_pairs=(pairs_aa, pairs_ab),
        # Setting optimize=True enables the "compressed" factorization
        optimize=True,
    )

    # create an empty quantum circuit
    qubits = QuantumRegister(2 * norb, name="q")
    circuit = QuantumCircuit(qubits)

    # prepare Hartree-Fock state as the reference state and append it
    # to the quantum circuit
    circuit.append(ffsim.qiskit.PrepareHartreeFockJW(norb, nelec), qubits)

    # apply the UCJ operator to the reference state
    circuit.append(ffsim.qiskit.UCJOpSpinBalancedJW(ucj_op), qubits)
    circuit.measure_all()
    return MappedProblem(norb, nelec, hcore, eri, float(nuclear_repulsion_energy),
                         float(reference_energy), circuit, pass_manager)


def step2_optimize(mapped: MappedProblem) -> QuantumCircuit:
    """STEP 1에서 만든 pass manager로 ISA 회로를 만듭니다."""
    circuit = mapped.circuit
    pass_manager = mapped.pass_manager
    isa_circuit = pass_manager.run(circuit)
    print(f"Gate counts: {isa_circuit.count_ops()}")
    return isa_circuit


def step3_execute(isa_circuit: QuantumCircuit) -> ExecutedCircuit:
    """StatevectorSampler로 100,000샷을 측정합니다. SQD 계산은 수행하지 않습니다."""
    rng = np.random.default_rng(12345)
    sampler = StatevectorSampler(seed=rng)
    job = sampler.run([isa_circuit], shots=100_000)

    primitive_result = job.result()
    pub_result = primitive_result[0]
    return ExecutedCircuit(pub_result, copy.deepcopy(rng.bit_generator.state))


# step4_postprocess의 settings로 바꿀 수 있는 원문 설정 이름.
STEP4_SETTINGS = ("energy_tol", "occupancies_tol", "max_iterations", "num_batches",
                  "samples_per_batch", "max_dim", "max_cycle")


def step4_postprocess(mapped: MappedProblem, executed: ExecutedCircuit, *,
                      wrap_solver: Callable | None = None,
                      settings: dict | None = None) -> PostprocessedResult:
    """측정 통계, 구성 복구·대각화 반복, FCI 오차 계산을 모두 담당합니다.

    wrap_solver: 원문의 sci_solver(spin_sq·max_cycle 포함)를 받아 대체 solver를 돌려주는 함수.
    None이면 원문 그대로입니다. MPI 배치 병렬은 sqd_workflow.mpi_solver.batch_parallel을 넘깁니다.
    settings: STEP4_SETTINGS 중 바꿀 값(성능 측정에서 문제 크기를 키울 때). None이면 원문 설정 그대로입니다.
    """
    norb = mapped.norb
    nelec = mapped.nelec
    n_alpha, n_beta = nelec
    hcore, eri = mapped.hcore, mapped.eri
    nuclear_repulsion_energy = mapped.nuclear_repulsion_energy
    reference_energy = mapped.reference_energy
    pub_result = executed.pub_result
    # 원문의 rng 객체를 단계 밖으로 넘기는 대신 같은 상태를 복원합니다.
    rng = np.random.default_rng()
    rng.bit_generator.state = copy.deepcopy(executed.rng_state)

    def is_valid_bitstring(
        bitstring: str, norb: int, nelec: tuple[int, int]
    ) -> bool:
        n_alpha, n_beta = nelec
        return (
            len(bitstring) == 2 * norb
            and bitstring[norb:].count("1") == n_alpha
            and bitstring[:norb].count("1") == n_beta
        )


    bit_array = pub_result.data.meas
    num_valid = sum(
        is_valid_bitstring(b, norb, nelec) for b in bit_array.get_bitstrings()
    )
    valid_fraction = num_valid / bit_array.num_shots
    print(f"Fraction of sampled configurations that are valid: {valid_fraction}")

    expected_fraction_random = (
        math.comb(norb, n_alpha) * math.comb(norb, n_beta) / 2 ** (2 * norb)
    )
    print(
        f"Expected fraction of valid configurations from uniformly random bitstrings: "
        f"{expected_fraction_random}"
    )

    # SQD options
    energy_tol = 1e-3
    occupancies_tol = 1e-3
    max_iterations = 5

    # Eigenstate solver options
    num_batches = 3
    samples_per_batch = 1000
    max_dim = 50
    symmetrize_spin = True
    carryover_threshold = 1e-4
    max_cycle = 200
    if settings:
        unknown = set(settings) - set(STEP4_SETTINGS)
        if unknown:
            raise ValueError(f"바꿀 수 없는 STEP 4 설정: {sorted(unknown)} (가능: {STEP4_SETTINGS})")
        energy_tol = settings.get("energy_tol", energy_tol)
        occupancies_tol = settings.get("occupancies_tol", occupancies_tol)
        max_iterations = settings.get("max_iterations", max_iterations)
        num_batches = settings.get("num_batches", num_batches)
        samples_per_batch = settings.get("samples_per_batch", samples_per_batch)
        max_dim = settings.get("max_dim", max_dim)
        max_cycle = settings.get("max_cycle", max_cycle)

    # Use the Hartree-Fock configuration as an initial guess for the orbital occupancies
    initial_occupancies = (
        np.array([1] * n_alpha + [0] * (norb - n_alpha)),
        np.array([1] * n_beta + [0] * (norb - n_beta)),
    )

    # Pass options to the built-in eigensolver. If you just want to use the defaults,
    # you can omit this step, in which case you would not specify the sci_solver argument
    # in the call to diagonalize_fermionic_hamiltonian below.
    sci_solver = partial(solve_sci_batch, spin_sq=0.0, max_cycle=max_cycle)
    if wrap_solver is not None:
        sci_solver = wrap_solver(sci_solver)

    # List to capture intermediate results
    result_history = []


    def callback(results: list[SCIResult]):
        result_history.append(results)
        iteration = len(result_history)
        print(f"Iteration {iteration}")
        for i, result in enumerate(results):
            print(f"\tSubsample {i}")
            print(f"\t\tEnergy: {result.energy + nuclear_repulsion_energy}")
            print(
                f"\t\tSubspace dimension: {np.prod(result.sci_state.amplitudes.shape)}"
            )


    result = diagonalize_fermionic_hamiltonian(
        hcore,
        eri,
        bit_array,
        samples_per_batch=samples_per_batch,
        norb=norb,
        nelec=nelec,
        num_batches=num_batches,
        energy_tol=energy_tol,
        occupancies_tol=occupancies_tol,
        max_iterations=max_iterations,
        sci_solver=sci_solver,
        symmetrize_spin=symmetrize_spin,
        max_dim=max_dim,
        initial_occupancies=initial_occupancies,
        carryover_threshold=carryover_threshold,
        callback=callback,
        seed=rng,
    )

    final_energy = result.energy + nuclear_repulsion_energy
    energy_error = final_energy - reference_energy
    print(f"Final energy: {final_energy}")
    print(f"Final energy error: {energy_error}")
    return PostprocessedResult(result, result_history, float(final_energy),
                               float(energy_error), float(valid_fraction),
                               float(expected_fraction_random))
