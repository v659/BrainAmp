import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import tempfile
import uuid
import re
import json
import subprocess

from fastapi import FastAPI, Request, Header, HTTPException, Depends, UploadFile, File, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from openai import OpenAI
import uvicorn

from app.config import config, OFFLINE_AUTH_FALLBACK, SUPABASE_OPTIONAL
from app.constants import DEFAULT_SUBJECT_PRESETS
from app.helpers import (
    build_offline_user,
    get_learning_assets_from_metadata,
    normalize_module_lookup_text,
    normalize_subject,
    try_parse_date,
)
from app.prompting import load_prompt_text
from app.schemas import (
    AddSourceData,
    LearningAssetData,
    SubjectPresetData,
    SubjectPresetOrderData,
    UpdateDocumentSubjectData,
)
from src.convert_to_raw_text import extract_text_from_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Validate configuration
if not config.OPENAI_API_KEY:
    raise RuntimeError("Missing required OPENAI_API_KEY")

supabase = None
SUPABASE_AVAILABLE = False

if config.SUPABASE_URL and config.SUPABASE_ANON_KEY:
    try:
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
        SUPABASE_AVAILABLE = True
    except Exception as e:
        SUPABASE_AVAILABLE = False
        logger.error(f"Supabase init failed: {e}")
        if not SUPABASE_OPTIONAL:
            raise
else:
    logger.warning("Supabase credentials missing. Running without Supabase.")
    if not SUPABASE_OPTIONAL:
        raise RuntimeError("Missing required SUPABASE_URL/SUPABASE_ANON_KEY")

try:
    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
except Exception as e:
    logger.error(f"OpenAI init failed: {e}")
    raise

if not SUPABASE_AVAILABLE and not OFFLINE_AUTH_FALLBACK:
    logger.warning(
        "Supabase unavailable. Set OFFLINE_AUTH_FALLBACK=true to allow temporary guest/offline mode."
    )

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


def resolve_course_module_for_user(user_id: str, identifier: str, need_task_date: bool = False) -> Optional[Dict[str, Any]]:
    fields = "id, title, task_date" if need_task_date else "id, title"
    ident = normalize_module_lookup_text(identifier)
    if not ident:
        return None

    all_rows = supabase.table("course_modules").select(fields).eq("user_id", user_id).limit(300).execute().data or []
    if not all_rows:
        return None

    # Semantic resolution via OpenAI only.
    try:
        candidates = []
        for row in all_rows[:160]:
            candidates.append({
                "id": str(row.get("id")),
                "title": str(row.get("title") or "")[:180],
                "task_date": str(row.get("task_date") or "") if need_task_date else None
            })

        system_prompt = (
            "You map a user phrase to one module title from candidates.\n"
            "Return ONLY valid JSON: {\"id\": \"<candidate_id_or_null>\"}.\n"
            "Rules:\n"
            "- Pick the single best semantic match.\n"
            "- If confidence is low, return null.\n"
            "- Never return an id not present in candidates."
        )
        user_prompt = (
            f"Phrase: {identifier}\n\n"
            f"Candidates:\n{json.dumps(candidates, ensure_ascii=True)}"
        )
        resp = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=120,
            temperature=0
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        parsed = json.loads(raw)
        chosen_id = str(parsed.get("id") or "").strip()
        if chosen_id:
            for row in all_rows:
                if str(row.get("id")) == chosen_id:
                    return row
    except Exception as e:
        logger.warning("OpenAI module resolution fallback failed: %s", e)

    return None


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


