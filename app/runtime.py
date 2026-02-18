import importlib
import sys
from types import ModuleType


def _resolve_main_module() -> ModuleType:
    """
    Resolve the active application module regardless of launch style:
    - `python main.py` -> module is `__main__`
    - `uvicorn main:app` -> module is `main`
    """
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "app"):
        return main_mod

    entry_mod = sys.modules.get("__main__")
    if entry_mod and hasattr(entry_mod, "app"):
        return entry_mod

    return importlib.import_module("main")


def get_main_attr(name: str):
    mod = _resolve_main_module()
    if not hasattr(mod, name):
        raise AttributeError(f"Application module is missing required attribute: {name}")
    return getattr(mod, name)
