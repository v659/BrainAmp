import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.helpers import get_planner_state_from_metadata, is_valid_time_hhmm, parse_iso_date_or_none
from app.schemas import PlannerBusySlotData, PlannerCommandData, PlannerReminderData, PlannerTaskData
from app.runtime import get_main_attr

get_current_user = get_main_attr("get_current_user")
logger = get_main_attr("logger")
resolve_course_module_for_user = get_main_attr("resolve_course_module_for_user")
supabase = get_main_attr("supabase")

router = APIRouter()

@router.get("/api/calendar")
async def get_calendar(month: Optional[str] = None, current_user=Depends(get_current_user)):
    """Get calendar tasks (course modules) for month YYYY-MM."""
    try:
        today = datetime.now().date()
        if month and re.match(r"^\d{4}-\d{2}$", month):
            year, mon = month.split("-")
            start_day = date(int(year), int(mon), 1)
        else:
            start_day = date(today.year, today.month, 1)

        if start_day.month == 12:
            end_day = date(start_day.year + 1, 1, 1)
        else:
            end_day = date(start_day.year, start_day.month + 1, 1)

        rows = supabase.table("course_modules").select(
            "id, course_id, task_date, title, day_index"
        ).eq("user_id", current_user.id).gte("task_date", start_day.isoformat()).lt("task_date",
                                                                                     end_day.isoformat()).order(
            "task_date", desc=False).order("day_index", desc=False).execute()

        grouped: Dict[str, list] = {}
        for row in rows.data or []:
            d = row.get("task_date")
            grouped.setdefault(d, []).append({
                **row,
                "item_type": "course_module"
            })

        planner_state = get_planner_state_from_metadata(current_user.user_metadata or {})
        for busy in planner_state["busy_slots"]:
            d = str(busy.get("date") or "")
            if not d or d < start_day.isoformat() or d >= end_day.isoformat():
                continue
            grouped.setdefault(d, []).append({
                "id": busy.get("id"),
                "item_type": "busy_slot",
                "title": busy.get("title") or "Busy",
                "start_time": busy.get("start_time"),
                "end_time": busy.get("end_time"),
            })
        for task in planner_state["custom_tasks"]:
            d = str(task.get("date") or "")
            if not d or d < start_day.isoformat() or d >= end_day.isoformat():
                continue
            grouped.setdefault(d, []).append({
                "id": task.get("id"),
                "item_type": "custom_task",
                "title": task.get("title") or "Task",
                "time": task.get("time"),
                "notes": task.get("notes"),
            })
        for rem in planner_state["reminders"]:
            d = str(rem.get("date") or "")
            if not d or d < start_day.isoformat() or d >= end_day.isoformat():
                continue
            grouped.setdefault(d, []).append({
                "id": rem.get("id"),
                "item_type": "reminder",
                "title": rem.get("text") or "Reminder",
                "time": rem.get("time"),
                "target_type": rem.get("target_type"),
                "target_id": rem.get("target_id"),
            })

        return {
            "month": start_day.strftime("%Y-%m"),
            "days": grouped
        }
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return {"month": month or datetime.now().strftime("%Y-%m"), "days": {}}


