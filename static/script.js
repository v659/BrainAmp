// Configuration
const CONFIG = {
    MAX_FILE_SIZE: 15 * 1024 * 1024, // 15MB
    MAX_FILES: 5,
    ALLOWED_EXTENSIONS: ['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg'],
    MAX_MESSAGE_LENGTH: 2000,
    REQUEST_TIMEOUT: 30000, // 30 seconds
};
const CHAT_DRAFT_KEY = "chat_draft_v1";
const DEFAULT_SUBJECT_PRESETS = [
    "Biology", "History", "Geography", "English", "Math",
    "Computer Science", "Languages", "Physics", "Chemistry", "Economics", "Other"
];

// Utility Functions
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(String(email).toLowerCase());
}

function validateUsername(username) {
    const re = /^[a-zA-Z0-9_-]+$/;
    return re.test(username) && username.length >= 1 && username.length <= 50;
}

function sanitizeInput(input) {
    const div = document.createElement('div');
    div.textContent = input;
    return div.innerHTML;
}

function renderMarkdown(markdownText) {
    if (!markdownText) return "";
    let html = sanitizeInput(markdownText);

    // Code blocks first to protect inner markdown.
    html = html.replace(/```([\s\S]*?)```/g, (match, code) => {
        return `<pre style="background:#111827;color:#f9fafb;padding:12px;border-radius:8px;overflow:auto;"><code>${code.trim()}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;">$1</code>');

    // Headings
    html = html.replace(/^### (.*)$/gm, '<h3 style="margin:10px 0 6px 0;">$1</h3>');
    html = html.replace(/^## (.*)$/gm, '<h2 style="margin:12px 0 8px 0;">$1</h2>');
    html = html.replace(/^# (.*)$/gm, '<h1 style="margin:14px 0 10px 0;">$1</h1>');

    // Bold / italic
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // Unordered lists
    html = html.replace(/(?:^|\n)([-*] .*(?:\n[-*] .*)*)/g, (block) => {
        const items = block.trim().split('\n').map(line => line.replace(/^[-*]\s+/, '').trim());
        return `\n<ul style="margin:8px 0 8px 20px;">${items.map(item => `<li>${item}</li>`).join('')}</ul>`;
    });

    // Ordered lists
    html = html.replace(/(?:^|\n)(\d+\. .*(?:\n\d+\. .*)*)/g, (block) => {
        const items = block.trim().split('\n').map(line => line.replace(/^\d+\.\s+/, '').trim());
        return `\n<ol style="margin:8px 0 8px 20px;">${items.map(item => `<li>${item}</li>`).join('')}</ol>`;
    });

    // Line breaks for remaining text lines.
    html = html.replace(/\n/g, "<br>");
    return html;
}

function getFileExtension(filename) {
    return filename.split('.').pop().toLowerCase();
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function showError(elementId, message) {
    const errorDiv = document.getElementById(elementId);
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

function clearError(elementId) {
    const errorDiv = document.getElementById(elementId);
    if (errorDiv) {
        errorDiv.textContent = '';
        errorDiv.style.display = 'none';
    }
}

async function refreshAuthSession() {
    const refreshToken = localStorage.getItem("refresh_token");
    if (!refreshToken) return false;

    try {
        const res = await fetch("/api/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
        if (!res.ok) return false;
        const data = await res.json();
        if (!data.access_token || !data.refresh_token) return false;

        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        return true;
    } catch (err) {
        console.error("Session refresh error:", err);
        return false;
    }
}

async function authenticatedFetch(url, options = {}) {
    const accessToken = localStorage.getItem("access_token");
    const headers = { ...(options.headers || {}) };
    if (accessToken) {
        headers.Authorization = "Bearer " + accessToken;
    }

    let response = await fetch(url, { ...options, headers });
    if (response.status !== 401) {
        return response;
    }

    const refreshed = await refreshAuthSession();
    if (!refreshed) {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        return response;
    }

    const newAccess = localStorage.getItem("access_token");
    const retryHeaders = { ...(options.headers || {}) };
    if (newAccess) retryHeaders.Authorization = "Bearer " + newAccess;
    return fetch(url, { ...options, headers: retryHeaders });
}

async function canUseOfflineGuestMode() {
    try {
        const res = await fetch("/api/system/status");
        if (!res.ok) return false;
        const data = await res.json();
        return !!data.offline_auth_fallback_enabled;
    } catch (err) {
        return false;
    }
}

// Authentication Functions
async function sendLogin() {
    const email = document.getElementById("email").value.trim();
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const errorDiv = document.getElementById("error");

    clearError("error");

    // Validation
    if (!email || !username || !password) {
        showError("error", "Please fill in all fields");
        return;
    }

    if (!validateEmail(email)) {
        showError("error", "Please enter a valid email address");
        return;
    }

    if (!validateUsername(username)) {
        showError("error", "Username can only contain letters, numbers, hyphens, and underscores");
        return;
    }

    if (password.length < 8) {
        showError("error", "Password must be at least 8 characters");
        return;
    }

    const button = document.querySelector('button');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Logging in...";

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT);

        const response = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, username, password }),
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        if (!response.ok || data.error) {
            showError("error", data.error || "Invalid credentials");
            return;
        }

        localStorage.setItem("access_token", data.access_token);
        if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
        window.location.href = "/dashboard";

    } catch (err) {
        console.error("Login error:", err);
        if (err.name === 'AbortError') {
            showError("error", "Request timed out. Please try again.");
        } else {
            showError("error", "Server unreachable. Please check your connection.");
        }
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

async function sendSignup() {
    const email = document.getElementById("email").value.trim();
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;

    clearError("error");

    // Validation
    if (!email || !username || !password) {
        showError("error", "All fields are required");
        return;
    }

    if (!validateEmail(email)) {
        showError("error", "Please enter a valid email address");
        return;
    }

    if (!validateUsername(username)) {
        showError("error", "Username can only contain letters, numbers, hyphens, and underscores");
        return;
    }

    if (password.length < 8) {
        showError("error", "Password must be at least 8 characters");
        return;
    }

    const button = document.querySelector('button');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Signing up...";

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT);

        const response = await fetch("/api/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, username, password }),
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        if (!response.ok || data.error) {
            showError("error", data.error || "Signup failed");
            return;
        }

        localStorage.setItem("access_token", data.access_token);
        if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
        window.location.href = "/dashboard";

    } catch (err) {
        console.error("Signup error:", err);
        if (err.name === 'AbortError') {
            showError("error", "Request timed out. Please try again.");
        } else {
            showError("error", "Server unreachable. Please check your connection.");
        }
    } finally {
        button.disabled = false;
        button.textContent = originalText;
    }
}

// User Functions
async function loadUser() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        const offlineAllowed = await canUseOfflineGuestMode();
        if (!offlineAllowed) {
            window.location.href = "/";
            return;
        }
    }

    try {
        const res = await authenticatedFetch("/api/me");

        if (!res.ok) {
            localStorage.removeItem("access_token");
            window.location.href = "/";
            return;
        }

        const data = await res.json();
        const welcomeText = document.getElementById("welcome-text");
        if (welcomeText) {
            welcomeText.textContent = `Welcome, ${sanitizeInput(data.display_name)}!`;
        }

    } catch (err) {
        console.error("Load user error:", err);
        localStorage.removeItem("access_token");
        window.location.href = "/";
    }
}

function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    window.location.href = "/";
}

// File Upload Functions
function validateFile(file) {
    const errors = [];

    // Check file size
    if (file.size > CONFIG.MAX_FILE_SIZE) {
        errors.push(`${file.name}: File too large (max ${CONFIG.MAX_FILE_SIZE / (1024*1024)}MB)`);
    }

    // Check file extension
    const ext = getFileExtension(file.name);
    if (!CONFIG.ALLOWED_EXTENSIONS.includes(ext)) {
        errors.push(`${file.name}: Invalid file type (allowed: ${CONFIG.ALLOWED_EXTENSIONS.join(', ')})`);
    }

    // Check filename length
    if (file.name.length > 255) {
        errors.push(`${file.name}: Filename too long`);
    }

    return errors;
}

let currentFiles = [];

function updateFileList() {
    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    const fileCount = document.getElementById('fileCount');
    const uploadBtn = document.getElementById('uploadBtn');

    if (!fileInput || !fileList || !fileCount || !uploadBtn) return;

    const newFiles = Array.from(fileInput.files);
    const validationErrors = [];

    newFiles.forEach(file => {
        const errors = validateFile(file);
        if (errors.length > 0) {
            validationErrors.push(...errors);
        } else {
            const key = file.name + file.size + file.lastModified;
            const existingKeys = new Set(currentFiles.map(f => f.name + f.size + f.lastModified));

            if (!existingKeys.has(key)) {
                currentFiles.push(file);
            }
        }
    });

    if (validationErrors.length > 0) {
        alert("File validation errors:\n" + validationErrors.join('\n'));
    }

    if (currentFiles.length > CONFIG.MAX_FILES) {
        alert(`Maximum ${CONFIG.MAX_FILES} files allowed`);
        currentFiles = currentFiles.slice(0, CONFIG.MAX_FILES);
    }

    // Update file input
    const dt = new DataTransfer();
    currentFiles.forEach(f => dt.items.add(f));
    fileInput.files = dt.files;

    // Update UI
    if (currentFiles.length === 0) {
        fileList.innerHTML = `<div class="file-item">No files selected</div>`;
        fileCount.textContent = '';
        uploadBtn.disabled = true;
        return;
    }

    uploadBtn.disabled = false;
    fileCount.textContent = `${currentFiles.length} file(s) selected`;

    fileList.innerHTML = currentFiles.map((file, i) => `
        <div class="file-item">
            <span>${i + 1}. ${sanitizeInput(file.name)} (${formatFileSize(file.size)})</span>
            <button class="remove-btn" onclick="removeFile(${i})">Remove</button>
        </div>
    `).join('');
}

function removeFile(index) {
    currentFiles.splice(index, 1);
    const dt = new DataTransfer();
    currentFiles.forEach(f => dt.items.add(f));
    document.getElementById('fileInput').files = dt.files;
    updateFileList();
}

function clearAllFiles() {
    currentFiles = [];
    document.getElementById('fileInput').files = new DataTransfer().files;
    updateFileList();
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const button = document.getElementById('uploadBtn');

    const files = Array.from(fileInput.files);

    if (!files || files.length === 0) {
        alert('Please select at least one file!');
        return;
    }

    if (files.length > CONFIG.MAX_FILES) {
        alert(`Maximum ${CONFIG.MAX_FILES} files allowed`);
        return;
    }

    // Final validation
    const validationErrors = [];
    files.forEach(file => {
        const errors = validateFile(file);
        validationErrors.push(...errors);
    });

    if (validationErrors.length > 0) {
        alert("File validation errors:\n" + validationErrors.join('\n'));
        return;
    }

    const accessToken = localStorage.getItem("access_token");
    if (!accessToken) {
        alert("Please log in first!");
        window.location.href = "/";
        return;
    }

    const originalText = button.textContent;
    button.textContent = `Uploading ${files.length} file(s)...`;
    button.disabled = true;

    try {
        const formData = new FormData();
        files.forEach(file => formData.append('files', file));

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000); // 60s timeout for upload

        const response = await authenticatedFetch('/api/upload', {
            method: 'POST',
            body: formData,
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Upload failed');
        }

        const result = await response.json();
        alert(`Upload successful!\nTopic: ${result.topic}`);
        clearAllFiles();

    } catch (error) {
        console.error('Upload error:', error);
        if (error.name === 'AbortError') {
            alert('Upload timed out. Please try with smaller files.');
        } else {
            alert(`Upload failed: ${error.message}`);
        }
    } finally {
        button.textContent = originalText;
        button.disabled = false;
    }
}

// Topics Functions
async function get_usersAndtopic(api) {
    const token = localStorage.getItem("access_token");
    if (!token) {
        const container = document.getElementById("topics-container");
        if (container) {
            container.innerHTML = `<div style="padding:20px;text-align:center;color:#dc2626;">Not logged in. Please log in again.</div>`;
        }
        return;
    }

    try {
        const [topicsRes, presetsRes] = await Promise.all([
            authenticatedFetch(api),
            authenticatedFetch("/api/subject-presets")
        ]);

        if (!topicsRes.ok) throw new Error(`HTTP ${topicsRes.status}`);

        const topicsData = await topicsRes.json();
        const presetsData = presetsRes.ok ? await presetsRes.json() : { presets: [] };
        const container = document.getElementById("topics-container");
        if (!container) return;
        container.innerHTML = "";

        let topics = topicsData.topics;
        if (!topics && Array.isArray(topicsData.result_topics)) {
            topics = topicsData.result_topics.map((t, i) => ({
                topic: t.topic,
                content: topicsData.result_content?.[i]?.content || "",
                subject: "Uncategorized",
                created_at: null
            }));
        }
        topics = topics || [];

        const presetSubjects = (presetsData.presets || [])
            .map(p => p.subject)
            .filter(Boolean);
        const subjectOrder = [...presetSubjects];

        topics.forEach(t => {
            const s = t.subject || "Uncategorized";
            if (!subjectOrder.includes(s)) subjectOrder.push(s);
        });

        if (subjectOrder.length === 0) {
            subjectOrder.push("Uncategorized");
        }

        const grouped = {};
        subjectOrder.forEach(s => grouped[s] = []);
        topics.forEach(t => {
            const s = t.subject || "Uncategorized";
            if (!grouped[s]) grouped[s] = [];
            grouped[s].push(t);
        });

        subjectOrder.forEach(subject => {
            const section = document.createElement("div");
            section.style.cssText = `
                width: 86%;
                margin: 14px auto;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                background: #ffffff;
                padding: 10px;
            `;
            section.dataset.subject = subject;

            const title = document.createElement("h3");
            title.textContent = subject;
            title.style.cssText = "margin:4px 0 10px 0;font-size:1rem;color:#111827;";
            section.appendChild(title);

            const dropZone = document.createElement("div");
            dropZone.style.cssText = "min-height:24px;padding:2px;";
            dropZone.ondragover = (e) => {
                e.preventDefault();
                dropZone.style.background = "#eff6ff";
            };
            dropZone.ondragleave = () => {
                dropZone.style.background = "transparent";
            };
            dropZone.ondrop = async (e) => {
                e.preventDefault();
                dropZone.style.background = "transparent";
                const documentId = e.dataTransfer.getData("text/plain");
                if (documentId) await moveDocumentToSubject(documentId, subject);
            };

            const docs = grouped[subject] || [];
            if (docs.length === 0) {
                const empty = document.createElement("div");
                empty.textContent = "No notes for this topic.";
                empty.style.cssText = "color:#6b7280;font-size:14px;padding:6px 0;";
                dropZone.appendChild(empty);
            } else {
                docs.forEach(topicObj => {
                    const topic = topicObj.topic || "Untitled";
                    const content = topicObj.content || "No content available";
                    const createdAt = topicObj.created_at ? new Date(topicObj.created_at).toLocaleDateString() : "Unknown date";
                    const documentId = topicObj.id;

                    const card = document.createElement("div");
                    card.style.cssText = "margin:8px 0;border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;";
                    if (documentId) {
                        card.draggable = true;
                        card.ondragstart = (e) => {
                            e.dataTransfer.setData("text/plain", documentId);
                            e.dataTransfer.effectAllowed = "move";
                        };
                    }

                    const row = document.createElement("div");
                    row.style.cssText = "display:flex;align-items:center;gap:8px;";

                    const button = document.createElement("button");
                    button.textContent = `${topic} (${createdAt})`;
                    button.style.cssText = "flex:1;padding:12px;text-align:left;border:none;background:transparent;cursor:pointer;font-weight:600;";

                    const deleteBtn = document.createElement("button");
                    deleteBtn.textContent = "Delete";
                    deleteBtn.style.cssText = "margin-right:8px;padding:6px 10px;border:none;border-radius:6px;background:#dc2626;color:#fff;cursor:pointer;font-size:12px;";
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation();
                        deleteDocument(documentId, topic);
                    };

                    const contentDiv = document.createElement("div");
                    contentDiv.style.cssText = "display:none;padding:12px;border-top:1px solid #ddd;";

                    const pre = document.createElement("pre");
                    pre.textContent = content;
                    pre.style.cssText = "white-space:pre-wrap;margin:0;max-height:260px;overflow-y:auto;";
                    contentDiv.appendChild(pre);

                    button.onclick = () => {
                        const isOpen = contentDiv.style.display === "block";
                        contentDiv.style.display = isOpen ? "none" : "block";
                    };

                    row.appendChild(button);
                    if (documentId) row.appendChild(deleteBtn);
                    card.appendChild(row);
                    card.appendChild(contentDiv);
                    dropZone.appendChild(card);
                });
            }

            section.appendChild(dropZone);
            container.appendChild(section);
        });

    } catch (err) {
        console.error("Get topics error:", err);
        const container = document.getElementById("topics-container");
        if (container) {
            container.innerHTML = `
                <div style="padding: 20px; text-align: center; color: #dc2626;">
                    Failed to load topics. Please refresh the page.
                </div>
            `;
        }
    }
}

async function moveDocumentToSubject(documentId, subject) {
    const token = localStorage.getItem("access_token");
    if (!token || !documentId || !subject) return;

    try {
        const res = await authenticatedFetch(`/api/documents/${documentId}/subject`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ subject })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to move note");
        await get_usersAndtopic("/api/get_topics");
    } catch (err) {
        console.error("Move document subject error:", err);
        alert(err.message || "Failed to move note");
    }
}

async function deleteDocument(documentId, topicName = "this document") {
    const token = localStorage.getItem("access_token");
    if (!token || !documentId) return;

    if (!confirm(`Delete "${topicName}"? This will also remove chats linked to this document.`)) {
        return;
    }

    try {
        const res = await authenticatedFetch(`/api/documents/${documentId}`, {
            method: "DELETE",
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to delete document");

        await get_usersAndtopic("/api/get_topics");
        if (typeof loadAllChats === "function") {
            await loadAllChats();
        }
    } catch (err) {
        console.error("Delete document error:", err);
        alert(err.message || "Failed to delete document");
    }
}

async function loadSubjectPresets() {
    // No separate presets panel anymore; topics render now includes subject sections.
}

async function addSubjectPreset() {
    const token = localStorage.getItem("access_token");
    const input = document.getElementById("new-subject-input");
    if (!token) return;

    const subject = input ? input.value.trim() : (prompt("Enter new subject preset") || "").trim();
    if (!subject) return;

    try {
        const res = await authenticatedFetch("/api/subject-presets", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ subject })
        });
        if (!res.ok) throw new Error("Failed to add subject preset");
        if (input) input.value = "";
        await get_usersAndtopic("/api/get_topics");
    } catch (err) {
        console.error("Add subject preset error:", err);
        alert("Failed to add subject preset");
    }
}

// Chat Functions
let currentTopicId = null;
let currentChatId = null;
let currentSubject = null;
let currentChatMode = null;
let currentAccountSettings = {};
let currentInjectedContext = null;

function getSidebarForMode(mode) {
    if (mode === "course") return document.getElementById("course-sidebar");
    if (mode === "quiz") return document.getElementById("quiz-sidebar");
    return document.getElementById("chat-sidebar");
}

function switchActiveSidebar(mode) {
    ["chat-sidebar", "course-sidebar", "quiz-sidebar"].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.style.display = "none";
        el.classList.remove("collapsed");
    });

    const active = getSidebarForMode(mode);
    if (active) active.style.display = "flex";
    const toggleBtn = document.querySelector(".toggle-sidebar-btn");
    if (toggleBtn) toggleBtn.style.left = "300px";
}

function updateChatPlaceholder() {
    const input = document.getElementById("chat-input");
    if (!input) return;

    if (currentChatMode === "course") {
        input.placeholder = "Describe what course you want from your notes (scope, pace, exam goals)...";
    } else if (currentChatMode === "quiz") {
        input.placeholder = "Ask for a quiz (topic, difficulty, question count, format)...";
    } else {
        input.placeholder = "Ask to go deeper into fundamentals (Socratic style), or ask concept questions...";
    }
}

function updateModeNotice() {
    const notice = document.getElementById("mode-notice");
    if (!notice) return;

    if (!currentChatMode) {
        notice.textContent = "Choose one mode to start this chat.";
        notice.style.color = "#b45309";
        return;
    }

    if (currentChatMode === "course") {
        const grade = (currentAccountSettings.grade_level || "").trim();
        const board = (currentAccountSettings.education_board || "").trim();
        if (!grade || !board) {
            notice.innerHTML = `Course mode selected. Add <strong>Grade</strong> and <strong>Board</strong> in Settings for better course generation.`;
            notice.style.color = "#b45309";
        } else {
            notice.textContent = `Course mode selected for Grade ${grade} | Board ${board}. Generated courses auto-save to Calendar/Courses and also create a quiz.`;
            notice.style.color = "#065f46";
        }
        return;
    }

    if (currentChatMode === "quiz") {
        notice.textContent = "Quiz mode selected. Generated quizzes are automatically saved to Quizzes.";
        notice.style.color = "#1d4ed8";
        return;
    }

    notice.textContent = "Fundamentals mode selected. Tutor will prioritize Socratic deep understanding.";
    notice.style.color = "#1d4ed8";
}

function setChatMode(mode) {
    currentChatMode = mode;
    switchActiveSidebar(mode);
    updateModeNotice();
    updateChatPlaceholder();
    const courseOptions = document.getElementById("course-mode-options");
    const quizOptions = document.getElementById("quiz-mode-options");
    if (courseOptions) courseOptions.style.display = mode === "course" ? "grid" : "none";
    if (quizOptions) quizOptions.style.display = mode === "quiz" ? "grid" : "none";

    document.querySelectorAll("[data-chat-mode]").forEach(btn => {
        btn.style.borderColor = btn.dataset.chatMode === mode ? "#2563eb" : "#d1d5db";
        btn.style.background = btn.dataset.chatMode === mode ? "#eff6ff" : "#fff";
    });

    if (mode === "course") {
        loadModeNoteSelectors();
        loadSavedCourses();
    } else if (mode === "quiz") {
        loadModeNoteSelectors();
        loadSavedQuizzes();
    } else {
        loadAllChats();
    }
}

function consumeChatDraftIfAny() {
    try {
        const raw = localStorage.getItem(CHAT_DRAFT_KEY);
        if (!raw) return;
        localStorage.removeItem(CHAT_DRAFT_KEY);

        const draft = JSON.parse(raw);
        if (!draft || typeof draft !== "object") return;
        if (draft.mode) {
            setChatMode(draft.mode);
        }
        currentInjectedContext = String(draft.extra_context || "").trim() || null;

        const input = document.getElementById("chat-input");
        if (!input) return;
        input.value = String(draft.message || "").trim().slice(0, CONFIG.MAX_MESSAGE_LENGTH);
        input.focus();
    } catch (err) {
        console.error("Consume chat draft error:", err);
    }
}

function fmtIsoDate(dateObj = new Date()) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, "0");
    const d = String(dateObj.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function getSelectedValues(selectId) {
    const el = document.getElementById(selectId);
    if (!el) return [];
    if (el.dataset.pickerType === "notes-checkboxes") {
        return Array.from(el.querySelectorAll("input[type='checkbox']:checked"))
            .map((cb) => cb.value)
            .filter(Boolean);
    }
    return Array.from(el.selectedOptions || []).map(o => o.value).filter(Boolean);
}

function formatCourseForChat(course, modules) {
    const lines = [
        `# ${course.title || "Generated Course"}`,
        "",
        `**Start Date:** ${course.start_date || "N/A"}`,
        `**Duration:** ${course.duration_days || modules.length || 0} day(s)`,
        "",
        "## Overview",
        course.overview || "No overview provided.",
        "",
        "## Plan"
    ];

    (modules || []).forEach((m) => {
        lines.push(
            "",
            `### Day ${m.day_index} - ${m.title || "Module"}`,
            `**Date:** ${m.task_date || "N/A"}`,
            `**Lesson**`,
            m.lesson_content || "No lesson content.",
            "",
            `**Practice**`,
            m.practice_content || "No practice content.",
            "",
            `**Quick Quiz**`,
            m.quiz_content || "No quiz content."
        );
    });
    return lines.join("\n");
}

function addLoadingMessage(label = "Working on your request...") {
    const chatMessages = document.getElementById("chat-messages");
    if (!chatMessages) return null;

    const card = document.createElement("div");
    card.className = "loading-message-card";
    card.innerHTML = `
        <div class="loading-message-sender">AI Tutor</div>
        <div class="loading-message-content">
            <span>${label}</span>
            <span class="typing-loader"><span></span><span></span><span></span></span>
        </div>
    `;
    chatMessages.appendChild(card);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return card;
}

function removeLoadingMessage(node) {
    if (node && node.parentNode) {
        node.parentNode.removeChild(node);
    }
}

async function loadModeNoteSelectors() {
    try {
        const res = await authenticatedFetch("/api/get_topics");
        if (!res.ok) return;
        const data = await res.json();
        const topics = data.topics || [];
        const selectors = ["course-documents", "quiz-documents"];
        selectors.forEach((id) => {
            const wrap = document.getElementById(id);
            if (!wrap) return;
            wrap.innerHTML = "";
            wrap.dataset.pickerType = "notes-checkboxes";
            if (!topics.length) {
                wrap.innerHTML = `<div class="notes-picker-empty">No notes found. You can still generate using AI general knowledge.</div>`;
                return;
            }
            topics.forEach((t) => {
                const label = document.createElement("label");
                label.className = "notes-picker-item";
                label.innerHTML = `
                    <input type="checkbox" value="${t.id}" />
                    <span>${t.topic || "Untitled"} (${t.subject || "Uncategorized"})</span>
                `;
                wrap.appendChild(label);
            });
        });
    } catch (err) {
        console.error("Load mode notes error:", err);
    }
}

async function showCourseInChat(courseId) {
    const res = await authenticatedFetch(`/api/courses/${courseId}`);
    if (!res.ok) throw new Error("Failed to load saved course");
    const data = await res.json();
    clearChat();
    addMessageToChat("Saved Course", formatCourseForChat(data.course || {}, data.modules || []), false);
}

async function loadSavedCourses() {
    const container = document.getElementById("course-list");
    if (!container) return;
    container.innerHTML = "";
    try {
        const res = await authenticatedFetch("/api/courses");
        if (!res.ok) return;
        const data = await res.json();
        const courses = data.courses || [];
        if (!courses.length) {
            container.innerHTML = `<div style="padding:16px;color:#6b7280;">No saved courses yet.</div>`;
            return;
        }

        courses.forEach((course) => {
            const row = document.createElement("div");
            row.className = "chat-item";

            const title = document.createElement("div");
            title.className = "chat-item-title";
            title.textContent = course.title || "Course";

            const time = document.createElement("div");
            time.className = "chat-item-time";
            time.textContent = course.created_at ? new Date(course.created_at).toLocaleString() : "Saved item";

            const actions = document.createElement("div");
            actions.style.cssText = "display:flex;gap:8px;margin-top:8px;";
            const viewBtn = document.createElement("button");
            viewBtn.textContent = "View";
            viewBtn.style.cssText = "padding:4px 8px;border:none;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;font-size:12px;";
            viewBtn.onclick = async () => {
                try {
                    await showCourseInChat(course.id);
                } catch (err) {
                    alert("Failed to open course.");
                }
            };
            actions.appendChild(viewBtn);

            row.appendChild(title);
            row.appendChild(time);
            row.appendChild(actions);
            container.appendChild(row);
        });
    } catch (err) {
        console.error("Load saved courses error:", err);
    }
}

async function loadSavedQuizzes() {
    const container = document.getElementById("quiz-list");
    if (!container) return;
    container.innerHTML = "";
    try {
        const res = await authenticatedFetch("/api/quizzes");
        if (!res.ok) return;
        const data = await res.json();
        const quizzes = data.quizzes || [];
        if (!quizzes.length) {
            container.innerHTML = `<div style="padding:16px;color:#6b7280;">No saved quizzes yet.</div>`;
            return;
        }

        quizzes.forEach((quiz) => {
            const row = document.createElement("div");
            row.className = "chat-item";
            const title = document.createElement("div");
            title.className = "chat-item-title";
            title.textContent = quiz.title || "Quiz";
            const time = document.createElement("div");
            time.className = "chat-item-time";
            time.textContent = quiz.created_at ? new Date(quiz.created_at).toLocaleString() : "Saved item";

            const actions = document.createElement("div");
            actions.style.cssText = "display:flex;gap:8px;margin-top:8px;";

            const viewBtn = document.createElement("button");
            viewBtn.textContent = "View";
            viewBtn.style.cssText = "padding:4px 8px;border:none;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;font-size:12px;";
            viewBtn.onclick = () => {
                clearChat();
                addMessageToChat("Saved Quiz", quiz.content || "", false);
            };

            const deleteBtn = document.createElement("button");
            deleteBtn.textContent = "Delete";
            deleteBtn.style.cssText = "padding:4px 8px;border:none;border-radius:6px;background:#dc2626;color:#fff;cursor:pointer;font-size:12px;";
            deleteBtn.onclick = async () => {
                const ok = confirm(`Delete saved quiz "${quiz.title || "item"}"?`);
                if (!ok) return;
                const delRes = await authenticatedFetch(`/api/quizzes/${quiz.id}`, { method: "DELETE" });
                if (!delRes.ok) {
                    alert("Failed to delete quiz.");
                    return;
                }
                await loadSavedQuizzes();
            };

            actions.appendChild(viewBtn);
            actions.appendChild(deleteBtn);
            row.appendChild(title);
            row.appendChild(time);
            row.appendChild(actions);
            container.appendChild(row);
        });
    } catch (err) {
        console.error("Load saved quizzes error:", err);
    }
}

async function loadChatTopics() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        const offlineAllowed = await canUseOfflineGuestMode();
        if (!offlineAllowed) {
            window.location.href = "/dashboard";
            return;
        }
    }

    try {
        const [presetRes, meRes] = await Promise.all([
            authenticatedFetch("/api/subject-presets"),
            authenticatedFetch("/api/me")
        ]);

        if (!presetRes.ok) throw new Error(`HTTP ${presetRes.status}`);

        const data = await presetRes.json();
        const me = meRes.ok ? await meRes.json() : {};
        currentAccountSettings = me.account_settings || {};
        const presets = data.presets || [];
        const container = document.getElementById("topics-container");

        if (!container) return;
        container.innerHTML = "";

        const modeSelector = document.createElement("div");
        modeSelector.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:14px;";
        modeSelector.innerHTML = `
            <button data-chat-mode="fundamentals" style="border:1px solid #d1d5db;border-radius:10px;padding:12px;background:#fff;text-align:left;cursor:pointer;">
                <strong>Go Deeper (Fundamentals)</strong><br><span style="font-size:12px;color:#6b7280;">Socratic + guided reasoning</span>
            </button>
            <button data-chat-mode="course" style="border:1px solid #d1d5db;border-radius:10px;padding:12px;background:#fff;text-align:left;cursor:pointer;">
                <strong>Generate Course</strong><br><span style="font-size:12px;color:#6b7280;">Build course from your notes</span>
            </button>
            <button data-chat-mode="quiz" style="border:1px solid #d1d5db;border-radius:10px;padding:12px;background:#fff;text-align:left;cursor:pointer;">
                <strong>Quiz Mode</strong><br><span style="font-size:12px;color:#6b7280;">Practice with generated quizzes</span>
            </button>
        `;
        container.appendChild(modeSelector);
        modeSelector.querySelectorAll("[data-chat-mode]").forEach(btn => {
            btn.onclick = () => setChatMode(btn.dataset.chatMode);
        });

        const modeNotice = document.createElement("div");
        modeNotice.id = "mode-notice";
        modeNotice.style.cssText = "margin-bottom:14px;padding:10px 12px;border:1px dashed #d1d5db;border-radius:8px;background:#fff;";
        container.appendChild(modeNotice);

        const modeOptionsWrap = document.createElement("div");
        modeOptionsWrap.style.cssText = "display:grid;gap:12px;margin-bottom:14px;";
        modeOptionsWrap.innerHTML = `
            <div id="course-mode-options" class="mode-options-panel" style="display:none;">
                <label>Course title (optional)</label>
                <input id="course-title-input" type="text" maxlength="120" placeholder="e.g. Algebra Revision Sprint" />
                <label>Select notes (optional, multi-select)</label>
                <div id="course-documents" class="notes-picker"></div>
                <small class="mode-hint">If none selected, AI uses general knowledge from your request.</small>
                <div class="mode-options-row">
                    <div>
                        <label>Start date</label>
                        <input id="course-start-date" type="date" />
                    </div>
                    <div>
                        <label>Duration days</label>
                        <input id="course-duration-days" type="number" min="7" max="90" value="14" />
                    </div>
                </div>
            </div>
            <div id="quiz-mode-options" class="mode-options-panel" style="display:none;">
                <label>Quiz title/topic (optional)</label>
                <input id="quiz-topic-input" type="text" maxlength="120" placeholder="e.g. Thermodynamics Mixed Practice" />
                <label>Select notes (optional, multi-select)</label>
                <div id="quiz-documents" class="notes-picker"></div>
                <small class="mode-hint">If none selected, AI uses general knowledge from your request.</small>
                <div class="mode-options-row">
                    <div>
                        <label>Question count</label>
                        <input id="quiz-question-count" type="number" min="3" max="25" value="8" />
                    </div>
                </div>
            </div>
        `;
        container.appendChild(modeOptionsWrap);

        const topicSelect = document.createElement("select");
        topicSelect.id = "topic-select";
        topicSelect.style.cssText = `
            width: 100%;
            padding: 12px;
            margin-bottom: 20px;
            border-radius: 8px;
            border: 1px solid #ddd;
            font-size: 14px;
        `;

        const defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = "Auto-detect subject from my message";
        topicSelect.appendChild(defaultOption);

        presets.forEach(preset => {
            const option = document.createElement("option");
            option.value = preset.subject;
            option.textContent = preset.subject;
            topicSelect.appendChild(option);
        });

        topicSelect.onchange = (e) => {
            currentSubject = e.target.value || null;
            currentTopicId = null;
            currentChatId = null;
            clearChat();
        };

        container.appendChild(topicSelect);

        const chatMessages = document.createElement("div");
        chatMessages.id = "chat-messages";
        chatMessages.style.cssText = `
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: white;
            border-radius: 8px;
            margin-bottom: 20px;
        `;

        const chatInputContainer = document.createElement("div");
        chatInputContainer.style.cssText = `display: flex; gap: 10px;`;

        const chatInput = document.createElement("textarea");
        chatInput.id = "chat-input";
        chatInput.maxLength = CONFIG.MAX_MESSAGE_LENGTH;
        chatInput.style.cssText = `
            flex: 1;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #ddd;
            font-size: 14px;
            resize: vertical;
            min-height: 60px;
            max-height: 200px;
        `;

        const sendButton = document.createElement("button");
        sendButton.id = "chat-send-button";
        sendButton.textContent = "Send";
        sendButton.onclick = sendMessage;
        sendButton.style.cssText = `
            padding: 12px 24px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
        `;

        chatInputContainer.appendChild(chatInput);
        chatInputContainer.appendChild(sendButton);

        container.appendChild(chatMessages);
        container.appendChild(chatInputContainer);

        currentChatMode = null;
        switchActiveSidebar("fundamentals");
        updateModeNotice();
        updateChatPlaceholder();
        const startDateInput = document.getElementById("course-start-date");
        if (startDateInput) startDateInput.value = fmtIsoDate(new Date());
        await loadModeNoteSelectors();
        await loadAllChats();
        consumeChatDraftIfAny();
    } catch (err) {
        console.error("Load chat topics error:", err);
    }
}

