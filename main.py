import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import tempfile
import uuid
import re
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request, Header, HTTPException, Depends, UploadFile, File, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, EmailStr, Field, validator
from supabase import create_client
from dotenv import load_dotenv
from openai import OpenAI
import uvicorn

from src.convert_to_raw_text import extract_text_from_file
from src.scrape_web import browse_allowed_sources

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Configuration
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


config = Config()
DEFAULT_SUBJECT_PRESETS = [
    "Biology",
    "History",
    "Geography",
    "English",
    "Math",
    "Computer Science",
    "Languages",
    "Physics",
    "Chemistry",
    "Economics",
]
DEFAULT_ACCOUNT_SETTINGS = {
    "web_search_enabled": True,
    "save_chat_history": True,
    "study_reminders_enabled": False,
    "grade_level": "",
    "education_board": "",
}

# Validate configuration
if not all([config.SUPABASE_URL, config.SUPABASE_ANON_KEY, config.OPENAI_API_KEY]):
    raise RuntimeError("Missing required environment variables")

# Initialize clients
try:
    supabase = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize clients: {e}")
    raise

# Initialize FastAPI
app = FastAPI(title="Brain Amp API", version="1.0.0")

# Add security middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
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


# Pydantic Models with Validation
class LoginData(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Username must be alphanumeric')
        return v


class SignupData(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Username must be alphanumeric')
        return v


class ChatMessage(BaseModel):
    topic_id: Optional[str] = Field(None, max_length=100)
    chat_id: Optional[str] = Field(None, max_length=100)
    subject: Optional[str] = Field(None, max_length=60)
    chat_mode: Optional[str] = Field(None, max_length=20)
    message: str = Field(..., min_length=1, max_length=2000)


class UpdateProfileData(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)


class AccountSettingsData(BaseModel):
    web_search_enabled: bool = True
    save_chat_history: bool = True
    study_reminders_enabled: bool = False
    grade_level: Optional[str] = Field("", max_length=30)
    education_board: Optional[str] = Field("", max_length=50)


class UpdatePasswordData(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class LearningAssetData(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    content: str = Field(..., min_length=10, max_length=12000)
    chat_id: Optional[str] = Field(None, max_length=100)


class AddSourceData(BaseModel):
    domain: str = Field(..., min_length=3, max_length=100)

    @validator('domain')
    def validate_domain(cls, v):
        v = v.strip().lower()
        if not '.' in v or ' ' in v:
            raise ValueError('Invalid domain format')
        return v


class SubjectPresetData(BaseModel):
    subject: str = Field(..., min_length=2, max_length=60)


class SubjectPresetOrderData(BaseModel):
    preset_ids: List[str] = Field(..., min_items=1)


class RefreshTokenData(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class UpdateDocumentSubjectData(BaseModel):
    subject: str = Field(..., min_length=2, max_length=60)


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


def try_parse_date(date_text: str) -> Optional[datetime]:
    cleaned = re.sub(r'(\d)(st|nd|rd|th)', r'\1', date_text.strip(), flags=re.IGNORECASE)
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_date_range_from_message(message: str) -> Optional[tuple[datetime, datetime]]:
    match = re.search(r'from\s+(.+?)\s+to\s+(.+?)(?:[\.\!\?]|$)', message, flags=re.IGNORECASE)
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


def infer_date_range_from_message(message: str, local_date_iso: str) -> Optional[tuple[datetime, datetime]]:
    """Use the model to infer date windows like yesterday/last week/tomorrow from user text."""
    try:
        system_prompt = load_prompt_text("system/date_range_inference_system.txt")
        user_prompt = load_prompt_text(
            "system/date_range_inference_user.txt",
            {
                "{LOCAL_DATE_ISO}": local_date_iso,
                "{MESSAGE}": message
            }
        )
        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            max_tokens=60,
            temperature=0
        )
        parsed = json.loads((response.choices[0].message.content or "").strip())
        start_text = parsed.get("start")
        end_text = parsed.get("end")
        if not start_text or not end_text:
            return None

        start_dt = try_parse_date(start_text)
        end_dt = try_parse_date(end_text)
        if not start_dt or not end_dt:
            return None
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt

        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_exclusive = end_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return start_dt, end_exclusive
    except Exception as e:
        logger.warning(f"Date range inference failed: {e}")
        return None


def get_subject_presets_for_user(user_id: str) -> List[str]:
    try:
        result = supabase.table("subject_presets").select("subject").eq("user_id", user_id).order("position",
                                                                                                    desc=False).execute()
        subjects = [normalize_subject(row["subject"]) for row in (result.data or []) if row.get("subject")]
        if subjects:
            return subjects
    except Exception as e:
        logger.warning(f"Failed to load subject presets for user {user_id}: {e}")
    return DEFAULT_SUBJECT_PRESETS


def ensure_subject_presets_seeded(user_id: str) -> List[dict]:
    try:
        existing = supabase.table("subject_presets").select("id, subject, position").eq("user_id", user_id).order(
            "position", desc=False).execute()
    except Exception:
        # Backward compatibility if `position` column is not present yet.
        existing = supabase.table("subject_presets").select("id, subject").eq("user_id", user_id).execute()
    if existing.data:
        normalized = []
        for idx, row in enumerate(existing.data):
            normalized.append({
                "id": row.get("id"),
                "subject": row.get("subject"),
                "position": row.get("position", idx)
            })
        return normalized

    rows = [
        {"user_id": user_id, "subject": subject, "position": idx}
        for idx, subject in enumerate(DEFAULT_SUBJECT_PRESETS)
    ]
    try:
        supabase.table("subject_presets").insert(rows).execute()
        seeded = supabase.table("subject_presets").select("id, subject, position").eq("user_id", user_id).order(
            "position", desc=False).execute()
        return seeded.data or []
    except Exception:
        # Backward compatibility if table does not support `position`.
        fallback_rows = [{"user_id": user_id, "subject": subject} for subject in DEFAULT_SUBJECT_PRESETS]
        supabase.table("subject_presets").insert(fallback_rows).execute()
        seeded = supabase.table("subject_presets").select("id, subject").eq("user_id", user_id).execute()
        return [
            {"id": row.get("id"), "subject": row.get("subject"), "position": idx}
            for idx, row in enumerate(seeded.data or [])
        ]


def classify_subject(topic: str, content: str, preset_subjects: List[str]) -> str:
    if not preset_subjects:
        return "Other"

    options = [normalize_subject(s) for s in preset_subjects]
    option_text = ", ".join(options)
    sample = content[:1200]

    prompt = load_prompt_text(
        "system/subject_classifier_user.txt",
        {
            "{SUBJECT_OPTIONS}": option_text,
            "{TOPIC}": topic,
            "{TEXT_SAMPLE}": sample,
        }
    )

    try:
        system_prompt = load_prompt_text("system/subject_classifier_system.txt")
        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0
        )
        parsed = json.loads(response.choices[0].message.content)
        picked = normalize_subject(parsed.get("subject", ""))
        if picked in options:
            return picked
    except Exception as e:
        logger.warning(f"Subject classification failed, using fallback: {e}")

    lower_blob = f"{topic}\n{content[:2000]}".lower()
    keyword_map = {
        "Biology": ["cell", "dna", "organism", "evolution", "photosynthesis", "genetics"],
        "History": ["empire", "war", "revolution", "century", "historical", "dynasty"],
        "Geography": ["climate", "map", "region", "country", "river", "population"],
        "English": ["poem", "novel", "grammar", "literature", "essay", "prose"],
        "Math": ["equation", "algebra", "calculus", "geometry", "integral", "derivative"],
        "Computer Science": ["algorithm", "code", "program", "database", "data structure", "computer"],
        "Languages": ["vocabulary", "verb", "translation", "pronunciation", "language", "tense"],
        "Physics": ["force", "energy", "velocity", "motion", "quantum", "electric"],
        "Chemistry": ["molecule", "atom", "reaction", "compound", "chemical", "bond"],
        "Economics": ["inflation", "market", "supply", "demand", "gdp", "economy"]
    }

    for subject in options:
        for keyword in keyword_map.get(subject, []):
            if keyword in lower_blob:
                return subject
    return options[-1] if options else "Other"


def detect_subject_from_message(message: str, preset_subjects: List[str]) -> Optional[str]:
    if not message or not preset_subjects:
        return None

    message_lower = message.lower()
    normalized = [normalize_subject(s) for s in preset_subjects]

    # Direct subject phrase match.
    for subject in normalized:
        if subject.lower() in message_lower:
            return subject

    alias_map = {
        "Math": ["math", "mathematics", "algebra", "calculus", "geometry", "trigonometry"],
        "Computer Science": ["cs", "computer science", "coding", "programming", "algorithm"],
        "Languages": ["language", "spanish", "french", "german", "hindi", "vocabulary", "grammar"],
        "Biology": ["biology", "bio", "cell", "genetics"],
        "History": ["history", "historical", "civilization", "empire"],
        "Geography": ["geography", "map", "climate", "region"],
        "English": ["english", "literature", "essay", "poem"],
        "Physics": ["physics", "force", "motion", "energy"],
        "Chemistry": ["chemistry", "chemical", "reaction", "atom"],
        "Economics": ["economics", "market", "inflation", "demand", "supply"]
    }

    for subject in normalized:
        for alias in alias_map.get(subject, []):
            if alias in message_lower:
                return subject
    return None


def detect_subjects_from_message(message: str, preset_subjects: List[str]) -> List[str]:
    if not message or not preset_subjects:
        return []

    message_lower = message.lower()
    normalized = [normalize_subject(s) for s in preset_subjects]
    found = []

    for subject in normalized:
        if subject.lower() in message_lower and subject not in found:
            found.append(subject)

    alias_map = {
        "Math": ["math", "mathematics", "algebra", "calculus", "geometry", "trigonometry"],
        "Computer Science": ["cs", "computer science", "computer", "coding", "programming", "algorithm"],
        "Languages": ["language", "spanish", "french", "german", "hindi", "vocabulary", "grammar"],
        "Biology": ["biology", "bio", "cell", "genetics"],
        "History": ["history", "historical", "civilization", "empire"],
        "Geography": ["geography", "map", "climate", "region"],
        "English": ["english", "literature", "essay", "poem"],
        "Physics": ["physics", "force", "motion", "energy"],
        "Chemistry": ["chemistry", "chemical", "reaction", "atom"],
        "Economics": ["economics", "market", "inflation", "demand", "supply"]
    }

    for subject in normalized:
        if subject in found:
            continue
        for alias in alias_map.get(subject, []):
            if re.search(rf"\b{re.escape(alias)}\b", message_lower):
                found.append(subject)
                break

    return found


def infer_subject_date_requests(message: str, preset_subjects: List[str], local_date_iso: str) -> List[dict]:
    """Infer one or more subject/date windows from message using model."""
    if not message:
        return []
    options = [normalize_subject(s) for s in preset_subjects] if preset_subjects else []

    try:
        system_prompt = load_prompt_text("system/request_inference_system.txt")
        user_prompt = load_prompt_text(
            "system/request_inference_user.txt",
            {
                "{ALLOWED_SUBJECTS}": ", ".join(options) if options else "None",
                "{LOCAL_DATE_ISO}": local_date_iso,
                "{MESSAGE}": message,
            }
        )
        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            max_tokens=220,
            temperature=0
        )
        parsed = json.loads((response.choices[0].message.content or "").strip())
        requests = parsed.get("requests", [])
        if not isinstance(requests, list):
            return []

        normalized_requests = []
        for req in requests:
            if not isinstance(req, dict):
                continue

            subject = req.get("subject")
            subject_norm = normalize_subject(subject) if subject else None
            if subject_norm and options and subject_norm not in options:
                continue

            start_text = req.get("start")
            end_text = req.get("end")
            date_range = None
            if start_text and end_text:
                start_dt = try_parse_date(start_text)
                end_dt = try_parse_date(end_text)
                if start_dt and end_dt:
                    if end_dt < start_dt:
                        start_dt, end_dt = end_dt, start_dt
                    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_exclusive = end_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    date_range = (start_dt, end_exclusive)

            normalized_requests.append({
                "subject": subject_norm,
                "date_range": date_range
            })
        return normalized_requests
    except Exception as e:
        logger.warning(f"Subject/date request inference failed: {e}")
        return []


def build_subject_context(user_id: str, subject: str) -> str:
    try:
        docs = supabase.table("documents").select("topic, content, created_at, subject").eq("user_id", user_id).eq(
            "subject", subject).order("created_at", desc=False).execute()
        rows = docs.data or []
    except Exception:
        # Backward compatibility when subject column is missing.
        rows = []

    if not rows:
        return ""

    chunks = []
    for row in rows:
        created_date = (row.get("created_at") or "")[:10] or "Unknown"
        chunks.append(
            f"--- Note Date: {created_date} | Subject: {subject} | Topic: {row.get('topic', 'Untitled')} ---\n{row.get('content', '')}"
        )
    return "\n\n".join(chunks)


def build_filtered_context(
        user_id: str,
        subject: Optional[str] = None,
        date_range: Optional[tuple[datetime, datetime]] = None
) -> str:
    try:
        query = supabase.table("documents").select("topic, content, created_at, subject").eq("user_id", user_id)
        if subject:
            query = query.eq("subject", subject)
        if date_range:
            start_dt, end_exclusive = date_range
            query = query.gte("created_at", start_dt.isoformat()).lt("created_at", end_exclusive.isoformat())
        docs = query.order("created_at", desc=False).execute()
        rows = docs.data or []
    except Exception:
        # Backward compatibility: fallback to basic fields and in-memory filtering.
        docs = supabase.table("documents").select("topic, content, created_at").eq("user_id", user_id).execute()
        rows = docs.data or []
        if date_range:
            start_dt, end_exclusive = date_range
            filtered = []
            for row in rows:
                created_raw = row.get("created_at")
                if not created_raw:
                    continue
                created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                if start_dt <= created_dt < end_exclusive:
                    filtered.append(row)
            rows = filtered

    if not rows:
        return ""

    chunks = []
    for row in rows:
        created_date = (row.get("created_at") or "")[:10] or "Unknown"
        row_subject = row.get("subject") or (subject if subject else "Uncategorized")
        chunks.append(
            f"--- Note Date: {created_date} | Subject: {row_subject} | Topic: {row.get('topic', 'Untitled')} ---\n{row.get('content', '')}"
        )
    return "\n\n".join(chunks)


def generate_chat_title_from_message(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    if not cleaned:
        return "New chat"

    try:
        system_prompt = load_prompt_text("system/chat_title_system.txt")
        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": cleaned}
            ],
            max_tokens=24,
            temperature=0.2
        )
        title = (response.choices[0].message.content or "").strip().strip('"').strip("'")
        title = re.sub(r"\s+", " ", title)
        if title:
            return title[:100] if len(title) <= 100 else title[:97] + "..."
    except Exception as e:
        logger.warning(f"Chat title generation fallback used: {e}")

    return cleaned[:100] if len(cleaned) <= 100 else cleaned[:97] + "..."


def get_terminal_datetime_context() -> tuple[str, str]:
    """Fetch local date/time from terminal as authoritative runtime context."""
    try:
        iso_now = subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
        long_now = subprocess.check_output(["date", "+%A, %B %d, %Y"], text=True).strip()
        return iso_now, long_now
    except Exception as e:
        logger.warning(f"Terminal date fetch failed, using Python datetime fallback: {e}")
        now = datetime.now()
        return now.strftime("%Y-%m-%d"), now.strftime("%A, %B %d, %Y")


# Dependency for authentication
async def get_current_user(authorization: str = Header(None)):
    """Verify JWT token and return current user"""
    if not authorization:
        logger.warning("Missing authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token"
        )

    try:
        token = authorization.replace("Bearer ", "")
        user = supabase.auth.get_user(token).user
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return user
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


# File validation helper
def validate_file(file: UploadFile) -> None:
    """Validate uploaded file"""
    # Check file extension
    file_ext = file.filename.split('.')[-1].lower()
    if file_ext not in config.ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type .{file_ext} not allowed. Allowed types: {', '.join(config.ALLOWED_FILE_EXTENSIONS)}"
        )

    # Check filename
    if len(file.filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename too long"
        )


