# IBM SQD 워크플로우 실행 패키지

`run_steps.py`를 중심으로 IBM 소규모 시뮬레이터 예제의 STEP 1~4를 실행하는 독립 폴더입니다. 이 폴더 전체를 다른 위치에 복사해 사용할 수 있습니다.

**먼저 읽기:** [HTML 가이드](docs/guide.html) · [Markdown 가이드](docs/guide.md)

## 설치와 실행

Python 3.11과 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비하고 **이 폴더 안에서** 실행합니다. 최초 설치에는 인터넷이 필요합니다.

```bash
uv sync --locked --extra test
uv run --locked python run_steps.py
uv run --locked --extra test python -m pytest -q
```

uv를 사용하지 않는 경우:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install '.[test]'
python run_steps.py
python -m pytest -q
```

pip 경로는 직접 의존성 버전을 고정하지만 전이 의존성은 `uv.lock`과 다를 수 있습니다. 재현 비교에는 uv 경로를 권장합니다. 검증 대상은 macOS arm64 / Python 3.11이며 다른 OS·CPU의 수치와 설치 가능 여부는 별도로 확인해야 합니다.

## 구성

```text
sqd_workflow_bundle/
├── run_steps.py                 # 네 단계를 연결하는 실행 진입점
├── sqd_workflow/
│   ├── __init__.py
│   └── ibm_steps.py             # 계산 함수 4개와 입출력 dataclass
├── pyproject.toml              # 설치·테스트·문서 의존성
├── uv.lock                     # 전이 의존성까지 고정
├── docs/guide.md                # 가이드 원본
├── docs/guide.html              # 브라우저용 가이드
├── tools/build_guide.py         # Markdown → HTML 재생성
├── references/n2_small_scale/   # IBM 고정 원본·독립 실행기·라이선스
├── tests/                      # 원본과 단계별 결과 비교
├── validation/                 # 분리된 환경에서 실행한 검증 기록
├── COPY_MANIFEST.json           # 복사본의 출처와 SHA-256
└── NOTICE.md                   # 라이선스·수정 내역
```

## 기본 계산

N₂ / STO-6G / 활성 공간 8궤도·10전자 / **16큐비트** / LUCJ 4회 / 100,000 shots / 배치 3개 / `max_dim=50`입니다. 검증 환경의 총에너지는 약 **−108.59593164616311 Ha**, SQD 반복은 2회였습니다. 더 자세한 근거는 [검증 기록](validation/README.md)을 참고하세요.

## 제공 범위

SDK 연결 직전의 **단일 프로세스 Python 워크플로우**입니다. STEP 4 안에서 SQD 복구·대각화 반복을 수행합니다. Slurm 제출, 실제 QPU 제출, MPI/GPU 솔버, 노드 간 직렬화는 후속 구현 대상입니다. STEP 1에 FCI 기준값 계산이 있으므로 분자 크기를 바로 키우기 전에 해당 경로를 분리해야 합니다.

## 문서 갱신

```bash
uv sync --locked --extra test --extra docs
uv run --locked --extra docs python tools/build_guide.py
```

`docs/guide.md`를 편집한 후 재생성합니다. HTML에는 현재 `run_steps.py` 전체 코드도 자동 삽입됩니다. 외부 폰트·스크립트 없이 열리며 브라우저 인쇄로 PDF를 저장할 수 있습니다.