function clearChat() {
    const chatMessages = document.getElementById("chat-messages");
    if (chatMessages) {
        chatMessages.innerHTML = "";
    }
}

function addMessageToChat(sender, message, isUser) {
    const chatMessages = document.getElementById("chat-messages");
    if (!chatMessages) return;

    const messageDiv = document.createElement("div");
    messageDiv.style.cssText = `
        margin-bottom: 16px;
        padding: 12px;
        border-radius: 8px;
        background: ${isUser ? '#e3f2fd' : '#f5f5f5'};
        ${isUser ? 'margin-left: 20%;' : 'margin-right: 20%;'}
    `;

    const senderDiv = document.createElement("div");
    senderDiv.textContent = sender;
    senderDiv.style.cssText = `
        font-weight: 600;
        margin-bottom: 6px;
        color: ${isUser ? '#1976d2' : '#666'};
    `;

    const contentDiv = document.createElement("div");
    contentDiv.style.cssText = `
        white-space: pre-wrap;
        word-wrap: break-word;
        line-height: 1.5;
    `;
    if (isUser) {
        contentDiv.textContent = message;
    } else {
        contentDiv.innerHTML = renderMarkdown(message);
    }

    messageDiv.appendChild(senderDiv);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showModeBlockingNotice(message) {
    const notice = document.getElementById("mode-notice");
    if (!notice) return;
    notice.textContent = message;
    notice.style.color = "#b91c1c";
}

function looksLikePlannerCommand(message) {
    const t = (message || "").trim().toLowerCase();
    return (
        /^move\s+.+\s+to\s+\d{4}-\d{2}-\d{2}/.test(t) ||
        /^add\s+task\s+.+\s+on\s+\d{4}-\d{2}-\d{2}/.test(t) ||
        /^mark\s+.+\s+busy\s+on\s+\d{4}-\d{2}-\d{2}\s+from\s+\d{1,2}:\d{2}\s+to\s+\d{1,2}:\d{2}/.test(t) ||
        /^remind\s+me\s+to\s+.+\s+on\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}:\d{2}/.test(t) ||
        /^when\s+is\s+.+\s+scheduled(?:\s+for)?\??$/.test(t) ||
        /^what\s+day\s+is\s+.+\s+scheduled(?:\s+for)?\??$/.test(t) ||
        /^is\s+.+\s+scheduled(?:\s+for)?\??$/.test(t)
    );
}

