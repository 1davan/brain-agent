"""
Flask web application for Brain Agent configuration and data management.
Provides a web UI to configure credentials, manage bot process, and view/edit data.
"""

import os
import sys
import json
import subprocess
import threading
import time
import asyncio
from functools import wraps
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, jsonify

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Bot process management
bot_process = None
bot_log_lines = []
MAX_LOG_LINES = 200

# Configuration
BASE_DIR = Path(__file__).parent.parent
ENV_FILE = BASE_DIR / ".env"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
DEFAULT_PASSWORD = "brainagent2024"

# Sheets client (initialized lazily)
_sheets_client = None

# Simple cache for API responses to reduce Google Sheets API calls
_cache = {}
CACHE_TTL = 30  # seconds


def get_cached(key):
    """Get cached value if not expired."""
    if key in _cache:
        value, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
    return None


def set_cached(key, value):
    """Set cache value with timestamp."""
    _cache[key] = (value, time.time())


def clear_cache(prefix=None):
    """Clear cache entries, optionally by prefix."""
    global _cache
    if prefix:
        _cache = {k: v for k, v in _cache.items() if not k.startswith(prefix)}
    else:
        _cache = {}


def get_sheets_client(force_reinit: bool = False):
    """Get or create SheetsClient instance."""
    global _sheets_client
    if _sheets_client is None or force_reinit:
        env_config = load_env()
        creds_path = env_config.get("GOOGLE_SHEETS_CREDENTIALS", "credentials.json")
        spreadsheet_id = env_config.get("SPREADSHEET_ID", "")

        if not spreadsheet_id:
            return None

        # Handle relative path
        if not os.path.isabs(creds_path):
            creds_path = str(BASE_DIR / creds_path)

        if not os.path.exists(creds_path):
            return None

        try:
            from app.database.sheets_client import SheetsClient
            _sheets_client = SheetsClient(creds_path, spreadsheet_id)
        except Exception as e:
            print(f"Failed to initialize SheetsClient: {e}")
            return None
    return _sheets_client


def reinit_sheets_client():
    """Force reinitialize the sheets client (runs migrations)."""
    global _sheets_client
    _sheets_client = None
    return get_sheets_client(force_reinit=True)


