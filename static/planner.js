function ensureAuthOrRedirect() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/login";
        return false;
    }
    return true;
}

function toMonthKey(d) {
    const m = String(d.getMonth() + 1).padStart(2, "0");
    return `${d.getFullYear()}-${m}`;
}

function parseMonthKey(monthKey) {
    const [y, m] = monthKey.split("-").map(Number);
    return new Date(y, m - 1, 1);
}

function fmtDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

let calendarState = { month: new Date(), days: {} };
const PLANNER_CHAT_DRAFT_KEY = "chat_draft_v1";
let selectedCalendarDay = null;
let selectedCourseId = null;

async function loadCalendarMonth(monthKey) {
    const res = await authenticatedFetch(`/api/calendar?month=${monthKey}`);
    if (!res.ok) return;
    const data = await res.json();
    calendarState.month = parseMonthKey(data.month);
    calendarState.days = data.days || {};
    renderCalendarGrid();
    renderCalendarDayList();
}

function renderCalendarGrid() {
    const grid = document.getElementById("calendar-grid");
    const label = document.getElementById("month-label");
    if (!grid || !label) return;

    const month = calendarState.month;
    label.textContent = month.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    grid.innerHTML = "";

    const firstDay = new Date(month.getFullYear(), month.getMonth(), 1);
    const lastDay = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    const blanks = firstDay.getDay();

    for (let i = 0; i < blanks; i += 1) {
        const blank = document.createElement("div");
        grid.appendChild(blank);
    }

    for (let day = 1; day <= lastDay.getDate(); day += 1) {
        const d = new Date(month.getFullYear(), month.getMonth(), day);
        const key = fmtDate(d);
        const tasks = calendarState.days[key] || [];

        const cell = document.createElement("div");
        cell.className = "day-cell";
        cell.innerHTML = `<div class=\"num\">${day}</div><div class=\"count\">${tasks.length} task(s)</div>`;
        cell.onclick = () => selectCalendarDay(key);
        grid.appendChild(cell);
    }
}

function renderCalendarDayList() {
    const list = document.getElementById("day-list");
    if (!list) return;
    list.innerHTML = "";

    const keys = Object.keys(calendarState.days).sort();
    if (!keys.length) {
        list.innerHTML = `<div class="list-item">No scheduled items this month.</div>`;
        return;
    }

    keys.forEach(k => {
        const tasks = calendarState.days[k] || [];
        const item = document.createElement("div");
        item.className = "list-item";
        item.textContent = `${k} • ${tasks.length} task(s)`;
        item.onclick = () => selectCalendarDay(k);
        list.appendChild(item);
    });
}

