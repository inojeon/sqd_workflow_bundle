"""Modified execution adapter for pinned Apache-2.0 example; see README.md.

Only measurement/export instrumentation and deterministic backend/transpiler seeds
are added. Numerical code is executed from original.py, independently of our API.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
from importlib.metadata import version


def run(output):
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[key] = '1'
    import numpy as np
    from pyscf import lib
    from qiskit import qpy
    from qiskit.quantum_info import Statevector
    from threadpoolctl import threadpool_limits
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name('original.py')
    info = json.loads(source.with_name('source.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != info['sha256']:
        raise ValueError('Pinned reference source checksum mismatch')
    parts = re.split(r'^# CELL (\d+)\n', source.read_text(), flags=re.M)
    scope = {}
    lib.num_threads(1)
    started = time.perf_counter()
    with threadpool_limits(limits=1):
        for i in range(1, len(parts), 2):
            cell, code = int(parts[i]), parts[i+1]
            if cell == 4:
                code = '\n'.join(line for line in code.splitlines()
                                 if 'qiskit_ibm_runtime' not in line and 'matplotlib' not in line)
            if cell == 11:
                code = code.replace('coupling_map=coupling_map,', 'coupling_map=coupling_map, seed=12345,')
                code = code.replace('optimization_level=3,', 'optimization_level=3, seed_transpiler=12345,')
            if cell == 22:
                rng_state = copy.deepcopy(scope['rng'].bit_generator.state)
            exec(compile(code, f'{source.name}:cell{cell}', 'exec'), scope)
    def write(name, obj):
        (out/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
    system = dict(norb=int(scope['norb']), nelec=[int(scope['n_alpha']),int(scope['n_beta'])],
                  active_orbitals=list(scope['active_space']), bit_order='beta[n-1..0],alpha[n-1..0]')
    np.savez(out/'hamiltonian.npz', h1=scope['hcore'], h2=scope['eri'], offset=scope['nuclear_repulsion_energy'])
    np.savez(out/'samples.npz', shots=scope['bit_array'].to_bool_array())
    with (out/'circuit.qpy').open('wb') as f:
        qpy.dump(scope['isa_circuit'],f)
    # Express probabilities in classical/logical order, including layout permutation.
    circuit = scope['isa_circuit'].remove_final_measurements(inplace=False)
    physical = Statevector.from_instruction(circuit).probabilities()
    mapping = [-1] * scope['isa_circuit'].num_clbits
    for op in scope['isa_circuit'].data:
        if op.operation.name == 'measure':
            mapping[scope['isa_circuit'].find_bit(op.clbits[0]).index] = scope['isa_circuit'].find_bit(op.qubits[0]).index
    indices = np.arange(len(physical))
    logical = sum(((indices >> q) & 1) << c for c, q in enumerate(mapping))
    probabilities = np.zeros_like(physical)
    np.add.at(probabilities, logical, physical)
    np.savez(out/'probabilities.npz', probabilities=probabilities)
    history=[]
    previous=None
    for iteration, results in enumerate(scope['result_history'],1):
        best=min(results,key=lambda r:r.energy)
        occ=np.asarray(best.orbital_occupancies)
        converged=bool(previous is not None and abs(best.energy-previous[0])<scope['energy_tol']
                       and np.max(np.abs(occ-previous[1]))<scope['occupancies_tol'])
        history.append(dict(iteration=iteration,converged=converged,batches=[dict(
            energy_hartree=float(r.energy+scope['nuclear_repulsion_energy']),
            subspace_dimension=int(r.sci_state.amplitudes.size),
            occupancies=np.asarray(r.orbital_occupancies).tolist()) for r in results]))
        previous=(best.energy,occ)
    r=scope['result']
    write('system.json',system)
    write('rng.json',rng_state)
    write('history.json',history)
    write('result.json',dict(total_energy_hartree=float(scope['final_energy']),
          electronic_energy_hartree=float(r.energy),energy_offset_hartree=float(scope['nuclear_repulsion_energy']),
          occupancies=np.asarray(r.orbital_occupancies).tolist(),iterations=len(history),
          termination='converged' if history[-1]['converged'] else 'max_iterations',
          converged=history[-1]['converged'],fci_energy_hartree=float(scope['reference_energy'])))
    r.sci_state.save(out/'state.npz')
    write('reference.json',dict(source=info,elapsed_seconds=time.perf_counter()-started,
          adaptations=['remove QPU/plot imports','backend seed=12345','transpiler seed=12345','export intermediate data'],
          versions={name:version(name) for name in ('numpy','pyscf','qiskit','qiskit-addon-sqd','ffsim')}))
    return out


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    run(p.parse_args().output)