@router.get("/api/calendar/day/{day_text}")
async def get_calendar_day(day_text: str, current_user=Depends(get_current_user)):
    try:
        day = parse_iso_date_or_none(day_text)
        if not day:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid day format")
        rows = supabase.table("course_modules").select(
            "id, course_id, task_date, title, day_index, lesson_content, practice_content, quiz_content"
        ).eq("user_id", current_user.id).eq("task_date", day.isoformat()).order("day_index", desc=False).execute()
        items = [{
            **row,
            "item_type": "course_module"
        } for row in (rows.data or [])]

        planner_state = get_planner_state_from_metadata(current_user.user_metadata or {})
        for busy in planner_state["busy_slots"]:
            if str(busy.get("date") or "") != day.isoformat():
                continue
            items.append({
                "id": busy.get("id"),
                "item_type": "busy_slot",
                "title": busy.get("title") or "Busy",
                "start_time": busy.get("start_time"),
                "end_time": busy.get("end_time"),
            })
        for task in planner_state["custom_tasks"]:
            if str(task.get("date") or "") != day.isoformat():
                continue
            items.append({
                "id": task.get("id"),
                "item_type": "custom_task",
                "title": task.get("title") or "Task",
                "time": task.get("time"),
                "notes": task.get("notes"),
            })
        for rem in planner_state["reminders"]:
            if str(rem.get("date") or "") != day.isoformat():
                continue
            items.append({
                "id": rem.get("id"),
                "item_type": "reminder",
                "title": rem.get("text") or "Reminder",
                "time": rem.get("time"),
                "target_type": rem.get("target_type"),
                "target_id": rem.get("target_id"),
            })

        def item_sort_key(it):
            if it.get("item_type") == "course_module":
                return ("", int(it.get("day_index") or 0))
            t = str(it.get("time") or it.get("start_time") or "99:99")
            return (t, 999)

        items = sorted(items, key=item_sort_key)
        return {"day": day.isoformat(), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar day error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load day")


def persist_planner_state(current_user, planner_state: Dict[str, List[Dict[str, Any]]]) -> None:
    user_metadata = current_user.user_metadata or {}
    merged_metadata = {**user_metadata, "planner_state": planner_state}
    result = supabase.auth.update_user({"data": merged_metadata})
    if not result or not result.user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to save planner data")


@router.post("/api/planner/busy")
async def add_busy_slot(data: PlannerBusySlotData, current_user=Depends(get_current_user)):
    try:
        day = parse_iso_date_or_none(data.date)
        if not day:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")
        if not is_valid_time_hhmm(data.start_time) or not is_valid_time_hhmm(data.end_time):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format")
        if data.start_time >= data.end_time:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_time must be after start_time")

        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        item = {
            "id": str(uuid.uuid4()),
            "date": day.isoformat(),
            "start_time": data.start_time,
            "end_time": data.end_time,
            "title": (data.title or "Busy").strip()[:120]
        }
        state["busy_slots"] = [item] + state["busy_slots"][:249]
        persist_planner_state(current_user, state)
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add busy slot error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add busy slot")


@router.delete("/api/planner/busy/{slot_id}")
async def delete_busy_slot(slot_id: str, current_user=Depends(get_current_user)):
    try:
        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        original = state["busy_slots"]
        filtered = [x for x in original if str(x.get("id")) != slot_id]
        if len(filtered) == len(original):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busy slot not found")
        state["busy_slots"] = filtered
        persist_planner_state(current_user, state)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete busy slot error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete busy slot")


@router.post("/api/planner/task")
async def add_custom_task(data: PlannerTaskData, current_user=Depends(get_current_user)):
    try:
        day = parse_iso_date_or_none(data.date)
        if not day:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")
        if data.time and not is_valid_time_hhmm(data.time):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format")

        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        item = {
            "id": str(uuid.uuid4()),
            "date": day.isoformat(),
            "title": data.title.strip()[:180],
            "time": (data.time or "").strip() or None,
            "notes": (data.notes or "").strip()[:1000] or None
        }
        state["custom_tasks"] = [item] + state["custom_tasks"][:249]
        persist_planner_state(current_user, state)
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add custom task error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add task")


@router.delete("/api/planner/task/{task_id}")
async def delete_custom_task(task_id: str, current_user=Depends(get_current_user)):
    try:
        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        original = state["custom_tasks"]
        filtered = [x for x in original if str(x.get("id")) != task_id]
        if len(filtered) == len(original):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        state["custom_tasks"] = filtered
        persist_planner_state(current_user, state)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete custom task error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete task")


@router.post("/api/planner/reminder")
async def add_reminder(data: PlannerReminderData, current_user=Depends(get_current_user)):
    try:
        day = parse_iso_date_or_none(data.date)
        if not day:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")
        if not is_valid_time_hhmm(data.time):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time format")

        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        item = {
            "id": str(uuid.uuid4()),
            "date": day.isoformat(),
            "time": data.time,
            "text": data.text.strip()[:240],
            "target_type": (data.target_type or "").strip()[:40] or None,
            "target_id": (data.target_id or "").strip()[:120] or None
        }
        state["reminders"] = [item] + state["reminders"][:249]
        persist_planner_state(current_user, state)
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add reminder error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add reminder")


@router.delete("/api/planner/reminder/{reminder_id}")
async def delete_reminder(reminder_id: str, current_user=Depends(get_current_user)):
    try:
        state = get_planner_state_from_metadata(current_user.user_metadata or {})
        original = state["reminders"]
        filtered = [x for x in original if str(x.get("id")) != reminder_id]
        if len(filtered) == len(original):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
        state["reminders"] = filtered
        persist_planner_state(current_user, state)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete reminder error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete reminder")


@router.post("/api/planner/command")
async def planner_command(data: PlannerCommandData, current_user=Depends(get_current_user)):
    raw = data.command.strip()
    try:
        schedule_match = re.search(
            r"^(?:when\s+is|what\s+day\s+is|is)\s+(.+?)\s+scheduled(?:\s+for)?\??$",
            raw,
            flags=re.IGNORECASE
        )
        if schedule_match:
            ident = schedule_match.group(1).strip().strip("\"'")
            module = resolve_course_module_for_user(current_user.id, ident, need_task_date=True)
            if not module:
                return {
                    "success": True,
                    "message": f"I couldn't find a scheduled module matching '{ident}'."
                }

            day_text = str(module.get("task_date") or "")
            pretty = day_text
            try:
                pretty = datetime.strptime(day_text, "%Y-%m-%d").strftime("%A, %B %d, %Y")
            except ValueError:
                pass
            return {
                "success": True,
                "message": f"'{module.get('title') or ident}' is scheduled for {pretty}."
            }

        move_match = re.search(r"^move\s+(.+?)\s+to\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?$", raw, flags=re.IGNORECASE)
        if move_match:
            ident = move_match.group(1).strip().strip("\"'")
            day_text = move_match.group(2).strip()
            time_text = (move_match.group(3) or "").strip() or None
            parsed_day = parse_iso_date_or_none(day_text)
            if not parsed_day:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target date")
            module = resolve_course_module_for_user(current_user.id, ident, need_task_date=False)
            if not module:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching module found")

            supabase.table("course_modules").update({"task_date": parsed_day.isoformat()}).eq("user_id", current_user.id).eq("id", module["id"]).execute()
            if time_text and is_valid_time_hhmm(time_text):
                state = get_planner_state_from_metadata(current_user.user_metadata or {})
                rem = {
                    "id": str(uuid.uuid4()),
                    "date": parsed_day.isoformat(),
                    "time": time_text,
                    "text": f"Work on {module.get('title') or 'module'}",
                    "target_type": "course_module",
                    "target_id": module["id"]
                }
                state["reminders"] = [rem] + state["reminders"][:249]
                persist_planner_state(current_user, state)
            return {"success": True, "message": f"Moved '{module.get('title')}' to {parsed_day.isoformat()}."}

        task_match = re.search(r"^add\s+task\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})(?:\s+at\s+(\d{1,2}:\d{2}))?$", raw, flags=re.IGNORECASE)
        if task_match:
            title = task_match.group(1).strip()
            day_text = task_match.group(2).strip()
            time_text = (task_match.group(3) or "").strip() or None
            day = parse_iso_date_or_none(day_text)
            if not day:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")
            if time_text and not is_valid_time_hhmm(time_text):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time")
            state = get_planner_state_from_metadata(current_user.user_metadata or {})
            item = {
                "id": str(uuid.uuid4()),
                "date": day.isoformat(),
                "title": title[:180],
                "time": time_text,
                "notes": None
            }
            state["custom_tasks"] = [item] + state["custom_tasks"][:249]
            persist_planner_state(current_user, state)
            return {"success": True, "message": f"Added task '{title}' on {day.isoformat()}."}

        busy_match = re.search(r"^mark\s+(.+?)\s+busy\s+on\s+(\d{4}-\d{2}-\d{2})\s+from\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})$", raw, flags=re.IGNORECASE)
        if busy_match:
            title = busy_match.group(1).strip() or "Busy"
            day = parse_iso_date_or_none(busy_match.group(2).strip())
            start_t = busy_match.group(3).strip()
            end_t = busy_match.group(4).strip()
            if not day or not is_valid_time_hhmm(start_t) or not is_valid_time_hhmm(end_t):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid busy slot input")
            state = get_planner_state_from_metadata(current_user.user_metadata or {})
            item = {
                "id": str(uuid.uuid4()),
                "date": day.isoformat(),
                "start_time": start_t,
                "end_time": end_t,
                "title": title[:120]
            }
            state["busy_slots"] = [item] + state["busy_slots"][:249]
            persist_planner_state(current_user, state)
            return {"success": True, "message": f"Marked '{title}' busy on {day.isoformat()} from {start_t} to {end_t}."}

        remind_match = re.search(r"^remind\s+me\s+to\s+(.+?)\s+on\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d{1,2}:\d{2})$", raw, flags=re.IGNORECASE)
        if remind_match:
            text_body = remind_match.group(1).strip()
            day = parse_iso_date_or_none(remind_match.group(2).strip())
            t = remind_match.group(3).strip()
            if not day or not is_valid_time_hhmm(t):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reminder input")
            state = get_planner_state_from_metadata(current_user.user_metadata or {})
            item = {
                "id": str(uuid.uuid4()),
                "date": day.isoformat(),
                "time": t,
                "text": text_body[:240],
                "target_type": None,
                "target_id": None
            }
            state["reminders"] = [item] + state["reminders"][:249]
            persist_planner_state(current_user, state)
            return {"success": True, "message": f"Reminder set for {day.isoformat()} at {t}."}

        return {"success": False, "message": "No planner action matched. Try: 'move <module> to YYYY-MM-DD HH:MM'."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Planner command error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to run planner command")
