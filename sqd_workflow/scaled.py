"""문제 크기를 바꿀 수 있는 STEP 1~3 (36큐비트까지). STEP 4는 stages.stage4를 그대로 씁니다.

ibm_steps.py는 IBM 예제 원문(N₂/STO-6G 16큐비트 고정)이라 손대지 않고, 같은 계산을 문제 정의(ProblemSpec)로
일반화했습니다. 프리셋 "n2_sto6g_16q"는 IBM 예제와 같은 적분·회로를 만듭니다(tests/test_scaled.py).

STEP 3 샘플러
- statevector: IBM 원문과 같은 Qiskit StatevectorSampler. 상태벡터 2^n개라 30큐비트 근처가 한계입니다.
- ffsim: LUCJ 상태를 전자 수 보존 공간(C(norb,nα)·C(norb,nβ) 차원)에서 정확히 만들고 샘플링합니다.
  36큐비트 N₂/cc-pVDZ도 7.3×10⁷ 차원(1.2 GB)이라 노드 하나에서 됩니다. 에뮬레이터 결과의 기준 분포로 씁니다.
- emulator: pennylane-lightning-MPI의 mpi_counts_cli(36큐비트 = 3노드 64 rank)로 상태벡터를 계산하고 샘플링합니다.
  STEP 2가 만든 OpenQASM(게이트 h x y z rx ry rz cx cz swap cp, 숫자 파라미터)을 실행하고, 결과(JSON counts)를
  convert_emulator_counts가 STEP 3 파일로 바꿉니다. 에뮬레이터는 모든 물리 큐비트를 문자열 왼쪽부터 q0 순서로 측정하므로,
  ISA 회로의 measure(물리 큐비트 → 고전 비트) 대응으로 Qiskit 고전 비트 순서(오른쪽이 c0)로 되돌립니다.

파일 계약은 stages.py와 같고, STEP 2가 step2_emulator.qasm·step2_measure_map.json을 더 씁니다.
"""
from __future__ import annotations

import json
import math
import pickle
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from sqd_workflow.stages import _require, _write_meta

EMULATOR_GATES = ("h", "x", "y", "z", "rx", "ry", "rz", "cx", "cz", "swap", "cp")


@dataclass(frozen=True)
class ProblemSpec:
    name: str
    atom: tuple                  # pyscf 형식 ((기호, (x, y, z)), ...) Å
    basis: str
    symmetry: str | bool
    n_frozen: int                # 동결 코어 공간 궤도 수
    norb: int | None             # 활성 공간 궤도 수(None = 동결 코어 뒤 전부)
    n_reps: int                  # LUCJ 반복 수
    fci: bool = True             # STEP 1에서 활성 공간 FCI 기준값 계산
    compilation_seed: int = 12345
    shots: int = 100_000
    sample_seed: int = 12345


N2_ATOM = (("N", (0.0, 0.0, -0.5)), ("N", (0.0, 0.0, 0.5)))
H18_CHAIN = tuple(("H", (0.0, 0.0, 1.0 * i)) for i in range(18))
PRESETS = {
    # IBM 예제와 같은 문제(검증용)
    "n2_sto6g_16q": ProblemSpec("n2_sto6g_16q", N2_ATOM, "sto-6g", "Dooh", 2, None, 4),
    # 36큐비트: IBM 예제의 N₂(1.0 Å, 코어 2개 동결, 전자 10개)에서 기저만 cc-pVDZ, 활성 궤도 18개
    "n2_ccpvdz_36q": ProblemSpec("n2_ccpvdz_36q", N2_ATOM, "cc-pvdz", "Dooh", 2, 18, 1),
    # 고전 대각화 규모 최대화: 수소 사슬 H18(1.0 Å 간격), STO-6G 18궤도·전자 (9,9) 반 채움 → D 상한 2.4×10⁹.
    # FCI는 계산하지 않고 CCSD(T)를 기록합니다.
    "h18_sto6g_36q": ProblemSpec("h18_sto6g_36q", H18_CHAIN, "sto-6g", False, 0, None, 4, fci=False),
}


def get_spec(name: str, **overrides) -> ProblemSpec:
    """프리셋 + 덮어쓰기. 예: get_spec("n2_ccpvdz_36q", norb=14) → 28큐비트 같은 계열."""
    spec = PRESETS[name]
    overrides = {k: v for k, v in overrides.items() if v is not None}
    if "norb" in overrides:
        overrides.setdefault("name", f"{name.rsplit('_', 1)[0]}_{2 * overrides['norb']}q")
    return replace(spec, **overrides)


