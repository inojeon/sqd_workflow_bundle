#!/usr/bin/env bash
# STEP 1~4 공용 가상환경을 공유 경로에 만듭니다(최초 1회, uv.lock 이 바뀌면 다시). 로그인 노드에서 실행합니다.
#   slurm/setup_env.sh
# uv.lock 고정 버전 + mpi4py 4.1.2(사이트 MPI로 소스 빌드). Python 3.11 은 uv 가 WF_ROOT/python 에 설치합니다.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/site.env"
as() { if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "$(id -un)" ]; then "$@"; else (cd / && sudo -u "$RUN_USER" "$@"); fi; }

[ -x "$MPI_HOME/bin/mpicc" ] || { echo "오류: $MPI_HOME/bin/mpicc 없음. 해결: site.env 의 MPI_HOME 확인"; exit 1; }
as mkdir -p "$WF_ROOT/bin" "$WF_ROOT/env-src" "$RUNS"
# 원본 폴더가 RUN_USER 에게 안 보일 수 있어(예: 700 홈) 현재 계정이 읽어 tar 로 넘깁니다.
tar -C "$HERE/.." -cf - pyproject.toml uv.lock | as tar -C "$WF_ROOT/env-src" -xf -

if ! as test -x "$UV"; then
  echo "uv $UV_VERSION 설치 → $WF_ROOT/bin"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
    | as env UV_INSTALL_DIR="$WF_ROOT/bin" UV_NO_MODIFY_PATH=1 sh
fi

as env -C "$WF_ROOT/env-src" \
  UV_PYTHON_INSTALL_DIR="$WF_ROOT/python" UV_CACHE_DIR="$WF_ROOT/uv-cache" UV_PROJECT_ENVIRONMENT="$VENV" \
  PATH="$MPI_HOME/bin:/usr/bin:/bin" MPICC="$MPI_HOME/bin/mpicc" MPICH_CC=gcc MPICH_CXX=g++ \
  "$UV" sync --locked --extra test --extra mpi --no-install-project --no-binary-package mpi4py \
  --managed-python --python 3.11

as env LD_LIBRARY_PATH="$MPI_HOME/lib" "$VENV/bin/python" - <<'PY'
import sys, mpi4py
from mpi4py import MPI
print("python", sys.version.split()[0], "| mpi4py", mpi4py.__version__, "|", MPI.Get_library_version().splitlines()[0])
PY
echo "환경 준비 완료: $VENV"
