# 공식 N₂ 기준 실행

Qiskit/documentation의 소규모 예제 코드 셀을 추출했습니다. 출처와 SHA-256은 source.json에, 코드의 Apache-2.0 라이선스는 LICENSE에 기록했습니다. 문서 본문 및 그림은 복제하지 않습니다.

original.py는 사용하지 않는 QPU import를 포함하는 원문 보존본입니다. run_reference.py는 실제 QPU/plot import를 제외하고 backend/transpiler seed=12345를 명시하며 계측과 결과 저장을 추가합니다. 계산 함수는 프로젝트 모듈을 호출하지 않습니다.

실행: `python references/n2_small_scale/run_reference.py --output runs/reference-new`.
과학적 설정 변경 옵션은 제공하지 않습니다. numpy Generator를 sampling/SQD에 공유하며 SQD 진입 직전 상태를 저장합니다. probabilities.npz는 classical/logical 비트 순서로 정규화된 확률입니다. 기존 출력 경로는 재사용하지 않습니다.
