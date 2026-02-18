from pathlib import Path
from typing import Dict, Optional

PROMPT_DIR = Path("prompt")
PROMPT_CACHE: Dict[str, str] = {}


def load_prompt_text(relative_path: str, replacements: Optional[Dict[str, str]] = None) -> str:
    key = relative_path
    if key not in PROMPT_CACHE:
        path = PROMPT_DIR / relative_path
        with open(path, "r", encoding="utf-8") as f:
            PROMPT_CACHE[key] = f.read()
    content = PROMPT_CACHE[key]
    if replacements:
        for token, value in replacements.items():
            content = content.replace(token, value)
    return content
