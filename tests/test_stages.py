"""STEP을 별도 프로세스로 나눠 실행해도 독립 원본과 같고, MPI STEP 4가 단일 프로세스 STEP 4와 같아야 합니다."""
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
# SDK는 이 변수들로 MPI를 감지합니다. 단일 프로세스 STEP에는 넘기지 않습니다.
MPI_VARS = ("OMPI_COMM_WORLD_SIZE", "PMI_SIZE", "SLURM_NTASKS", "MPI_LOCALNRANKS")


def _env():
    return {k: v for k, v in os.environ.items() if k not in MPI_VARS}


def _run(cmd, **kw):
    proc = subprocess.run(cmd, cwd=ROOT, env=_env(), capture_output=True, text=True, timeout=600, **kw)
    assert proc.returncode == 0, f"{cmd}\n--- stdout\n{proc.stdout[-3000:]}\n--- stderr\n{proc.stderr[-3000:]}"
    return proc


@pytest.fixture(scope="session")
def staged_dir(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("staged")
    for step in (1, 2, 3, 4):        # STEP마다 새 프로세스: 별도 Slurm 작업과 같은 조건
        _run([sys.executable, "run_step.py", str(step), "--workdir", str(workdir)])
    return workdir


@pytest.mark.reference
def test_staged_run_matches_reference(staged_dir, reference_dir):
    actual = json.loads((staged_dir / "step4_result.json").read_text())
    expected = json.loads((reference_dir / "result.json").read_text())
    problem = np.load(staged_dir / "step1_problem.npz")
    np.testing.assert_allclose(problem["hcore"], np.load(reference_dir / "hamiltonian.npz")["h1"], atol=1e-10)
    np.testing.assert_allclose(problem["eri"], np.load(reference_dir / "hamiltonian.npz")["h2"], atol=1e-10)
    np.testing.assert_array_equal(np.load(staged_dir / "step3_samples.npz")["shots"],
                                  np.load(reference_dir / "samples.npz")["shots"])
    assert json.loads((staged_dir / "step3_rng.json").read_text()) == json.loads((reference_dir / "rng.json").read_text())
    assert abs(actual["total_energy_hartree"] - expected["total_energy_hartree"]) < 1e-8
    assert abs(actual["fci_energy_hartree"] - expected["fci_energy_hartree"]) < 1e-8
    np.testing.assert_allclose(actual["occupancies"], expected["occupancies"], atol=1e-7)
    expected_history = json.loads((reference_dir / "history.json").read_text())
    for actual_batches, expected_iteration in zip(actual["history"], expected_history, strict=True):
        for a, b in zip(actual_batches, expected_iteration["batches"], strict=True):
            assert a["subspace_dimension"] == b["subspace_dimension"]
            assert abs(a["energy_hartree"] - b["energy_hartree"]) < 1e-8
            np.testing.assert_allclose(a["occupancies"], b["occupancies"], atol=1e-7)


def _mpiexec():
    if os.environ.get("SQD_MPIEXEC"):
        return shlex.split(os.environ["SQD_MPIEXEC"])
    exe = shutil.which("mpiexec")
    return [exe] if exe else None


@pytest.mark.mpi
@pytest.mark.parametrize("ranks", [2, 3])
def test_mpi_step4_matches_serial(staged_dir, tmp_path, ranks):
    """rank 2: 배치 0·2 → rank 0, 배치 1 → rank 1(불균등). rank 3: 배치마다 1 rank."""
    pytest.importorskip("mpi4py")
    launcher = _mpiexec()
    if launcher is None:
        pytest.skip("mpiexec 없음(SQD_MPIEXEC로 실행 명령을 지정할 수 있습니다)")
    for name in ("step1_problem.npz", "step3_samples.npz", "step3_rng.json"):
        shutil.copy(staged_dir / name, tmp_path / name)
    _run([*launcher, "-n", str(ranks), sys.executable, "run_step.py", "4", "--workdir", str(tmp_path), "--mpi"])
    serial = json.loads((staged_dir / "step4_result.json").read_text())
    parallel = json.loads((tmp_path / "step4_result.json").read_text())
    assert parallel == serial                                  # 같은 스레드 수: 모든 값이 비트 단위로 같다
    meta = json.loads((tmp_path / "step4.json").read_text())
    assert meta["mpi_size"] == ranks
    s, p = np.load(staged_dir / "step4_state.npz"), np.load(tmp_path / "step4_state.npz")
    for key in ("amplitudes", "ci_strs_a", "ci_strs_b"):
        np.testing.assert_array_equal(p[key], s[key])
