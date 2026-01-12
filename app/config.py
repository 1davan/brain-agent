from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram
    telegram_token: str

    # Groq API (instead of OpenAI)
    groq_api_key: str

    # Google Sheets
    google_sheets_credentials: str
    spreadsheet_id: str

    # Google Calendar (uses same credentials as Sheets)
    google_calendar_id: str = "primary"

    # Gmail Configuration (for email drafts)
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Google Keep
    google_keep_token: str = ""

    # Caching Configuration
    cache_size: int = 1000
    max_memory_items: int = 100

    # Agent Configuration
    embedding_model: str = "all-MiniLM-L6-v2"
    groq_model: str = "llama-3.3-70b-versatile"

    # Timezone Configuration
    timezone: str = "Australia/Brisbane"

    # Bot Settings
    bot_name: str = "Brain Agent"
    default_task_priority: str = "medium"

    # Proactive Features
    checkin_hours: str = "8,10,12,14,16,18"
    daily_summary_hour: int = 9
    proactive_check_interval: int = 5
    reminder_minutes_before: int = 60
    daily_summary_enabled: str = "true"
    checkins_enabled: str = "true"
    deadline_reminders_enabled: str = "true"

    # Task & Calendar Settings
    task_archive_days: int = 7
    session_timeout_minutes: int = 5
    calendar_lookahead_days: int = 7
    email_default_sign_off: str = "Best regards"
    auto_create_calendar_for_tasks: str = "true"
    include_calendar_in_responses: str = "true"
    calendar_delete_requires_confirmation: str = "true"
    email_require_confirmation: str = "true"

    # AI Context Limits
    max_memories_context: int = 5
    max_tasks_context: int = 5
    max_conversations_context: int = 5
    discussion_mode_memory_limit: int = 15
    discussion_mode_task_limit: int = 15

    # Voice & Interaction
    voice_transcription_enabled: str = "true"
    show_transcription_in_response: str = "true"
    typing_indicator_enabled: str = "true"

    # Advanced Settings
    use_pipeline: str = "true"
    debug_mode: str = "false"

    # Web UI
    web_password: str = "brainagent2024"

    # Email Writing Styles
    email_writing_style_professional: str = ""
    email_writing_style_casual: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"