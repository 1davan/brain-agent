/**
 * Brain Agent Dashboard JavaScript
 * Spreadsheet-style inline editing with drag-and-drop reordering
 */

// ============================================================================
// STATE
// ============================================================================

let currentUserId = '';
let autoRefreshInterval = null;
let searchTimeout = null;

// Track dirty state for save buttons
let memoriesData = [];
let memoriesDirty = false;
let memoriesDeleted = [];

let tasksData = [];
let tasksDirty = false;
let tasksDeleted = [];
let tasksReordered = false;

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initTabNavigation();
    loadUsers();
    updateStatus();
    setInterval(updateStatus, 5000);
});

// ============================================================================
// TAB NAVIGATION
// ============================================================================

function initTabNavigation() {
    const tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const tabId = this.dataset.tab;
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    // Update button states
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    // Update content visibility
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === 'tab-' + tabId);
    });

    // Load data for the tab
    if (tabId === 'settings') loadSettings();
    else if (tabId === 'memories') loadMemories();
    else if (tabId === 'tasks') loadTasks();
    else if (tabId === 'conversations') loadConversations();
    else if (tabId === 'commands') loadCommandStats();
    else if (tabId === 'logs') refreshLogs();
}

// ============================================================================
// USER SELECTOR
// ============================================================================

function loadUsers() {
    fetch('/api/users')
        .then(r => r.json())
        .then(data => {
            const select = document.getElementById('userSelect');
            select.innerHTML = '';

            if (data.success && data.users.length > 0) {
                data.users.forEach((user, idx) => {
                    const option = document.createElement('option');
                    option.value = user.user_id;
                    option.textContent = user.username ?
                        `${user.username} (${user.user_id})` :
                        user.user_id;
                    select.appendChild(option);
                });

                const savedUser = localStorage.getItem('selectedUserId');
                if (savedUser && data.users.find(u => u.user_id === savedUser)) {
                    select.value = savedUser;
                }
                currentUserId = select.value;
            } else {
                select.innerHTML = '<option value="">No users found</option>';
            }
        })
        .catch(e => {
            console.error('Failed to load users:', e);
            document.getElementById('userSelect').innerHTML =
                '<option value="">Error loading users</option>';
        });
}

function onUserChange() {
    const select = document.getElementById('userSelect');
    currentUserId = select.value;
    localStorage.setItem('selectedUserId', currentUserId);

    const activeTab = document.querySelector('.tab-btn.active');
    if (activeTab) {
        const tabId = activeTab.dataset.tab;
        if (tabId === 'memories') loadMemories();
        else if (tabId === 'tasks') loadTasks();
        else if (tabId === 'conversations') loadConversations();
    }
}

// ============================================================================
// TOAST NOTIFICATIONS
// ============================================================================

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast show ' + type;

    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

// ============================================================================
// SEARCH DEBOUNCE
// ============================================================================

function debounceSearch(callback) {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(callback, 300);
}

// ============================================================================
// MEMORIES - SPREADSHEET STYLE
// ============================================================================

