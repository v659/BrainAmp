import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB
    MAX_FILES_PER_UPLOAD = 5
    ALLOWED_FILE_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}
    CHAT_HISTORY_LIMIT = 12
    DOCUMENT_CONTENT_LIMIT = 12000
    WEB_CONTEXT_LIMIT = 3000
    PASSWORD_MIN_LENGTH = 8
    OPENAI_MODEL = "gpt-4o-mini"


def is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


config = Config()
SUPABASE_OPTIONAL = is_truthy(os.getenv("SUPABASE_OPTIONAL", "true"))
OFFLINE_AUTH_FALLBACK = is_truthy(os.getenv("OFFLINE_AUTH_FALLBACK", "false"))