# HTML Routes
@app.get("/", response_class=HTMLResponse)
async def serve_starter(request: Request):
    return templates.TemplateResponse("starter.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/signup", response_class=HTMLResponse)
async def serve_signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def serve_settings(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/upload", response_class=HTMLResponse)
async def serve_upload(request: Request):
    return templates.TemplateResponse("upload_docs.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def serve_chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/topics", response_class=HTMLResponse)
async def serve_topics(request: Request):
    return templates.TemplateResponse("topics.html", {"request": request})


@app.get("/sources", response_class=HTMLResponse)
async def serve_sources(request: Request):
    return templates.TemplateResponse("add_sources.html", {"request": request})


# API Routes
@app.post("/api/login")
async def login(data: LoginData):
    """User login endpoint"""
    try:
        result = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })

        if result.user:
            logger.info(f"User logged in: {result.user.id}")
            return {
                "status": "logged_in",
                "user_id": result.user.id,
                "email": result.user.email,
                "display_name": result.user.user_metadata.get("display_name", data.username),
                "access_token": result.session.access_token,
                "refresh_token": result.session.refresh_token
            }

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"}
        )
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"}
        )


@app.post("/api/signup")
async def signup(data: SignupData):
    """User signup endpoint"""
    try:
        result = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "data": {"display_name": data.username}
            }
        })

        if result.user:
            logger.info(f"New user signed up: {result.user.id}")
            return {
                "status": "signed_up",
                "user_id": result.user.id,
                "email": result.user.email,
                "display_name": result.user.user_metadata.get("display_name", data.username),
                "access_token": result.session.access_token,
                "refresh_token": result.session.refresh_token
            }

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Signup failed"}
        )
    except Exception as e:
        logger.error(f"Signup error: {e}")
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Email already registered"}
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Signup failed. Please try again."}
        )


