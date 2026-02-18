import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import ChatMessage
from app.helpers import get_account_settings_from_metadata, parse_date_range_from_message
from app.runtime import get_main_attr
from src.scrape_web import browse_allowed_sources

build_filtered_context = get_main_attr("build_filtered_context")
config = get_main_attr("config")
detect_subjects_from_message = get_main_attr("detect_subjects_from_message")
generate_chat_title_from_message = get_main_attr("generate_chat_title_from_message")
get_current_user = get_main_attr("get_current_user")
get_subject_presets_for_user = get_main_attr("get_subject_presets_for_user")
get_terminal_datetime_context = get_main_attr("get_terminal_datetime_context")
infer_date_range_from_message = get_main_attr("infer_date_range_from_message")
infer_subject_date_requests = get_main_attr("infer_subject_date_requests")
load_prompt_text = get_main_attr("load_prompt_text")
logger = get_main_attr("logger")
normalize_subject = get_main_attr("normalize_subject")
openai_client = get_main_attr("openai_client")
supabase = get_main_attr("supabase")

router = APIRouter()

@router.post("/api/chat/send")
async def send_chat(
        chat_data: ChatMessage,
        current_user=Depends(get_current_user)
):
    """Send chat message and get AI response"""
    try:
        user_metadata = current_user.user_metadata or {}
        account_settings = get_account_settings_from_metadata(user_metadata)
        chat_mode = (chat_data.chat_mode or "fundamentals").strip().lower()
        if chat_mode not in {"fundamentals", "general", "course", "quiz"}:
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

        injected_context = (chat_data.extra_context or "").strip()
        if injected_context:
            scoped_context = injected_context[:20000]
            if document_content:
                document_content = f"{document_content}\n\n=== User Provided Context ===\n{scoped_context}"
            else:
                document_content = f"=== User Provided Context ===\n{scoped_context}"

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

        mode_instruction = None
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
        elif chat_mode == "general":
            mode_instruction = load_prompt_text("system/mode_general_system.txt")
        # Fundamentals mode intentionally uses prompt.md instructions directly.

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
        messages = [{"role": "system", "content": tutor_role_prompt}]
        if mode_instruction:
            messages.append({"role": "system", "content": mode_instruction})
        messages.append({"role": "system", "content": context_system_prompt})

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


@router.get("/api/chat/list/{topic_id}")
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


@router.get("/api/chat/history/{chat_id}")
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


@router.get("/api/chat/list-all")
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


@router.get("/api/chat/topics")
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


@router.get("/api/get_topics")
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

@router.delete("/api/chat/{chat_id}")
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
