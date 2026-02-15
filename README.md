# BrainAmp

BrainAmp is a FastAPI-based study assistant that lets users upload notes, chat with an AI tutor, and optionally enrich answers with web context from user-approved domains.

You need your own API keys right now. A public site was previously set up but is currently suspended.

## What It Does

- Auth via Supabase (`signup`, `login`, token refresh, profile updates)
- Upload up to 5 files per request (`pdf`, `docx`, `txt`, `png`, `jpg`, `jpeg`)
- Extract text from documents and images (OCR for images via OpenAI Vision)
- Auto-generate a topic and classify documents into subject presets
- Chat with context from uploaded notes, filtered by subject/date when requested
- Optional web context from user-allowed domains only
- Dashboard stats, chat history, document/source management

## Tech Stack

- Backend: FastAPI + Uvicorn
- Templates/UI: Jinja2 + static JS/CSS
- Auth + data: Supabase
- LLM/OCR: OpenAI API (`gpt-4o-mini`)

## Project Layout

```text
main.py                      # FastAPI app + routes
src/convert_to_raw_text.py   # File text extraction (PDF/DOCX/TXT/Image OCR)
src/scrape_web.py            # Domain-limited web retrieval helpers
templates/                   # HTML templates
static/                      # Frontend scripts/assets
prompt/                      # Prompt templates for topic extraction + tutoring
tests/                       # Basic test scaffolding
```

## Prerequisites

- Python 3.10+
- Supabase project with required tables (see below)
- OpenAI API key

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
OPENAI_API_KEY=your_openai_api_key
```

The app exits at startup if any of these are missing.

## Run

```bash
python main.py
```

Server starts on `http://127.0.0.1:8080`.

Main pages:

- `/` starter
- `/login`
- `/signup`
- `/dashboard`
- `/upload`
- `/chat`
- `/topics`
- `/sources`

Health check:

- `GET /health`

## Core API Endpoints

Auth:

- `POST /api/signup`
- `POST /api/login`
- `POST /api/refresh`
- `GET /api/me`
- `POST /api/update-profile`

Documents:

- `POST /api/upload`
- `GET /api/get_topics`
- `DELETE /api/documents/{document_id}`
- `PATCH /api/documents/{document_id}/subject`

Chat:

- `POST /api/chat/send`
- `GET /api/chat/list/{topic_id}`
- `GET /api/chat/history/{chat_id}`
- `GET /api/chat/list-all`
- `GET /api/chat/topics`
- `DELETE /api/chat/{chat_id}`

Sources and presets:

- `GET /api/sources`
- `POST /api/sources`
- `DELETE /api/sources/{source_id}`
- `GET /api/subject-presets`
- `POST /api/subject-presets`
- `PUT /api/subject-presets/reorder`

Dashboard:

- `GET /api/dashboard/stats`

## Expected Supabase Tables

The code expects these tables (at minimum):

- `documents`
- `chat_messages`
- `allowed_sources`
- `subject_presets`

Notable fields used by the app include:

- `documents`: `id`, `user_id`, `topic`, `content`, `subject`, `created_at`, `file_count`, `file_names`
- `chat_messages`: `id`, `user_id`, `topic_id`, `chat_id`, `chat_title`, `role`, `content`, `created_at`
- `allowed_sources`: `id`, `user_id`, `domain`
- `subject_presets`: `id`, `user_id`, `subject`, `position`

## Domain-Limited Web Context

Web retrieval only runs against domains that:

1. Are explicitly added by the current user in `allowed_sources`
2. Are in `src/scrape_web.py` `DOMAIN_SEARCH`

This keeps browsing constrained to approved sources.

## Notes and Limits

- Max file size: `15MB` per file
- Max files per upload: `5`
- Combined text/context is truncated before prompt submission
- CORS is currently open (`allow_origins=["*"]`), which should be tightened for production

## Troubleshooting

- `RuntimeError: Missing required environment variables`:
  Ensure `.env` has all required keys.
- Upload accepted but no text extracted:
  Check file type and whether the source file has machine-readable text.
- 401 errors on API routes:
  Ensure `Authorization: Bearer <access_token>` is sent.

## License

This project is licensed under the terms in `LICENSE`.