@app.post("/api/update-profile")
async def update_profile(
        data: UpdateProfileData,
        current_user=Depends(get_current_user)
):
    """Update user profile"""
    try:
        result = supabase.auth.update_user({
            "data": {"display_name": data.display_name}
        })

        if result and result.user:
            logger.info(f"Profile updated for user: {current_user.id}")
            return {"success": True, "display_name": data.display_name}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update profile"}
        )
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update profile. Please try again."}
        )


@app.post("/api/account-settings")
async def update_account_settings(
        data: AccountSettingsData,
        current_user=Depends(get_current_user)
):
    """Update persisted account settings in user metadata"""
    try:
        user_metadata = current_user.user_metadata or {}
        merged_metadata = {
            **user_metadata,
            "account_settings": {
                "web_search_enabled": data.web_search_enabled,
                "save_chat_history": data.save_chat_history,
                "study_reminders_enabled": data.study_reminders_enabled,
                "grade_level": (data.grade_level or "").strip(),
                "education_board": (data.education_board or "").strip(),
            }
        }

        result = supabase.auth.update_user({"data": merged_metadata})
        if result and result.user:
            logger.info(f"Account settings updated for user: {current_user.id}")
            return {"success": True, "account_settings": merged_metadata["account_settings"]}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update account settings"}
        )
    except Exception as e:
        logger.error(f"Account settings update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update account settings. Please try again."}
        )


