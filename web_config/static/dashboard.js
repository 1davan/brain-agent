/**
 * Brain Agent Dashboard JavaScript
 * Handles tab navigation, data loading, and CRUD operations
 */

// ============================================================================
// STATE
// ============================================================================

let currentUserId = '';
let autoRefreshInterval = null;
let searchTimeout = null;

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
    if (tabId === 'memories') loadMemories();
    else if (tabId === 'tasks') loadTasks();
    else if (tabId === 'conversations') loadConversations();
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

                // Set default user (first one or from localStorage)
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

    // Reload current tab data
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
// MEMORIES
// ============================================================================

function loadMemories() {
    const category = document.getElementById('memoryCategory').value;
    const search = document.getElementById('memorySearch').value;
    const loading = document.getElementById('memoriesLoading');
    const list = document.getElementById('memoriesList');

    loading.style.display = 'block';
    list.innerHTML = '';

    let url = `/api/memories?user_id=${encodeURIComponent(currentUserId)}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            loading.style.display = 'none';

            if (!data.success) {
                list.innerHTML = `<div class="empty-state">Error: ${data.error}</div>`;
                return;
            }

            if (data.memories.length === 0) {
                list.innerHTML = '<div class="empty-state">No memories found. Click "+ Add Memory" to create one.</div>';
                return;
            }

            data.memories.forEach(memory => {
                list.appendChild(createMemoryCard(memory));
            });
        })
        .catch(e => {
            loading.style.display = 'none';
            list.innerHTML = `<div class="empty-state">Error loading memories: ${e}</div>`;
        });
}

function createMemoryCard(memory) {
    const card = document.createElement('div');
    card.className = 'data-card';

    let tags = [];
    try {
        tags = JSON.parse(memory.tags || '[]');
    } catch (e) {
        tags = [];
    }

    const confidencePercent = Math.round(memory.confidence * 100);

    card.innerHTML = `
        <div class="card-header">
            <span class="category-badge category-${memory.category}">${memory.category}</span>
            <span class="memory-key">${escapeHtml(memory.key)}</span>
            <div class="card-actions">
                <button class="btn btn-secondary btn-small" onclick="editMemory('${escapeHtml(memory.key)}')">Edit</button>
                <button class="btn btn-danger btn-small" onclick="deleteMemory('${escapeHtml(memory.key)}')">Delete</button>
            </div>
        </div>
        <div class="card-body">
            <p class="memory-value">${escapeHtml(memory.value)}</p>
        </div>
        <div class="card-footer">
            <div class="confidence-display">
                <span>Confidence:</span>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${confidencePercent}%"></div>
                </div>
                <span>${memory.confidence.toFixed(2)}</span>
            </div>
            <div class="tags">
                ${tags.map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
            </div>
        </div>
    `;

    return card;
}

function showAddMemoryModal() {
    document.getElementById('memoryModalTitle').textContent = 'Add Memory';
    document.getElementById('memoryEditKey').value = '';
    document.getElementById('memoryFormCategory').value = 'knowledge';
    document.getElementById('memoryFormKey').value = '';
    document.getElementById('memoryFormValue').value = '';
    document.getElementById('memoryFormConfidence').value = 80;
    document.getElementById('memoryConfidenceDisplay').textContent = '0.80';
    document.getElementById('memoryFormTags').value = '';

    document.getElementById('memoryModal').classList.add('show');
}

function editMemory(key) {
    // Find the memory in the list
    fetch(`/api/memories?user_id=${encodeURIComponent(currentUserId)}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) return;

            const memory = data.memories.find(m => m.key === key);
            if (!memory) return;

            document.getElementById('memoryModalTitle').textContent = 'Edit Memory';
            document.getElementById('memoryEditKey').value = memory.key;
            document.getElementById('memoryFormCategory').value = memory.category;
            document.getElementById('memoryFormKey').value = memory.key;
            document.getElementById('memoryFormValue').value = memory.value;

            const confidencePercent = Math.round(memory.confidence * 100);
            document.getElementById('memoryFormConfidence').value = confidencePercent;
            document.getElementById('memoryConfidenceDisplay').textContent = memory.confidence.toFixed(2);

            let tags = [];
            try {
                tags = JSON.parse(memory.tags || '[]');
            } catch (e) {
                tags = [];
            }
            document.getElementById('memoryFormTags').value = tags.join(', ');

            document.getElementById('memoryModal').classList.add('show');
        });
}