function loadMemories() {
    const category = document.getElementById('memoryCategory').value;
    const search = document.getElementById('memorySearch').value;
    const loading = document.getElementById('memoriesLoading');
    const tbody = document.getElementById('memoriesList');

    loading.style.display = 'block';
    tbody.innerHTML = '';

    let url = `/api/memories?user_id=${encodeURIComponent(currentUserId)}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            loading.style.display = 'none';

            if (!data.success) {
                tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Error: ${data.error}</td></tr>`;
                return;
            }

            memoriesData = data.memories;
            memoriesDirty = false;
            memoriesDeleted = [];
            updateMemoriesSaveButton();

            if (data.memories.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No memories found. Click "+ Add Row" to create one.</td></tr>';
                return;
            }

            data.memories.forEach((memory, idx) => {
                tbody.appendChild(createMemoryRow(memory, idx));
            });
        })
        .catch(e => {
            loading.style.display = 'none';
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Error loading memories: ${e}</td></tr>`;
        });
}

function createMemoryRow(memory, idx) {
    const tr = document.createElement('tr');
    tr.dataset.idx = idx;
    tr.dataset.key = memory.key;
    tr.dataset.isNew = memory._isNew ? 'true' : 'false';

    let tags = [];
    try {
        tags = JSON.parse(memory.tags || '[]');
    } catch (e) {
        tags = [];
    }

    tr.innerHTML = `
        <td>
            <select class="cell-input" data-field="category" onchange="markMemoryDirty(${idx})">
                <option value="personal" ${memory.category === 'personal' ? 'selected' : ''}>Personal</option>
                <option value="work" ${memory.category === 'work' ? 'selected' : ''}>Work</option>
                <option value="preferences" ${memory.category === 'preferences' ? 'selected' : ''}>Preferences</option>
                <option value="knowledge" ${memory.category === 'knowledge' ? 'selected' : ''}>Knowledge</option>
                <option value="health" ${memory.category === 'health' ? 'selected' : ''}>Health</option>
                <option value="finance" ${memory.category === 'finance' ? 'selected' : ''}>Finance</option>
                <option value="relationships" ${memory.category === 'relationships' ? 'selected' : ''}>Relationships</option>
                <option value="goals" ${memory.category === 'goals' ? 'selected' : ''}>Goals</option>
                <option value="habits" ${memory.category === 'habits' ? 'selected' : ''}>Habits</option>
            </select>
        </td>
        <td>
            <input type="text" class="cell-input" data-field="key" value="${escapeHtml(memory.key)}"
                   onchange="markMemoryDirty(${idx})" ${memory._isNew ? '' : 'readonly'}>
        </td>
        <td>
            <textarea class="cell-input cell-textarea" data-field="value"
                      onchange="markMemoryDirty(${idx})">${escapeHtml(memory.value)}</textarea>
        </td>
        <td>
            <input type="range" class="cell-slider" data-field="confidence" min="0" max="100"
                   value="${Math.round(memory.confidence * 100)}" onchange="markMemoryDirty(${idx})">
            <span class="slider-value">${memory.confidence.toFixed(2)}</span>
        </td>
        <td>
            <input type="text" class="cell-input" data-field="tags" value="${tags.join(', ')}"
                   onchange="markMemoryDirty(${idx})" placeholder="tag1, tag2">
        </td>
        <td>
            <button class="btn-icon btn-delete" onclick="deleteMemoryRow(${idx})" title="Delete">&#x2715;</button>
        </td>
    `;

    // Update slider display on input
    const slider = tr.querySelector('input[type="range"]');
    const sliderValue = tr.querySelector('.slider-value');
    slider.addEventListener('input', () => {
        sliderValue.textContent = (slider.value / 100).toFixed(2);
    });

    return tr;
}

function addMemoryRow() {
    const newMemory = {
        user_id: currentUserId,
        category: 'knowledge',
        key: '',
        value: '',
        confidence: 0.8,
        tags: '[]',
        _isNew: true,
        _dirty: true
    };

    memoriesData.push(newMemory);
    const tbody = document.getElementById('memoriesList');

    // Remove empty state message if present
    if (tbody.querySelector('.empty-state')) {
        tbody.innerHTML = '';
    }

    tbody.appendChild(createMemoryRow(newMemory, memoriesData.length - 1));
    memoriesDirty = true;
    updateMemoriesSaveButton();

    // Focus the key input
    const lastRow = tbody.lastElementChild;
    lastRow.querySelector('input[data-field="key"]').focus();
}

function markMemoryDirty(idx) {
    memoriesData[idx]._dirty = true;
    memoriesDirty = true;
    updateMemoriesSaveButton();
}

function deleteMemoryRow(idx) {
    const memory = memoriesData[idx];

    if (!memory._isNew) {
        memoriesDeleted.push(memory.key);
    }

    memoriesData.splice(idx, 1);
    memoriesDirty = true;
    updateMemoriesSaveButton();

    // Re-render
    const tbody = document.getElementById('memoriesList');
    tbody.innerHTML = '';

    if (memoriesData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No memories. Click "+ Add Row" to create one.</td></tr>';
    } else {
        memoriesData.forEach((m, i) => {
            tbody.appendChild(createMemoryRow(m, i));
        });
    }
}

function updateMemoriesSaveButton() {
    const btn = document.getElementById('saveMemoriesBtn');
    btn.disabled = !memoriesDirty;
    btn.textContent = memoriesDirty ? 'Save Changes *' : 'Save Changes';
}

async function saveAllMemories() {
    const btn = document.getElementById('saveMemoriesBtn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        // Delete memories first
        for (const key of memoriesDeleted) {
            await fetch(`/api/memories/${encodeURIComponent(key)}?user_id=${encodeURIComponent(currentUserId)}`, {
                method: 'DELETE'
            });
        }

        // Save new and updated memories
        const rows = document.querySelectorAll('#memoriesList tr[data-idx]');
        for (let i = 0; i < memoriesData.length; i++) {
            const memory = memoriesData[i];
            if (!memory._dirty) continue;

            const row = rows[i];
            if (!row) continue;

            const tagsInput = row.querySelector('[data-field="tags"]').value;
            const tags = tagsInput.split(',').map(t => t.trim()).filter(t => t);

            const memoryData = {
                user_id: currentUserId,
                category: row.querySelector('[data-field="category"]').value,
                key: row.querySelector('[data-field="key"]').value,
                value: row.querySelector('[data-field="value"]').value,
                confidence: row.querySelector('[data-field="confidence"]').value / 100,
                tags: tags
            };

            if (!memoryData.key) continue;

            if (memory._isNew) {
                await fetch('/api/memories', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(memoryData)
                });
            } else {
                await fetch(`/api/memories/${encodeURIComponent(memory.key)}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(memoryData)
                });
            }
        }

        showToast('Memories saved successfully', 'success');
        loadMemories();
    } catch (e) {
        showToast('Error saving memories: ' + e, 'error');
        btn.disabled = false;
        btn.textContent = 'Save Changes *';
    }
}

