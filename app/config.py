from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Settings loaded from .env file.
    Only contains credentials and secrets - all behavioral settings
    are loaded from the Google Sheet Config tab at runtime.
    """
    # Telegram
    telegram_token: str

    # Groq API
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

    # Web UI
    web_password: str = "brainagent2024"

    class Config:
        env_file = ".env"
        extra = "ignore"