async function sendMessage() {
    const input = document.getElementById("chat-input");
    const sendBtn = document.getElementById("chat-send-button");
    if (!input) return;
    const message = input.value.trim();

    if (!currentChatMode) {
        showModeBlockingNotice("Choose a chat mode first: Fundamentals, Course, or Quiz.");
        input.focus();
        return;
    }
    if (currentChatMode === "course") {
        const grade = (currentAccountSettings.grade_level || "").trim();
        const board = (currentAccountSettings.education_board || "").trim();
        if (!grade || !board) {
            showModeBlockingNotice("Set Grade and Board in Settings before using Course mode.");
            return;
        }
    }

    if (!message) {
        showModeBlockingNotice("Type a message to continue.");
        input.focus();
        return;
    }

    if (message.length > CONFIG.MAX_MESSAGE_LENGTH) {
        showModeBlockingNotice(`Message too long (max ${CONFIG.MAX_MESSAGE_LENGTH} characters).`);
        input.focus();
        return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/";
        return;
    }

    input.value = "";
    addMessageToChat("You", message, true);
    const loadingNode = addLoadingMessage(currentChatMode === "fundamentals" ? "Thinking..." : "Generating...");
    if (sendBtn) sendBtn.disabled = true;
    input.disabled = true;

    try {
        if (looksLikePlannerCommand(message)) {
            const cmdRes = await authenticatedFetch("/api/planner/command", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ command: message })
            });
            const cmdData = await cmdRes.json();
            if (!cmdRes.ok) {
                throw new Error(cmdData.detail || "Planner command failed");
            }
            addMessageToChat("Planner", cmdData.message || "Planner updated.", false);
            return;
        }

        if (currentChatMode === "course") {
            const docIds = getSelectedValues("course-documents");
            const titleInput = document.getElementById("course-title-input");
            const startDateInput = document.getElementById("course-start-date");
            const durationInput = document.getElementById("course-duration-days");
            const startDate = startDateInput ? startDateInput.value : "";
            const durationDays = Number(durationInput ? durationInput.value : 14);
            const title = titleInput ? titleInput.value.trim() : "";

            if (!startDate) {
                throw new Error("Pick a valid start date.");
            }

            const courseRes = await authenticatedFetch("/api/courses/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    document_ids: docIds,
                    title: title || null,
                    request: message,
                    start_date: startDate,
                    duration_days: durationDays
                })
            });
            const courseData = await courseRes.json();
            if (!courseRes.ok) {
                throw new Error(courseData.detail || "Failed to generate course");
            }

            let detail = null;
            if (courseData.offline && courseData.course && courseData.modules) {
                detail = { course: courseData.course, modules: courseData.modules };
            } else {
                const detailRes = await authenticatedFetch(`/api/courses/${courseData.course_id}`);
                if (!detailRes.ok) throw new Error("Course created but failed to load details");
                detail = await detailRes.json();
            }
            const courseText = formatCourseForChat(detail.course || {}, detail.modules || []);
            const suffix = courseData.auto_quiz_id ? "\n\nAuto-saved quiz created and added to Quizzes." : "";
            addMessageToChat("AI Tutor", courseText + suffix, false);
            await loadSavedCourses();
            await loadSavedQuizzes();
        } else if (currentChatMode === "quiz") {
            const docIds = getSelectedValues("quiz-documents");
            const topicInput = document.getElementById("quiz-topic-input");
            const countInput = document.getElementById("quiz-question-count");
            const topic = topicInput ? topicInput.value.trim() : "";
            const questionCount = Number(countInput ? countInput.value : 8);

            const quizRes = await authenticatedFetch("/api/quizzes/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    document_ids: docIds,
                    topic: topic || null,
                    request: message,
                    question_count: questionCount
                })
            });
            const quizData = await quizRes.json();
            if (!quizRes.ok) {
                throw new Error(quizData.detail || "Failed to generate quiz");
            }
            addMessageToChat("AI Tutor", quizData.quiz?.content || "Quiz generated.", false);
            await loadSavedQuizzes();
        } else {
            const response = await authenticatedFetch("/api/chat/send", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    topic_id: currentTopicId,
                    subject: currentSubject,
                    chat_id: currentChatId,
                    chat_mode: currentChatMode,
                    extra_context: currentInjectedContext,
                    message: message
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Failed to send message");
            }

            const data = await response.json();
            if (!currentChatId) {
                currentChatId = data.chat_id;
            }
            addMessageToChat("AI Tutor", data.ai_response, false);
            currentInjectedContext = null;
            await loadAllChats();
        }
    } catch (err) {
        console.error("Send message error:", err);
        addMessageToChat("System", `Error: ${err.message || "Failed to get AI response. Please try again."}`, false);
    } finally {
        removeLoadingMessage(loadingNode);
        if (sendBtn) sendBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function loadChatHistory(chatId) {
    const token = localStorage.getItem("access_token");
    if (!token || !chatId) return;

    try {
        const res = await authenticatedFetch(`/api/chat/history/${chatId}`);

        if (!res.ok) throw new Error("Failed to load history");

        const data = await res.json();
        clearChat();
        currentChatId = chatId;

        data.messages.forEach(msg => {
            addMessageToChat(
                msg.is_user ? "You" : "AI Tutor",
                msg.content,
                msg.is_user
            );
        });

    } catch (err) {
        console.error("Load chat history error:", err);
    }
}

// Settings Functions
async function loadSettings() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/";
        return;
    }

    try {
        const res = await authenticatedFetch("/api/me");

        if (!res.ok) {
            window.location.href = "/";
            return;
        }

        const user = await res.json();
        const emailInput = document.getElementById("email");
        const displayNameInput = document.getElementById("display-name");
        const webSearchInput = document.getElementById("web-search-enabled");
        const saveChatInput = document.getElementById("save-chat-history");
        const remindersInput = document.getElementById("study-reminders-enabled");
        const gradeLevelInput = document.getElementById("grade-level");
        const educationBoardInput = document.getElementById("education-board");
        const settings = user.account_settings || {};

        if (emailInput) emailInput.value = user.email || "";
        if (displayNameInput) displayNameInput.value = user.display_name || "";
        if (webSearchInput) webSearchInput.checked = settings.web_search_enabled !== false;
        if (saveChatInput) saveChatInput.checked = settings.save_chat_history !== false;
        if (remindersInput) remindersInput.checked = settings.study_reminders_enabled === true;
        if (gradeLevelInput) gradeLevelInput.value = settings.grade_level || "";
        if (educationBoardInput) educationBoardInput.value = settings.education_board || "";
    } catch (err) {
        console.error("Load settings error:", err);
        window.location.href = "/";
    }
}

