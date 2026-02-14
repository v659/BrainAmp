// Configuration
const CONFIG = {
    MAX_FILE_SIZE: 15 * 1024 * 1024, // 15MB
    MAX_FILES: 5,
    ALLOWED_EXTENSIONS: ['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg'],
    MAX_MESSAGE_LENGTH: 2000,
    REQUEST_TIMEOUT: 30000, // 30 seconds
};
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
        window.location.href = "/";
        return;
    }

    try {
        const res = await fetch("/api/me", {
            headers: { "Authorization": "Bearer " + token }
        });

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

        const response = await fetch('/api/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${accessToken}` },
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
        const res = await fetch(api, {
            headers: { "Authorization": "Bearer " + token }
        });

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        const container = document.getElementById("topics-container");

        if (!container) return;

        container.innerHTML = "";

        let topics = data.topics;
        if (!topics && Array.isArray(data.result_topics)) {
            topics = data.result_topics.map((t, i) => ({
                topic: t.topic,
                content: data.result_content?.[i]?.content || "",
                subject: "Uncategorized",
                created_at: null
            }));
        }

        if (!topics || topics.length === 0) {
            container.innerHTML = `
                <div style="padding: 20px; text-align: center; color: #999;">
                    No topics yet. Upload a document to get started!
                </div>
            `;
            return;
        }

        const grouped = {};
        topics.forEach((topicObj) => {
            const subject = topicObj.subject || "Uncategorized";
            if (!grouped[subject]) grouped[subject] = [];
            grouped[subject].push(topicObj);
        });

        Object.keys(grouped).sort().forEach(subject => {
            const sectionTitle = document.createElement("h3");
            sectionTitle.textContent = subject;
            sectionTitle.style.cssText = `
                width: 80%;
                margin: 20px auto 8px auto;
                font-size: 1rem;
                color: #374151;
            `;
            container.appendChild(sectionTitle);

            grouped[subject].forEach((topicObj) => {
                const topic = topicObj.topic || "Untitled";
                const content = topicObj.content || "No content available";
                const createdAt = topicObj.created_at ? new Date(topicObj.created_at).toLocaleDateString() : "Unknown date";

                const wrapper = document.createElement("div");
                wrapper.style.cssText = `
                    width: 80%;
                    margin: 10px auto;
                    border-radius: 8px;
                    background: #fff;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.1);
                `;

                const button = document.createElement("button");
                button.textContent = `${topic} (${createdAt})`;
                button.style.cssText = `
                    width: 100%;
                    padding: 14px;
                    font-size: 1rem;
                    text-align: left;
                    border: none;
                    background: transparent;
                    cursor: pointer;
                    font-weight: 600;
                `;

                const contentDiv = document.createElement("div");
                contentDiv.style.cssText = `
                    display: none;
                    padding: 14px;
                    border-top: 1px solid #ddd;
                `;

                const pre = document.createElement("pre");
                pre.textContent = content;
                pre.style.cssText = `
                    white-space: pre-wrap;
                    margin: 0;
                    max-height: 400px;
                    overflow-y: auto;
                `;

                contentDiv.appendChild(pre);

                button.onclick = () => {
                    const isOpen = contentDiv.style.display === "block";
                    contentDiv.style.display = isOpen ? "none" : "block";
                };

                wrapper.appendChild(button);
                wrapper.appendChild(contentDiv);
                container.appendChild(wrapper);
            });
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

async function loadSubjectPresets() {
    const token = localStorage.getItem("access_token");
    const listDiv = document.getElementById("subject-preset-list");
    if (!listDiv) return;
    if (!token) {
        listDiv.innerHTML = `<div style="color:#dc2626;padding:8px 0;">Not logged in.</div>`;
        return;
    }

    try {
        const res = await fetch("/api/subject-presets", {
            headers: { "Authorization": "Bearer " + token }
        });
        if (!res.ok) throw new Error("Failed to load subject presets");
        const data = await res.json();
        const presets = data.presets || [];

        listDiv.innerHTML = "";
        if (presets.length === 0) {
            listDiv.innerHTML = `<div style="color:#6b7280;padding:8px 0;">No presets found</div>`;
            return;
        }

        presets.forEach((preset, index) => {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #eee;";

            const name = document.createElement("span");
            name.textContent = preset.subject;
            row.appendChild(name);

            if (preset.id) {
                const controls = document.createElement("div");
                controls.style.cssText = "display:flex;gap:6px;";
                const upBtn = document.createElement("button");
                upBtn.textContent = "Up";
                upBtn.style.cssText = "padding:6px 10px;cursor:pointer;";
                upBtn.disabled = index === 0;
                upBtn.onclick = () => reorderSubjectPreset(index, -1, presets);

                const downBtn = document.createElement("button");
                downBtn.textContent = "Down";
                downBtn.style.cssText = "padding:6px 10px;cursor:pointer;";
                downBtn.disabled = index === presets.length - 1;
                downBtn.onclick = () => reorderSubjectPreset(index, 1, presets);

                controls.appendChild(upBtn);
                controls.appendChild(downBtn);
                row.appendChild(controls);
            }

            listDiv.appendChild(row);
        });
    } catch (err) {
        console.error("Load subject presets error:", err);
        listDiv.innerHTML = DEFAULT_SUBJECT_PRESETS.map(name =>
            `<div style="padding:8px 0;border-bottom:1px solid #eee;">${sanitizeInput(name)}</div>`
        ).join('');
    }
}

async function addSubjectPreset() {
    const token = localStorage.getItem("access_token");
    const input = document.getElementById("new-subject-input");
    if (!token || !input) return;

    const subject = input.value.trim();
    if (!subject) return;

    try {
        const res = await fetch("/api/subject-presets", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ subject })
        });
        if (!res.ok) throw new Error("Failed to add subject preset");
        input.value = "";
        await loadSubjectPresets();
    } catch (err) {
        console.error("Add subject preset error:", err);
        alert("Failed to add subject preset");
    }
}

async function reorderSubjectPreset(index, direction, presets) {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    const target = index + direction;
    if (target < 0 || target >= presets.length) return;

    const cloned = [...presets];
    const [moved] = cloned.splice(index, 1);
    cloned.splice(target, 0, moved);
    const presetIds = cloned.map(p => p.id).filter(Boolean);

    try {
        const res = await fetch("/api/subject-presets/reorder", {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ preset_ids: presetIds })
        });
        if (!res.ok) throw new Error("Failed to reorder");
        await loadSubjectPresets();
    } catch (err) {
        console.error("Reorder subject presets error:", err);
        alert("Failed to reorder subject presets");
    }
}

