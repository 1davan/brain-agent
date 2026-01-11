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
        required_sheets = ["Memories", "Tasks", "Archive", "Conversations", "Users"]
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
                      "progress_percent", "last_discussed", "completed_at", "archived"],
            "Archive": ["user_id", "original_sheet", "content", "archived_at", "reason"],
            "Conversations": ["user_id", "session_id", "message_type", "content", "timestamp", "intent", "entities"],
            "Users": ["user_id", "chat_id", "username", "first_seen", "last_active", "preferences"]
        }
        return columns.get(sheet_name, [])