async function updateProfile() {
    const displayName = document.getElementById("display-name").value.trim();
    const notification = document.getElementById("profile-notification");

    if (!displayName) {
        showNotification(notification, "Display name cannot be empty", "error");
        return;
    }

    if (displayName.length > 50) {
        showNotification(notification, "Display name too long (max 50 characters)", "error");
        return;
    }

    const btn = document.getElementById("profile-save-btn");
    if (!btn) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
        const res = await authenticatedFetch("/api/update-profile", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ display_name: displayName })
        });

        const data = await res.json();

        if (res.ok) {
            showNotification(notification, "Profile updated successfully!", "success");
        } else {
            showNotification(notification, data.error || "Update failed", "error");
        }
    } catch (err) {
        console.error("Update profile error:", err);
        showNotification(notification, "Network error. Please try again.", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

async function updateAccountSettings() {
    const notification = document.getElementById("account-settings-notification");
    const webSearchInput = document.getElementById("web-search-enabled");
    const saveChatInput = document.getElementById("save-chat-history");
    const remindersInput = document.getElementById("study-reminders-enabled");
    const gradeLevelInput = document.getElementById("grade-level");
    const educationBoardInput = document.getElementById("education-board");
    const btn = document.getElementById("account-settings-save-btn");

    if (!webSearchInput || !saveChatInput || !remindersInput || !btn) return;

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
        const res = await authenticatedFetch("/api/account-settings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                web_search_enabled: webSearchInput.checked,
                save_chat_history: saveChatInput.checked,
                study_reminders_enabled: remindersInput.checked,
                grade_level: gradeLevelInput ? gradeLevelInput.value.trim() : "",
                education_board: educationBoardInput ? educationBoardInput.value.trim() : ""
            })
        });

        const data = await res.json();
        if (res.ok) {
            showNotification(notification, "Account settings updated.", "success");
        } else {
            showNotification(notification, data.error || "Failed to update settings.", "error");
        }
    } catch (err) {
        console.error("Update account settings error:", err);
        showNotification(notification, "Network error. Please try again.", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

async function updatePassword() {
    const notification = document.getElementById("password-notification");
    const newPasswordInput = document.getElementById("new-password");
    const confirmPasswordInput = document.getElementById("confirm-password");
    const btn = document.getElementById("password-save-btn");

    if (!notification || !newPasswordInput || !confirmPasswordInput || !btn) return;

    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (newPassword.length < 8) {
        showNotification(notification, "Password must be at least 8 characters.", "error");
        return;
    }

    if (newPassword !== confirmPassword) {
        showNotification(notification, "Passwords do not match.", "error");
        return;
    }

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Updating...";

    try {
        const res = await authenticatedFetch("/api/change-password", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ new_password: newPassword })
        });

        const data = await res.json();
        if (res.ok) {
            newPasswordInput.value = "";
            confirmPasswordInput.value = "";
            showNotification(notification, "Password updated successfully.", "success");
        } else {
            showNotification(notification, data.error || "Failed to update password.", "error");
        }
    } catch (err) {
        console.error("Update password error:", err);
        showNotification(notification, "Network error. Please try again.", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function showNotification(element, message, type) {
    if (!element) return;

    element.textContent = message;
    element.className = `notification ${type}`;
    element.style.display = 'block';

    setTimeout(() => {
        element.style.display = 'none';
    }, 3000);
}

// Dashboard Functions
async function loadDashboardStats() {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    try {
        const [topicsRes, statsRes] = await Promise.all([
            authenticatedFetch("/api/chat/topics"),
            authenticatedFetch("/api/dashboard/stats")
        ]);

        if (topicsRes.ok) {
            const topicsData = await topicsRes.json();
            const count = topicsData.topics?.length || 0;

            const docCount = document.getElementById("doc-count");
            const topicCount = document.getElementById("topic-count");

            if (docCount) docCount.textContent = count;
            if (topicCount) topicCount.textContent = count;
        }

        if (statsRes.ok) {
            const statsData = await statsRes.json();

            const chatCount = document.getElementById("chat-count");
            const weekCount = document.getElementById("week-count");

            if (chatCount) chatCount.textContent = statsData.chat_count || 0;
            if (weekCount) weekCount.textContent = statsData.week_count || 0;
        }
    } catch (err) {
        console.error("Load stats error:", err);
    }
}

// Sidebar Functions
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('collapsed');
    }
}

