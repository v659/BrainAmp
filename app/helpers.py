import re
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.constants import DEFAULT_ACCOUNT_SETTINGS


def is_ssl_or_network_auth_error(err: Exception) -> bool:
    msg = str(err).lower()
    ssl_markers = [
        "certificate_verify_failed",
        "self-signed certificate",
        "ssl:",
        "tls",
        "connection reset",
        "temporarily unavailable",
        "name resolution",
    ]
    return any(marker in msg for marker in ssl_markers)


def build_offline_auth_response(username: str, email: str, mode: str = "logged_in") -> Dict[str, Any]:
    token = f"offline-{uuid.uuid4()}"
    return {
        "status": mode,
        "user_id": "offline-user",
        "email": email or "offline@example.local",
        "display_name": username or "Offline User",
        "access_token": token,
        "refresh_token": token,
        "offline": True,
    }


def build_offline_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="offline-user",
        user_metadata={
            "account_settings": {
                **DEFAULT_ACCOUNT_SETTINGS,
                "grade_level": "General",
                "education_board": "General",
            }
        },
    )


def normalize_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", subject.strip()).title()


def get_account_settings_from_metadata(user_metadata: dict) -> dict:
    settings = user_metadata.get("account_settings") if isinstance(user_metadata, dict) else None
    if not isinstance(settings, dict):
        return DEFAULT_ACCOUNT_SETTINGS.copy()

    return {
        "web_search_enabled": bool(settings.get("web_search_enabled", DEFAULT_ACCOUNT_SETTINGS["web_search_enabled"])),
        "save_chat_history": bool(settings.get("save_chat_history", DEFAULT_ACCOUNT_SETTINGS["save_chat_history"])),
        "study_reminders_enabled": bool(
            settings.get("study_reminders_enabled", DEFAULT_ACCOUNT_SETTINGS["study_reminders_enabled"])
        ),
        "grade_level": str(settings.get("grade_level", DEFAULT_ACCOUNT_SETTINGS["grade_level"]) or "").strip(),
        "education_board": str(settings.get("education_board", DEFAULT_ACCOUNT_SETTINGS["education_board"]) or "").strip(),
    }


def get_learning_assets_from_metadata(user_metadata: dict) -> Dict[str, List[Dict[str, Any]]]:
    raw = user_metadata.get("learning_assets") if isinstance(user_metadata, dict) else None
    if not isinstance(raw, dict):
        return {"courses": [], "quizzes": []}

    courses = raw.get("courses", [])
    quizzes = raw.get("quizzes", [])
    return {
        "courses": courses if isinstance(courses, list) else [],
        "quizzes": quizzes if isinstance(quizzes, list) else [],
    }


def get_planner_state_from_metadata(user_metadata: dict) -> Dict[str, List[Dict[str, Any]]]:
    raw = user_metadata.get("planner_state") if isinstance(user_metadata, dict) else None
    if not isinstance(raw, dict):
        return {"busy_slots": [], "custom_tasks": [], "reminders": []}

    busy_slots = raw.get("busy_slots", [])
    custom_tasks = raw.get("custom_tasks", [])
    reminders = raw.get("reminders", [])
    return {
        "busy_slots": busy_slots if isinstance(busy_slots, list) else [],
        "custom_tasks": custom_tasks if isinstance(custom_tasks, list) else [],
        "reminders": reminders if isinstance(reminders, list) else [],
    }


def is_valid_time_hhmm(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not re.match(r"^\d{1,2}:\d{2}$", value.strip()):
        return False
    parts = value.strip().split(":")
    h = int(parts[0])
    m = int(parts[1])
    return 0 <= h <= 23 and 0 <= m <= 59


def normalize_module_lookup_text(value: str) -> str:
    text = re.sub(r"^[\"']+|[\"']+$", "", (value or "").strip(), flags=re.IGNORECASE)
    text = re.sub(r"^\s*the\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(course\s+module|module|course)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def try_parse_date(date_text: str) -> Optional[datetime]:
    cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", date_text.strip(), flags=re.IGNORECASE)
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_iso_date_or_none(date_text: str) -> Optional[date]:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except Exception:
        return None


def parse_date_range_from_message(message: str) -> Optional[tuple[datetime, datetime]]:
    match = re.search(r"from\s+(.+?)\s+to\s+(.+?)(?:[\.\!\?]|$)", message, flags=re.IGNORECASE)
    if not match:
        return None

    start_dt = try_parse_date(match.group(1))
    end_dt = try_parse_date(match.group(2))

    if not start_dt or not end_dt:
        return None
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_exclusive = end_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return start_dt, end_exclusive
