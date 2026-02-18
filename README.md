# BrainAmp

BrainAmp is a FastAPI-powered study platform that helps students turn raw notes into guided learning.
You can upload documents, chat with an AI tutor, generate structured courses, practice with quizzes, and schedule study tasks in a planner-style calendar.

## Access

A public BrainAmp link will be released soon.

## Why Use BrainAmp

BrainAmp is useful when you want one workflow for the full learning loop:

- Turn mixed study files into usable context (PDF/DOCX/TXT/images).
- Ask focused questions tied to your own notes.
- Generate day-by-day course plans from your material.
- Create and evaluate quizzes for exam-style practice.
- Keep learning tasks organized on a calendar.
- Optionally enrich responses with web context from only user-approved domains.

## Frontend Experience

BrainAmp ships with server-rendered pages (Jinja templates) and lightweight JS/CSS assets.

Primary pages:

- `starter.html` (`/`): entry page.
- `index.html` (`/login`): sign in.
- `signup.html` (`/signup`): account creation.
- `dashboard.html` (`/dashboard`): metrics + quick navigation.
- `upload_docs.html` (`/upload`): note/document upload.
- `chat.html` (`/chat`): AI tutoring across fundamentals/course/quiz modes.
- `topics.html` (`/topics`): topic and note management.
- `calendar.html` (`/calendar`): planner and day-level schedule.
- `courses.html` (`/courses`): generated course plans and modules.
- `quizzes.html` (`/quizzes`): quiz generation + management.
- `add_sources.html` (`/sources`): manage allowed web domains.
- `settings.html` (`/settings`): account and study preferences.

Frontend scripts:

- `static/script.js`: auth/session flow, chat, upload, topics, settings, dashboard, sources, quizzes, course actions.
- `static/planner.js`: calendar rendering, planner actions, day detail handling.

Styling is split per page in `static/css/`.

## Tech Stack

- Backend: FastAPI + Uvicorn
- Frontend: Jinja2 templates + vanilla JS/CSS
- LLM/OCR: OpenAI API (`gpt-4o-mini` by default)
- Auth + persistence: Supabase

## Current Project Structure

```text
.
├── main.py                    # App initialization, shared helpers, HTML + core API routes
├── app/
│   ├── config.py              # Env/config flags
│   ├── constants.py           # Default constants (e.g., subject presets)
│   ├── helpers.py             # Utility + metadata helpers
│   ├── prompting.py           # Prompt loading utilities
│   ├── schemas.py             # Pydantic request/response schemas
│   └── routers/
│       ├── auth.py            # Auth + account settings endpoints
│       ├── chat.py            # Chat endpoints and topic/chat listing
│       ├── courses.py         # Course generation + module management
│       ├── planner.py         # Calendar + planner CRUD + command endpoint
│       └── quizzes.py         # Quiz generation/evaluation/list/delete
├── src/
│   ├── convert_to_raw_text.py # File text extraction + OCR pipeline
│   └── scrape_web.py          # Domain-restricted web browsing helpers
├── prompt/
│   ├── prompt.md
│   └── system/                # System/user prompt templates by feature
├── templates/                 # Jinja HTML pages
├── static/
│   ├── script.js
│   ├── planner.js
│   └── css/
├── tests/
├── requirements.txt
└── README.md
```

## Usage Flow

1. Sign up or log in.
2. Upload notes/documents in `/upload`.
3. Open `/chat` and ask questions against your notes.
4. Generate a course plan in `/courses` for a structured schedule.
5. Track or adjust tasks in `/calendar`.
6. Generate/review quizzes in `/quizzes`.
7. Add trusted web domains in `/sources` if you want web-enriched responses.
8. Use `/settings` to tune account preferences (web search toggle, chat history behavior, grade/board context).

## Route Reference

### HTML Routes

- `GET /`
- `GET /login`
- `GET /signup`
- `GET /settings`
- `GET /upload`
- `GET /dashboard`
- `GET /chat`
- `GET /topics`
- `GET /calendar`
- `GET /courses`
- `GET /quizzes`
- `GET /sources`

### System and Health

- `GET /api/system/status`
- `GET /health`

### Auth and Account

- `POST /api/login`
- `POST /api/signup`
- `POST /api/refresh`
- `GET /api/me`
- `POST /api/update-profile`
- `POST /api/account-settings`
- `POST /api/change-password`

### Documents and Topics

- `POST /api/upload`
- `GET /api/get_topics`
- `GET /api/chat/topics`
- `DELETE /api/documents/{document_id}`
- `PATCH /api/documents/{document_id}/subject`

### Chat

- `POST /api/chat/send`
- `GET /api/chat/list/{topic_id}`
- `GET /api/chat/history/{chat_id}`
- `GET /api/chat/list-all`
- `DELETE /api/chat/{chat_id}`

### Sources and Subject Presets

- `GET /api/sources`
- `POST /api/sources`
- `DELETE /api/sources/{source_id}`
- `GET /api/subject-presets`
- `POST /api/subject-presets`
- `PUT /api/subject-presets/reorder`

### Dashboard and Learning Assets

- `GET /api/dashboard/stats`
- `GET /api/learning-assets`
- `POST /api/learning-assets/course`
- `POST /api/learning-assets/quiz`
- `DELETE /api/learning-assets/course/{asset_id}`
- `DELETE /api/learning-assets/quiz/{asset_id}`

### Courses

- `POST /api/courses/generate`
- `GET /api/courses`
- `GET /api/courses/{course_id}`
- `DELETE /api/courses/{course_id}`
- `PATCH /api/course-modules/{module_id}`
- `GET /api/course-modules`

### Planner and Calendar

- `GET /api/calendar`
- `GET /api/calendar/day/{day_text}`
- `POST /api/planner/busy`
- `DELETE /api/planner/busy/{slot_id}`
- `POST /api/planner/task`
- `DELETE /api/planner/task/{task_id}`
- `POST /api/planner/reminder`
- `DELETE /api/planner/reminder/{reminder_id}`
- `POST /api/planner/command`

### Quizzes

- `POST /api/quizzes/generate`
- `POST /api/quizzes/evaluate-answer`
- `GET /api/quizzes`
- `DELETE /api/quizzes/{quiz_id}`

## Expected Supabase Tables

Minimum tables for full functionality:

- `documents`
- `chat_messages`
- `allowed_sources`
- `subject_presets`
- `course_plans`
- `course_modules`
- `saved_quizzes`

## Domain-Limited Web Context

When web context is enabled, BrainAmp only browses:

1. Domains saved by the current user in `allowed_sources`.
2. Domains permitted by the backend search mapping in `src/scrape_web.py`.

This keeps web enrichment bounded and user-controlled.

## License

This project is licensed under the terms in `LICENSE`.

## Acknowledgments

Special thanks to Codex for accelerating post-hackathon development, iteration speed, and testing throughput throughout this project.