@app.get("/api/learning-assets")
async def list_learning_assets(current_user=Depends(get_current_user)):
    """Get saved courses and quizzes for the current user"""
    user_metadata = current_user.user_metadata or {}
    assets = get_learning_assets_from_metadata(user_metadata)
    return assets


@app.post("/api/learning-assets/course")
async def save_course_asset(
        data: LearningAssetData,
        current_user=Depends(get_current_user)
):
    """Save a generated course to user metadata"""
    try:
        user_metadata = current_user.user_metadata or {}
        assets = get_learning_assets_from_metadata(user_metadata)
        new_item = {
            "id": str(uuid.uuid4()),
            "title": data.title.strip(),
            "content": data.content.strip(),
            "chat_id": data.chat_id,
            "created_at": datetime.now().isoformat()
        }
        assets["courses"] = [new_item] + assets["courses"][:24]

        merged_metadata = {**user_metadata, "learning_assets": assets}
        result = supabase.auth.update_user({"data": merged_metadata})
        if result and result.user:
            return {"success": True, "course": new_item}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to save course"}
        )
    except Exception as e:
        logger.error(f"Save course asset error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to save course. Please try again."}
        )


@app.post("/api/learning-assets/quiz")
async def save_quiz_asset(
        data: LearningAssetData,
        current_user=Depends(get_current_user)
):
    """Save a generated quiz to user metadata"""
    try:
        user_metadata = current_user.user_metadata or {}
        assets = get_learning_assets_from_metadata(user_metadata)
        new_item = {
            "id": str(uuid.uuid4()),
            "title": data.title.strip(),
            "content": data.content.strip(),
            "chat_id": data.chat_id,
            "created_at": datetime.now().isoformat()
        }
        assets["quizzes"] = [new_item] + assets["quizzes"][:24]

        merged_metadata = {**user_metadata, "learning_assets": assets}
        result = supabase.auth.update_user({"data": merged_metadata})
        if result and result.user:
            return {"success": True, "quiz": new_item}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to save quiz"}
        )
    except Exception as e:
        logger.error(f"Save quiz asset error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to save quiz. Please try again."}
        )


@app.delete("/api/learning-assets/course/{asset_id}")
async def delete_course_asset(asset_id: str, current_user=Depends(get_current_user)):
    """Delete one saved course"""
    try:
        user_metadata = current_user.user_metadata or {}
        assets = get_learning_assets_from_metadata(user_metadata)
        courses = assets["courses"]
        filtered = [item for item in courses if str(item.get("id")) != asset_id]
        if len(filtered) == len(courses):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        assets["courses"] = filtered
        merged_metadata = {**user_metadata, "learning_assets": assets}
        supabase.auth.update_user({"data": merged_metadata})
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete course asset error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to delete course")