function saveMemory() {
    const editKey = document.getElementById('memoryEditKey').value;
    const isEdit = !!editKey;

    const tagsInput = document.getElementById('memoryFormTags').value;
    const tags = tagsInput.split(',').map(t => t.trim()).filter(t => t);

    const memoryData = {
        user_id: currentUserId,
        category: document.getElementById('memoryFormCategory').value,
        key: document.getElementById('memoryFormKey').value,
        value: document.getElementById('memoryFormValue').value,
        confidence: document.getElementById('memoryFormConfidence').value / 100,
        tags: tags
    };

    const url = isEdit ? `/api/memories/${encodeURIComponent(editKey)}` : '/api/memories';
    const method = isEdit ? 'PUT' : 'POST';

    fetch(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(memoryData)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(isEdit ? 'Memory updated' : 'Memory created', 'success');
            closeModal('memoryModal');
            loadMemories();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    })
    .catch(e => {
        showToast('Error: ' + e, 'error');
    });
}

function deleteMemory(key) {
    if (!confirm('Archive this memory? It will be moved to the Archive sheet.')) return;

    fetch(`/api/memories/${encodeURIComponent(key)}?user_id=${encodeURIComponent(currentUserId)}`, {
        method: 'DELETE'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast('Memory archived', 'success');
            loadMemories();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    })
    .catch(e => {
        showToast('Error: ' + e, 'error');
    });
}

// ============================================================================
// TASKS
// ============================================================================

function loadTasks() {
    const status = document.getElementById('taskStatus').value;
    const priority = document.getElementById('taskPriority').value;
    const showArchived = document.getElementById('taskShowArchived').checked;
    const search = document.getElementById('taskSearch').value;
    const loading = document.getElementById('tasksLoading');
    const list = document.getElementById('tasksList');

    loading.style.display = 'block';
    list.innerHTML = '';

    let url = `/api/tasks?user_id=${encodeURIComponent(currentUserId)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (priority) url += `&priority=${encodeURIComponent(priority)}`;
    if (showArchived) url += '&archived=true';
    if (search) url += `&search=${encodeURIComponent(search)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            loading.style.display = 'none';

            if (!data.success) {
                list.innerHTML = `<div class="empty-state">Error: ${data.error}</div>`;
                return;
            }

            if (data.tasks.length === 0) {
                list.innerHTML = '<div class="empty-state">No tasks found. Click "+ Add Task" to create one.</div>';
                return;
            }

            data.tasks.forEach(task => {
                list.appendChild(createTaskCard(task));
            });
        })
        .catch(e => {
            loading.style.display = 'none';
            list.innerHTML = `<div class="empty-state">Error loading tasks: ${e}</div>`;
        });
}

function createTaskCard(task) {
    const card = document.createElement('div');
    card.className = `data-card task-card priority-${task.priority}`;
    if (task.status === 'complete') card.classList.add('completed');
    if (task.archived) card.classList.add('archived');

    const deadlineStr = task.deadline ? formatDate(task.deadline) : 'No deadline';
    const isOverdue = task.deadline && new Date(task.deadline) < new Date() && task.status !== 'complete';

    card.innerHTML = `
        <div class="card-header">
            <div class="task-status">
                <input type="checkbox" ${task.status === 'complete' ? 'checked' : ''}
                       onchange="toggleTaskComplete('${task.task_id}', this.checked)">
                <span class="task-title ${task.status === 'complete' ? 'strikethrough' : ''}">${escapeHtml(task.title)}</span>
            </div>
            <div class="card-actions">
                <span class="priority-badge priority-${task.priority}">${task.priority}</span>
                <button class="btn btn-secondary btn-small" onclick="editTask('${task.task_id}')">Edit</button>
                <button class="btn btn-danger btn-small" onclick="archiveTask('${task.task_id}')">${task.archived ? 'Unarchive' : 'Archive'}</button>
            </div>
        </div>
        ${task.description ? `<div class="card-body"><p>${escapeHtml(task.description)}</p></div>` : ''}
        <div class="card-footer">
            <div class="progress-section">
                <span>Progress: ${task.progress_percent}%</span>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${task.progress_percent}%"></div>
                </div>
            </div>
            <div class="task-meta">
                <span class="deadline ${isOverdue ? 'overdue' : ''}">${deadlineStr}</span>
                ${task.is_recurring ? `<span class="recurring-badge">Recurring: ${escapeHtml(task.recurrence_pattern)}</span>` : ''}
            </div>
        </div>
    `;

    return card;
}