def _pass_manager(norb: int, seed: int):
    import ffsim
    from qiskit.providers.fake_provider import GenericBackendV2
    from qiskit.transpiler import CouplingMap
    pairs_aa = [(p, p + 1) for p in range(norb - 1)]
    coupling_map = CouplingMap.from_grid(norb, 2)
    backend = GenericBackendV2(coupling_map.size(), coupling_map=coupling_map, seed=seed,
                               basis_gates=["cp", "xx_plus_yy", "p", "x", "swap"])
    return ffsim.qiskit.generate_lucj_pass_manager(
        backend=backend, norb=norb, connectivity="square", interaction_pairs=(pairs_aa, None),
        optimization_level=3, seed_transpiler=seed)


def _ucj_operator(norb: int, ccsd, n_reps: int, pairs_ab):
    import ffsim
    pairs_aa = [(p, p + 1) for p in range(norb - 1)]
    return ffsim.UCJOpSpinBalanced.from_t_amplitudes(
        t2=ccsd.t2, t1=ccsd.t1, n_reps=n_reps, interaction_pairs=(pairs_aa, pairs_ab), optimize=True)


def stage1(workdir: Path, spec: ProblemSpec) -> None:
    """ibm_steps.step1_map과 같은 순서: RHF → 활성 공간 적분 → (FCI) → CCSD → LUCJ 회로."""
    import ffsim
    import pyscf
    import pyscf.cc
    import pyscf.mcscf
    from qiskit import QuantumCircuit, QuantumRegister
    started = time.perf_counter()
    mol = pyscf.gto.Mole()
    mol.build(atom=[[a, xyz] for a, xyz in spec.atom], basis=spec.basis, symmetry=spec.symmetry)
    norb_total = mol.nao_nr()
    norb = spec.norb or norb_total - spec.n_frozen
    active_space = range(spec.n_frozen, spec.n_frozen + norb)
    scf = pyscf.scf.RHF(mol).run()
    n_electrons = int(sum(scf.mo_occ[active_space]))
    nelec = ((n_electrons + mol.spin) // 2, (n_electrons - mol.spin) // 2)
    cas = pyscf.mcscf.CASCI(scf, norb, nelec)
    mo = cas.sort_mo(active_space, base=0)
    hcore, ecore = cas.get_h1cas(mo)
    eri = pyscf.ao2mo.restore(1, cas.get_h2cas(mo), norb)
    timing = {}
    reference_energy = float("nan")
    if spec.fci:
        t0 = time.perf_counter()
        reference_energy = float(cas.run().e_tot)
        timing["fci_seconds"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    ccsd = pyscf.cc.CCSD(scf, frozen=[i for i in range(norb_total) if i not in active_space]).run()
    timing["ccsd_seconds"] = time.perf_counter() - t0
    ccsd_t = float("nan")
    if not spec.fci:                       # FCI 대신 기준값으로 CCSD(T)
        t0 = time.perf_counter()
        ccsd_t = float(ccsd.e_tot + ccsd.ccsd_t())
        timing["ccsd_t_seconds"] = time.perf_counter() - t0
    _, pairs_ab = _pass_manager(norb, spec.compilation_seed)
    ucj_op = _ucj_operator(norb, ccsd, spec.n_reps, pairs_ab)
    qubits = QuantumRegister(2 * norb, name="q")
    circuit = QuantumCircuit(qubits)
    circuit.append(ffsim.qiskit.PrepareHartreeFockJW(norb, nelec), qubits)
    circuit.append(ffsim.qiskit.UCJOpSpinBalancedJW(ucj_op), qubits)
    circuit.measure_all()
    np.savez(workdir / "step1_problem.npz", norb=norb, nelec=np.array(nelec), hcore=hcore, eri=eri,
             nuclear_repulsion_energy=float(ecore), reference_energy=reference_energy)
    (workdir / "step1_circuit.pkl").write_bytes(pickle.dumps(circuit))
    (workdir / "step1_ucj.pkl").write_bytes(pickle.dumps(ucj_op))       # ffsim 샘플러용
    _write_meta(workdir, 1, ["step1_problem.npz", "step1_circuit.pkl", "step1_ucj.pkl"], [], started,
                compilation_seed=spec.compilation_seed, norb=norb, nelec=list(nelec), qubits=2 * norb,
                reference_energy=reference_energy, ccsd_energy=float(ccsd.e_tot), ccsd_t_energy=ccsd_t,
                rhf_energy=float(scf.e_tot),
                fci_dimension=math.comb(norb, nelec[0]) * math.comb(norb, nelec[1]), spec=asdict(spec), timing=timing)


def to_emulator_qasm(isa_circuit) -> tuple[str, list[int], dict]:
    """ISA 회로 → (OpenQASM 2.0 문자열, measure_map, 게이트 수).

    measure_map[c] = 고전 비트 c가 측정하는 물리 큐비트. 파라미터는 repr(float)로 씁니다(pi 식 금지, 파서 제약).
    """
    from qiskit import transpile
    emu = transpile(isa_circuit, basis_gates=list(EMULATOR_GATES), optimization_level=1)
    measure_map = [-1] * emu.num_clbits
    lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{emu.num_qubits}];"]   # include는 에뮬레이터가 무시
    for inst in emu.data:
        name = inst.operation.name
        qs = [emu.find_bit(q).index for q in inst.qubits]
        if name == "measure":
            measure_map[emu.find_bit(inst.clbits[0]).index] = qs[0]
            continue
        if name == "barrier":
            continue
        if name not in EMULATOR_GATES:
            raise ValueError(f"에뮬레이터가 지원하지 않는 게이트: {name}")
        params = [float(p) for p in inst.operation.params]
        head = name + (f"({','.join(repr(p) for p in params)})" if params else "")
        lines.append(f"{head} {','.join(f'q[{q}]' for q in qs)};")
    if -1 in measure_map:
        raise ValueError("측정되지 않는 고전 비트가 있습니다")
    return "\n".join(lines) + "\n", measure_map, dict(emu.count_ops())


def stage2(workdir: Path, spec: ProblemSpec) -> None:
    from types import SimpleNamespace
    from qiskit import qpy
    from sqd_workflow import ibm_steps
    _require(workdir, "step1.json", "step1_circuit.pkl")
    started = time.perf_counter()
    meta1 = json.loads((workdir / "step1.json").read_text())
    circuit = pickle.loads((workdir / "step1_circuit.pkl").read_bytes())
    pass_manager, _ = _pass_manager(meta1["norb"], meta1["compilation_seed"])
    isa = ibm_steps.step2_optimize(SimpleNamespace(circuit=circuit, pass_manager=pass_manager))
    with open(workdir / "step2_isa.qpy", "wb") as f:
        qpy.dump(isa, f)
    qasm, measure_map, emu_counts = to_emulator_qasm(isa)
    (workdir / "step2_emulator.qasm").write_text(qasm)
    (workdir / "step2_measure_map.json").write_text(json.dumps(measure_map) + "\n")
    _write_meta(workdir, 2, ["step2_isa.qpy", "step2_emulator.qasm", "step2_measure_map.json"], ["step1_circuit.pkl"],
                started, gate_counts=dict(isa.count_ops()), depth=isa.depth(), emulator_gate_counts=emu_counts,
                emulator_gates_total=sum(emu_counts.get(g, 0) for g in EMULATOR_GATES))


def _write_samples(workdir: Path, shots_bool: np.ndarray, sampler: str, started: float, inputs: list[str], **extra):
    """STEP 3 파일. step3_rng.json은 STEP 4의 SQD 난수 시작 상태(default_rng(sample_seed))입니다."""
    spec = json.loads((workdir / "step1.json").read_text())["spec"]
    np.savez(workdir / "step3_samples.npz", shots=shots_bool, num_bits=shots_bool.shape[1])
    (workdir / "step3_rng.json").write_text(json.dumps(np.random.default_rng(spec["sample_seed"]).bit_generator.state) + "\n")
    _write_meta(workdir, 3, ["step3_samples.npz", "step3_rng.json"], inputs, started, sampler=sampler,
                num_shots=int(shots_bool.shape[0]), unique=int(len(np.unique(np.packbits(shots_bool, axis=1), axis=0))),
                **extra)


def exact_probabilities(workdir: Path) -> tuple[np.ndarray, np.ndarray]:
    """ffsim로 LUCJ 상태의 정확한 분포: (비트열 bool 행렬[Qiskit 순서, 열 0 = 가장 왼쪽 비트], 확률)."""
    import ffsim
    meta1 = json.loads((workdir / "step1.json").read_text())
    norb, nelec = meta1["norb"], tuple(meta1["nelec"])
    ucj_op = pickle.loads((workdir / "step1_ucj.pkl").read_bytes())
    vec = ffsim.apply_unitary(ffsim.hartree_fock_state(norb, nelec), ucj_op, norb=norb, nelec=nelec)
    probs = np.abs(vec) ** 2
    addresses = np.arange(len(vec))
    strings = ffsim.addresses_to_strings(addresses, norb, nelec, bitstring_type=ffsim.BitstringType.BIT_ARRAY)
    return np.asarray(strings, dtype=bool), probs


def stage3(workdir: Path, spec: ProblemSpec, *, sampler: str, counts_file: Path | None = None) -> None:
    started = time.perf_counter()
    meta = json.loads((workdir / "step1.json").read_text())
    spec_d = meta["spec"]
    rng = np.random.default_rng(spec_d["sample_seed"])
    if sampler == "statevector":
        if spec.name == "n2_sto6g_16q":                 # IBM 원문 경로 그대로(샘플·난수 상태까지 동일)
            from sqd_workflow import stages
            stages.stage3(workdir)
            return
        from qiskit import qpy
        from qiskit.primitives import StatevectorSampler
        with open(workdir / "step2_isa.qpy", "rb") as f:
            isa = qpy.load(f)[0]
        result = StatevectorSampler(seed=rng).run([isa], shots=spec_d["shots"]).result()[0]
        _write_samples(workdir, result.data.meas.to_bool_array(), sampler, started, ["step2_isa.qpy"])
    elif sampler == "ffsim":
        _require(workdir, "step1_ucj.pkl")
        import ffsim
        norb, nelec = meta["norb"], tuple(meta["nelec"])
        ucj_op = pickle.loads((workdir / "step1_ucj.pkl").read_bytes())
        t0 = time.perf_counter()
        vec = ffsim.apply_unitary(ffsim.hartree_fock_state(norb, nelec), ucj_op, norb=norb, nelec=nelec, copy=False)
        probs = np.abs(vec) ** 2
        del vec
        evolve_s = time.perf_counter() - t0
        norm = float(probs.sum())
        probs /= norm
        idx = rng.choice(len(probs), size=spec_d["shots"], p=probs)   # 뽑힌 주소만 문자열로 바꿉니다(큰 차원 메모리)
        strings = ffsim.addresses_to_strings(idx, norb, nelec, bitstring_type=ffsim.BitstringType.BIT_ARRAY)
        _write_samples(workdir, np.asarray(strings, dtype=bool), sampler, started, ["step1_ucj.pkl"], norm=norm,
                       dimension=int(len(probs)), evolve_seconds=evolve_s, sample_seconds=time.perf_counter() - t0 - evolve_s)
    elif sampler == "emulator":
        _require(workdir, "step2_measure_map.json")
        counts_file = counts_file or workdir / "step3_emulator_counts.json"
        shots = convert_emulator_counts(json.loads(counts_file.read_text()),
                                        json.loads((workdir / "step2_measure_map.json").read_text()), rng)
        emu_meta = workdir / "step3_emulator.json"
        extra = json.loads(emu_meta.read_text()) if emu_meta.exists() else {}
        _write_samples(workdir, shots, sampler, started, [counts_file.name, "step2_emulator.qasm"], emulator=extra)
    else:
        raise ValueError(f"알 수 없는 샘플러: {sampler}")


def convert_emulator_counts(counts: dict, measure_map: list[int], rng) -> np.ndarray:
    """에뮬레이터 counts(문자 i = 물리 큐비트 i) → shot bool 행렬(Qiskit 고전 비트 순서, 열 0 = c_{n-1}).

    shot 순서는 정보가 없으므로 seed 고정 난수로 섞습니다(STEP 4는 순서와 무관하게 개수만 씁니다).
    """
    keys = list(counts)
    phys = np.array([[c == "1" for c in k] for k in keys], dtype=bool)          # (고유, 물리 큐비트)
    n_clbits = len(measure_map)
    clbits = phys[:, measure_map]                                                 # 열 c = 고전 비트 c
    rows = clbits[:, ::-1]                                                        # Qiskit 문자열: 왼쪽 = c_{n-1}
    reps = np.array([int(counts[k]) for k in keys])
    shots = np.repeat(rows, reps, axis=0)
    assert shots.shape[1] == n_clbits
    return shots[rng.permutation(len(shots))]