@app.delete("/api/learning-assets/quiz/{asset_id}")
async def delete_quiz_asset(asset_id: str, current_user=Depends(get_current_user)):
    """Delete one saved quiz"""
    try:
        user_metadata = current_user.user_metadata or {}
        assets = get_learning_assets_from_metadata(user_metadata)
        quizzes = assets["quizzes"]
        filtered = [item for item in quizzes if str(item.get("id")) != asset_id]
        if len(filtered) == len(quizzes):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

        assets["quizzes"] = filtered
        merged_metadata = {**user_metadata, "learning_assets": assets}
        supabase.auth.update_user({"data": merged_metadata})
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete quiz asset error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to delete quiz")


@app.post("/api/change-password")
async def change_password(
        data: UpdatePasswordData,
        current_user=Depends(get_current_user)
):
    """Change account password for authenticated user"""
    try:
        result = supabase.auth.update_user({"password": data.new_password})
        if result and result.user:
            logger.info(f"Password updated for user: {current_user.id}")
            return {"success": True}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update password"}
        )
    except Exception as e:
        logger.error(f"Password update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update password. Please try again."}
        )


@app.post("/api/refresh")
async def refresh_access_token(data: RefreshTokenData):
    """Refresh access token using Supabase refresh token."""
    try:
        refreshed = supabase.auth.refresh_session(data.refresh_token)
        session = refreshed.session
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to refresh session"
            )
        return {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@app.get("/api/me")
async def get_me(current_user=Depends(get_current_user)):
    """Get current user information"""
    user_metadata = current_user.user_metadata or {}
    display_name = user_metadata.get("display_name", "User")
    if not display_name or display_name == "User":
        display_name = current_user.email.split('@')[0]
    account_settings = get_account_settings_from_metadata(user_metadata)

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "display_name": display_name,
        "account_settings": account_settings
    }


@app.post("/api/upload")
async def upload_docs(
        files: List[UploadFile] = File(...),
        current_user=Depends(get_current_user)
):
    """Upload and process documents"""
    # Validate number of files
    if len(files) > config.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {config.MAX_FILES_PER_UPLOAD} files allowed per upload"
        )

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded"
        )

    combined_text = ""
    total_size = 0

    try:
        for file in files:
            # Validate file
            validate_file(file)

            # Read file content
            content = await file.read()
            file_size = len(content)
            total_size += file_size

            # Check individual file size
            if file_size > config.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File {file.filename} exceeds maximum size of {config.MAX_FILE_SIZE / (1024 * 1024)}MB"
                )

            # Check total size
            if total_size > config.MAX_FILE_SIZE * 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Total upload size exceeds maximum allowed"
                )

            # Process file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as temp_file:
                temp_path = temp_file.name
                temp_file.write(content)

            try:
                file_extension = file.filename.split('.')[-1].lower()
                raw_text = extract_text_from_file(temp_path, file_extension)

                if not raw_text or len(raw_text.strip()) < 10:
                    logger.warning(f"No text extracted from {file.filename}")
                    continue

                combined_text += f"\n\n--- Document: {file.filename} ---\n\n"
                combined_text += raw_text
            finally:
                os.unlink(temp_path)

        if not combined_text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No text could be extracted from uploaded files"
            )

        # Extract topic using AI
        prompt_template = load_prompt_text("topic_extraction_prompt.md")

        formatted_prompt = prompt_template.replace("{TEXT}", combined_text[:5000])  # Limit context

        try:
            topic_extraction_system = load_prompt_text("system/topic_extraction_system.txt")
            response = openai_client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": topic_extraction_system},
                    {"role": "user", "content": formatted_prompt}
                ],
                max_tokens=100,
                temperature=0.3
            )

            topic_output = response.choices[0].message.content.strip()
            topic = topic_output.replace("Topic:", "").strip()

            if not topic:
                topic = "Untitled Document"
        except Exception as e:
            logger.error(f"Topic extraction error: {e}")
            topic = "Untitled Document"

        # Classify subject from user presets
        preset_subjects = get_subject_presets_for_user(current_user.id)
        subject = classify_subject(topic=topic, content=combined_text, preset_subjects=preset_subjects)

        # Save to database
        try:
            result = supabase.table("documents").insert({
                "user_id": current_user.id,
                "content": combined_text,
                "topic": topic,
                "subject": subject,
                "file_count": len(files),
                "file_names": [f.filename for f in files]
            }).execute()

            logger.info(f"Document uploaded by user {current_user.id}: {topic}")

            return {
                "success": True,
                "topic": topic,
                "subject": subject,
                "message": f"Successfully uploaded {len(files)} file(s)"
            }
        except Exception as db_error:
            logger.error(f"Database error during upload: {db_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save document"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed. Please try again."
        )


