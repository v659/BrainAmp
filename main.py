import os
import logging
from typing import Optional, List
from datetime import datetime, timedelta
import tempfile
import uuid

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
    DOCUMENT_CONTENT_LIMIT = 2000
    WEB_CONTEXT_LIMIT = 2000
    PASSWORD_MIN_LENGTH = 8
    OPENAI_MODEL = "gpt-4o-mini"


config = Config()

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
    message: str = Field(..., min_length=1, max_length=2000)


class UpdateProfileData(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)


class AddSourceData(BaseModel):
    domain: str = Field(..., min_length=3, max_length=100)

    @validator('domain')
    def validate_domain(cls, v):
        v = v.strip().lower()
        if not '.' in v or ' ' in v:
            raise ValueError('Invalid domain format')
        return v


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
                "access_token": result.session.access_token
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
                "access_token": result.session.access_token
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


@app.get("/api/me")
async def get_me(current_user=Depends(get_current_user)):
    """Get current user information"""
    display_name = current_user.user_metadata.get("display_name", "User")
    if not display_name or display_name == "User":
        display_name = current_user.email.split('@')[0]

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "display_name": display_name
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
        with open("prompt/topic_extraction_prompt.md", "r") as f:
            prompt_template = f.read()

        formatted_prompt = prompt_template.replace("{TEXT}", combined_text[:5000])  # Limit context

        try:
            response = openai_client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a topic extraction assistant."},
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

        # Save to database
        try:
            result = supabase.table("documents").insert({
                "user_id": current_user.id,
                "content": combined_text,
                "topic": topic,
                "file_count": len(files),
                "file_names": [f.filename for f in files]
            }).execute()

            logger.info(f"Document uploaded by user {current_user.id}: {topic}")

            return {
                "success": True,
                "topic": topic,
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
        # Validate topic_id if provided
        document_content = ""
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

        # Generate or use existing chat_id
        chat_id = chat_data.chat_id or str(uuid.uuid4())
        is_new_chat = not chat_data.chat_id

        # Generate chat title from first message (limited to 100 chars)
        chat_title = None
        if is_new_chat:
            chat_title = chat_data.message[:100] if len(chat_data.message) <= 100 else chat_data.message[:97] + "..."

        # Get allowed domains for web search
        res = supabase.table("allowed_sources").select("domain").eq("user_id", current_user.id).execute()
        allowed_domains = [r["domain"] for r in res.data]

        # Determine if web search is needed
        web_context = ""
        if allowed_domains:
            domain_selection_prompt = f"""
You may request information from EXACTLY ONE of the following allowed domains:
{", ".join(allowed_domains)}

If external information is useful, respond ONLY in valid JSON:
{{"domain": "<one allowed domain>", "query": "<search query>"}}

If no external information is needed, respond with:
{{"domain": null}}
"""

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
        with open("prompt/prompt.md") as f:
            tutor_prompt = f.read()

        # Prepare messages
        messages = [
            {"role": "system", "content": "You are an AI tutor following the specified framework."},
            {"role": "system", "content": f"""
DOCUMENT CONTEXT:
{document_content[:config.DOCUMENT_CONTENT_LIMIT] if document_content else "None"}

EXTERNAL REFERENCE MATERIAL:
{web_context[:config.WEB_CONTEXT_LIMIT] if web_context else "None"}

INSTRUCTIONS:
{tutor_prompt}
"""}
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
        try:
            messages_to_insert = [
                {
                    "user_id": current_user.id,
                    "topic_id": chat_data.topic_id,
                    "chat_id": chat_id,
                    "role": "user",
                    "content": chat_data.message,
                    "chat_title": chat_title  # Only set for first message
                },
                {
                    "user_id": current_user.id,
                    "topic_id": chat_data.topic_id,
                    "chat_id": chat_id,
                    "role": "assistant",
                    "content": ai_text,
                    "chat_title": chat_title  # Only set for first message
                }
            ]

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


@app.get("/api/chat/topics")
async def get_chat_topics(current_user=Depends(get_current_user)):
    """Get all topics for the user"""
    try:
        result = supabase.table("documents").select("id, topic").eq("user_id", current_user.id).execute()
        return {"topics": result.data}
    except Exception as e:
        logger.error(f"Get topics error: {e}")
        return {"topics": []}


@app.get("/api/get_topics")
async def get_topics(current_user=Depends(get_current_user)):
    """Get all topics with content for the user"""
    try:
        result = supabase.table("documents").select("topic, content").eq("user_id", current_user.id).execute()

        return {
            "result_topics": [{"topic": r["topic"]} for r in result.data],
            "result_content": [{"content": r["content"]} for r in result.data]
        }
    except Exception as e:
        logger.error(f"Get topics with content error: {e}")
        return {"result_topics": [], "result_content": []}


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


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)