import json
import os
from typing import List, Dict, Any, Optional
import pandas as pd
from datetime import datetime

class LocalStorage:
    """Simple local JSON-based storage as fallback for Google Sheets"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # Initialize data files
        self.memories_file = os.path.join(data_dir, "memories.json")
        self.tasks_file = os.path.join(data_dir, "tasks.json")
        self.archive_file = os.path.join(data_dir, "archive.json")
        self.conversations_file = os.path.join(data_dir, "conversations.json")

        # Initialize empty files if they don't exist
        for file_path in [self.memories_file, self.tasks_file, self.archive_file, self.conversations_file]:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump([], f)

    def _load_data(self, file_path: str) -> List[Dict]:
        """Load data from JSON file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_data(self, file_path: str, data: List[Dict]):
        """Save data to JSON file"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def get_sheet_data(self, sheet_name: str, user_id: Optional[str] = None) -> pd.DataFrame:
        """Get data from local storage"""
        file_map = {
            "Memories": self.memories_file,
            "Tasks": self.tasks_file,
            "Archive": self.archive_file,
            "Conversations": self.conversations_file
        }

        if sheet_name not in file_map:
            return pd.DataFrame()

        data = self._load_data(file_map[sheet_name])

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)

        if user_id and 'user_id' in df.columns:
            df = df[df['user_id'] == user_id]

        return df

    async def append_row(self, sheet_name: str, row_data: Dict[str, Any]):
        """Append new row to local storage"""
        file_map = {
            "Memories": self.memories_file,
            "Tasks": self.tasks_file,
            "Archive": self.archive_file,
            "Conversations": self.conversations_file
        }

        if sheet_name not in file_map:
            return

        data = self._load_data(file_map[sheet_name])

        # Add timestamp if not present
        if 'timestamp' not in row_data:
            row_data['timestamp'] = datetime.now().isoformat()

        data.append(row_data)
        self._save_data(file_map[sheet_name], data)

    async def update_row(self, sheet_name: str, row_index: int, row_data: Dict[str, Any]):
        """Update existing row in local storage"""
        file_map = {
            "Memories": self.memories_file,
            "Tasks": self.tasks_file,
            "Archive": self.archive_file,
            "Conversations": self.conversations_file
        }

        if sheet_name not in file_map:
            return

        data = self._load_data(file_map[sheet_name])

        if 0 <= row_index - 2 < len(data):  # -2 because sheets are 1-indexed and skip header
            data[row_index - 2].update(row_data)
            self._save_data(file_map[sheet_name], data)

    async def find_row_by_id(self, sheet_name: str, user_id: str, item_id: str) -> Optional[int]:
        """Find row index by user_id and item_id"""
        df = await self.get_sheet_data(sheet_name, user_id)
        if df.empty:
            return None

        # Look for matching item
        for idx, row in df.iterrows():
            if str(row.get('id', '')) == item_id or str(row.get('task_id', '')) == item_id:
                return idx + 2  # +2 because sheets are 1-indexed and we skip header
        return None