// ============================================================================
// TASKS - SPREADSHEET STYLE WITH DRAG & DROP
// ============================================================================

function loadTasks() {
    const status = document.getElementById('taskStatus').value;
    const showArchived = document.getElementById('taskShowArchived').checked;
    const search = document.getElementById('taskSearch').value;
    const loading = document.getElementById('tasksLoading');
    const tbody = document.getElementById('tasksList');

    loading.style.display = 'block';
    tbody.innerHTML = '';

    let url = `/api/tasks?user_id=${encodeURIComponent(currentUserId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (showArchived) url += '&archived=true';
    if (search) url += `&search=${encodeURIComponent(search)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            loading.style.display = 'none';

            if (!data.success) {
                tbody.innerHTML = `<tr><td colspan="8" class="empty-state">Error: ${data.error}</td></tr>`;
                return;
            }

            tasksData = data.tasks;
            tasksDirty = false;
            tasksDeleted = [];
            tasksReordered = false;
            updateTasksSaveButton();

            if (data.tasks.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No tasks found. Click "+ Add Row" to create one.</td></tr>';
                return;
            }

            data.tasks.forEach((task, idx) => {
                tbody.appendChild(createTaskRow(task, idx));
            });

            initTaskDragDrop();
        })
        .catch(e => {
            loading.style.display = 'none';
            tbody.innerHTML = `<tr><td colspan="8" class="empty-state">Error loading tasks: ${e}</td></tr>`;
        });
}

function createTaskRow(task, idx) {
    const tr = document.createElement('tr');
    tr.dataset.idx = idx;
    tr.dataset.taskId = task.task_id || '';
    tr.dataset.isNew = task._isNew ? 'true' : 'false';
    tr.draggable = true;

    if (task.status === 'complete') tr.classList.add('row-complete');
    if (task.archived) tr.classList.add('row-archived');

    // Format deadline for datetime-local input
    let deadlineValue = '';
    if (task.deadline) {
        try {
            const dt = new Date(task.deadline);
            if (!isNaN(dt.getTime())) {
                deadlineValue = dt.toISOString().slice(0, 16);
            }
        } catch (e) {}
    }

    tr.innerHTML = `
        <td class="col-drag">
            <span class="drag-handle" title="Drag to reorder">&#x2630;</span>
        </td>
        <td>
            <input type="checkbox" class="cell-checkbox" data-field="status"
                   ${task.status === 'complete' ? 'checked' : ''} onchange="markTaskDirty(${idx})">
        </td>
        <td>
            <select class="cell-input cell-priority priority-${task.priority}" data-field="priority"
                    onchange="markTaskDirty(${idx}); updatePriorityColor(this)">
                <option value="critical" ${task.priority === 'critical' ? 'selected' : ''}>Critical</option>
                <option value="high" ${task.priority === 'high' ? 'selected' : ''}>High</option>
                <option value="medium" ${task.priority === 'medium' ? 'selected' : ''}>Medium</option>
                <option value="low" ${task.priority === 'low' ? 'selected' : ''}>Low</option>
            </select>
        </td>
        <td>
            <input type="text" class="cell-input" data-field="title" value="${escapeHtml(task.title)}"
                   onchange="markTaskDirty(${idx})" placeholder="Task title">
        </td>
        <td>
            <textarea class="cell-input cell-textarea" data-field="description"
                      onchange="markTaskDirty(${idx})" placeholder="Description">${escapeHtml(task.description)}</textarea>
        </td>
        <td>
            <input type="range" class="cell-slider" data-field="progress_percent" min="0" max="100"
                   value="${task.progress_percent}" onchange="markTaskDirty(${idx})">
            <span class="slider-value">${task.progress_percent}%</span>
        </td>
        <td>
            <input type="datetime-local" class="cell-input cell-datetime" data-field="deadline"
                   value="${deadlineValue}" onchange="markTaskDirty(${idx})">
        </td>
        <td>
            <button class="btn-icon btn-delete" onclick="deleteTaskRow(${idx})" title="Archive">&#x2715;</button>
        </td>
    `;

    // Update slider display on input
    const slider = tr.querySelector('input[type="range"]');
    const sliderValue = tr.querySelector('.slider-value');
    slider.addEventListener('input', () => {
        sliderValue.textContent = slider.value + '%';
    });

    return tr;
}