function toggleChatSidebar() {
    const sidebar = getSidebarForMode(currentChatMode);
    const toggleBtn = document.querySelector(".toggle-sidebar-btn");
    if (sidebar) {
        sidebar.classList.toggle('collapsed');
        if (toggleBtn) {
            toggleBtn.style.left = sidebar.classList.contains("collapsed") ? "10px" : "300px";
        }
    }
}

function startNewChat() {
    currentChatId = null;
    currentTopicId = null;
    currentSubject = null;
    currentChatMode = null;
    currentInjectedContext = null;
    clearChat();
    loadChatTopics();
}

// All Chats Functions
async function loadAllChats() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        const offlineAllowed = await canUseOfflineGuestMode();
        if (!offlineAllowed) {
            window.location.href = "/";
            return;
        }
    }

    try {
        const chatsRes = await authenticatedFetch("/api/chat/list-all");

        if (!chatsRes.ok) return;
        const chatsData = await chatsRes.json();
        const chats = chatsData.chats || [];
        const chatListDiv = document.getElementById("chat-list");

        if (!chatListDiv) return;

        chatListDiv.innerHTML = "";

        if (chats.length === 0) {
            chatListDiv.innerHTML = `
                <div style="padding: 20px; text-align: center; color: #999;">
                    No chats yet.<br>Upload a document to get started!
                </div>
            `;
            return;
        }

        chats.forEach(chat => {
            const chatItem = document.createElement("div");
            chatItem.className = "chat-item";
            chatItem.onclick = (e) => loadChatById(chat.chat_id, chat.topic_id, e);

            const displayTitle = chat.chat_title || chat.topic_name || "Chat session";
            const previewText = chat.topic_name || "Chat session";
            const createdAt = chat.created_at ? new Date(chat.created_at).toLocaleString() : "Click to load";

            const topRow = document.createElement("div");
            topRow.style.cssText = "display:flex;justify-content:space-between;align-items:flex-start;gap:8px;";
            const titleDiv = document.createElement("div");
            titleDiv.className = "chat-item-title";
            titleDiv.textContent = displayTitle;
            titleDiv.style.flex = "1";

            const deleteBtn = document.createElement("button");
            deleteBtn.textContent = "Delete";
            deleteBtn.style.cssText = `
                border:none;
                border-radius:6px;
                background:#dc2626;
                color:#fff;
                cursor:pointer;
                font-size:11px;
                padding:4px 8px;
            `;
            deleteBtn.onclick = async (e) => {
                e.stopPropagation();
                await deleteChat(chat.chat_id, displayTitle);
            };

            topRow.appendChild(titleDiv);
            topRow.appendChild(deleteBtn);
            chatItem.appendChild(topRow);

            const previewDiv = document.createElement("div");
            previewDiv.className = "chat-item-preview";
            previewDiv.textContent = previewText;
            chatItem.appendChild(previewDiv);

            const timeDiv = document.createElement("div");
            timeDiv.className = "chat-item-time";
            timeDiv.textContent = createdAt;
            chatItem.appendChild(timeDiv);

            chatListDiv.appendChild(chatItem);
        });

        if (chatListDiv.children.length === 0) {
            chatListDiv.innerHTML = `
                <div style="padding: 20px; text-align: center; color: #999;">
                    No chats yet.<br>Start a conversation!
                </div>
            `;
        }
    } catch (err) {
        console.error("Load all chats error:", err);
    }
}