async function selectCalendarDay(dayKey) {
    selectedCalendarDay = dayKey;
    const res = await authenticatedFetch(`/api/calendar/day/${dayKey}`);
    if (!res.ok) return;
    const data = await res.json();

    const title = document.getElementById("day-title");
    const items = document.getElementById("day-items");
    if (!title || !items) return;

    title.textContent = `Plan for ${data.day}`;
    items.innerHTML = "";
    ["task-date", "busy-date", "reminder-date"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = data.day;
    });

    if (!(data.items || []).length) {
        items.innerHTML = `<div class="day-task">No tasks for this day.</div>`;
        return;
    }

    (data.items || []).forEach(it => {
        const card = document.createElement("div");
        card.className = "day-task";
        if (it.item_type === "course_module") {
            card.innerHTML = `
                <div class="title">${it.title}</div>
                <div class="meta">Course: ${it.course_id} • Day ${it.day_index}</div>
                <div class="actions">
                    <a href="/courses?course_id=${it.course_id}&module_id=${it.id}">Open in Courses</a>
                </div>
            `;
        } else if (it.item_type === "busy_slot") {
            card.innerHTML = `
                <div class="title">${it.title}</div>
                <div class="meta">Busy: ${it.start_time || "--:--"} - ${it.end_time || "--:--"}</div>
                <div class="actions">
                    <button type="button" data-delete-busy="${it.id}">Delete</button>
                </div>
            `;
        } else if (it.item_type === "custom_task") {
            card.innerHTML = `
                <div class="title">${it.title}</div>
                <div class="meta">Task${it.time ? ` at ${it.time}` : ""}${it.notes ? ` • ${it.notes}` : ""}</div>
                <div class="actions">
                    <button type="button" data-delete-task="${it.id}">Delete</button>
                </div>
            `;
        } else if (it.item_type === "reminder") {
            card.innerHTML = `
                <div class="title">${it.title}</div>
                <div class="meta">Reminder at ${it.time || "--:--"}</div>
                <div class="actions">
                    <button type="button" data-delete-reminder="${it.id}">Delete</button>
                </div>
            `;
        }
        items.appendChild(card);
    });

    items.querySelectorAll("[data-delete-busy]").forEach(btn => {
        btn.addEventListener("click", async () => {
            const id = btn.getAttribute("data-delete-busy");
            await authenticatedFetch(`/api/planner/busy/${id}`, { method: "DELETE" });
            await refreshCalendarViews();
        });
    });
    items.querySelectorAll("[data-delete-task]").forEach(btn => {
        btn.addEventListener("click", async () => {
            const id = btn.getAttribute("data-delete-task");
            await authenticatedFetch(`/api/planner/task/${id}`, { method: "DELETE" });
            await refreshCalendarViews();
        });
    });
    items.querySelectorAll("[data-delete-reminder]").forEach(btn => {
        btn.addEventListener("click", async () => {
            const id = btn.getAttribute("data-delete-reminder");
            await authenticatedFetch(`/api/planner/reminder/${id}`, { method: "DELETE" });
            await refreshCalendarViews();
        });
    });
}

async function refreshCalendarViews() {
    await loadCalendarMonth(toMonthKey(calendarState.month));
    if (selectedCalendarDay) {
        await selectCalendarDay(selectedCalendarDay);
    }
}

async function addTaskFromUI() {
    const title = (document.getElementById("task-title")?.value || "").trim();
    const date = (document.getElementById("task-date")?.value || "").trim();
    const time = (document.getElementById("task-time")?.value || "").trim();
    if (!title || !date) return;
    await authenticatedFetch("/api/planner/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, date, time: time || null })
    });
    document.getElementById("task-title").value = "";
    await refreshCalendarViews();
}

async function addBusyFromUI() {
    const title = (document.getElementById("busy-title")?.value || "").trim();
    const date = (document.getElementById("busy-date")?.value || "").trim();
    const start = (document.getElementById("busy-start")?.value || "").trim();
    const end = (document.getElementById("busy-end")?.value || "").trim();
    if (!date || !start || !end) return;
    await authenticatedFetch("/api/planner/busy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title || "Busy", date, start_time: start, end_time: end })
    });
    await refreshCalendarViews();
}

async function addReminderFromUI() {
    const text = (document.getElementById("reminder-text")?.value || "").trim();
    const date = (document.getElementById("reminder-date")?.value || "").trim();
    const time = (document.getElementById("reminder-time")?.value || "").trim();
    if (!text || !date || !time) return;
    await authenticatedFetch("/api/planner/reminder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, date, time })
    });
    document.getElementById("reminder-text").value = "";
    await refreshCalendarViews();
}

async function loadCoursesList(selectedId = null) {
    const list = document.getElementById("courses-list");
    if (!list) return;
    const res = await authenticatedFetch("/api/courses");
    if (!res.ok) return;
    const data = await res.json();
    const courses = data.courses || [];

    list.innerHTML = "";
    if (!courses.length) {
        list.innerHTML = `<div class="list-item">No courses yet.</div>`;
        return;
    }

    courses.forEach(c => {
        const item = document.createElement("div");
        item.className = `list-item${selectedId === c.id ? " active" : ""}`;
        item.innerHTML = `<strong>${c.title}</strong><br><small>${c.start_date} • ${c.duration_days} days</small>`;
        item.onclick = () => openCourse(c.id);
        list.appendChild(item);
    });
}