@app.post("/api/chat/send")
async def send_chat(
        chat_data: ChatMessage,
        current_user=Depends(get_current_user)
):
    """Send chat message and get AI response"""
    try:
        user_metadata = current_user.user_metadata or {}
        account_settings = get_account_settings_from_metadata(user_metadata)
        chat_mode = (chat_data.chat_mode or "fundamentals").strip().lower()
        if chat_mode not in {"fundamentals", "course", "quiz"}:
            chat_mode = "fundamentals"
        if chat_mode == "course":
            grade_level = (account_settings.get("grade_level") or "").strip()
            education_board = (account_settings.get("education_board") or "").strip()
            if not grade_level or not education_board:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please set your Grade and Board in Settings before using course mode."
                )

        # Load document context from a selected topic, selected/derived subject, or requested date range.
        local_date_iso, local_date_long = get_terminal_datetime_context()
        document_content = ""
        context_notice = ""
        selected_subject = normalize_subject(chat_data.subject) if chat_data.subject else None
        if chat_data.topic_id:
            doc = supabase.table("documents").select("content").eq("id", chat_data.topic_id).eq("user_id",
                                                                                                current_user.id).execute()
            if doc.data:
                document_content = doc.data[0]["content"]
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found"
                )
        else:
            explicit_date_range = parse_date_range_from_message(chat_data.message)
            preset_subjects = get_subject_presets_for_user(current_user.id)
            request_specs = []

            if selected_subject:
                inferred_date_range = infer_date_range_from_message(chat_data.message, local_date_iso)
                request_specs.append({
                    "subject": selected_subject,
                    "date_range": explicit_date_range or inferred_date_range
                })
            else:
                inferred_requests = infer_subject_date_requests(
                    message=chat_data.message,
                    preset_subjects=preset_subjects,
                    local_date_iso=local_date_iso
                )
                for req in inferred_requests:
                    request_specs.append(req)

                if not request_specs:
                    inferred_date_range = infer_date_range_from_message(chat_data.message, local_date_iso)
                    inferred_subjects = detect_subjects_from_message(chat_data.message, preset_subjects)
                    if inferred_subjects:
                        for subject in inferred_subjects:
                            request_specs.append({
                                "subject": subject,
                                "date_range": explicit_date_range or inferred_date_range
                            })
                    elif explicit_date_range or inferred_date_range:
                        request_specs.append({
                            "subject": None,
                            "date_range": explicit_date_range or inferred_date_range
                        })

            context_chunks = []
            missing_requests = []
            for spec in request_specs:
                subject = spec.get("subject")
                date_range = spec.get("date_range")
                chunk = build_filtered_context(
                    user_id=current_user.id,
                    subject=subject,
                    date_range=date_range
                )
                if chunk:
                    label = subject or "All subjects"
                    context_chunks.append(f"=== Requested Notes: {label} ===\n{chunk}")
                elif date_range:
                    start_dt, end_exclusive = date_range
                    date_label = f"{start_dt.date()} to {(end_exclusive - timedelta(days=1)).date()}"
                    missing_requests.append(f"{subject or 'All subjects'} ({date_label})")

            if context_chunks:
                document_content = "\n\n".join(context_chunks)
            elif missing_requests:
                context_notice = (
                    "No notes were found for: " + ", ".join(missing_requests) +
                    ". Tell the user this briefly, then offer another range or subject."
                )

        # Generate or use existing chat_id
        chat_id = chat_data.chat_id or str(uuid.uuid4())
        is_new_chat = not chat_data.chat_id

        # Generate chat title from first message (limited to 100 chars)
        chat_title = None
        if is_new_chat:
            chat_title = generate_chat_title_from_message(chat_data.message)

        # Get allowed domains for web search
        res = supabase.table("allowed_sources").select("domain").eq("user_id", current_user.id).execute()
        allowed_domains = [r["domain"] for r in res.data]

        # Determine if web search is needed
        web_context = ""
        if account_settings.get("web_search_enabled", True) and allowed_domains:
            domain_selection_prompt = load_prompt_text(
                "system/domain_selection_system.md",
                {"{ALLOWED_DOMAINS}": ", ".join(allowed_domains)}
            )

            try:
                selection = openai_client.chat.completions.create(
                    model=config.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": domain_selection_prompt},
                        {"role": "user", "content": chat_data.message}
                    ],
                    max_tokens=100,
                    temperature=0
                )

                import json
                decision = json.loads(selection.choices[0].message.content)
                chosen_domain = decision.get("domain")
                query = decision.get("query", chat_data.message)

                if chosen_domain in allowed_domains:
                    web_context = browse_allowed_sources(query=query, forced_domain=chosen_domain)
                    logger.info(f"Web search performed: {chosen_domain}")
            except Exception as e:
                logger.warning(f"Web search decision error: {e}")

        # Load chat history
        history = supabase.table("chat_messages").select("role, content").eq("user_id", current_user.id).eq("chat_id",
                                                                                                            chat_id).order(
            "created_at", desc=False).limit(config.CHAT_HISTORY_LIMIT).execute()

        # Load tutor prompt
        tutor_prompt = load_prompt_text("prompt.md")

        if chat_mode == "course":
            grade_level = account_settings.get("grade_level", "")
            education_board = account_settings.get("education_board", "")
            mode_instruction = load_prompt_text(
                "system/mode_course_system.txt",
                {
                    "{GRADE_LEVEL}": grade_level,
                    "{EDUCATION_BOARD}": education_board
                }
            )
        elif chat_mode == "quiz":
            mode_instruction = load_prompt_text("system/mode_quiz_system.txt")
        else:
            mode_instruction = load_prompt_text("system/mode_fundamentals_system.txt")

        tutor_role_prompt = load_prompt_text("system/tutor_role_system.txt")
        context_system_prompt = load_prompt_text(
            "system/chat_context_system.md",
            {
                "{LOCAL_DATE_ISO}": local_date_iso,
                "{LOCAL_DATE_LONG}": local_date_long,
                "{DOCUMENT_CONTEXT}": document_content[:config.DOCUMENT_CONTENT_LIMIT] if document_content else "None",
                "{WEB_CONTEXT}": web_context[:config.WEB_CONTEXT_LIMIT] if web_context else "None",
                "{TUTOR_PROMPT}": tutor_prompt,
                "{CONTEXT_NOTICE}": context_notice if context_notice else "None",
            }
        )

        # Prepare messages
        messages = [
            {"role": "system", "content": tutor_role_prompt},
            {"role": "system", "content": mode_instruction},
            {"role": "system", "content": context_system_prompt}
        ]

        for m in history.data or []:
            messages.append({"role": m["role"], "content": m["content"]})

        messages.append({"role": "user", "content": chat_data.message})

        # Get AI response
        try:
            response = openai_client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=messages,
                max_tokens=1500,
                temperature=0.7
            )

            ai_text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate response"
            )

        # Save messages to database
        if account_settings.get("save_chat_history", True):
            try:
                user_msg = {
                    "user_id": current_user.id,
                    "topic_id": chat_data.topic_id,
                    "chat_id": chat_id,
                    "role": "user",
                    "content": chat_data.message
                }
                assistant_msg = {
                    "user_id": current_user.id,
                    "topic_id": chat_data.topic_id,
                    "chat_id": chat_id,
                    "role": "assistant",
                    "content": ai_text
                }
                # Persist title only for the first message pair in a chat.
                if chat_title:
                    user_msg["chat_title"] = chat_title
                    assistant_msg["chat_title"] = chat_title

                messages_to_insert = [user_msg, assistant_msg]

                supabase.table("chat_messages").insert(messages_to_insert).execute()

                logger.info(f"Chat message saved for user {current_user.id}")
            except Exception as e:
                logger.error(f"Failed to save chat messages: {e}")

        return {
            "chat_id": chat_id,
            "ai_response": ai_text
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat failed. Please try again."
        )