function updatePriorityColor(select) {
    select.className = 'cell-input cell-priority priority-' + select.value;
}

function addTaskRow() {
    const newTask = {
        user_id: currentUserId,
        task_id: '',
        title: '',
        description: '',
        priority: 'medium',
        status: 'pending',
        deadline: '',
        progress_percent: 0,
        _isNew: true,
        _dirty: true
    };

    // Add at the beginning (highest priority position)
    tasksData.unshift(newTask);
    const tbody = document.getElementById('tasksList');

    if (tbody.querySelector('.empty-state')) {
        tbody.innerHTML = '';
    }

    // Re-render all rows with updated indices
    tbody.innerHTML = '';
    tasksData.forEach((task, idx) => {
        tbody.appendChild(createTaskRow(task, idx));
    });

    tasksDirty = true;
    updateTasksSaveButton();
    initTaskDragDrop();

    // Focus the title input
    tbody.querySelector('input[data-field="title"]').focus();
}

function markTaskDirty(idx) {
    tasksData[idx]._dirty = true;
    tasksDirty = true;
    updateTasksSaveButton();

    // Update row styling based on checkbox
    const row = document.querySelector(`#tasksList tr[data-idx="${idx}"]`);
    if (row) {
        const checkbox = row.querySelector('[data-field="status"]');
        row.classList.toggle('row-complete', checkbox.checked);
    }
}

function deleteTaskRow(idx) {
    const task = tasksData[idx];

    if (!task._isNew && task.task_id) {
        tasksDeleted.push(task.task_id);
    }

    tasksData.splice(idx, 1);
    tasksDirty = true;
    updateTasksSaveButton();

    // Re-render
    const tbody = document.getElementById('tasksList');
    tbody.innerHTML = '';

    if (tasksData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No tasks. Click "+ Add Row" to create one.</td></tr>';
    } else {
        tasksData.forEach((t, i) => {
            tbody.appendChild(createTaskRow(t, i));
        });
        initTaskDragDrop();
    }
}

function updateTasksSaveButton() {
    const btn = document.getElementById('saveTasksBtn');
    const hasChanges = tasksDirty || tasksReordered;
    btn.disabled = !hasChanges;
    btn.textContent = hasChanges ? 'Save Changes *' : 'Save Changes';
}

// ============================================================================
// DRAG AND DROP FOR TASKS
// ============================================================================

let draggedRow = null;

function initTaskDragDrop() {
    const tbody = document.getElementById('tasksList');
    const rows = tbody.querySelectorAll('tr[draggable="true"]');

    rows.forEach(row => {
        row.addEventListener('dragstart', handleDragStart);
        row.addEventListener('dragend', handleDragEnd);
        row.addEventListener('dragover', handleDragOver);
        row.addEventListener('drop', handleDrop);
        row.addEventListener('dragenter', handleDragEnter);
        row.addEventListener('dragleave', handleDragLeave);
    });
}

function handleDragStart(e) {
    draggedRow = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', this.innerHTML);
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('#tasksList tr').forEach(row => {
        row.classList.remove('drag-over');
    });
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
    this.classList.add('drag-over');
}

function handleDragLeave(e) {
    this.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();

    if (draggedRow !== this) {
        const tbody = document.getElementById('tasksList');
        const rows = Array.from(tbody.querySelectorAll('tr[data-idx]'));
        const fromIdx = parseInt(draggedRow.dataset.idx);
        const toIdx = parseInt(this.dataset.idx);

        // Reorder in data array
        const [moved] = tasksData.splice(fromIdx, 1);
        tasksData.splice(toIdx, 0, moved);

        // Mark all as needing priority update
        tasksData.forEach((task, i) => {
            task._newOrder = i;
        });

        tasksReordered = true;
        updateTasksSaveButton();

        // Re-render
        tbody.innerHTML = '';
        tasksData.forEach((task, idx) => {
            tbody.appendChild(createTaskRow(task, idx));
        });
        initTaskDragDrop();
    }

    this.classList.remove('drag-over');
}