def generate_course_plan_from_notes(
        document_topic: str,
        document_text: str,
        start_date_text: str,
        duration_days: int,
        grade_level: str,
        education_board: str,
        course_title: str,
        user_request: str = "",
) -> dict:
    base_system_prompt = load_prompt_text(
        "system/course_generation_system.md",
        {
            "{DURATION_DAYS}": str(duration_days),
            "{GRADE_LEVEL}": grade_level,
            "{EDUCATION_BOARD}": education_board,
        }
    )
    base_user_prompt = load_prompt_text(
        "system/course_generation_user.md",
        {
            "{DOCUMENT_TOPIC}": document_topic or "Untitled topic",
            "{START_DATE}": start_date_text,
            "{DURATION_DAYS}": str(duration_days),
            "{DOCUMENT_TEXT}": document_text[:9000],
            "{COURSE_TITLE}": course_title or "None",
            "{USER_REQUEST}": (user_request or "None")[:2000],
        }
    )

    compact_system_suffix = (
        "\n\nCRITICAL COMPACT MODE:\n"
        "- Keep total JSON concise.\n"
        "- lesson max 700 characters.\n"
        "- practice max 350 characters.\n"
        "- quiz max 280 characters.\n"
        "- Avoid extra prose outside JSON."
    )
    compact_user_suffix = (
        "\n\nYour previous response was too long or invalid JSON. "
        "Retry with concise but useful content and strictly valid JSON."
    )

    parsed = None
    last_err = None
    for attempt in range(2):
        compact = attempt == 1
        system_prompt = base_system_prompt + (compact_system_suffix if compact else "")
        user_prompt = base_user_prompt + (compact_user_suffix if compact else "")

        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2800 if not compact else 2000,
            temperature=0.35 if not compact else 0.25
        )
        raw = (response.choices[0].message.content or "").strip()
        finish_reason = response.choices[0].finish_reason if response.choices else "unknown"
        logger.debug(
            "Course generation debug: attempt=%s finish_reason=%s system_prompt_len=%s user_prompt_len=%s raw_len=%s",
            attempt + 1,
            finish_reason,
            len(system_prompt),
            len(user_prompt),
            len(raw),
        )
        if raw:
            logger.debug("Course generation raw preview (first 500 chars): %s", raw[:500])
        else:
            logger.error("Course generation raw response is empty")

        try:
            parsed = json.loads(raw)
            break
        except Exception as parse_err:
            last_err = parse_err
            logger.error(
                "Course JSON parse failed (attempt %s): %s | raw_preview=%s",
                attempt + 1,
                parse_err,
                raw[:1200] if raw else "<empty>",
            )
            if attempt == 0 and finish_reason == "length":
                continue
            if attempt == 0:
                continue
            raise

    if parsed is None:
        raise last_err if last_err else ValueError("Failed to parse course generation JSON")
    tasks = parsed.get("modules")
    if not isinstance(tasks, list):
        raise ValueError("Course generation returned invalid modules payload")

    normalized_modules = []
    for idx, module in enumerate(tasks):
        if not isinstance(module, dict):
            continue
        day_value = int(module.get("day") or 1)
        if day_value < 1:
            day_value = 1
        if day_value > duration_days:
            day_value = duration_days
        normalized_modules.append({
            "day": day_value,
            "title": (module.get("title") or f"Task {idx + 1}").strip()[:120],
            "lesson": (module.get("lesson") or "Study the key ideas from your notes and explain them in your own words.").strip()[:12000],
            "practice": (module.get("practice") or "Solve at least 3 practice prompts based on this lesson.").strip()[:4000],
            "quiz": (module.get("quiz") or "Create and answer 3 self-check questions.").strip()[:4000],
        })

    if not normalized_modules:
        for i in range(duration_days):
            normalized_modules.append({
                "day": i + 1,
                "title": f"Day {i + 1} fundamentals",
                "lesson": "Study the relevant notes and capture core concepts with examples.",
                "practice": "Practice with 3-5 questions.",
                "quiz": "Write and answer 3 quick checks.",
            })

    return {
        "course_title": (parsed.get("course_title") or course_title or document_topic or "Generated Course").strip()[:120],
        "overview": (parsed.get("overview") or "Personalized course plan generated from your notes.").strip()[:5000],
        "modules": normalized_modules
    }


def get_user_documents_for_course(
        user_id: str,
        document_ids: List[str],
        fallback_topic: str = "General topic"
) -> tuple[list, str, str]:
    if (not SUPABASE_AVAILABLE or not supabase) and document_ids:
        topic_text = (fallback_topic or "General topic").strip()[:180]
        return [], topic_text, ""

    if document_ids:
        docs = []
        for doc_id in document_ids:
            res = supabase.table("documents").select("id, topic, content").eq("user_id", user_id).eq("id", doc_id).limit(
                1).execute()
            if res.data:
                docs.append(res.data[0])
        if not docs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected notes not found")
    else:
        # No notes selected: allow pure general-knowledge generation.
        docs = []
        topic_text = (fallback_topic or "General topic").strip()[:180]
        return docs, topic_text, ""

    topic_text = " + ".join([(d.get("topic") or "Untitled") for d in docs])[:180]
    merged_content = "\n\n".join([
        f"--- {d.get('topic') or 'Untitled'} ---\n{d.get('content') or ''}" for d in docs
    ])
    return docs, topic_text, merged_content


# Dependency for authentication
async def get_current_user(authorization: str = Header(None)):
    """Verify JWT token and return current user"""
    if not authorization:
        if OFFLINE_AUTH_FALLBACK:
            logger.warning("Missing authorization header; using offline fallback user.")
            return build_offline_user()
        logger.warning("Missing authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token"
        )

    try:
        if not SUPABASE_AVAILABLE or not supabase:
            if OFFLINE_AUTH_FALLBACK:
                logger.warning("Supabase unavailable; using offline fallback user.")
                return build_offline_user()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase unavailable"
            )
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
        if OFFLINE_AUTH_FALLBACK:
            logger.warning("Authentication failed; using offline fallback user.")
            return build_offline_user()
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


from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.chat import router as chat_router  # noqa: E402
from app.routers.courses import router as courses_router  # noqa: E402
from app.routers.planner import router as planner_router  # noqa: E402
from app.routers.quizzes import router as quizzes_router  # noqa: E402

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(courses_router)
app.include_router(planner_router)
app.include_router(quizzes_router)

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


@app.get("/calendar", response_class=HTMLResponse)
async def serve_calendar(request: Request):
    return templates.TemplateResponse("calendar.html", {"request": request})


@app.get("/courses", response_class=HTMLResponse)
async def serve_courses(request: Request):
    return templates.TemplateResponse("courses.html", {"request": request})


@app.get("/quizzes", response_class=HTMLResponse)
async def serve_quizzes(request: Request):
    return templates.TemplateResponse("quizzes.html", {"request": request})


@app.get("/sources", response_class=HTMLResponse)
async def serve_sources(request: Request):
    return templates.TemplateResponse("add_sources.html", {"request": request})


# API Routes
@app.get("/api/system/status")
async def system_status():
    return {
        "supabase_available": bool(SUPABASE_AVAILABLE and supabase),
        "offline_auth_fallback_enabled": bool(OFFLINE_AUTH_FALLBACK),
    }



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
                    detail="Total upload size exceeds maximum allowed"
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
            supabase.table("documents").insert({
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
