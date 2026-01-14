import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from typing import List, Dict, Any, Optional
import json
from datetime import datetime

class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        """
        Initialize Google Sheets client.

        Note: You need to:
        1. Create a service account in Google Cloud Console
        2. Enable Google Sheets API
        3. Share your spreadsheet with the service account email
        4. Download the credentials JSON file
        """
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        self.client = gspread.authorize(self.creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)

        # Ensure required sheets exist
        self._ensure_sheets_exist()

    def _ensure_sheets_exist(self):
        """Create required sheets if they don't exist and ensure they have proper headers"""
        required_sheets = ["Memories", "Tasks", "Archive", "Conversations", "Users", "Settings", "Config"]
        existing_sheets = [sheet.title for sheet in self.spreadsheet.worksheets()]

        for sheet_name in required_sheets:
            if sheet_name not in existing_sheets:
                # Create the sheet
                sheet = self.spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
                print(f"Created sheet: {sheet_name}")

                # Add headers to the new sheet
                headers = self._get_sheet_columns(sheet_name)
                if headers:
                    sheet.update('A1', [headers])
                    print(f"Added headers to {sheet_name}: {headers}")
            else:
                # Check if existing sheet has headers, if not, add them
                sheet = self.spreadsheet.worksheet(sheet_name)
                try:
                    current_headers = sheet.row_values(1)
                    expected_headers = self._get_sheet_columns(sheet_name)

                    if not current_headers or len(current_headers) < len(expected_headers):
                        sheet.update('A1', [expected_headers])
                        print(f"Updated headers for {sheet_name}: {expected_headers}")
                except Exception as e:
                    print(f"Warning: Could not check headers for {sheet_name}: {e}")
                    # Try to add headers anyway
                    try:
                        expected_headers = self._get_sheet_columns(sheet_name)
                        if expected_headers:
                            sheet.update('A1', [expected_headers])
                            print(f"Added headers to {sheet_name}: {expected_headers}")
                    except Exception as e2:
                        print(f"Error adding headers to {sheet_name}: {e2}")

        # Run migrations for schema changes
        self._migrate_config_sheet()
        self._migrate_tasks_sheet()

    def _migrate_tasks_sheet(self):
        """Migrate Tasks sheet to add skipped_until column if missing."""
        try:
            sheet = self.spreadsheet.worksheet("Tasks")
            headers = sheet.row_values(1)

            # Check if skipped_until column exists
            if headers and 'skipped_until' not in headers:
                print("Migrating Tasks sheet to add skipped_until column...")
                # Add the new column header at the end
                new_col_index = len(headers) + 1
                sheet.update_cell(1, new_col_index, 'skipped_until')
                print(f"Tasks sheet migrated: added skipped_until column at position {new_col_index}")

        except Exception as e:
            print(f"Error migrating Tasks sheet: {e}")

    def _migrate_config_sheet(self):
        """Migrate Config sheet to add user_id column if missing (for per-user settings)."""
        try:
            sheet = self.spreadsheet.worksheet("Config")
            headers = sheet.row_values(1)

            # Check if migration is needed: old format has 'variable' in column A
            if headers and headers[0] == 'variable':
                print("Migrating Config sheet to add user_id column...")

                # Get all existing data
                all_data = sheet.get_all_values()

                if len(all_data) > 0:
                    # Prepend user_id to headers
                    new_headers = ['user_id'] + all_data[0]

                    # Prepend empty user_id to each data row (global defaults)
                    new_data = [new_headers]
                    for row in all_data[1:]:
                        new_data.append([''] + row)

                    # Clear and rewrite the sheet
                    sheet.clear()
                    sheet.update('A1', new_data)
                    print(f"Config sheet migrated: added user_id column, {len(new_data)-1} rows updated")

        except Exception as e:
            print(f"Error migrating Config sheet: {e}")

    async def get_sheet_data(self, sheet_name: str, user_id: Optional[str] = None) -> pd.DataFrame:
        """Get data from sheet with optional user filtering"""
        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            data = sheet.get_all_records()

            if not data:
                # Return empty DataFrame with expected columns
                return pd.DataFrame()

            df = pd.DataFrame(data)

            if user_id and 'user_id' in df.columns:
                # Convert both to string for comparison since user_id might be stored as int
                df = df[df['user_id'].astype(str) == str(user_id)]

            return df
        except Exception as e:
            print(f"Error getting sheet data: {e}")
            return pd.DataFrame()

    async def append_row(self, sheet_name: str, row_data: Dict[str, Any]):
        """Append new row to sheet"""
        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            # Convert all values to strings for Google Sheets
            row_values = [str(row_data.get(col, '')) for col in self._get_sheet_columns(sheet_name)]
            sheet.append_row(row_values)
        except Exception as e:
            print(f"Error appending row: {e}")

    async def update_row(self, sheet_name: str, row_index: int, row_data: Dict[str, Any]):
        """Update existing row - only updates specified columns"""
        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            columns = self._get_sheet_columns(sheet_name)
            
            # Update only the columns specified in row_data
            for col_name, value in row_data.items():
                if col_name in columns:
                    col_index = columns.index(col_name) + 1  # 1-indexed
                    sheet.update_cell(row_index, col_index, str(value))
                    
            print(f"Updated row {row_index} in {sheet_name}: {list(row_data.keys())}")
        except Exception as e:
            print(f"Error updating row: {e}")

    async def find_row_by_id(self, sheet_name: str, user_id: str, item_id: str) -> Optional[int]:
        """Find row index by user_id and item_id/key"""
        try:
            # Get full sheet data (not filtered) to get correct row index
            sheet = self.spreadsheet.worksheet(sheet_name)
            all_data = sheet.get_all_records()
            
            if not all_data:
                return None

            # Look for matching item - check all possible ID columns
            id_columns = ['id', 'task_id', 'key', 'memory_id']
            
            for idx, row in enumerate(all_data):
                # Check if this row belongs to the user
                if str(row.get('user_id', '')) != str(user_id):
                    continue
                    
                # Check all possible ID columns
                for col in id_columns:
                    if str(row.get(col, '')) == str(item_id):
                        return idx + 2  # +2 because sheets are 1-indexed and we skip header
            
            return None
        except Exception as e:
            print(f"Error finding row: {e}")
            return None
    
    async def delete_row(self, sheet_name: str, row_index: int):
        """Delete a row from the sheet"""
        try:
            sheet = self.spreadsheet.worksheet(sheet_name)
            sheet.delete_rows(row_index)
            print(f"Deleted row {row_index} from {sheet_name}")
        except Exception as e:
            print(f"Error deleting row: {e}")

    def _get_sheet_columns(self, sheet_name: str) -> List[str]:
        """Get expected columns for each sheet type"""
        columns = {
            "Memories": ["user_id", "category", "key", "value", "embedding", "timestamp", "confidence", "tags"],
            "Tasks": ["user_id", "task_id", "title", "description", "priority", "status", "deadline",
                      "created_at", "updated_at", "dependencies", "notes",
                      "is_recurring", "recurrence_pattern", "recurrence_end_date", "parent_task_id",
                      "progress_percent", "last_discussed", "completed_at", "archived", "skipped_until"],
            "Archive": ["user_id", "original_sheet", "content", "archived_at", "reason"],
            "Conversations": ["user_id", "session_id", "message_type", "content", "timestamp", "intent", "entities"],
            "Users": ["user_id", "chat_id", "username", "first_seen", "last_active", "preferences"],
            "Settings": ["user_id", "setting_key", "setting_value", "updated_at"],
            "Config": ["user_id", "variable", "value", "description", "type"]
        }
        return columns.get(sheet_name, [])

    async def get_user_setting(self, user_id: str, setting_key: str) -> Optional[str]:
        """Get a specific user setting"""
        try:
            df = await self.get_sheet_data("Settings", user_id)
            if df.empty:
                return None
            match = df[df['setting_key'] == setting_key]
            if not match.empty:
                return str(match.iloc[0]['setting_value'])
            return None
        except Exception as e:
            print(f"Error getting user setting: {e}")
            return None

    async def set_user_setting(self, user_id: str, setting_key: str, setting_value: str):
        """Set a user setting (creates or updates)"""
        try:
            df = await self.get_sheet_data("Settings", user_id)
            now = datetime.now().isoformat()

            if not df.empty:
                match = df[df['setting_key'] == setting_key]
                if not match.empty:
                    # Update existing
                    row_idx = match.index[0] + 2  # +2 for header and 0-indexing
                    await self.update_row("Settings", row_idx, {
                        "setting_value": setting_value,
                        "updated_at": now
                    })
                    return

            # Create new
            await self.append_row("Settings", {
                "user_id": user_id,
                "setting_key": setting_key,
                "setting_value": setting_value,
                "updated_at": now
            })
        except Exception as e:
            print(f"Error setting user setting: {e}")

    async def get_all_user_settings(self, user_id: str) -> Dict[str, str]:
        """Get all settings for a user as a dict"""
        try:
            df = await self.get_sheet_data("Settings", user_id)
            if df.empty:
                return {}
            settings = {}
            for _, row in df.iterrows():
                key = str(row.get('setting_key', ''))
                value = str(row.get('setting_value', ''))
                if key:
                    settings[key] = value
            return settings
        except Exception as e:
            print(f"Error getting all user settings: {e}")
            return {}

    def get_config_sync(self, variable: str, user_id: Optional[str] = None) -> Optional[str]:
        """Get a config variable with optional per-user override (sync version).

        Lookup order:
        1. If user_id provided, check for user-specific value first
        2. Fall back to global value (empty user_id)
        """
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()

            global_value = None
            user_value = None

            for row in data:
                if str(row.get('variable', '')) == variable:
                    row_user_id = str(row.get('user_id', '')).strip()
                    if not row_user_id:
                        # Global default
                        global_value = str(row.get('value', ''))
                    elif user_id and row_user_id == str(user_id):
                        # User-specific override
                        user_value = str(row.get('value', ''))

            # Return user-specific if found, otherwise global
            return user_value if user_value is not None else global_value
        except Exception as e:
            print(f"Error getting config: {e}")
            return None

    async def get_config(self, variable: str, user_id: Optional[str] = None) -> Optional[str]:
        """Get a config variable with optional per-user override"""
        return self.get_config_sync(variable, user_id)

    async def get_all_config(self, user_id: Optional[str] = None) -> Dict[str, str]:
        """Get all config variables, with user-specific overrides applied if user_id provided.

        Returns a dict where each variable has its effective value
        (user override if exists, otherwise global default).
        """
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()

            # First collect all global defaults
            config = {}
            for row in data:
                var = str(row.get('variable', ''))
                val = str(row.get('value', ''))
                row_user_id = str(row.get('user_id', '')).strip()

                if var and not row_user_id:
                    # Global default
                    config[var] = val

            # Then apply user-specific overrides if user_id provided
            if user_id:
                for row in data:
                    var = str(row.get('variable', ''))
                    val = str(row.get('value', ''))
                    row_user_id = str(row.get('user_id', '')).strip()

                    if var and row_user_id == str(user_id):
                        # User-specific override
                        config[var] = val

            return config
        except Exception as e:
            print(f"Error getting all config: {e}")
            return {}

    async def get_all_config_with_details(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all config variables with full details including user_id.

        Returns list of config entries. If user_id provided, returns:
        - Global defaults for variables without user override
        - User-specific entries for variables with user override
        """
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()

            # Collect globals and user overrides separately
            globals_dict = {}
            user_overrides = {}

            for row in data:
                var = str(row.get('variable', ''))
                if not var:
                    continue

                row_user_id = str(row.get('user_id', '')).strip()
                entry = {
                    'user_id': row_user_id,
                    'variable': var,
                    'value': str(row.get('value', '')),
                    'description': str(row.get('description', '')),
                    'type': str(row.get('type', 'string'))
                }

                if not row_user_id:
                    globals_dict[var] = entry
                elif user_id and row_user_id == str(user_id):
                    user_overrides[var] = entry

            # Build result: use user override if exists, otherwise global
            result = []
            for var, global_entry in globals_dict.items():
                if var in user_overrides:
                    result.append(user_overrides[var])
                else:
                    result.append(global_entry)

            return result
        except Exception as e:
            print(f"Error getting config with details: {e}")
            return []

    async def set_config(self, variable: str, value: str, user_id: Optional[str] = None,
                        description: str = "", var_type: str = "string") -> bool:
        """Set a config variable. If user_id provided, sets user-specific override."""
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()

            target_user_id = str(user_id) if user_id else ""

            # Find existing row
            for idx, row in enumerate(data):
                row_var = str(row.get('variable', ''))
                row_user_id = str(row.get('user_id', '')).strip()

                if row_var == variable and row_user_id == target_user_id:
                    # Update existing row (value is in column 3 now with user_id in column 1)
                    sheet.update_cell(idx + 2, 3, str(value))
                    return True

            # Create new row
            sheet.append_row([target_user_id, variable, str(value), description, var_type])
            return True
        except Exception as e:
            print(f"Error setting config: {e}")
            return False

    async def delete_user_config(self, variable: str, user_id: str) -> bool:
        """Delete a user-specific config override (reverts to global default)."""
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()

            for idx, row in enumerate(data):
                row_var = str(row.get('variable', ''))
                row_user_id = str(row.get('user_id', '')).strip()

                if row_var == variable and row_user_id == str(user_id):
                    sheet.delete_rows(idx + 2)
                    return True

            return False
        except Exception as e:
            print(f"Error deleting user config: {e}")
            return False

    def initialize_default_config(self):
        """Initialize default config values if Config sheet is empty"""
        try:
            sheet = self.spreadsheet.worksheet("Config")
            data = sheet.get_all_records()
            if data:  # Already has data
                return

            # Default configuration (user_id, variable, value, description, type)
            # Empty user_id = global default
            defaults = [
                # --- PROACTIVE FEATURES ---
                ["", "daily_summary_enabled", "true", "Enable daily morning summary", "bool"],
                ["", "daily_summary_hour", "9", "Hour to send daily summary (24h format)", "int"],
                ["", "default_checkin_hours", "10,14,18", "Comma-separated hours for task check-ins (24h format)", "string"],
                ["", "checkins_enabled", "true", "Enable periodic task check-ins", "bool"],
                ["", "deadline_reminders_enabled", "true", "Enable deadline reminder notifications", "bool"],
                ["", "reminder_minutes_before", "60", "Minutes before deadline to send reminder", "int"],
                ["", "proactive_check_interval", "5", "Minutes between proactive checks", "int"],

                # --- TASK SETTINGS ---
                ["", "task_archive_days", "7", "Days after completion to auto-archive tasks", "int"],
                ["", "default_task_priority", "medium", "Default priority for new tasks (high/medium/low)", "string"],
                ["", "auto_create_calendar_for_tasks", "true", "Auto-create calendar events for timed tasks", "bool"],

                # --- AI CONTEXT LIMITS ---
                ["", "max_memories_context", "5", "Max memories to include in AI context", "int"],
                ["", "max_tasks_context", "5", "Max tasks to include in AI context", "int"],
                ["", "max_conversations_context", "5", "Max conversation history to include", "int"],
                ["", "discussion_mode_memory_limit", "15", "Max memories in task discussion mode", "int"],
                ["", "discussion_mode_task_limit", "15", "Max tasks in task discussion mode", "int"],

                # --- SESSION & INTERACTION ---
                ["", "session_timeout_minutes", "5", "Minutes of inactivity before task discussion ends", "int"],
                ["", "typing_indicator_enabled", "true", "Show typing indicator while processing", "bool"],
                ["", "include_calendar_in_responses", "true", "Include upcoming events in relevant responses", "bool"],

                # --- AI PIPELINE ---
                ["", "use_pipeline", "true", "Enable 4-stage AI pipeline (true/false)", "bool"],
                ["", "ai_model", "llama-3.3-70b-versatile", "Groq model to use for AI responses", "string"],

                # --- VOICE & MEDIA ---
                ["", "voice_transcription_enabled", "true", "Enable voice message transcription", "bool"],
                ["", "show_transcription_in_response", "true", "Show transcribed text in bot response", "bool"],

                # --- EMAIL SETTINGS ---
                ["", "email_require_confirmation", "true", "Require confirmation before sending emails", "bool"],
                ["", "email_default_sign_off", "Best regards", "Default email sign-off text", "string"],

                # --- CALENDAR SETTINGS ---
                ["", "calendar_lookahead_days", "7", "Days ahead to show in calendar queries", "int"],
                ["", "calendar_delete_requires_confirmation", "true", "Require confirmation to delete events", "bool"],

                # --- SYSTEM ---
                ["", "timezone", "Australia/Brisbane", "Timezone for all time calculations", "string"],
                ["", "bot_name", "Brain Agent", "Name the bot uses to refer to itself", "string"],
                ["", "debug_mode", "false", "Enable verbose debug logging", "bool"]
            ]

            # Add all defaults
            for row in defaults:
                sheet.append_row(row)
            print("Initialized default Config values")

        except Exception as e:
            print(f"Error initializing default config: {e}")