async function saveAllTasks() {
    const btn = document.getElementById('saveTasksBtn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        // Archive deleted tasks
        for (const taskId of tasksDeleted) {
            await fetch(`/api/tasks/${encodeURIComponent(taskId)}?user_id=${encodeURIComponent(currentUserId)}`, {
                method: 'DELETE'
            });
        }

        // Save tasks in order (position = priority)
        const rows = document.querySelectorAll('#tasksList tr[data-idx]');
        const priorityMap = {0: 'critical', 1: 'critical', 2: 'high', 3: 'high'};

        for (let i = 0; i < tasksData.length; i++) {
            const task = tasksData[i];
            const row = rows[i];
            if (!row) continue;

            // Calculate priority based on position if reordered
            let priority = row.querySelector('[data-field="priority"]').value;

            const checkbox = row.querySelector('[data-field="status"]');
            const taskData = {
                user_id: currentUserId,
                title: row.querySelector('[data-field="title"]').value,
                description: row.querySelector('[data-field="description"]').value,
                priority: priority,
                status: checkbox.checked ? 'complete' : 'pending',
                deadline: row.querySelector('[data-field="deadline"]').value,
                progress_percent: parseInt(row.querySelector('[data-field="progress_percent"]').value)
            };

            if (!taskData.title) continue;

            if (task._isNew) {
                await fetch('/api/tasks', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(taskData)
                });
            } else if (task._dirty || tasksReordered) {
                await fetch(`/api/tasks/${encodeURIComponent(task.task_id)}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(taskData)
                });
            }
        }

        showToast('Tasks saved successfully', 'success');
        loadTasks();
    } catch (e) {
        showToast('Error saving tasks: ' + e, 'error');
        btn.disabled = false;
        btn.textContent = 'Save Changes *';
    }
}

// ============================================================================
// CONVERSATIONS
// ============================================================================

function loadConversations() {
    const sessionId = document.getElementById('conversationSession').value;
    const search = document.getElementById('conversationSearch').value;
    const loading = document.getElementById('conversationsLoading');
    const list = document.getElementById('conversationsList');

    loading.style.display = 'block';
    list.innerHTML = '';

    let url = `/api/conversations?user_id=${encodeURIComponent(currentUserId)}`;
    if (sessionId) url += `&session_id=${encodeURIComponent(sessionId)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            loading.style.display = 'none';

            if (!data.success) {
                list.innerHTML = `<div class="empty-state">Error: ${data.error}</div>`;
                return;
            }

            // Update session dropdown
            const sessionSelect = document.getElementById('conversationSession');
            const currentValue = sessionSelect.value;
            sessionSelect.innerHTML = '<option value="">All Sessions</option>';
            data.sessions.forEach(session => {
                const option = document.createElement('option');
                option.value = session;
                option.textContent = session;
                sessionSelect.appendChild(option);
            });
            sessionSelect.value = currentValue;

            if (data.conversations.length === 0) {
                list.innerHTML = '<div class="empty-state">No conversations found.</div>';
                return;
            }

            // Group by session
            const grouped = {};
            data.conversations.forEach(conv => {
                if (!grouped[conv.session_id]) {
                    grouped[conv.session_id] = [];
                }
                grouped[conv.session_id].push(conv);
            });

            Object.keys(grouped).forEach(sessionId => {
                const sessionDiv = document.createElement('div');
                sessionDiv.className = 'conversation-session';

                const header = document.createElement('div');
                header.className = 'session-header';
                header.innerHTML = `<strong>Session:</strong> ${escapeHtml(sessionId)}`;
                sessionDiv.appendChild(header);

                const messages = document.createElement('div');
                messages.className = 'session-messages';

                grouped[sessionId].sort((a, b) =>
                    new Date(a.timestamp) - new Date(b.timestamp)
                );

                grouped[sessionId].forEach(conv => {
                    const msg = document.createElement('div');
                    msg.className = `message message-${conv.message_type}`;
                    msg.innerHTML = `
                        <div class="message-header">
                            <span class="message-type">${conv.message_type}</span>
                            <span class="message-time">${formatDate(conv.timestamp)}</span>
                            ${conv.intent ? `<span class="intent-badge">${escapeHtml(conv.intent)}</span>` : ''}
                        </div>
                        <div class="message-content">${escapeHtml(conv.content)}</div>
                    `;
                    messages.appendChild(msg);
                });

                sessionDiv.appendChild(messages);
                list.appendChild(sessionDiv);
            });
        })
        .catch(e => {
            loading.style.display = 'none';
            list.innerHTML = `<div class="empty-state">Error loading conversations: ${e}</div>`;
        });
}

// ============================================================================
// LOGS
// ============================================================================

function refreshLogs() {
    fetch('/api/logs')
        .then(r => r.json())
        .then(data => {
            const viewer = document.getElementById('logViewer');
            if (data.logs && data.logs.length > 0) {
                viewer.textContent = data.logs.join('\n');
                viewer.scrollTop = viewer.scrollHeight;
            } else {
                viewer.textContent = 'No logs available. Start the bot to see output.';
            }
        })
        .catch(e => {
            document.getElementById('logViewer').textContent = 'Error fetching logs: ' + e;
        });
}

function toggleAutoRefresh() {
    const checkbox = document.getElementById('autoRefresh');
    if (checkbox.checked) {
        refreshLogs();
        autoRefreshInterval = setInterval(refreshLogs, 3000);
    } else {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }
}

// ============================================================================
// STATUS
// ============================================================================

function updateStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            const badge = document.querySelector('.status-badge');
            if (badge) {
                badge.textContent = 'Bot: ' + data.status.toUpperCase();
                badge.className = 'status-badge status-' + data.status;
            }
        });
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;

    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ============================================================================
