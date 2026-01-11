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
    # Set to your calendar email or leave as 'primary' for main calendar
    google_calendar_id: str = "primary"

    # Gmail Configuration (for email drafts)
    gmail_address: str = ""
    gmail_app_password: str = ""

    # Caching Configuration
    cache_size: int = 1000  # In-memory cache size for embeddings
    max_memory_items: int = 100  # Max memory items per user

    # Agent Configuration
    embedding_model: str = "all-MiniLM-L6-v2"  # Lightweight model for low-memory environments (384 dims, ~90MB)
    groq_model: str = "llama-3.3-70b-versatile"  # Groq model for reasoning (upgraded)

    # Timezone Configuration
    timezone: str = "Australia/Brisbane"  # User's timezone for scheduling

    # Proactive Features
    daily_summary_hour: int = 9  # Hour for daily summary (9 AM)
    reminder_minutes_before: int = 60  # Minutes before deadline for reminder

    class Config:
        env_file = ".env"