import json
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import EvaluateQuizAnswerData, GenerateQuizData
from app.runtime import get_main_attr

OFFLINE_AUTH_FALLBACK = get_main_attr("OFFLINE_AUTH_FALLBACK")
SUPABASE_AVAILABLE = get_main_attr("SUPABASE_AVAILABLE")
config = get_main_attr("config")
get_current_user = get_main_attr("get_current_user")
get_user_documents_for_course = get_main_attr("get_user_documents_for_course")
load_prompt_text = get_main_attr("load_prompt_text")
logger = get_main_attr("logger")
openai_client = get_main_attr("openai_client")
supabase = get_main_attr("supabase")

router = APIRouter()

@router.post("/api/quizzes/generate")
async def generate_quiz(data: GenerateQuizData, current_user=Depends(get_current_user)):
    try:
        source_topic = (data.topic or "Quiz").strip()
        material = ""
        source_course_id = None
        source_module_id = None

        if data.document_ids:
            docs, merged_topic, merged_content = get_user_documents_for_course(current_user.id, data.document_ids)
            source_topic = data.topic or merged_topic
            material = merged_content
            source_course_id = None
            source_module_id = None
        else:
            source_topic = (data.topic or data.request or "General knowledge quiz").strip()
            material = f"No user notes were provided. Generate a high-quality quiz from general knowledge on: {source_topic}."

        system_prompt = load_prompt_text("system/quiz_generation_system.md", {"{QUESTION_COUNT}": str(data.question_count)})
        user_prompt = load_prompt_text(
            "system/quiz_generation_user.md",
            {
                "{TOPIC}": source_topic,
                "{MATERIAL}": material[:9000],
                "{USER_REQUEST}": (data.request or "").strip()[:2000] or "None"
            }
        )

        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1400,
            temperature=0.5
        )
        quiz_text = (response.choices[0].message.content or "").strip()

        offline_quiz = {
            "id": f"offline-quiz-{uuid.uuid4()}",
            "title": f"{source_topic} Quiz",
            "content": quiz_text,
            "source_course_id": source_course_id,
            "source_module_id": source_module_id,
            "created_at": datetime.utcnow().isoformat()
        }
        if not SUPABASE_AVAILABLE or not supabase:
            return {"success": True, "offline": True, "quiz": offline_quiz}

        quiz_row = supabase.table("saved_quizzes").insert({
            "user_id": current_user.id,
            "title": f"{source_topic} Quiz",
            "content": quiz_text,
            "source_course_id": source_course_id,
            "source_module_id": source_module_id,
        }).execute()

        if not quiz_row.data:
            if OFFLINE_AUTH_FALLBACK:
                return {"success": True, "offline": True, "quiz": offline_quiz}
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save quiz")

        return {"success": True, "quiz": quiz_row.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Generate quiz error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate quiz")


@router.post("/api/quizzes/evaluate-answer")
async def evaluate_quiz_answer(data: EvaluateQuizAnswerData, current_user=Depends(get_current_user)):
    try:
        quiz_row = supabase.table("saved_quizzes").select(
            "id, title, content"
        ).eq("user_id", current_user.id).eq("id", data.quiz_id).limit(1).execute()

        if not quiz_row.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

        quiz = quiz_row.data[0]
        system_prompt = (
            "You are a strict, high-standards exam grader.\n"
            "Return ONLY valid JSON with this exact schema:\n"
            "{\n"
            "  \"correctness\": \"correct|partially_correct|incorrect\",\n"
            "  \"is_exam_acceptable\": true,\n"
            "  \"verdict\": \"string\",\n"
            "  \"what_was_good\": \"string\",\n"
            "  \"improvements\": [\"string\", \"string\"],\n"
            "  \"ideal_answer\": \"string\"\n"
            "}\n"
            "Rules:\n"
            "- Grade the student's answer against the quiz question and quiz context.\n"
            "- Use strict marking: do NOT give benefit of the doubt.\n"
            "- Do NOT assume implied knowledge. If a required concept is missing, penalize it.\n"
            "- `correct` only if the response is fully accurate, sufficiently complete, and precise.\n"
            "- `partially_correct` if some core ideas are right but details/precision/completeness are lacking.\n"
            "- `incorrect` if core understanding is wrong, vague, or off-topic.\n"
            "- `is_exam_acceptable` should be true only if the answer would likely earn strong marks.\n"
            "- If wording is ambiguous, grade conservatively.\n"
            "- `verdict` must be one short sentence.\n"
            "- `what_was_good` should be concise.\n"
            "- `improvements` should contain 2-4 specific bullet points.\n"
            "- `ideal_answer` should be exam-ready but concise.\n"
            "- Never include markdown/code fences.\n"
        )
        user_prompt = (
            f"Quiz title: {quiz.get('title') or 'Quiz'}\n"
            f"Question number: {data.question_index or 'unknown'} / {data.total_questions or 'unknown'}\n\n"
            f"Question:\n{data.question}\n\n"
            f"Student answer:\n{data.user_answer}\n\n"
            f"Quiz content/context:\n{(quiz.get('content') or '')[:12000]}"
        )

        response = openai_client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=700,
            temperature=0.05
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()

        parsed = json.loads(raw)
        correctness = str(parsed.get("correctness") or "partially_correct").strip().lower()
        if correctness not in {"correct", "partially_correct", "incorrect"}:
            correctness = "partially_correct"

        improvements = parsed.get("improvements")
        if not isinstance(improvements, list):
            improvements = []
        improvements = [str(item).strip()[:300] for item in improvements if str(item).strip()][:4]

        return {
            "success": True,
            "evaluation": {
                "correctness": correctness,
                "is_exam_acceptable": bool(parsed.get("is_exam_acceptable", False)),
                "verdict": str(parsed.get("verdict") or "Answer reviewed.").strip()[:240],
                "what_was_good": str(parsed.get("what_was_good") or "").strip()[:1200],
                "improvements": improvements,
                "ideal_answer": str(parsed.get("ideal_answer") or "").strip()[:3000],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Evaluate quiz answer error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate answer"
        )


@router.get("/api/quizzes")
async def list_quizzes(current_user=Depends(get_current_user)):
    try:
        rows = supabase.table("saved_quizzes").select(
            "id, title, content, source_course_id, source_module_id, created_at"
        ).eq("user_id", current_user.id).order("created_at", desc=True).execute()
        return {"quizzes": rows.data or []}
    except Exception as e:
        logger.error(f"List quizzes error: {e}")
        return {"quizzes": []}


@router.delete("/api/quizzes/{quiz_id}")
async def delete_quiz(quiz_id: str, current_user=Depends(get_current_user)):
    try:
        check = supabase.table("saved_quizzes").select("id").eq("user_id", current_user.id).eq("id", quiz_id).limit(
            1).execute()
        if not check.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
        supabase.table("saved_quizzes").delete().eq("user_id", current_user.id).eq("id", quiz_id).execute()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete quiz error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete quiz")