// BOT COMMANDS
// ============================================================================

async function triggerCheckin() {
    const btn = document.getElementById('btnCheckin');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending...';

    try {
        const response = await fetch('/api/commands/checkin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Check-in sent successfully', 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to send check-in: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Send Check-in Now';
    }
}

async function triggerDailySummary() {
    const btn = document.getElementById('btnSummary');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending...';

    try {
        const response = await fetch('/api/commands/daily-summary', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Daily summary sent successfully', 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to send summary: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Send Daily Summary';
    }
}

async function clearSession() {
    const btn = document.getElementById('btnClearSession');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Clearing...';

    try {
        const response = await fetch('/api/commands/clear-session', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Session cleared', 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to clear session: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Clear Session';
    }
}

async function runAutoArchive() {
    const btn = document.getElementById('btnArchive');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Running...';

    try {
        const response = await fetch('/api/commands/auto-archive', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast(`Archived ${data.archived_count} task(s)`, 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to run auto-archive: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Run Auto-Archive';
    }
}

async function processRecurring() {
    const btn = document.getElementById('btnRecurring');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Processing...';

    try {
        const response = await fetch('/api/commands/process-recurring', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast(data.message || 'Recurring tasks processed', 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to process recurring: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Process Recurring';
    }
}

async function checkDeadlines() {
    const btn = document.getElementById('btnDeadlines');
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Checking...';

    try {
        const response = await fetch('/api/commands/check-deadlines', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await response.json();

        if (data.success) {
            showToast(`Sent ${data.reminders_sent} deadline reminder(s)`, 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to check deadlines: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Check Deadlines';
    }
}

async function sendCustomMessage() {
    const btn = document.getElementById('btnSendMessage');
    const textarea = document.getElementById('customMessage');
    const message = textarea.value.trim();

    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    if (!message) {
        showToast('Please enter a message', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending...';

    try {
        const response = await fetch('/api/commands/send-message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId, message: message})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Message sent successfully', 'success');
            textarea.value = '';
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to send message: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Send to User';
    }
}

async function loadCommandStats() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`/api/commands/stats?user_id=${encodeURIComponent(currentUserId)}`);
        const data = await response.json();

        if (data.success) {
            document.getElementById('statBotStatus').textContent = data.bot_status || '--';
            document.getElementById('statCheckinHours').textContent = data.checkin_hours || '--';
            document.getElementById('statCurrentHour').textContent = data.current_hour || '--';
            document.getElementById('statPendingTasks').textContent = data.pending_tasks || '0';
        }
    } catch (e) {
        console.error('Failed to load command stats:', e);
    }

    // Also load user settings
    loadUserSettings();
}

// ============================================================================
// USER SETTINGS
// ============================================================================

async function loadUserSettings() {
    if (!currentUserId) return;

    try {
        const response = await fetch(`/api/users/${encodeURIComponent(currentUserId)}/settings`);
        const data = await response.json();

        if (data.success && data.settings) {
            document.getElementById('settingEmailEnabled').checked = data.settings.email_enabled;
            document.getElementById('settingCalendarEnabled').checked = data.settings.calendar_enabled;
            document.getElementById('settingCalendarId').value = data.settings.calendar_id || '';
            document.getElementById('settingCheckinHours').value = data.settings.checkin_hours || '';
        }
    } catch (e) {
        console.error('Failed to load user settings:', e);
    }
}

async function toggleUserSetting(settingName, value) {
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    try {
        const body = {};
        body[settingName] = value;

        const response = await fetch(`/api/users/${encodeURIComponent(currentUserId)}/settings`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        const data = await response.json();

        if (data.success) {
            showToast(`${settingName.replace('_', ' ')} ${value ? 'enabled' : 'disabled'}`, 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
            // Revert checkbox
            if (settingName === 'email_enabled') {
                document.getElementById('settingEmailEnabled').checked = !value;
            } else if (settingName === 'calendar_enabled') {
                document.getElementById('settingCalendarEnabled').checked = !value;
            }
        }
    } catch (e) {
        showToast('Failed to update setting: ' + e, 'error');
    }
}

async function saveCalendarId() {
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    const calendarId = document.getElementById('settingCalendarId').value.trim();

    try {
        const response = await fetch(`/api/users/${encodeURIComponent(currentUserId)}/settings`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({calendar_id: calendarId})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Calendar ID saved', 'success');
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to save calendar ID: ' + e, 'error');
    }
}

async function saveCheckinHours() {
    if (!currentUserId) {
        showToast('Please select a user first', 'error');
        return;
    }

    const checkinHours = document.getElementById('settingCheckinHours').value.trim();

    try {
        const response = await fetch(`/api/users/${encodeURIComponent(currentUserId)}/settings`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({checkin_hours: checkinHours})
        });
        const data = await response.json();

        if (data.success) {
            showToast('Check-in hours saved', 'success');
            loadCommandStats(); // Refresh the stats display
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to save check-in hours: ' + e, 'error');
    }
}

// ============================================================================
// SETTINGS TAB - Per-User Config Management
// ============================================================================

// Mapping of setting variables to their category sections
const SETTINGS_CATEGORIES = {
    proactive: [
        'daily_summary_enabled', 'daily_summary_hour', 'default_checkin_hours',
        'checkins_enabled', 'deadline_reminders_enabled', 'reminder_minutes_before',
        'proactive_check_interval'
    ],
    tasks: [
        'task_archive_days', 'default_task_priority', 'auto_create_calendar_for_tasks'
    ],
    ai: [
        'max_memories_context', 'max_tasks_context', 'max_conversations_context',
        'discussion_mode_memory_limit', 'discussion_mode_task_limit', 'use_pipeline', 'ai_model'
    ],
    session: [
        'session_timeout_minutes', 'typing_indicator_enabled', 'include_calendar_in_responses'
    ],
    voice: [
        'voice_transcription_enabled', 'show_transcription_in_response'
    ],
    email: [
        'email_require_confirmation', 'email_default_sign_off'
    ],
    calendar: [
        'calendar_lookahead_days', 'calendar_delete_requires_confirmation'
    ],
    system: [
        'timezone', 'bot_name', 'debug_mode'
    ]
};

let settingsData = [];
let settingsUserId = '';

async function loadSettings() {
    const userFilter = document.getElementById('settingsUserFilter');
    const search = document.getElementById('settingsSearch').value.toLowerCase();
    const loading = document.getElementById('settingsLoading');

    settingsUserId = userFilter.value;

    loading.style.display = 'block';

    // Populate user dropdown if not already done
    if (userFilter.options.length <= 1) {
        try {
            const usersResponse = await fetch('/api/users');
            const usersData = await usersResponse.json();
            if (usersData.success && usersData.users.length > 0) {
                usersData.users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.user_id;
                    option.textContent = user.username ?
                        `${user.username} (${user.user_id})` :
                        `User ${user.user_id}`;
                    userFilter.appendChild(option);
                });
            }
        } catch (e) {
            console.error('Failed to load users for settings:', e);
        }
    }

    try {
        // Fetch config with raw details
        let url = '/api/config?raw=true';
        if (settingsUserId) {
            url += `&user_id=${encodeURIComponent(settingsUserId)}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        loading.style.display = 'none';

        if (!data.success) {
            showToast('Error loading settings: ' + data.error, 'error');
            return;
        }

        settingsData = data.config;

        // Render settings by category
        renderSettingsCategory('settingsProactive', SETTINGS_CATEGORIES.proactive, search);
        renderSettingsCategory('settingsTasks', SETTINGS_CATEGORIES.tasks, search);
        renderSettingsCategory('settingsAI', SETTINGS_CATEGORIES.ai, search);
        renderSettingsCategory('settingsSession', SETTINGS_CATEGORIES.session, search);
        renderSettingsCategory('settingsVoice', SETTINGS_CATEGORIES.voice, search);
        renderSettingsCategory('settingsEmail', SETTINGS_CATEGORIES.email, search);
        renderSettingsCategory('settingsCalendar', SETTINGS_CATEGORIES.calendar, search);
        renderSettingsCategory('settingsSystem', SETTINGS_CATEGORIES.system, search);

    } catch (e) {
        loading.style.display = 'none';
        showToast('Error loading settings: ' + e, 'error');
    }
}

function renderSettingsCategory(containerId, variables, search) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    variables.forEach(varName => {
        const setting = settingsData.find(s => s.variable === varName);
        if (!setting) return;

        // Apply search filter
        if (search && !varName.toLowerCase().includes(search) &&
            !setting.description.toLowerCase().includes(search)) {
            return;
        }

        const isUserOverride = setting.user_id && setting.user_id !== '';
        const row = createSettingRow(setting, isUserOverride);
        container.appendChild(row);
    });

    // Hide section if empty after filtering
    const section = container.closest('.settings-section');
    if (container.children.length === 0) {
        section.style.display = 'none';
    } else {
        section.style.display = '';
    }
}

function createSettingRow(setting, isUserOverride) {
    const div = document.createElement('div');
    div.className = 'setting-item' + (isUserOverride ? ' user-override' : '');
    div.dataset.variable = setting.variable;

    const labelText = setting.variable.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

    let inputHtml = '';
    if (setting.type === 'bool') {
        const isChecked = setting.value.toLowerCase() === 'true';
        inputHtml = `
            <label class="toggle-switch">
                <input type="checkbox" data-var="${escapeHtml(setting.variable)}"
                       ${isChecked ? 'checked' : ''} onchange="updateSetting('${escapeHtml(setting.variable)}', this.checked ? 'true' : 'false')">
                <span class="toggle-slider"></span>
            </label>
        `;
    } else if (setting.type === 'int') {
        inputHtml = `
            <input type="number" class="setting-input" data-var="${escapeHtml(setting.variable)}"
                   value="${escapeHtml(setting.value)}"
                   onchange="updateSetting('${escapeHtml(setting.variable)}', this.value)">
        `;
    } else {
        inputHtml = `
            <input type="text" class="setting-input" data-var="${escapeHtml(setting.variable)}"
                   value="${escapeHtml(setting.value)}"
                   onchange="updateSetting('${escapeHtml(setting.variable)}', this.value)">
        `;
    }

    let revertBtn = '';
    if (isUserOverride && settingsUserId) {
        revertBtn = `<button class="btn-icon btn-revert" onclick="revertSetting('${escapeHtml(setting.variable)}')" title="Revert to global default">&#x21B6;</button>`;
    }

    div.innerHTML = `
        <div class="setting-header">
            <span class="setting-name">${labelText}</span>
            ${isUserOverride ? '<span class="override-badge">User Override</span>' : ''}
            ${revertBtn}
        </div>
        <div class="setting-control">
            ${inputHtml}
        </div>
        <div class="setting-description">${escapeHtml(setting.description)}</div>
    `;

    return div;
}

async function updateSetting(variable, value) {
    try {
        const body = {
            value: value
        };

        // If a user is selected, this becomes a user-specific override
        if (settingsUserId) {
            body.user_id = settingsUserId;
        }

        const response = await fetch(`/api/config/${encodeURIComponent(variable)}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });

        const data = await response.json();

        if (data.success) {
            showToast(`${variable.replace(/_/g, ' ')} updated`, 'success');
            // Reload to reflect any override badge changes
            loadSettings();
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to update setting: ' + e, 'error');
    }
}

async function revertSetting(variable) {
    if (!settingsUserId) {
        showToast('No user selected to revert', 'error');
        return;
    }

    if (!confirm(`Revert "${variable.replace(/_/g, ' ')}" to global default for this user?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/config/${encodeURIComponent(variable)}?user_id=${encodeURIComponent(settingsUserId)}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Reverted to global default`, 'success');
            loadSettings();
        } else {
            showToast('Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Failed to revert setting: ' + e, 'error');
    }
}
