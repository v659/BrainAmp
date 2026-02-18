import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.helpers import get_account_settings_from_metadata, parse_iso_date_or_none
from app.schemas import GenerateCourseData, UpdateCourseModuleData
from main import (
    OFFLINE_AUTH_FALLBACK,
    SUPABASE_AVAILABLE,
    config,
    generate_course_plan_from_notes,
    get_current_user,
    get_user_documents_for_course,
    load_prompt_text,
    logger,
    openai_client,
    supabase,
)

router = APIRouter()

@router.post("/api/courses/generate")
async def generate_course(
        data: GenerateCourseData,
        current_user=Depends(get_current_user)
):
    """Generate and persist a course plan + dated modules from user notes."""
    try:
        account_settings = get_account_settings_from_metadata(current_user.user_metadata or {})
        grade_level = (account_settings.get("grade_level") or "").strip()
        education_board = (account_settings.get("education_board") or "").strip()
        if not grade_level or not education_board:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Set Grade and Board in Settings before generating a course."
            )

        start_day = parse_iso_date_or_none(data.start_date)
        if not start_day:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start_date. Use YYYY-MM-DD.")

        fallback_topic = (data.title or data.request or "General course").strip()
        docs, merged_topic, merged_content = get_user_documents_for_course(
            current_user.id,
            data.document_ids or [],
            fallback_topic=fallback_topic
        )

        generated = generate_course_plan_from_notes(
            document_topic=merged_topic or "Untitled",
            document_text=(
                merged_content
                if (merged_content or "").strip()
                else f"No user notes were provided. Build this course using robust general knowledge for: {fallback_topic or merged_topic}."
            ),
            start_date_text=data.start_date,
            duration_days=data.duration_days,
            grade_level=grade_level,
            education_board=education_board,
            course_title=(data.title or "").strip(),
            user_request=(data.request or "").strip(),
        )

        modules_payload = []
        for idx, module in enumerate(generated["modules"]):
            day_idx = int(module["day"])
            task_date = (start_day + timedelta(days=(day_idx - 1))).isoformat()
            modules_payload.append({
                "course_id": None,
                "user_id": current_user.id,
                "day_index": idx + 1,
                "task_date": task_date,
                "title": module["title"],
                "lesson_content": module["lesson"],
                "practice_content": module["practice"],
                "quiz_content": module["quiz"]
            })

        if not SUPABASE_AVAILABLE or not supabase:
            offline_course_id = f"offline-{uuid.uuid4()}"
            modules = []
            for payload in modules_payload:
                modules.append({
                    "id": f"offline-module-{uuid.uuid4()}",
                    "day_index": payload["day_index"],
                    "task_date": payload["task_date"],
                    "title": payload["title"],
                    "lesson_content": payload["lesson_content"],
                    "practice_content": payload["practice_content"],
                    "quiz_content": payload["quiz_content"],
                })
            return {
                "success": True,
                "offline": True,
                "course_id": offline_course_id,
                "title": generated["course_title"],
                "module_count": len(modules),
                "auto_quiz_id": None,
                "course": {
                    "id": offline_course_id,
                    "title": generated["course_title"],
                    "overview": generated["overview"],
                    "start_date": data.start_date,
                    "duration_days": data.duration_days,
                    "created_at": datetime.utcnow().isoformat()
                },
                "modules": modules
            }

        try:
            course_insert = supabase.table("course_plans").insert({
                "user_id": current_user.id,
                "document_id": docs[0].get("id") if docs else None,
                "title": generated["course_title"],
                "overview": generated["overview"],
                "start_date": data.start_date,
                "duration_days": data.duration_days
            }).execute()
            if not course_insert.data:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save course")
            course_id = course_insert.data[0]["id"]

            for payload in modules_payload:
                payload["course_id"] = course_id
            supabase.table("course_modules").insert(modules_payload).execute()

            # Auto-create a stored quiz whenever a new course is generated.
            auto_quiz_system = load_prompt_text("system/quiz_generation_system.md", {"{QUESTION_COUNT}": "10"})
            auto_quiz_user = load_prompt_text(
                "system/quiz_generation_user.md",
                {
                    "{TOPIC}": generated["course_title"],
                    "{USER_REQUEST}": "Mastery check quiz aligned to the generated course plan.",
                    "{MATERIAL}": (
                        generated["overview"] + "\n\n" +
                        "\n\n".join([
                            f"{m['title']}\nLesson: {m['lesson']}\nPractice: {m['practice']}" for m in generated["modules"]
                        ])
                    )[:9000]
                }
            )
            quiz_resp = openai_client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": auto_quiz_system},
                    {"role": "user", "content": auto_quiz_user},
                ],
                max_tokens=1400,
                temperature=0.5
            )
            quiz_text = (quiz_resp.choices[0].message.content or "").strip()
            quiz_insert = supabase.table("saved_quizzes").insert({
                "user_id": current_user.id,
                "title": f"{generated['course_title']} Quiz",
                "content": quiz_text,
                "source_course_id": course_id,
                "source_module_id": None,
            }).execute()
            auto_quiz_id = quiz_insert.data[0]["id"] if quiz_insert.data else None

            return {
                "success": True,
                "course_id": course_id,
                "title": generated["course_title"],
                "module_count": len(modules_payload),
                "auto_quiz_id": auto_quiz_id
            }
        except Exception as db_err:
            if OFFLINE_AUTH_FALLBACK:
                logger.warning("Course save failed; returning offline/transient course: %s", db_err)
                offline_course_id = f"offline-{uuid.uuid4()}"
                modules = []
                for payload in modules_payload:
                    modules.append({
                        "id": f"offline-module-{uuid.uuid4()}",
                        "day_index": payload["day_index"],
                        "task_date": payload["task_date"],
                        "title": payload["title"],
                        "lesson_content": payload["lesson_content"],
                        "practice_content": payload["practice_content"],
                        "quiz_content": payload["quiz_content"],
                    })
                return {
                    "success": True,
                    "offline": True,
                    "course_id": offline_course_id,
                    "title": generated["course_title"],
                    "module_count": len(modules),
                    "auto_quiz_id": None,
                    "course": {
                        "id": offline_course_id,
                        "title": generated["course_title"],
                        "overview": generated["overview"],
                        "start_date": data.start_date,
                        "duration_days": data.duration_days,
                        "created_at": datetime.utcnow().isoformat()
                    },
                    "modules": modules
                }
            raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Generate course error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate course")


