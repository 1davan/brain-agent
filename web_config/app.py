"""
Flask web application for Brain Agent configuration.
Provides a web UI to configure API keys and settings before starting the bot.
"""

import os
import sys
import json
import subprocess
import signal
import threading
import time
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response

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
DEFAULT_PASSWORD = "brainagent2024"  # Change this or set WEB_PASSWORD in .env


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
            # Quote values that contain spaces or special chars
            if " " in str(value) or "'" in str(value):
                lines.append(f'{key}="{value}"')
            else:
                lines.append(f"{key}={value}")

    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def save_credentials_json(json_content):
    """Save Google credentials JSON to file."""
    try:
        # Validate JSON
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

        # Start thread to read output
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


# Routes

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
            # Build config from form - Required Keys
            new_config = {
                "TELEGRAM_TOKEN": request.form.get("telegram_token", "").strip(),
                "GROQ_API_KEY": request.form.get("groq_api_key", "").strip(),
                "SPREADSHEET_ID": request.form.get("spreadsheet_id", "").strip(),
                "GOOGLE_SHEETS_CREDENTIALS": "credentials.json",
                # Optional Services
                "GOOGLE_CALENDAR_ID": request.form.get("calendar_id", "").strip() or "primary",
                "GMAIL_ADDRESS": request.form.get("gmail_address", "").strip(),
                "GMAIL_APP_PASSWORD": request.form.get("gmail_app_password", "").strip(),
                "GOOGLE_KEEP_TOKEN": request.form.get("keep_token", "").strip(),
                # Basic Settings
                "GROQ_MODEL": request.form.get("groq_model", "llama-3.3-70b-versatile"),
                "TIMEZONE": request.form.get("timezone", "Australia/Brisbane"),
                "BOT_NAME": request.form.get("bot_name", "Brain Agent"),
                "DEFAULT_TASK_PRIORITY": request.form.get("default_task_priority", "medium"),
                # Proactive Features
                "CHECKIN_HOURS": request.form.get("checkin_hours", "8,10,12,14,16,18"),
                "DAILY_SUMMARY_HOUR": request.form.get("daily_summary_hour", "8"),
                "PROACTIVE_CHECK_INTERVAL": request.form.get("proactive_check_interval", "5"),
                "REMINDER_MINUTES_BEFORE": request.form.get("reminder_minutes_before", "60"),
                "DAILY_SUMMARY_ENABLED": "true" if request.form.get("daily_summary_enabled") else "false",
                "CHECKINS_ENABLED": "true" if request.form.get("checkins_enabled") else "false",
                "DEADLINE_REMINDERS_ENABLED": "true" if request.form.get("deadline_reminders_enabled") else "false",
                # Task & Calendar Settings
                "TASK_ARCHIVE_DAYS": request.form.get("task_archive_days", "7"),
                "SESSION_TIMEOUT_MINUTES": request.form.get("session_timeout_minutes", "5"),
                "CALENDAR_LOOKAHEAD_DAYS": request.form.get("calendar_lookahead_days", "7"),
                "EMAIL_DEFAULT_SIGN_OFF": request.form.get("email_default_sign_off", "Best regards"),
                "AUTO_CREATE_CALENDAR_FOR_TASKS": "true" if request.form.get("auto_create_calendar_for_tasks") else "false",
                "INCLUDE_CALENDAR_IN_RESPONSES": "true" if request.form.get("include_calendar_in_responses") else "false",
                "CALENDAR_DELETE_REQUIRES_CONFIRMATION": "true" if request.form.get("calendar_delete_requires_confirmation") else "false",
                "EMAIL_REQUIRE_CONFIRMATION": "true" if request.form.get("email_require_confirmation") else "false",
                # AI Context Limits
                "MAX_MEMORIES_CONTEXT": request.form.get("max_memories_context", "5"),
                "MAX_TASKS_CONTEXT": request.form.get("max_tasks_context", "5"),
                "MAX_CONVERSATIONS_CONTEXT": request.form.get("max_conversations_context", "5"),
                "DISCUSSION_MODE_MEMORY_LIMIT": request.form.get("discussion_mode_memory_limit", "15"),
                "DISCUSSION_MODE_TASK_LIMIT": request.form.get("discussion_mode_task_limit", "15"),
                # Voice & Interaction
                "VOICE_TRANSCRIPTION_ENABLED": "true" if request.form.get("voice_transcription_enabled") else "false",
                "SHOW_TRANSCRIPTION_IN_RESPONSE": "true" if request.form.get("show_transcription_in_response") else "false",
                "TYPING_INDICATOR_ENABLED": "true" if request.form.get("typing_indicator_enabled") else "false",
                # Advanced Settings
                "USE_PIPELINE": "true" if request.form.get("use_pipeline") else "false",
                "DEBUG_MODE": "true" if request.form.get("debug_mode") else "false",
                # Email Writing Styles
                "EMAIL_WRITING_STYLE_PROFESSIONAL": request.form.get("email_writing_style_professional", "").strip(),
                "EMAIL_WRITING_STYLE_CASUAL": request.form.get("email_writing_style_casual", "").strip(),
                # Security
                "WEB_PASSWORD": request.form.get("web_password", "").strip() or DEFAULT_PASSWORD,
            }

            # Save credentials JSON if provided
            creds_json = request.form.get("credentials_json", "").strip()
            if creds_json:
                success, err = save_credentials_json(creds_json)
                if not success:
                    error = err

            if not error:
                save_env(new_config)
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

    # Load current config
    current_config = load_env()

    # Load credentials JSON if exists
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
        "logs": bot_log_lines[-50:]  # Last 50 lines
    })


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


def run_server(host="0.0.0.0", port=5000, debug=False):
    """Run the Flask server."""
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_server(debug=True)
