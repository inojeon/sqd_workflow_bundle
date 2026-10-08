# 출처와 수정 내역

## IBM 코드 출처

- 공식 페이지: https://quantum.cloud.ibm.com/docs/en/tutorials/sample-based-quantum-diagonalization#small-scale-simulator-example
- 고정 notebook revision: `64fbdc210b4379f9079e3d8f8e2ee8877cbc3ba2`
- 상세 URL·셀 번호·SHA-256: `references/n2_small_scale/source.json`
- 원본 코드의 라이선스: `references/n2_small_scale/LICENSE` (Apache-2.0)

IBM 예제에서 계산 모듈로 옮기면서 네 함수와 반환 dataclass, 난수 상태 복원, 결정적 컴파일 시드를 추가했습니다. 2026-10-08에 `step4_postprocess`에 선택 인자 `wrap_solver`(solver 감싸기)와 `settings`(성능 측정용 크기 변경)를 추가했습니다(기본값은 원문 그대로). STEP별 실행(`run_step.py`, `sqd_workflow/stages.py`)과 MPI 배치 병렬(`sqd_workflow/mpi_solver.py`), Slurm 스크립트(`slurm/`)는 이 프로젝트에서 새로 작성했으며 IBM 원본의 일부가 아닙니다. 그림과 설명 본문은 복제하지 않았습니다. 라이선스 및 출처 파일을 함께 보존하세요. 외부 의존 패키지는 각 패키지의 라이선스를 따릅니다.