async function deleteChat(chatId, chatTitle = "this chat") {
    const token = localStorage.getItem("access_token");
    if (!token || !chatId) return;

    if (!confirm(`Delete "${chatTitle}"? This will remove all messages in this chat.`)) {
        return;
    }

    try {
        const res = await authenticatedFetch(`/api/chat/${chatId}`, {
            method: "DELETE",
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to delete chat");

        if (currentChatId === chatId) {
            currentChatId = null;
            clearChat();
        }
        await loadAllChats();
    } catch (err) {
        console.error("Delete chat error:", err);
        alert(err.message || "Failed to delete chat");
    }
}

async function loadChatById(chatId, topicId, eventObj = null) {
    currentChatId = chatId;
    currentTopicId = topicId || null;
    currentSubject = null;
    currentInjectedContext = null;
    setChatMode("fundamentals");

    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    if (eventObj && eventObj.currentTarget) {
        eventObj.currentTarget.classList.add('active');
    }

    if (!document.getElementById("chat-messages")) {
        await loadChatTopics();
    }

    const topicSelect = document.getElementById("topic-select");
    if (topicSelect) {
        topicSelect.value = "";
    }

    await loadChatHistory(chatId);
}

if (document.getElementById('fileInput')) {
    document.addEventListener('DOMContentLoaded', updateFileList);
}