function showAddTaskModal() {
    document.getElementById('taskModalTitle').textContent = 'Add Task';
    document.getElementById('taskEditId').value = '';
    document.getElementById('taskFormTitle').value = '';
    document.getElementById('taskFormDescription').value = '';
    document.getElementById('taskFormPriority').value = 'medium';
    document.getElementById('taskFormDeadline').value = '';
    document.getElementById('taskFormProgress').value = 0;
    document.getElementById('taskProgressDisplay').textContent = '0';
    document.getElementById('taskFormRecurring').checked = false;
    document.getElementById('recurrenceGroup').style.display = 'none';
    document.getElementById('taskFormRecurrence').value = '';
    document.getElementById('taskFormNotes').value = '';

    document.getElementById('taskModal').classList.add('show');
}

function editTask(taskId) {
    fetch(`/api/tasks?user_id=${encodeURIComponent(currentUserId)}`)
        .then(r => r.json())
        .then(data => {
            if (!data.success) return;

            const task = data.tasks.find(t => t.task_id === taskId);
            if (!task) return;

            document.getElementById('taskModalTitle').textContent = 'Edit Task';
            document.getElementById('taskEditId').value = task.task_id;
            document.getElementById('taskFormTitle').value = task.title;
            document.getElementById('taskFormDescription').value = task.description;
            document.getElementById('taskFormPriority').value = task.priority;
            document.getElementById('taskFormProgress').value = task.progress_percent;
            document.getElementById('taskProgressDisplay').textContent = task.progress_percent;
            document.getElementById('taskFormRecurring').checked = task.is_recurring;
            document.getElementById('recurrenceGroup').style.display = task.is_recurring ? 'block' : 'none';
            document.getElementById('taskFormRecurrence').value = task.recurrence_pattern;
            document.getElementById('taskFormNotes').value = task.notes;

            // Format deadline for datetime-local input
            if (task.deadline) {
                const dt = new Date(task.deadline);
                const formatted = dt.toISOString().slice(0, 16);
                document.getElementById('taskFormDeadline').value = formatted;
            } else {
                document.getElementById('taskFormDeadline').value = '';
            }

            document.getElementById('taskModal').classList.add('show');
        });
}

function saveTask() {
    const editId = document.getElementById('taskEditId').value;
    const isEdit = !!editId;

    const taskData = {
        user_id: currentUserId,
        title: document.getElementById('taskFormTitle').value,
        description: document.getElementById('taskFormDescription').value,
        priority: document.getElementById('taskFormPriority').value,
        deadline: document.getElementById('taskFormDeadline').value,
        progress_percent: parseInt(document.getElementById('taskFormProgress').value),
        is_recurring: document.getElementById('taskFormRecurring').checked,
        recurrence_pattern: document.getElementById('taskFormRecurrence').value,
        notes: document.getElementById('taskFormNotes').value
    };

    const url = isEdit ? `/api/tasks/${encodeURIComponent(editId)}` : '/api/tasks';
    const method = isEdit ? 'PUT' : 'POST';

    fetch(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(taskData)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(isEdit ? 'Task updated' : 'Task created', 'success');
            closeModal('taskModal');
            loadTasks();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    })
    .catch(e => {
        showToast('Error: ' + e, 'error');
    });
}

function toggleTaskComplete(taskId, isComplete) {
    const url = isComplete ?
        `/api/tasks/${encodeURIComponent(taskId)}/complete` :
        `/api/tasks/${encodeURIComponent(taskId)}`;

    const body = isComplete ?
        { user_id: currentUserId } :
        { user_id: currentUserId, status: 'pending', progress_percent: 0 };

    fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(isComplete ? 'Task completed' : 'Task reopened', 'success');
            loadTasks();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    });
}

function archiveTask(taskId) {
    fetch(`/api/tasks/${encodeURIComponent(taskId)}?user_id=${encodeURIComponent(currentUserId)}`, {
        method: 'DELETE'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast('Task archived', 'success');
            loadTasks();
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    });
}

function toggleRecurringField() {
    const isRecurring = document.getElementById('taskFormRecurring').checked;
    document.getElementById('recurrenceGroup').style.display = isRecurring ? 'block' : 'none';
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

            // Render grouped conversations
            Object.keys(grouped).forEach(sessionId => {
                const sessionDiv = document.createElement('div');
                sessionDiv.className = 'conversation-session';

                const header = document.createElement('div');
                header.className = 'session-header';
                header.innerHTML = `<strong>Session:</strong> ${escapeHtml(sessionId)}`;
                sessionDiv.appendChild(header);

                const messages = document.createElement('div');
                messages.className = 'session-messages';

                // Sort messages by timestamp ascending within session
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
// MODAL HELPERS
// ============================================================================

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('show');
}

// Close modal on outside click
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('show');
    }
});

// Close modal on escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal.show').forEach(modal => {
            modal.classList.remove('show');
        });
    }
});

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function escapeHtml(text) {
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