@router.get("/api/courses")
async def list_courses(current_user=Depends(get_current_user)):
    try:
        rows = supabase.table("course_plans").select("id, title, overview, start_date, duration_days, created_at").eq(
            "user_id", current_user.id).order("created_at", desc=True).execute()
        return {"courses": rows.data or []}
    except Exception as e:
        logger.error(f"List courses error: {e}")
        return {"courses": []}


@router.get("/api/courses/{course_id}")
async def get_course(course_id: str, current_user=Depends(get_current_user)):
    try:
        course = supabase.table("course_plans").select(
            "id, title, overview, start_date, duration_days, created_at"
        ).eq("user_id", current_user.id).eq("id", course_id).limit(1).execute()
        if not course.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
        modules = supabase.table("course_modules").select(
            "id, day_index, task_date, title, lesson_content, practice_content, quiz_content"
        ).eq("user_id", current_user.id).eq("course_id", course_id).order("day_index", desc=False).execute()
        return {"course": course.data[0], "modules": modules.data or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get course error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load course")


@router.delete("/api/courses/{course_id}")
async def delete_course(course_id: str, current_user=Depends(get_current_user)):
    try:
        check = supabase.table("course_plans").select("id").eq("user_id", current_user.id).eq("id", course_id).limit(1).execute()
        if not check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        supabase.table("saved_quizzes").delete().eq("user_id", current_user.id).eq("source_course_id", course_id).execute()
        supabase.table("course_modules").delete().eq("user_id", current_user.id).eq("course_id", course_id).execute()
        supabase.table("course_plans").delete().eq("user_id", current_user.id).eq("id", course_id).execute()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete course error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete course")


@router.patch("/api/course-modules/{module_id}")
async def update_course_module(module_id: str, data: UpdateCourseModuleData, current_user=Depends(get_current_user)):
    try:
        patch_data: Dict[str, Any] = {}
        if data.title and data.title.strip():
            patch_data["title"] = data.title.strip()
        if data.task_date:
            parsed_date = parse_iso_date_or_none(data.task_date.strip())
            if not parsed_date:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid task_date format")
            patch_data["task_date"] = parsed_date.isoformat()

        if not patch_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes provided")

        check = supabase.table("course_modules").select("id").eq("user_id", current_user.id).eq("id", module_id).limit(1).execute()
        if not check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

        updated = supabase.table("course_modules").update(patch_data).eq("user_id", current_user.id).eq("id", module_id).execute()
        row = updated.data[0] if updated.data else None
        return {"success": True, "module": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update module error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update module")


@router.get("/api/course-modules")
async def list_course_modules(current_user=Depends(get_current_user)):
    try:
        rows = supabase.table("course_modules").select(
            "id, course_id, task_date, day_index, title"
        ).eq("user_id", current_user.id).order("task_date", desc=False).order("day_index", desc=False).execute()
        return {"modules": rows.data or []}
    except Exception as e:
        logger.error(f"List course modules error: {e}")
        return {"modules": []}
