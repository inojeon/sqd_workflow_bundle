# archive/ — 개발 과정에서 만든 부속 코드·문서·기록

핵심 두 모듈(`sqd_workflow/ibm_steps.py`, `sqd_workflow/emulator_steps.py`)을 만들고 검증하는 과정에서 나온 것들입니다. 핵심 코드를 읽는 데는 필요하지 않아 이 폴더로 옮겼습니다. **그대로 실행되도록 유지하지 않습니다.** 원래 위치(저장소 루트)에서 돌아가던 코드라 import 경로와 상대 경로가 그 기준으로 적혀 있습니다. 다시 쓰려면 아래 "원래 위치"로 되돌리고 `sqd_workflow/emulator_steps.py`가 `scaled.py`에서 가져오던 보조 함수(`h_chain`, `_pass_manager`, `_ucj_operator`, `to_emulator_qasm`, `convert_emulator_counts`)가 지금은 `emulator_steps.py` 안에 있다는 점만 감안하면 됩니다.

| 보관 항목 | 원래 위치 | 내용 |
| --- | --- | --- |
| `sqd_workflow/scaled.py` | `sqd_workflow/scaled.py` | 문제 크기 일반화(프리셋 16~36큐비트), ffsim 샘플러, 파일 기반 stage1~3. `emulator_steps.py`는 여기서 보조 함수 5개만 쓰다가 자체 포함으로 바꿨습니다. |
| `sqd_workflow/stages.py` | `sqd_workflow/stages.py` | STEP별 별도 프로세스 실행용 파일 계약(npz·qpy·json) |
| `run_step.py`, `run_scaled.py` | 루트 | 위 두 모듈의 실행기(STEP 하나씩, 36큐비트 프리셋) |
| `slurm/` | `slurm/` | `step.sbatch`·`submit_chain.sh`(STEP별 작업 체인), `scaled_step.sbatch`·`submit_scaled.sh`·`submit_step4.sh`(36큐비트 실행) |
| `tests/` | `tests/` | 원본 재현 비교, STEP 분리·MPI 동등성, 프리셋 검증 |
| `bench/`, `examples/` | 같은 이름 | STEP 4 단일 프로세스 대 MPI 성능 사다리, 샘플 분포 검사, 예제 작업 체인 |
| `validation/` | `validation/` | 분리된 환경과 클러스터에서 실행한 검증 로그·결과 |
| `docs/` | `docs/` | 가이드와 실험 정리 문서. 핵심 두 파일의 차이는 `docs/emulator_steps_변경점.md` |
| `tools/` | `tools/` | `docs/*.md` → HTML 변환기 |
| `references/n2_small_scale/` | `references/` | IBM 원본 코드 사본·독립 실행기·출처(`source.json`)·라이선스(Apache-2.0). `NOTICE.md`가 가리킵니다. |
| `COPY_MANIFEST.json` | 루트 | 원 프로젝트에서 복사해 올 때의 출처와 SHA-256 |
