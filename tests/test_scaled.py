"""문제 크기를 바꿀 수 있는 STEP 1~3(sqd_workflow/scaled.py) 검증.

- 프리셋 n2_sto6g_16q가 IBM 예제 STEP 1~3(stages.py)과 같은 적분·ISA 회로·샘플을 만든다.
- 에뮬레이터용 OpenQASM과 측정 대응표로 계산한 분포가 ffsim의 정확한 LUCJ 분포와 같다(변환 오류 검출).
- 에뮬레이터 counts 변환의 비트 순서.
"""
import json
import subprocess
import sys

import numpy as np
import pytest

from test_stages import ROOT, _env, staged_dir  # noqa: F401  (staged_dir: 같은 세션 fixture 재사용)


@pytest.fixture(scope="session")
def scaled16(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("scaled16")
    for step in (1, 2):
        subprocess.run([sys.executable, "run_scaled.py", str(step), "--problem", "n2_sto6g_16q", "--workdir", str(workdir)],
                       cwd=ROOT, env=_env(), check=True, capture_output=True, timeout=600)
    subprocess.run([sys.executable, "run_scaled.py", "3", "--problem", "n2_sto6g_16q", "--workdir", str(workdir),
                    "--sampler", "statevector"], cwd=ROOT, env=_env(), check=True, capture_output=True, timeout=600)
    return workdir


def test_preset16_matches_ibm_steps(scaled16, staged_dir):
    from qiskit import qpy
    a, b = np.load(scaled16 / "step1_problem.npz"), np.load(staged_dir / "step1_problem.npz")
    for key in b.files:
        np.testing.assert_array_equal(a[key], b[key])
    with open(scaled16 / "step2_isa.qpy", "rb") as f1, open(staged_dir / "step2_isa.qpy", "rb") as f2:
        assert qpy.load(f1)[0] == qpy.load(f2)[0]
    np.testing.assert_array_equal(np.load(scaled16 / "step3_samples.npz")["shots"],
                                  np.load(staged_dir / "step3_samples.npz")["shots"])


def test_emulator_qasm_matches_exact_distribution(scaled16):
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    from sqd_workflow import scaled
    qc = QuantumCircuit.from_qasm_str((scaled16 / "step2_emulator.qasm").read_text())
    assert {i.operation.name for i in qc.data} <= set(scaled.EMULATOR_GATES)
    measure_map = json.loads((scaled16 / "step2_measure_map.json").read_text())
    p = Statevector(qc).probabilities()                       # 인덱스 비트 i = 물리 큐비트 i
    idx = np.nonzero(p > 1e-14)[0]
    phys = ((idx[:, None] >> np.arange(qc.num_qubits)) & 1).astype(bool)
    rows = phys[:, measure_map][:, ::-1]
    emu = {r.tobytes(): v for r, v in zip(rows, p[idx])}
    strings, probs = scaled.exact_probabilities(scaled16)
    exact = {r.tobytes(): v for r, v in zip(strings, probs) if v > 1e-14}
    keys = set(emu) | set(exact)
    assert 0.5 * sum(abs(emu.get(k, 0) - exact.get(k, 0)) for k in keys) < 1e-10


def test_convert_emulator_counts_bit_order():
    from sqd_workflow import scaled
    # 물리 큐비트 3개, 고전 비트 c0←q2, c1←q0, c2←q1. 에뮬레이터 문자열 "abc" = q0 q1 q2
    counts = {"100": 2, "011": 1}
    shots = scaled.convert_emulator_counts(counts, [2, 0, 1], np.random.default_rng(0))
    got = sorted("".join("1" if b else "0" for b in r) for r in shots)
    # "100": q0=1 → c1=1 → Qiskit 문자열 c2c1c0 = "010". "011": q1=1,q2=1 → c2=1,c0=1 → "101"
    assert got == ["010", "010", "101"]
