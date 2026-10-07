"""IBM 단계 분리 후에도 독립 원본과 계산이 일치해야 합니다."""
import json
import numpy as np
import pytest

@pytest.mark.reference
def test_ibm_steps_match_reference(reference_dir):
    from sqd_workflow.ibm_steps import step1_map, step2_optimize, step3_execute, step4_postprocess
    from threadpoolctl import threadpool_limits
    from pyscf import lib
    lib.num_threads(1)
    with threadpool_limits(limits=1):
        mapped = step1_map()
        # STEP 1은 추상 회로를 반환하고 STEP 2에서만 transpile합니다.
        before_operations = dict(mapped.circuit.count_ops())
        isa_circuit = step2_optimize(mapped)
        assert dict(mapped.circuit.count_ops()) == before_operations
        assert "ucj_balanced_jw" in before_operations
        assert "ucj_balanced_jw" not in isa_circuit.count_ops()
        assert isa_circuit.num_clbits == 16
        execution = step3_execute(isa_circuit)
        saved_rng = json.loads(json.dumps(execution.rng_state))
        actual = step4_postprocess(mapped, execution)
    assert execution.rng_state == saved_rng
    expected = json.loads((reference_dir/'result.json').read_text())
    np.testing.assert_allclose(mapped.hcore, np.load(reference_dir/'hamiltonian.npz')['h1'],atol=1e-10)
    np.testing.assert_allclose(mapped.eri, np.load(reference_dir/'hamiltonian.npz')['h2'],atol=1e-10)
    np.testing.assert_array_equal(execution.pub_result.data.meas.to_bool_array(),np.load(reference_dir/'samples.npz')['shots'])
    assert execution.rng_state == json.loads((reference_dir/'rng.json').read_text())
    assert abs(actual.final_energy-expected['total_energy_hartree'])<1e-8
    assert abs(mapped.reference_energy-expected['fci_energy_hartree'])<1e-8
    np.testing.assert_allclose(actual.result.orbital_occupancies,expected['occupancies'],atol=1e-7)
    expected_history=json.loads((reference_dir/'history.json').read_text())
    for actual_batches, expected_iteration in zip(actual.result_history,expected_history,strict=True):
        for a,b in zip(actual_batches,expected_iteration['batches'],strict=True):
            assert a.sci_state.amplitudes.size == b['subspace_dimension']
            assert abs(a.energy+mapped.nuclear_repulsion_energy-b['energy_hartree'])<1e-8
            np.testing.assert_allclose(a.orbital_occupancies,b['occupancies'],atol=1e-7)