// Chat Functions
let currentTopicId = null;
let currentChatId = null;
let currentSubject = null;

async function loadChatTopics() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/dashboard";
        return;
    }

    try {
        const res = await fetch("/api/subject-presets", {
            headers: { "Authorization": "Bearer " + token }
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        const presets = data.presets || [];
        const container = document.getElementById("topics-container");

        if (!container) return;

        container.innerHTML = "";

        // Create optional subject selection UI
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

        // Create chat interface
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
        chatInputContainer.style.cssText = `
            display: flex;
            gap: 10px;
        `;

        const chatInput = document.createElement("textarea");
        chatInput.id = "chat-input";
        chatInput.placeholder = "Type your message (you can mention subject in text, or use date range like from 2026-01-01 to 2026-01-15)...";
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
    contentDiv.textContent = message;
    contentDiv.style.cssText = `
        white-space: pre-wrap;
        word-wrap: break-word;
    `;

    messageDiv.appendChild(senderDiv);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
    const input = document.getElementById("chat-input");
    const message = input.value.trim();

    if (!message) {
        alert("Please enter a message");
        return;
    }

    if (message.length > CONFIG.MAX_MESSAGE_LENGTH) {
        alert(`Message too long (max ${CONFIG.MAX_MESSAGE_LENGTH} characters)`);
        return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/";
        return;
    }

    input.value = "";
    addMessageToChat("You", message, true);

    try {
        const response = await fetch("/api/chat/send", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
            },
            body: JSON.stringify({
                topic_id: currentTopicId,
                subject: currentSubject,
                chat_id: currentChatId,
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

    } catch (err) {
        console.error("Send message error:", err);
        addMessageToChat("System", "Error: Failed to get AI response. Please try again.", false);
    }
}

async function loadChatHistory(chatId) {
    const token = localStorage.getItem("access_token");
    if (!token || !chatId) return;

    try {
        const res = await fetch(`/api/chat/history/${chatId}`, {
            headers: { "Authorization": "Bearer " + token }
        });

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
        const res = await fetch("/api/me", {
            headers: { "Authorization": "Bearer " + token }
        });

        if (!res.ok) {
            window.location.href = "/";
            return;
        }

        const user = await res.json();
        const emailInput = document.getElementById("email");
        const displayNameInput = document.getElementById("display-name");

        if (emailInput) emailInput.value = user.email || "";
        if (displayNameInput) displayNameInput.value = user.display_name || "";
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

    const token = localStorage.getItem("access_token");
    const btn = document.querySelector('.btn-save');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
        const res = await fetch("/api/update-profile", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token
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
            fetch("/api/chat/topics", {
                headers: { "Authorization": "Bearer " + token }
            }),
            fetch("/api/dashboard/stats", {
                headers: { "Authorization": "Bearer " + token }
            })
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
    const sidebar = document.getElementById('chat-sidebar');
    if (sidebar) {
        sidebar.classList.toggle('collapsed');
    }
}

function startNewChat() {
    currentChatId = null;
    currentTopicId = null;
    currentSubject = null;
    clearChat();
    loadChatTopics();
}

// All Chats Functions
async function loadAllChats() {
    const token = localStorage.getItem("access_token");
    if (!token) {
        window.location.href = "/";
        return;
    }

    try {
        const chatsRes = await fetch("/api/chat/list-all", {
            headers: { "Authorization": "Bearer " + token }
        });

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

            chatItem.innerHTML = `
                <div class="chat-item-title">${sanitizeInput(displayTitle)}</div>
                <div class="chat-item-preview">${sanitizeInput(previewText)}</div>
                <div class="chat-item-time">${sanitizeInput(createdAt)}</div>
            `;

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

async function loadChatById(chatId, topicId, eventObj = null) {
    currentChatId = chatId;
    currentTopicId = topicId || null;
    currentSubject = null;

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