def run_async(coro):
    """Run async coroutine in sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def get_password():
    """Get the web UI password from .env or use default."""
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith("WEB_PASSWORD="):
                    return line.split("=", 1)[1].strip().strip('"\'')
    return DEFAULT_PASSWORD


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def load_env():
    """Load current .env values into a dictionary."""
    config = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip().strip('"\'')
    return config


def save_env(config):
    """Save configuration to .env file."""
    lines = []
    for key, value in config.items():
        if value:
            if " " in str(value) or "'" in str(value):
                lines.append(f'{key}="{value}"')
            else:
                lines.append(f"{key}={value}")

    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def save_credentials_json(json_content):
    """Save Google credentials JSON to file."""
    try:
        parsed = json.loads(json_content)
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(parsed, f, indent=2)
        return True, None
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"


def get_bot_status():
    """Check if bot process is running."""
    global bot_process
    if bot_process is None:
        return "stopped"
    poll = bot_process.poll()
    if poll is None:
        return "running"
    else:
        return "stopped"


def read_bot_output(process):
    """Read bot output in a separate thread."""
    global bot_log_lines
    try:
        for line in iter(process.stdout.readline, ""):
            if line:
                bot_log_lines.append(line.rstrip())
                if len(bot_log_lines) > MAX_LOG_LINES:
                    bot_log_lines.pop(0)
            if process.poll() is not None:
                break
    except Exception as e:
        bot_log_lines.append(f"[LOG ERROR] {e}")


def start_bot():
    """Start the bot subprocess."""
    global bot_process, bot_log_lines

    if get_bot_status() == "running":
        return False, "Bot is already running"

    bot_log_lines = []

    try:
        bot_script = BASE_DIR / "simple_bot.py"
        bot_process = subprocess.Popen(
            [sys.executable, str(bot_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(BASE_DIR)
        )

        output_thread = threading.Thread(target=read_bot_output, args=(bot_process,), daemon=True)
        output_thread.start()

        return True, "Bot started successfully"
    except Exception as e:
        return False, f"Failed to start bot: {e}"


def stop_bot():
    """Stop the bot subprocess."""
    global bot_process

    if bot_process is None or get_bot_status() == "stopped":
        return False, "Bot is not running"

    try:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()
            bot_process.wait()

        bot_process = None
        return True, "Bot stopped successfully"
    except Exception as e:
        return False, f"Failed to stop bot: {e}"


# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route("/")
def index():
    """Redirect to login or config."""
    if session.get("logged_in"):
        return redirect(url_for("config"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == get_password():
            session["logged_in"] = True
            return redirect(url_for("config"))
        else:
            error = "Invalid password"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/config", methods=["GET", "POST"])
@login_required
def config():
    """Main configuration page."""
    message = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save":
            new_config = {
                "TELEGRAM_TOKEN": request.form.get("telegram_token", "").strip(),
                "GROQ_API_KEY": request.form.get("groq_api_key", "").strip(),
                "SPREADSHEET_ID": request.form.get("spreadsheet_id", "").strip(),
                "GOOGLE_SHEETS_CREDENTIALS": "credentials.json",
                "GOOGLE_CALENDAR_ID": request.form.get("calendar_id", "").strip() or "primary",
                "GMAIL_ADDRESS": request.form.get("gmail_address", "").strip(),
                "GMAIL_APP_PASSWORD": request.form.get("gmail_app_password", "").strip(),
                "GOOGLE_KEEP_TOKEN": request.form.get("keep_token", "").strip(),
                "WEB_PASSWORD": request.form.get("web_password", "").strip() or DEFAULT_PASSWORD,
            }

            creds_json = request.form.get("credentials_json", "").strip()
            if creds_json:
                success, err = save_credentials_json(creds_json)
                if not success:
                    error = err

            if not error:
                save_env(new_config)
                # Reset sheets client to pick up new credentials
                global _sheets_client
                _sheets_client = None
                message = "Configuration saved successfully"

        elif action == "start":
            success, msg = start_bot()
            if success:
                message = msg
            else:
                error = msg

        elif action == "stop":
            success, msg = stop_bot()
            if success:
                message = msg
            else:
                error = msg

        elif action == "restart":
            stop_bot()
            time.sleep(1)
            success, msg = start_bot()
            if success:
                message = "Bot restarted successfully"
            else:
                error = msg

    current_config = load_env()

    creds_json = ""
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE) as f:
                creds_json = f.read()
        except Exception:
            pass

    return render_template(
        "config.html",
        config=current_config,
        creds_json=creds_json,
        bot_status=get_bot_status(),
        message=message,
        error=error
    )


# ============================================================================
# BOT STATUS & LOG APIS
# ============================================================================

@app.route("/api/status")
@login_required
def api_status():
    """Get bot status as JSON."""
    return jsonify({
        "status": get_bot_status(),
        "log_count": len(bot_log_lines)
    })


@app.route("/api/logs")
@login_required
def api_logs():
    """Get bot logs as JSON."""
    return jsonify({
        "logs": bot_log_lines[-50:]
    })


# ============================================================================
# CONNECTION TEST APIS
# ============================================================================

@app.route("/api/test/telegram", methods=["POST"])
@login_required
def test_telegram():
    """Test Telegram API connection."""
    token = request.json.get("token", "")
    if not token:
        return jsonify({"success": False, "error": "No token provided"})

    try:
        import requests
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                bot_name = data.get("result", {}).get("username", "Unknown")
                return jsonify({"success": True, "message": f"Connected to @{bot_name}"})
        return jsonify({"success": False, "error": f"API returned: {resp.text[:100]}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test/groq", methods=["POST"])
@login_required
def test_groq():
    """Test Groq API connection."""
    api_key = request.json.get("api_key", "")
    if not api_key:
        return jsonify({"success": False, "error": "No API key provided"})

    try:
        import requests
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            return jsonify({"success": True, "message": "Groq API connected"})
        return jsonify({"success": False, "error": f"API returned status {resp.status_code}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test/sheets", methods=["POST"])
@login_required
def test_sheets():
    """Test Google Sheets connection."""
    creds_json = request.json.get("credentials", "")
    spreadsheet_id = request.json.get("spreadsheet_id", "")

    if not creds_json or not spreadsheet_id:
        return jsonify({"success": False, "error": "Missing credentials or spreadsheet ID"})

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_data = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)

        return jsonify({"success": True, "message": f"Connected to: {spreadsheet.title}"})
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "Invalid JSON in credentials"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# USERS API
# ============================================================================

@app.route("/api/users")
@login_required
def api_users():
    """Get list of users from Users sheet."""
    # Check cache first
    cached = get_cached("users")
    if cached:
        return jsonify({"success": True, "users": cached})

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        df = run_async(client.get_sheet_data("Users"))
        users = []
        for _, row in df.iterrows():
            users.append({
                "user_id": str(row.get("user_id", "")),
                "username": str(row.get("username", "")),
                "chat_id": str(row.get("chat_id", "")),
                "last_active": str(row.get("last_active", ""))
            })
        set_cached("users", users)
        return jsonify({"success": True, "users": users})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# MEMORIES API
# ============================================================================

@app.route("/api/memories")
@login_required
def api_memories_list():
    """Get memories for a user."""
    user_id = request.args.get("user_id", "")
    category = request.args.get("category", "")
    search = request.args.get("search", "").lower()

    # Check cache first (only for base query without filters)
    cache_key = f"memories:{user_id}"
    cached_memories = get_cached(cache_key)

    if cached_memories is None:
        client = get_sheets_client()
        if not client:
            return jsonify({"success": False, "error": "Sheets client not configured"})

        try:
            df = run_async(client.get_sheet_data("Memories", user_id if user_id else None))
            cached_memories = []
            for _, row in df.iterrows():
                cached_memories.append({
                    "user_id": str(row.get("user_id", "")),
                    "category": str(row.get("category", "")),
                    "key": str(row.get("key", "")),
                    "value": str(row.get("value", "")),
                    "confidence": float(row.get("confidence", 0.5)) if row.get("confidence") else 0.5,
                    "tags": str(row.get("tags", "[]")),
                    "timestamp": str(row.get("timestamp", ""))
                })
            set_cached(cache_key, cached_memories)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # Apply filters on cached data
    memories = []
    for memory in cached_memories:
        if category and memory["category"] != category:
            continue
        if search and search not in memory["key"].lower() and search not in memory["value"].lower():
            continue
        memories.append(memory)

    return jsonify({"success": True, "memories": memories})


@app.route("/api/memories", methods=["POST"])
@login_required
def api_memories_create():
    """Create a new memory."""
    data = request.json
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        now = datetime.now().isoformat()
        memory_data = {
            "user_id": data.get("user_id", ""),
            "category": data.get("category", "knowledge"),
            "key": data.get("key", ""),
            "value": data.get("value", ""),
            "embedding": "",  # Will be generated by bot if needed
            "timestamp": now,
            "confidence": str(data.get("confidence", 0.8)),
            "tags": json.dumps(data.get("tags", []))
        }
        run_async(client.append_row("Memories", memory_data))
        clear_cache("memories")  # Invalidate cache
        return jsonify({"success": True, "message": "Memory created"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/memories/<key>", methods=["PUT"])
@login_required
def api_memories_update(key):
    """Update a memory."""
    data = request.json
    user_id = data.get("user_id", "")
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        row_idx = run_async(client.find_row_by_id("Memories", user_id, key))
        if not row_idx:
            return jsonify({"success": False, "error": "Memory not found"})

        update_data = {}
        if "category" in data:
            update_data["category"] = data["category"]
        if "value" in data:
            update_data["value"] = data["value"]
        if "confidence" in data:
            update_data["confidence"] = str(data["confidence"])
        if "tags" in data:
            update_data["tags"] = json.dumps(data["tags"]) if isinstance(data["tags"], list) else data["tags"]
        if "key" in data and data["key"] != key:
            update_data["key"] = data["key"]

        if update_data:
            run_async(client.update_row("Memories", row_idx, update_data))
            clear_cache("memories")  # Invalidate cache

        return jsonify({"success": True, "message": "Memory updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/memories/<key>", methods=["DELETE"])
@login_required
def api_memories_delete(key):
    """Archive a memory (soft delete)."""
    user_id = request.args.get("user_id", "")
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        # Get the memory data first
        df = run_async(client.get_sheet_data("Memories", user_id))
        memory_row = df[df["key"].astype(str) == str(key)]

        if memory_row.empty:
            return jsonify({"success": False, "error": "Memory not found"})

        # Archive it
        now = datetime.now().isoformat()
        archive_data = {
            "user_id": user_id,
            "original_sheet": "Memories",
            "content": memory_row.iloc[0].to_json(),
            "archived_at": now,
            "reason": "deleted_via_ui"
        }
        run_async(client.append_row("Archive", archive_data))

        # Delete from Memories
        row_idx = run_async(client.find_row_by_id("Memories", user_id, key))
        if row_idx:
            run_async(client.delete_row("Memories", row_idx))

        clear_cache("memories")  # Invalidate cache
        return jsonify({"success": True, "message": "Memory archived"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# TASKS API
# ============================================================================

@app.route("/api/tasks")
@login_required
def api_tasks_list():
    """Get tasks for a user."""
    user_id = request.args.get("user_id", "")
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")
    show_archived = request.args.get("archived", "false").lower() == "true"
    search = request.args.get("search", "").lower()

    # Check cache first
    cache_key = f"tasks:{user_id}"
    cached_tasks = get_cached(cache_key)

    if cached_tasks is None:
        client = get_sheets_client()
        if not client:
            return jsonify({"success": False, "error": "Sheets client not configured"})

        try:
            df = run_async(client.get_sheet_data("Tasks", user_id if user_id else None))
            cached_tasks = []
            for _, row in df.iterrows():
                cached_tasks.append({
                    "user_id": str(row.get("user_id", "")),
                    "task_id": str(row.get("task_id", "")),
                    "title": str(row.get("title", "")),
                    "description": str(row.get("description", "")),
                    "priority": str(row.get("priority", "medium")),
                    "status": str(row.get("status", "pending")),
                    "deadline": str(row.get("deadline", "")),
                    "created_at": str(row.get("created_at", "")),
                    "updated_at": str(row.get("updated_at", "")),
                    "notes": str(row.get("notes", "")),
                    "progress_percent": int(row.get("progress_percent", 0)) if row.get("progress_percent") else 0,
                    "is_recurring": str(row.get("is_recurring", "false")).lower() == "true",
                    "recurrence_pattern": str(row.get("recurrence_pattern", "")),
                    "archived": str(row.get("archived", "false")).lower() == "true"
                })
            set_cached(cache_key, cached_tasks)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # Apply filters on cached data
    tasks = []
    for task in cached_tasks:
        if status and task["status"] != status:
            continue
        if priority and task["priority"] != priority:
            continue
        if not show_archived and task["archived"]:
            continue
        if search and search not in task["title"].lower() and search not in task["description"].lower():
            continue
        tasks.append(task)

    # Sort by priority and deadline
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    tasks.sort(key=lambda t: (priority_order.get(t["priority"], 2), t["deadline"] or "9999"))

    return jsonify({"success": True, "tasks": tasks})


@app.route("/api/tasks", methods=["POST"])
@login_required
def api_tasks_create():
    """Create a new task."""
    data = request.json
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        import uuid
        now = datetime.now().isoformat()
        user_id = data.get("user_id", "")
        task_id = f"task_{user_id}_{uuid.uuid4().hex[:8]}"

        task_data = {
            "user_id": user_id,
            "task_id": task_id,
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "priority": data.get("priority", "medium"),
            "status": "pending",
            "deadline": data.get("deadline", ""),
            "created_at": now,
            "updated_at": now,
            "dependencies": "[]",
            "notes": "",
            "is_recurring": str(data.get("is_recurring", False)).lower(),
            "recurrence_pattern": data.get("recurrence_pattern", ""),
            "recurrence_end_date": "",
            "parent_task_id": "",
            "progress_percent": "0",
            "last_discussed": "",
            "completed_at": "",
            "archived": "false"
        }
        run_async(client.append_row("Tasks", task_data))
        clear_cache("tasks")  # Invalidate cache
        return jsonify({"success": True, "message": "Task created", "task_id": task_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/tasks/<task_id>", methods=["PUT"])
@login_required
def api_tasks_update(task_id):
    """Update a task."""
    data = request.json
    user_id = data.get("user_id", "")
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        row_idx = run_async(client.find_row_by_id("Tasks", user_id, task_id))
        if not row_idx:
            return jsonify({"success": False, "error": "Task not found"})

        now = datetime.now().isoformat()
        update_data = {"updated_at": now}

        allowed_fields = ["title", "description", "priority", "status", "deadline",
                         "notes", "progress_percent", "is_recurring", "recurrence_pattern", "archived"]
        for field in allowed_fields:
            if field in data:
                value = data[field]
                if field in ["is_recurring", "archived"]:
                    value = str(value).lower()
                elif field == "progress_percent":
                    value = str(int(value))
                update_data[field] = value

        # If completing task, set completed_at
        if data.get("status") == "complete":
            update_data["completed_at"] = now
            update_data["progress_percent"] = "100"

        run_async(client.update_row("Tasks", row_idx, update_data))
        clear_cache("tasks")  # Invalidate cache
        return jsonify({"success": True, "message": "Task updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
@login_required
def api_tasks_complete(task_id):
    """Quick complete a task."""
    data = request.json
    user_id = data.get("user_id", "")
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        row_idx = run_async(client.find_row_by_id("Tasks", user_id, task_id))
        if not row_idx:
            return jsonify({"success": False, "error": "Task not found"})

        now = datetime.now().isoformat()
        update_data = {
            "status": "complete",
            "completed_at": now,
            "progress_percent": "100",
            "updated_at": now
        }
        run_async(client.update_row("Tasks", row_idx, update_data))
        clear_cache("tasks")  # Invalidate cache
        return jsonify({"success": True, "message": "Task completed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def api_tasks_delete(task_id):
    """Archive a task (soft delete)."""
    user_id = request.args.get("user_id", "")
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        row_idx = run_async(client.find_row_by_id("Tasks", user_id, task_id))
        if not row_idx:
            return jsonify({"success": False, "error": "Task not found"})

        now = datetime.now().isoformat()
        run_async(client.update_row("Tasks", row_idx, {"archived": "true", "updated_at": now}))
        clear_cache("tasks")  # Invalidate cache
        return jsonify({"success": True, "message": "Task archived"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# CONVERSATIONS API
# ============================================================================

@app.route("/api/conversations")
@login_required
def api_conversations_list():
    """Get conversations for a user."""
    user_id = request.args.get("user_id", "")
    session_id = request.args.get("session_id", "")
    search = request.args.get("search", "").lower()
    limit = int(request.args.get("limit", 100))

    # Check cache first
    cache_key = f"conversations:{user_id}"
    cached_convos = get_cached(cache_key)

    if cached_convos is None:
        client = get_sheets_client()
        if not client:
            return jsonify({"success": False, "error": "Sheets client not configured"})

        try:
            df = run_async(client.get_sheet_data("Conversations", user_id if user_id else None))
            cached_convos = []
            for _, row in df.iterrows():
                cached_convos.append({
                    "user_id": str(row.get("user_id", "")),
                    "session_id": str(row.get("session_id", "")),
                    "message_type": str(row.get("message_type", "")),
                    "content": str(row.get("content", "")),
                    "timestamp": str(row.get("timestamp", "")),
                    "intent": str(row.get("intent", "")),
                    "entities": str(row.get("entities", "{}"))
                })
            set_cached(cache_key, cached_convos)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # Apply filters on cached data
    conversations = []
    for conv in cached_convos:
        if session_id and conv["session_id"] != session_id:
            continue
        if search and search not in conv["content"].lower():
            continue
        conversations.append(conv)

    # Sort by timestamp descending and limit
    conversations.sort(key=lambda c: c["timestamp"], reverse=True)
    conversations = conversations[:limit]

    # Get unique sessions for filter dropdown
    sessions = list(set(c["session_id"] for c in conversations if c["session_id"]))

    return jsonify({"success": True, "conversations": conversations, "sessions": sessions})


# ============================================================================
# CONFIG API
# ============================================================================

@app.route("/api/config")
@login_required
def api_config_list():
    """Get all config variables with optional user filter.

    Query params:
    - user_id: If provided, returns effective config for that user (with overrides applied)
    - raw: If "true", returns all entries with user_id info (for editing UI)
    """
    user_id = request.args.get("user_id", "")
    raw = request.args.get("raw", "false").lower() == "true"

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        if raw:
            # Return detailed config with user_id info for the settings UI
            config_list = run_async(client.get_all_config_with_details(user_id if user_id else None))
            return jsonify({"success": True, "config": config_list})
        else:
            # Return simple key-value config (effective values for user)
            config = run_async(client.get_all_config(user_id if user_id else None))
            return jsonify({"success": True, "config": config})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/config/<variable>", methods=["PUT"])
@login_required
def api_config_update(variable):
    """Update a config variable.

    JSON body:
    - value: The new value
    - user_id: If provided, creates/updates user-specific override; otherwise updates global
    """
    data = request.json
    value = data.get("value", "")
    user_id = data.get("user_id", "")

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        success = run_async(client.set_config(variable, value, user_id if user_id else None))
        if success:
            clear_cache("config")
            return jsonify({"success": True, "message": "Config updated"})
        else:
            return jsonify({"success": False, "error": "Failed to update config"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/config/<variable>", methods=["DELETE"])
@login_required
def api_config_delete(variable):
    """Delete a user-specific config override (reverts to global default).

    Query params:
    - user_id: Required - the user whose override to delete
    """
    user_id = request.args.get("user_id", "")

    if not user_id:
        return jsonify({"success": False, "error": "user_id required to delete override"})

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        success = run_async(client.delete_user_config(variable, user_id))
        if success:
            clear_cache("config")
            return jsonify({"success": True, "message": "Config override deleted"})
        else:
            return jsonify({"success": False, "error": "Override not found"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/config/migrate", methods=["POST"])
@login_required
def api_config_migrate():
    """Force reinitialize sheets client to run migrations."""
    try:
        client = reinit_sheets_client()
        if client:
            clear_cache("config")
            return jsonify({"success": True, "message": "Sheets client reinitialized, migrations applied"})
        else:
            return jsonify({"success": False, "error": "Failed to reinitialize sheets client"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# COMMANDS API
# ============================================================================

def get_telegram_token():
    """Get Telegram token from env."""
    env_config = load_env()
    return env_config.get("TELEGRAM_TOKEN", "")


def send_telegram_message(chat_id, text, reply_markup=None):
    """Send message via Telegram API."""
    import requests
    token = get_telegram_token()
    if not token:
        return {"ok": False, "description": "Telegram token not configured"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    try:
        response = requests.post(url, data=data, timeout=10)
        return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def get_user_chat_id(user_id):
    """Get chat_id for a user_id."""
    client = get_sheets_client()
    if not client:
        return None
    try:
        df = run_async(client.get_sheet_data("Users"))
        for _, row in df.iterrows():
            if str(row.get("user_id", "")) == str(user_id):
                return str(row.get("chat_id", ""))
        return None
    except:
        return None


@app.route("/api/commands/checkin", methods=["POST"])
@login_required
def api_commands_checkin():
    """Trigger a task check-in for the user."""
    data = request.json
    user_id = data.get("user_id", "")
    chat_id = get_user_chat_id(user_id)

    if not chat_id:
        return jsonify({"success": False, "error": "User not found or no chat_id"})

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        # Get pending tasks for check-in
        df = run_async(client.get_sheet_data("Tasks", user_id))
        pending = df[df["status"] == "pending"]
        if "archived" in df.columns:
            pending = pending[pending["archived"].astype(str) != "true"]

        if pending.empty:
            return jsonify({"success": False, "error": "No pending tasks for check-in"})

        # Get first pending task
        task = pending.iloc[0]
        title = str(task.get("title", "your task"))
        task_id = str(task.get("task_id", ""))
        progress = int(task.get("progress_percent", 0) or 0)

        # Build check-in message
        message = f"Hey! Just checking in on '<b>{title}</b>'."
        if progress > 0:
            message += f" Last I heard you were at {progress}%."
        else:
            message += " Have you had a chance to start on it?"
        message += "\n\nReply with your progress or tap a button below:"

        # Add inline buttons
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Done!", "callback_data": f"task_done:{task_id}"},
                    {"text": "50%", "callback_data": f"task_progress:{task_id}:50"},
                    {"text": "25%", "callback_data": f"task_progress:{task_id}:25"}
                ],
                [
                    {"text": "Blocked", "callback_data": f"task_blocked:{task_id}"},
                    {"text": "Skip", "callback_data": f"task_skip:{task_id}"}
                ]
            ]
        }

        result = send_telegram_message(chat_id, message, reply_markup)
        if result.get("ok"):
            return jsonify({"success": True, "message": f"Check-in sent for: {title}"})
        else:
            return jsonify({"success": False, "error": result.get("description", "Failed to send")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/commands/daily-summary", methods=["POST"])
@login_required
def api_commands_daily_summary():
    """Send daily summary to user - improved format."""
    data = request.json
    user_id = data.get("user_id", "")
    chat_id = get_user_chat_id(user_id)

    if not chat_id:
        return jsonify({"success": False, "error": "User not found or no chat_id"})

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        # Get pending tasks
        df = run_async(client.get_sheet_data("Tasks", user_id))
        pending_df = df[df["status"] == "pending"]
        if "archived" in df.columns:
            pending_df = pending_df[pending_df["archived"].astype(str) != "true"]

        now = datetime.now()
        today = now.date()

        # Categorize tasks
        overdue = []
        due_today = []
        high_priority = []
        pending_tasks = []

        for _, task in pending_df.iterrows():
            title = str(task.get("title", "Untitled"))
            priority = str(task.get("priority", ""))
            deadline = str(task.get("deadline", ""))
            task_id = str(task.get("task_id", ""))

            task_info = {"title": title, "priority": priority, "task_id": task_id}
            pending_tasks.append(task_info)

            if priority in ("high", "critical"):
                high_priority.append(task_info)

            if deadline:
                try:
                    deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
                    if deadline_dt.date() < today:
                        overdue.append(task_info)
                    elif deadline_dt.date() == today:
                        due_today.append(task_info)
                except:
                    pass

        # Build improved message
        day_name = now.strftime("%A, %B %d")
        message = f"DAILY SUMMARY - {day_name}\n\n"

        if not pending_tasks:
            message += "No pending tasks. Enjoy your day!"
        else:
            # Today's Focus section (pick 1-3 most important)
            focus_tasks = []
            for t in overdue[:2]:
                focus_tasks.append((t, "overdue"))
            for t in due_today[:2]:
                if len(focus_tasks) < 3:
                    focus_tasks.append((t, "today"))
            for t in high_priority[:2]:
                if len(focus_tasks) < 3 and t not in [x[0] for x in focus_tasks]:
                    focus_tasks.append((t, "priority"))

            if focus_tasks:
                message += "TODAY'S FOCUS:\n"
                for i, (task, reason) in enumerate(focus_tasks[:3], 1):
                    suffix = " (overdue!)" if reason == "overdue" else ""
                    message += f"  {i}. {task['title']}{suffix}\n"
                message += "\n"

            # Warnings section
            if overdue:
                message += f"WARNING: {len(overdue)} overdue task(s)\n\n"

            # Stats summary
            message += "STATS:\n"
            message += f"  - {len(pending_tasks)} pending tasks"
            if high_priority:
                message += f" ({len(high_priority)} high priority)"
            message += "\n"
            if due_today:
                message += f"  - {len(due_today)} due today\n"
            if overdue:
                message += f"  - {len(overdue)} overdue\n"

            message += "\nUse /summary in Telegram for quick action buttons."

        result = send_telegram_message(chat_id, message)
        if result.get("ok"):
            return jsonify({"success": True, "message": "Daily summary sent"})
        else:
            return jsonify({"success": False, "error": result.get("description", "Failed to send")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/commands/clear-session", methods=["POST"])
@login_required
def api_commands_clear_session():
    """Clear task discussion session for user (sends message to confirm)."""
    data = request.json
    user_id = data.get("user_id", "")
    chat_id = get_user_chat_id(user_id)

    if not chat_id:
        return jsonify({"success": False, "error": "User not found or no chat_id"})

    message = "Session cleared. Ready for new requests!"
    result = send_telegram_message(chat_id, message)

    if result.get("ok"):
        return jsonify({"success": True, "message": "Session clear message sent"})
    else:
        return jsonify({"success": False, "error": result.get("description", "Failed to send")})


@app.route("/api/commands/auto-archive", methods=["POST"])
@login_required
def api_commands_auto_archive():
    """Archive completed tasks older than 7 days."""
    data = request.json
    user_id = data.get("user_id", "")

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        df = run_async(client.get_sheet_data("Tasks", user_id))
        now = datetime.now()
        archived_count = 0

        for idx, task in df.iterrows():
            if str(task.get("status", "")) != "complete":
                continue
            if str(task.get("archived", "")).lower() == "true":
                continue

            completed_at = str(task.get("completed_at", ""))
            if not completed_at:
                continue

            try:
                completed_date = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                days_old = (now - completed_date.replace(tzinfo=None)).days
                if days_old >= 7:
                    task_id = str(task.get("task_id", ""))
                    row_idx = run_async(client.find_row_by_id("Tasks", user_id, task_id))
                    if row_idx:
                        run_async(client.update_row("Tasks", row_idx, {"archived": "true"}))
                        archived_count += 1
            except:
                continue

        clear_cache("tasks")
        return jsonify({"success": True, "message": f"Archived {archived_count} task(s)"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/commands/process-recurring", methods=["POST"])
@login_required
def api_commands_process_recurring():
    """Process recurring tasks - placeholder for now."""
    return jsonify({"success": True, "message": "Recurring task processing triggered (handled by bot)"})


@app.route("/api/commands/check-deadlines", methods=["POST"])
@login_required
def api_commands_check_deadlines():
    """Check for upcoming deadlines and notify user - improved format."""
    data = request.json
    user_id = data.get("user_id", "")
    chat_id = get_user_chat_id(user_id)

    if not chat_id:
        return jsonify({"success": False, "error": "User not found or no chat_id"})

    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        df = run_async(client.get_sheet_data("Tasks", user_id))
        pending = df[df["status"] == "pending"]
        if "archived" in df.columns:
            pending = pending[pending["archived"].astype(str) != "true"]

        now = datetime.now()
        today = now.date()

        overdue = []
        due_today = []
        due_tomorrow = []
        due_this_week = []

        for _, task in pending.iterrows():
            deadline = str(task.get("deadline", ""))
            if not deadline:
                continue
            try:
                deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00")).replace(tzinfo=None)
                days_diff = (deadline_dt.date() - today).days
                task_info = {
                    "title": str(task.get("title", "Untitled")),
                    "days": days_diff,
                    "deadline": deadline_dt
                }

                if days_diff < 0:
                    overdue.append(task_info)
                elif days_diff == 0:
                    due_today.append(task_info)
                elif days_diff == 1:
                    due_tomorrow.append(task_info)
                elif days_diff <= 7:
                    due_this_week.append(task_info)
            except:
                continue

        if not overdue and not due_today and not due_tomorrow and not due_this_week:
            return jsonify({"success": True, "message": "No upcoming deadlines within the next week"})

        message = "DEADLINE CHECK\n\n"

        # Overdue section
        if overdue:
            overdue.sort(key=lambda x: x["days"])
            message += f"CRITICAL - Overdue ({len(overdue)} task{'s' if len(overdue) != 1 else ''}):\n"
            for item in overdue[:4]:
                days_ago = abs(item["days"])
                message += f"  - {item['title']} ({days_ago}d ago)\n"
            if len(overdue) > 4:
                message += f"  ... and {len(overdue) - 4} more\n"
            message += "\n"

        # Today section
        if due_today:
            message += f"TODAY ({len(due_today)} task{'s' if len(due_today) != 1 else ''}):\n"
            for item in due_today[:4]:
                message += f"  - {item['title']}\n"
            if len(due_today) > 4:
                message += f"  ... and {len(due_today) - 4} more\n"
            message += "\n"

        # Tomorrow section
        if due_tomorrow:
            message += f"TOMORROW ({len(due_tomorrow)} task{'s' if len(due_tomorrow) != 1 else ''}):\n"
            for item in due_tomorrow[:3]:
                message += f"  - {item['title']}\n"
            if len(due_tomorrow) > 3:
                message += f"  ... and {len(due_tomorrow) - 3} more\n"
            message += "\n"

        # This week section
        if due_this_week:
            message += f"THIS WEEK ({len(due_this_week)} task{'s' if len(due_this_week) != 1 else ''}):\n"
            for item in due_this_week[:3]:
                day_name = item["deadline"].strftime("%a")
                message += f"  - {item['title']} ({day_name})\n"
            if len(due_this_week) > 3:
                message += f"  ... and {len(due_this_week) - 3} more\n"
            message += "\n"

        message += "Use /deadlines in Telegram for quick actions."

        result = send_telegram_message(chat_id, message)
        total_count = len(overdue) + len(due_today) + len(due_tomorrow) + len(due_this_week)
        if result.get("ok"):
            return jsonify({"success": True, "message": f"Sent deadline check ({total_count} tasks with deadlines)"})
        else:
            return jsonify({"success": False, "error": result.get("description", "Failed to send")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/commands/send-message", methods=["POST"])
@login_required
def api_commands_send_message():
    """Send a custom message to user."""
    data = request.json
    user_id = data.get("user_id", "")
    message = data.get("message", "").strip()
    chat_id = get_user_chat_id(user_id)

    if not chat_id:
        return jsonify({"success": False, "error": "User not found or no chat_id"})

    if not message:
        return jsonify({"success": False, "error": "Message cannot be empty"})

    result = send_telegram_message(chat_id, message)
    if result.get("ok"):
        return jsonify({"success": True, "message": "Message sent"})
    else:
        return jsonify({"success": False, "error": result.get("description", "Failed to send")})


@app.route("/api/commands/stats")
@login_required
def api_commands_stats():
    """Get quick stats for the commands page."""
    user_id = request.args.get("user_id", "")

    client = get_sheets_client()

    stats = {
        "bot_status": get_bot_status(),
        "checkin_hours": "8, 10, 12, 14, 16, 18",  # Default
        "current_hour": datetime.now().strftime("%H:%M"),
        "pending_tasks": 0
    }

    # Get check-in hours from env
    env_config = load_env()
    stats["checkin_hours"] = env_config.get("CHECKIN_HOURS", "10, 14, 18")

    # Get pending task count
    if client and user_id:
        try:
            df = run_async(client.get_sheet_data("Tasks", user_id))
            pending = df[df["status"] == "pending"]
            if "archived" in df.columns:
                pending = pending[pending["archived"].astype(str) != "true"]
            stats["pending_tasks"] = len(pending)
        except:
            pass

    return jsonify({"success": True, "stats": stats})


# ============================================================================
# USER SETTINGS API
# ============================================================================

@app.route("/api/users/<user_id>/settings")
@login_required
def api_user_settings_get(user_id):
    """Get user-specific settings (email_enabled, calendar_enabled, calendar_id)."""
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        settings = run_async(client.get_all_user_settings(user_id))
        return jsonify({
            "success": True,
            "settings": {
                "email_enabled": settings.get("email_enabled", "true") != "false",
                "calendar_enabled": settings.get("calendar_enabled", "true") != "false",
                "calendar_id": settings.get("calendar_id", ""),
                "checkin_hours": settings.get("checkin_hours", "")
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/users/<user_id>/settings", methods=["PUT"])
@login_required
def api_user_settings_update(user_id):
    """Update user-specific settings."""
    data = request.json
    client = get_sheets_client()
    if not client:
        return jsonify({"success": False, "error": "Sheets client not configured"})

    try:
        # Update email_enabled
        if "email_enabled" in data:
            run_async(client.set_user_setting(
                user_id, "email_enabled",
                "true" if data["email_enabled"] else "false"
            ))

        # Update calendar_enabled
        if "calendar_enabled" in data:
            run_async(client.set_user_setting(
                user_id, "calendar_enabled",
                "true" if data["calendar_enabled"] else "false"
            ))

        # Update calendar_id
        if "calendar_id" in data:
            run_async(client.set_user_setting(
                user_id, "calendar_id",
                data["calendar_id"]
            ))

        # Update checkin_hours
        if "checkin_hours" in data:
            run_async(client.set_user_setting(
                user_id, "checkin_hours",
                data["checkin_hours"]
            ))

        return jsonify({"success": True, "message": "Settings updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================================
# SERVER
# ============================================================================

def run_server(host="0.0.0.0", port=5000, debug=False):
    """Run the Flask server with auto-start bot."""
    # Auto-start the bot when the server starts
    print("[SERVER] Auto-starting bot...")
    success, msg = start_bot()
    if success:
        print(f"[SERVER] Bot auto-started successfully")
    else:
        print(f"[SERVER] Bot auto-start failed: {msg}")

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_server(debug=True)
