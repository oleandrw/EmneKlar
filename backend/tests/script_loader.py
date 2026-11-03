"""Import the stand-alone scripts in ../scripts (setup.py, update.py, …) the way they import each other."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from emneklar.config import REPO_DIR

SCRIPTS_DIR = REPO_DIR / "scripts"


def load_script(name: str) -> ModuleType:
    """Load scripts/<name>.py as module ``name`` (setup.py and package_release.py do ``import update``)."""
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.append(str(SCRIPTS_DIR))  # lowest priority; lets the scripts find each other
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses and `import update` need the module to be registered
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module