@app.get("/api/chat/list/{topic_id}")
async def list_chats(topic_id: str, current_user=Depends(get_current_user)):
    """List all chats for a topic with their titles"""
    try:
        result = supabase.table("chat_messages").select("chat_id, chat_title, created_at").eq("user_id",
                                                                                              current_user.id).eq(
            "topic_id", topic_id).order("created_at", desc=True).execute()

        # Get unique chats with their titles (first occurrence has the title)
        seen_chats = {}
        for row in result.data:
            chat_id = row["chat_id"]
            if chat_id not in seen_chats:
                seen_chats[chat_id] = {
                    "chat_id": chat_id,
                    "chat_title": row.get("chat_title"),
                    "created_at": row["created_at"]
                }

        chats = list(seen_chats.values())
        return {"chats": chats}
    except Exception as e:
        logger.error(f"List chats error: {e}")
        return {"chats": []}


@app.get("/api/chat/history/{chat_id}")
async def get_chat_history(chat_id: str, current_user=Depends(get_current_user)):
    """Get all messages from a specific chat"""
    try:
        result = supabase.table("chat_messages").select("role, content, created_at").eq("user_id", current_user.id).eq(
            "chat_id", chat_id).order("created_at", desc=False).execute()

        messages = [
            {
                "role": msg["role"],
                "content": msg["content"],
                "is_user": msg["role"] == "user"
            }
            for msg in result.data
        ]

        return {"messages": messages}
    except Exception as e:
        logger.error(f"Chat history error: {e}")
        return {"messages": []}


@app.get("/api/chat/list-all")
async def list_all_chats(current_user=Depends(get_current_user)):
    """List all chats for the user, including chats not tied to a single topic"""
    try:
        messages = supabase.table("chat_messages").select("chat_id, chat_title, topic_id, created_at").eq("user_id",
                                                                                                            current_user.id).order(
            "created_at", desc=True).execute()

        docs = supabase.table("documents").select("id, topic").eq("user_id", current_user.id).execute()
        topic_map = {row["id"]: row.get("topic", "Untitled") for row in (docs.data or [])}

        seen = {}
        for row in messages.data or []:
            chat_id = row.get("chat_id")
            if not chat_id:
                continue
            topic_id = row.get("topic_id")
            row_title = row.get("chat_title")

            if chat_id not in seen:
                seen[chat_id] = {
                    "chat_id": chat_id,
                    "chat_title": row_title,
                    "topic_id": topic_id,
                    "topic_name": topic_map.get(topic_id, "Date-range notes") if topic_id else "Date-range notes",
                    "created_at": row.get("created_at")
                }
            else:
                # If latest row had null title, backfill from older titled rows.
                if not seen[chat_id].get("chat_title") and row_title:
                    seen[chat_id]["chat_title"] = row_title

        return {"chats": list(seen.values())}
    except Exception as e:
        logger.error(f"List all chats error: {e}")
        return {"chats": []}


@app.get("/api/chat/topics")
async def get_chat_topics(current_user=Depends(get_current_user)):
    """Get all topics for the user"""
    try:
        try:
            result = supabase.table("documents").select("id, topic, subject, created_at").eq("user_id",
                                                                                              current_user.id).order(
                "created_at", desc=True).execute()
            rows = result.data or []
        except Exception:
            # Backward compatibility for older schema.
            result = supabase.table("documents").select("id, topic").eq("user_id", current_user.id).execute()
            rows = [{"id": r.get("id"), "topic": r.get("topic"), "subject": "Uncategorized", "created_at": None}
                    for r in (result.data or [])]
        return {"topics": rows}
    except Exception as e:
        logger.error(f"Get topics error: {e}")
        return {"topics": []}


@app.get("/api/get_topics")
async def get_topics(current_user=Depends(get_current_user)):
    """Get all topics with content for the user"""
    try:
        try:
            result = supabase.table("documents").select("id, topic, content, subject, created_at").eq("user_id",
                                                                                                        current_user.id).order(
                "created_at", desc=True).execute()
            rows = result.data or []
        except Exception:
            # Backward compatibility for older schema.
            result = supabase.table("documents").select("id, topic, content").eq("user_id", current_user.id).execute()
            rows = [{
                "id": r.get("id"),
                "topic": r.get("topic"),
                "content": r.get("content"),
                "subject": "Uncategorized",
                "created_at": None
            } for r in (result.data or [])]

        topics = []
        for row in rows:
            topics.append({
                "id": row.get("id"),
                "topic": row.get("topic"),
                "content": row.get("content"),
                "subject": row.get("subject") or "Uncategorized",
                "created_at": row.get("created_at")
            })
        return {"topics": topics}
    except Exception as e:
        logger.error(f"Get topics with content error: {e}")
        return {"topics": []}


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str, current_user=Depends(get_current_user)):
    """Delete a document and its related chat messages"""
    try:
        doc_check = supabase.table("documents").select("id").eq("id", document_id).eq("user_id", current_user.id).execute()
        if not doc_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        supabase.table("documents").delete().eq("id", document_id).eq("user_id", current_user.id).execute()
        supabase.table("chat_messages").delete().eq("topic_id", document_id).eq("user_id", current_user.id).execute()

        logger.info(f"Document deleted by user {current_user.id}: {document_id}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete document error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to delete document"
        )