async function openCourse(courseId) {
    selectedCourseId = courseId;
    const res = await authenticatedFetch(`/api/courses/${courseId}`);
    if (!res.ok) return;
    const data = await res.json();
    const course = data.course;
    const modules = data.modules || [];

    document.getElementById("course-empty")?.classList.add("hidden");
    document.getElementById("course-view")?.classList.remove("hidden");
    document.getElementById("course-view-title").textContent = course.title;
    document.getElementById("course-view-overview").textContent = course.overview || "";
    const deeperBtn = document.getElementById("course-go-deeper-btn");
    if (deeperBtn) {
        deeperBtn.onclick = () => goDeeperFromCourse(course, modules);
    }
    const deleteCourseBtn = document.getElementById("delete-course-btn");
    if (deleteCourseBtn) {
        deleteCourseBtn.onclick = async () => {
            const ok = confirm(`Delete course "${course.title}" and related modules/quizzes?`);
            if (!ok) return;
            const delRes = await authenticatedFetch(`/api/courses/${courseId}`, { method: "DELETE" });
            if (!delRes.ok) return;
            selectedCourseId = null;
            document.getElementById("course-view")?.classList.add("hidden");
            document.getElementById("course-empty")?.classList.remove("hidden");
            await loadCoursesList();
        };
    }

    const moduleWrap = document.getElementById("course-modules");
    moduleWrap.innerHTML = "";
    const params = new URLSearchParams(window.location.search);
    const activeModuleId = params.get("module_id");

    modules.forEach(m => {
        const card = document.createElement("div");
        card.className = "module-card";
        if (activeModuleId && activeModuleId === m.id) {
            card.classList.add("active");
        }
        card.innerHTML = `
            <div class="module-head">
                <div class="module-title">${m.title}</div>
                <div class="module-day">Day ${m.day_index} • ${m.task_date}</div>
            </div>
            <div class="module-edit">
                <input type="text" class="module-title-input" value="${escapeHtml(m.title || "")}" />
                <input type="date" class="module-date-input" value="${m.task_date || ""}" />
                <button class="btn ghost module-save-btn" type="button">Save</button>
            </div>
            <div class="module-actions">
                <button class="btn module-deeper-btn" type="button">Go Deeper</button>
            </div>
            <div class="module-section"><h4>Lesson</h4><p>${m.lesson_content || ""}</p></div>
            <div class="module-section"><h4>Practice</h4><p>${m.practice_content || ""}</p></div>
            <div class="module-section"><h4>Quick Quiz</h4><p>${m.quiz_content || ""}</p></div>
        `;
        const moduleDeeperBtn = card.querySelector(".module-deeper-btn");
        if (moduleDeeperBtn) {
            moduleDeeperBtn.onclick = () => goDeeperFromCourse(course, [m], modules);
        }
        const moduleSaveBtn = card.querySelector(".module-save-btn");
        if (moduleSaveBtn) {
            moduleSaveBtn.onclick = async () => {
                const newTitle = (card.querySelector(".module-title-input")?.value || "").trim();
                const newDate = (card.querySelector(".module-date-input")?.value || "").trim();
                const patchBody = {};
                if (newTitle && newTitle !== (m.title || "")) patchBody.title = newTitle;
                if (newDate && newDate !== (m.task_date || "")) patchBody.task_date = newDate;
                if (!Object.keys(patchBody).length) return;
                const patchRes = await authenticatedFetch(`/api/course-modules/${m.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(patchBody)
                });
                if (!patchRes.ok) return;
                await openCourse(courseId);
            };
        }
        moduleWrap.appendChild(card);
    });

    await loadCoursesList(courseId);
}

let selectedQuiz = null;
let quizSession = {
    questions: [],
    index: 0,
    evaluated: false
};

function extractQuizQuestions(content) {
    const rawLines = String(content || "").split(/\r?\n/);
    const lines = rawLines.map(line => line.trim()).filter(Boolean);
    if (!lines.length) return [];

    const questions = [];
    let current = "";
    let inAnswerKey = false;
    const questionStart = /^(?:q(?:uestion)?\s*\d+[\)\.: -]+|\d+[\)\.: -]+)\s*/i;

    for (const line of lines) {
        if (/^(answer\s*key|answers)\b/i.test(line)) {
            inAnswerKey = true;
        }
        if (inAnswerKey) continue;

        if (questionStart.test(line)) {
            if (current) questions.push(current.trim());
            current = line.replace(questionStart, "").trim();
            continue;
        }

        if (!current) {
            if (line.includes("?")) {
                current = line;
            }
            continue;
        }

        if (questionStart.test(line)) {
            questions.push(current.trim());
            current = line.replace(questionStart, "").trim();
        } else {
            current += ` ${line}`;
        }
    }
    if (current) questions.push(current.trim());

    if (questions.length) return questions.slice(0, 40);

    const sentenceQuestions = (content || "").match(/[^?]+\?/g) || [];
    if (sentenceQuestions.length) {
        return sentenceQuestions.map(q => q.trim()).filter(Boolean).slice(0, 40);
    }

    return lines.slice(0, 20);
}

function escapeHtml(raw) {
    const div = document.createElement("div");
    div.textContent = raw || "";
    return div.innerHTML;
}

function buildEvaluationHtml(result) {
    const verdictClass = `verdict-${result.correctness || "partially_correct"}`;
    const improvements = (result.improvements || [])
        .map(item => `<li>${escapeHtml(item)}</li>`)
        .join("");
    const examReady = result.is_exam_acceptable ? "Yes" : "Not yet";

    return `
        <div class="evaluation-card">
            <div class="evaluation-top">
                <span class="verdict-chip ${verdictClass}">${escapeHtml((result.correctness || "").replaceAll("_", " "))}</span>
                <span class="exam-chip">Exam-ready: ${examReady}</span>
            </div>
            <p><strong>Verdict:</strong> ${escapeHtml(result.verdict || "")}</p>
            <p><strong>What you did well:</strong> ${escapeHtml(result.what_was_good || "")}</p>
            ${improvements ? `<div><strong>How to improve:</strong><ul>${improvements}</ul></div>` : ""}
            <div><strong>Model answer:</strong></div>
            <div class="ideal-answer">${typeof renderMarkdown === "function" ? renderMarkdown(result.ideal_answer || "") : escapeHtml(result.ideal_answer || "")}</div>
        </div>
    `;
}

function renderQuizReveal() {
    const target = document.getElementById("quiz-view-content");
    if (!target || !selectedQuiz) return;

    const total = quizSession.questions.length;
    if (!total) {
        target.innerHTML = typeof renderMarkdown === "function"
            ? renderMarkdown(selectedQuiz.content || "")
            : escapeHtml(selectedQuiz.content || "");
        return;
    }

    const i = quizSession.index;
    const qText = quizSession.questions[i] || "";
    const nextDisabled = quizSession.evaluated ? "" : "disabled";

    target.innerHTML = `
        <div class="reveal-wrap">
            <div class="reveal-progress">Question ${i + 1} of ${total}</div>
            <div class="reveal-question">${escapeHtml(qText)}</div>
            <label class="answer-label" for="quiz-answer-input">Your answer (in your own words)</label>
            <textarea id="quiz-answer-input" class="quiz-answer-input" rows="7" placeholder="Type your answer here..."></textarea>
            <div class="reveal-actions">
                <button class="btn ghost" id="quiz-prev-btn" ${i === 0 ? "disabled" : ""}>Previous</button>
                <button class="btn" id="quiz-evaluate-btn">Check Answer</button>
                <button class="btn ghost" id="quiz-next-btn" ${i >= total - 1 ? "disabled" : nextDisabled}>Next</button>
            </div>
            <div id="quiz-eval-result" class="quiz-eval-result"></div>
        </div>
    `;

    document.getElementById("quiz-prev-btn")?.addEventListener("click", () => {
        if (quizSession.index <= 0) return;
        quizSession.index -= 1;
        quizSession.evaluated = false;
        renderQuizReveal();
    });
    document.getElementById("quiz-next-btn")?.addEventListener("click", () => {
        if (!quizSession.evaluated || quizSession.index >= total - 1) return;
        quizSession.index += 1;
        quizSession.evaluated = false;
        renderQuizReveal();
    });
    document.getElementById("quiz-evaluate-btn")?.addEventListener("click", evaluateCurrentAnswer);
}

async function evaluateCurrentAnswer() {
    if (!selectedQuiz || !quizSession.questions.length) return;
    const answerInput = document.getElementById("quiz-answer-input");
    const resultWrap = document.getElementById("quiz-eval-result");
    const evalBtn = document.getElementById("quiz-evaluate-btn");
    if (!answerInput || !resultWrap || !evalBtn) return;

    const userAnswer = answerInput.value.trim();
    if (!userAnswer) {
        resultWrap.innerHTML = `<div class="eval-error">Enter your answer before checking.</div>`;
        return;
    }

    evalBtn.disabled = true;
    resultWrap.innerHTML = `<div class="eval-pending">Reviewing your answer...</div>`;

    try {
        const res = await authenticatedFetch("/api/quizzes/evaluate-answer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                quiz_id: selectedQuiz.id,
                question: quizSession.questions[quizSession.index],
                user_answer: userAnswer,
                question_index: quizSession.index + 1,
                total_questions: quizSession.questions.length
            })
        });

        const data = await res.json();
        if (!res.ok) {
            resultWrap.innerHTML = `<div class="eval-error">${escapeHtml(data.detail || "Failed to evaluate answer.")}</div>`;
            return;
        }

        quizSession.evaluated = true;
        resultWrap.innerHTML = buildEvaluationHtml(data.evaluation || {});

        const nextBtn = document.getElementById("quiz-next-btn");
        if (nextBtn) nextBtn.disabled = quizSession.index >= quizSession.questions.length - 1;
    } catch (err) {
        resultWrap.innerHTML = `<div class="eval-error">Failed to evaluate answer. Please try again.</div>`;
    } finally {
        evalBtn.disabled = false;
    }
}

async function loadQuizzesList(selectedId = null) {
    const list = document.getElementById("quizzes-list");
    if (!list) return;
    const res = await authenticatedFetch("/api/quizzes");
    if (!res.ok) return;
    const data = await res.json();
    const quizzes = data.quizzes || [];

    list.innerHTML = "";
    if (!quizzes.length) {
        list.innerHTML = `<div class="list-item">No quizzes yet.</div>`;
        return;
    }

    quizzes.forEach(q => {
        const item = document.createElement("div");
        item.className = `list-item${selectedId === q.id ? " active" : ""}`;
        item.innerHTML = `<strong>${q.title}</strong><br><small>${new Date(q.created_at).toLocaleString()}</small>`;
        item.onclick = () => openQuiz(q);
        list.appendChild(item);
    });
}

function openQuiz(quiz) {
    selectedQuiz = quiz;
    quizSession = {
        questions: extractQuizQuestions(quiz.content || ""),
        index: 0,
        evaluated: false
    };
    document.getElementById("quiz-empty")?.classList.add("hidden");
    document.getElementById("quiz-view")?.classList.remove("hidden");
    document.getElementById("quiz-view-title").textContent = quiz.title || "Quiz";
    renderQuizReveal();
    loadQuizzesList(quiz.id);
}

async function deleteSelectedQuiz() {
    if (!selectedQuiz) return;
    const ok = confirm(`Delete quiz \"${selectedQuiz.title}\"?`);
    if (!ok) return;

    const res = await authenticatedFetch(`/api/quizzes/${selectedQuiz.id}`, { method: "DELETE" });
    if (!res.ok) {
        alert("Failed to delete quiz.");
        return;
    }

    selectedQuiz = null;
    quizSession = { questions: [], index: 0, evaluated: false };
    document.getElementById("quiz-view")?.classList.add("hidden");
    document.getElementById("quiz-empty")?.classList.remove("hidden");
    await loadQuizzesList();
}

function goDeeperFromCourse(course, targetModules, allModules = null) {
    const modules = allModules && allModules.length ? allModules : targetModules;
    const moduleContext = (modules || []).map((m, idx) => (
        `Module ${idx + 1}: ${m.title || "Untitled"}\n` +
        `Date: ${m.task_date || "N/A"}\n` +
        `Lesson:\n${m.lesson_content || ""}\n\n` +
        `Practice:\n${m.practice_content || ""}\n\n` +
        `Quick Quiz:\n${m.quiz_content || ""}`
    )).join("\n\n---\n\n");

    const focusTitle = targetModules && targetModules.length === 1
        ? (targetModules[0].title || course.title || "this module")
        : (course.title || "this course");
    const prompt = (
        `Help me go deeper into ${focusTitle} using the Socratic method. ` +
        `Ask one probing question at a time, evaluate my responses, and coach me for exam-ready answers.`
    ).trim();
    const deepContext = (
        `Course title: ${course.title || "Untitled course"}\n` +
        `Course overview:\n${course.overview || ""}\n\n` +
        `Course modules context:\n${moduleContext}`
    ).trim();

    localStorage.setItem(PLANNER_CHAT_DRAFT_KEY, JSON.stringify({
        mode: "fundamentals",
        message: prompt.slice(0, 1800),
        extra_context: deepContext.slice(0, 20000)
    }));
    window.location.href = "/chat";
}

async function bootCalendarPage() {
    if (!ensureAuthOrRedirect()) return;

    const month = new Date();
    await loadCalendarMonth(toMonthKey(month));

    document.getElementById("prev-month").onclick = async () => {
        const d = new Date(calendarState.month.getFullYear(), calendarState.month.getMonth() - 1, 1);
        await loadCalendarMonth(toMonthKey(d));
    };
    document.getElementById("next-month").onclick = async () => {
        const d = new Date(calendarState.month.getFullYear(), calendarState.month.getMonth() + 1, 1);
        await loadCalendarMonth(toMonthKey(d));
    };
    document.getElementById("today-btn").onclick = async () => {
        const d = new Date();
        await loadCalendarMonth(toMonthKey(d));
        await selectCalendarDay(fmtDate(d));
    };
    document.getElementById("add-task-btn")?.addEventListener("click", addTaskFromUI);
    document.getElementById("add-busy-btn")?.addEventListener("click", addBusyFromUI);
    document.getElementById("add-reminder-btn")?.addEventListener("click", addReminderFromUI);
}

async function bootCoursesPage() {
    if (!ensureAuthOrRedirect()) return;
    await loadCoursesList();

    const params = new URLSearchParams(window.location.search);
    const courseId = params.get("course_id");
    if (courseId) {
        await openCourse(courseId);
    }
}

async function bootQuizzesPage() {
    if (!ensureAuthOrRedirect()) return;
    await loadQuizzesList();
    document.getElementById("delete-quiz-btn").onclick = deleteSelectedQuiz;
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("calendar-grid")) {
        bootCalendarPage();
    }
    if (document.getElementById("courses-list")) {
        bootCoursesPage();
    }
    if (document.getElementById("quizzes-list")) {
        bootQuizzesPage();
    }
});
