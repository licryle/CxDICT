"""Shared test fixtures: make the packaged CLI shims runnable as subprocesses.

The suite imports `cxdict` via pytest's `pythonpath` setting, but
subprocess runs of `scripts/*.py` inherit only the OS environment — so the
package root is exported here for every child process.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