@app.patch("/api/documents/{document_id}/subject")
async def update_document_subject(
        document_id: str,
        data: UpdateDocumentSubjectData,
        current_user=Depends(get_current_user)
):
    """Move a document to another subject"""
    try:
        subject = normalize_subject(data.subject)
        doc_check = supabase.table("documents").select("id").eq("id", document_id).eq("user_id", current_user.id).execute()
        if not doc_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        supabase.table("documents").update({"subject": subject}).eq("id", document_id).eq("user_id",
                                                                                          current_user.id).execute()
        logger.info(f"Document subject updated by user {current_user.id}: {document_id} -> {subject}")
        return {"success": True, "subject": subject}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update document subject error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update document subject"
        )


@app.delete("/api/chat/{chat_id}")
async def delete_chat(chat_id: str, current_user=Depends(get_current_user)):
    """Delete all messages in a chat thread for the current user"""
    try:
        chat_check = supabase.table("chat_messages").select("chat_id").eq("chat_id", chat_id).eq("user_id",
                                                                                                   current_user.id).limit(
            1).execute()
        if not chat_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found"
            )

        supabase.table("chat_messages").delete().eq("chat_id", chat_id).eq("user_id", current_user.id).execute()
        logger.info(f"Chat deleted by user {current_user.id}: {chat_id}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete chat error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to delete chat"
        )


@app.get("/api/dashboard/stats")
async def get_dashboard_stats(current_user=Depends(get_current_user)):
    """Get dashboard statistics"""
    try:
        # Get unique chat count
        chat_result = supabase.table("chat_messages").select("chat_id").eq("user_id", current_user.id).execute()
        unique_chats = len(set(row["chat_id"] for row in chat_result.data))

        # Get messages from last week
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        week_result = supabase.table("chat_messages").select("id").eq("user_id", current_user.id).gte("created_at",
                                                                                                      week_ago).execute()
        week_count = len(week_result.data)

        return {
            "chat_count": unique_chats,
            "week_count": week_count
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {
            "chat_count": 0,
            "week_count": 0
        }


@app.get("/api/sources")
async def get_sources(current_user=Depends(get_current_user)):
    """Get allowed sources for the user"""
    try:
        res = supabase.table("allowed_sources").select("id, domain").eq("user_id", current_user.id).execute()
        return {"sources": res.data}
    except Exception as e:
        logger.error(f"Get sources error: {e}")
        return {"sources": []}


@app.post("/api/sources")
async def add_source(data: AddSourceData, current_user=Depends(get_current_user)):
    """Add an allowed source"""
    try:
        supabase.table("allowed_sources").insert({
            "user_id": current_user.id,
            "domain": data.domain
        }).execute()

        logger.info(f"Source added by user {current_user.id}: {data.domain}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Add source error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add source"
        )


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str, current_user=Depends(get_current_user)):
    """Delete an allowed source"""
    try:
        supabase.table("allowed_sources").delete().eq("id", source_id).eq("user_id", current_user.id).execute()

        logger.info(f"Source deleted by user {current_user.id}: {source_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Delete source error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to delete source"
        )


@app.get("/api/subject-presets")
async def get_subject_presets(current_user=Depends(get_current_user)):
    """Get ordered subject presets for the user"""
    try:
        seeded = ensure_subject_presets_seeded(current_user.id)
        return {"presets": seeded}
    except Exception as e:
        logger.error(f"Get subject presets error: {e}")
        defaults = [{"subject": s, "position": idx} for idx, s in enumerate(DEFAULT_SUBJECT_PRESETS)]
        return {"presets": defaults}


@app.post("/api/subject-presets")
async def add_subject_preset(data: SubjectPresetData, current_user=Depends(get_current_user)):
    """Add a new subject preset"""
    subject = normalize_subject(data.subject)
    try:
        existing = ensure_subject_presets_seeded(current_user.id)
        if any(normalize_subject(r["subject"]) == subject for r in existing):
            return {"success": True, "message": "Subject already exists"}

        max_position = max([r.get("position", 0) for r in existing], default=-1)
        supabase.table("subject_presets").insert({
            "user_id": current_user.id,
            "subject": subject,
            "position": max_position + 1
        }).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"Add subject preset error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add subject preset"
        )


@app.put("/api/subject-presets/reorder")
async def reorder_subject_presets(data: SubjectPresetOrderData, current_user=Depends(get_current_user)):
    """Reorder subject presets by IDs"""
    try:
        owned = supabase.table("subject_presets").select("id").eq("user_id", current_user.id).execute()
        owned_ids = {row["id"] for row in owned.data or []}
        if not set(data.preset_ids).issubset(owned_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid subject preset IDs"
            )

        for index, preset_id in enumerate(data.preset_ids):
            try:
                supabase.table("subject_presets").update({"position": index}).eq("id", preset_id).eq("user_id",
                                                                                                      current_user.id).execute()
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Preset reordering requires a `position` column in subject_presets"
                )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reorder subject presets error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to reorder subject presets"
        )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
