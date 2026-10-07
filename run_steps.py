"""IBM 소규모 예제의 STEP 1~4를 순서대로 실행합니다.

프로젝트 루트에서: python run_steps.py
계산 본문: sqd_workflow/ibm_steps.py
공식 예제: https://quantum.cloud.ibm.com/docs/en/tutorials/sample-based-quantum-diagonalization#small-scale-simulator-example
이 파일은 SDK 연결 전의 로컬 워크플로우이며, Slurm/QPU 작업 제출은 하지 않습니다.
"""
import os

for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(variable, "1")

from pyscf import lib
from threadpoolctl import threadpool_limits
from sqd_workflow.ibm_steps import (
    step1_map,
    step2_optimize,
    step3_execute,
    step4_postprocess,
)


def main():
    lib.num_threads(1)
    with threadpool_limits(limits=1):
        print("[IBM STEP 1/4] Map classical inputs to a quantum problem", flush=True)
        mapped = step1_map()

        print("[IBM STEP 2/4] Optimize for quantum hardware execution", flush=True)
        isa_circuit = step2_optimize(mapped)

        print("[IBM STEP 3/4] Execute using Qiskit primitives", flush=True)
        executed = step3_execute(isa_circuit)

        print("[IBM STEP 4/4] Post-process and return result in desired classical format", flush=True)
        # STEP 1의 적분·분자 정보와 STEP 3의 샘플·난수 상태를 함께 사용합니다.
        result = step4_postprocess(mapped, executed)

    print(f"SQD 반복 횟수: {len(result.result_history)}")
    print(f"Alpha 궤도 점유수: {result.result.orbital_occupancies[0]}")
    print(f"Beta  궤도 점유수: {result.result.orbital_occupancies[1]}")
    return result


if __name__ == "__main__":
    main()
