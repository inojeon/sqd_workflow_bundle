import os

# Apply limits before numerical imports and propagate into subprocesses.
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

import subprocess
import sys
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def reference_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("reference") / "result"
    subprocess.run([sys.executable, "references/n2_small_scale/run_reference.py",
                    "--output", str(out)], check=True, timeout=120)
    return out

