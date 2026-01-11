#!/usr/bin/env python3
"""
Google Keep integration using gkeepapi (unofficial library).
Allows reading, creating, and editing notes.

Setup:
1. pip install gkeepapi
2. Get a master token (see: https://gkeepapi.readthedocs.io/en/latest/#obtaining-a-master-token)
3. Add GOOGLE_KEEP_TOKEN to .env
"""

import os
import gkeepapi
from typing import Optional, Dict, Any, List
from datetime import datetime


class KeepService:
    def __init__(self, email: str = None, master_token: str = None):
        """
        Initialize Google Keep service.

        Args:
            email: Gmail address
            master_token: Google master token for authentication
        """
        self.email = email or os.getenv('GMAIL_ADDRESS', '')
        self.master_token = master_token or os.getenv('GOOGLE_KEEP_TOKEN', '')
        self.keep = gkeepapi.Keep()
        self.authenticated = False

        if self.email and self.master_token:
            self._authenticate()
        else:
            print("Keep service: Missing GMAIL_ADDRESS or GOOGLE_KEEP_TOKEN in .env")
            print("To get a master token, see: https://gkeepapi.readthedocs.io/en/latest/#obtaining-a-master-token")

    def _authenticate(self):
        """Authenticate with Google Keep using master token."""
        try:
            self.keep.resume(self.email, self.master_token)
            self.keep.sync()
            self.authenticated = True
            print(f"Keep service authenticated for: {self.email}")
        except Exception as e:
            print(f"Keep authentication failed: {e}")
            print("You may need to refresh your master token.")
            self.authenticated = False

    def sync(self):
        """Sync with Google Keep servers."""
        if not self.authenticated:
            return False
        try:
            self.keep.sync()
            return True
        except Exception as e:
            print(f"Keep sync error: {e}")
            return False

    async def list_notes(self, max_results: int = 20, include_archived: bool = False) -> List[Dict[str, Any]]:
        """
        List all notes from Google Keep.

        Args:
            max_results: Maximum notes to return
            include_archived: Whether to include archived notes

        Returns:
            List of note summaries
        """
        if not self.authenticated:
            return []

        try:
            self.sync()
            notes = []

            all_notes = self.keep.all() if include_archived else [n for n in self.keep.all() if not n.archived]

            for note in list(all_notes)[:max_results]:
                notes.append({
                    'id': note.id,
                    'title': note.title or '(Untitled)',
                    'text': note.text[:200] + '...' if len(note.text) > 200 else note.text,
                    'pinned': note.pinned,
                    'archived': note.archived,
                    'color': str(note.color) if note.color else None,
                    'labels': [label.name for label in note.labels.all()],
                    'type': 'list' if hasattr(note, 'items') else 'note'
                })

            return notes

        except Exception as e:
            print(f"Error listing Keep notes: {e}")
            return []

    async def search_notes(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search notes by title or content.

        Args:
            query: Search term (case-insensitive)
            max_results: Maximum results to return

        Returns:
            List of matching notes
        """
        if not self.authenticated:
            return []

        try:
            self.sync()
            query_lower = query.lower()
            matches = []

            for note in self.keep.all():
                if note.archived:
                    continue

                title_match = query_lower in (note.title or '').lower()
                text_match = query_lower in (note.text or '').lower()

                if title_match or text_match:
                    matches.append({
                        'id': note.id,
                        'title': note.title or '(Untitled)',
                        'text': note.text[:200] + '...' if len(note.text) > 200 else note.text,
                        'pinned': note.pinned,
                        'match_type': 'title' if title_match else 'content'
                    })

                    if len(matches) >= max_results:
                        break

            return matches

        except Exception as e:
            print(f"Error searching Keep notes: {e}")
            return []

    async def find_note_by_title(self, title_query: str) -> Optional[Dict[str, Any]]:
        """
        Find a note by partial title match.

        Args:
            title_query: Partial title to search for

        Returns:
            Best matching note or None
        """
        if not self.authenticated:
            return None

        try:
            self.sync()
            query_lower = title_query.lower()
            best_match = None
            best_score = 0

            for note in self.keep.all():
                if note.archived:
                    continue

                title = (note.title or '').lower()

                # Exact match
                if title == query_lower:
                    return {
                        'id': note.id,
                        'title': note.title,
                        'text': note.text,
                        'pinned': note.pinned
                    }

                # Partial match - score by how much of the query is in the title
                if query_lower in title:
                    score = len(query_lower) / len(title) if title else 0
                    if score > best_score:
                        best_score = score
                        best_match = note

                # Also check if all words in query are in title
                query_words = query_lower.split()
                if all(word in title for word in query_words):
                    score = len(query_words) / len(title.split()) if title else 0
                    if score > best_score:
                        best_score = score
                        best_match = note

            if best_match:
                return {
                    'id': best_match.id,
                    'title': best_match.title,
                    'text': best_match.text,
                    'pinned': best_match.pinned
                }

            return None

        except Exception as e:
            print(f"Error finding Keep note: {e}")
            return None

    async def get_note(self, note_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific note by ID."""
        if not self.authenticated:
            return None

        try:
            self.sync()
            note = self.keep.get(note_id)

            if note:
                return {
                    'id': note.id,
                    'title': note.title,
                    'text': note.text,
                    'pinned': note.pinned,
                    'archived': note.archived,
                    'color': str(note.color) if note.color else None,
                    'labels': [label.name for label in note.labels.all()]
                }

            return None

        except Exception as e:
            print(f"Error getting Keep note: {e}")
            return None

    async def create_note(self, title: str, text: str = '', pinned: bool = False) -> Optional[Dict[str, Any]]:
        """
        Create a new note in Google Keep.

        Args:
            title: Note title
            text: Note content
            pinned: Whether to pin the note

        Returns:
            Created note info or None
        """
        if not self.authenticated:
            return None

        try:
            note = self.keep.createNote(title, text)
            note.pinned = pinned
            self.keep.sync()

            return {
                'id': note.id,
                'title': note.title,
                'text': note.text,
                'pinned': note.pinned,
                'status': 'created'
            }

        except Exception as e:
            print(f"Error creating Keep note: {e}")
            return None

    async def add_to_note(self, note_id: str, new_text: str, position: str = 'top') -> Optional[Dict[str, Any]]:
        """
        Add text to an existing note.

        Args:
            note_id: Note ID to update
            new_text: Text to add
            position: 'top' to prepend, 'bottom' to append

        Returns:
            Updated note info or None
        """
        if not self.authenticated:
            return None

        try:
            self.sync()
            note = self.keep.get(note_id)

            if not note:
                return None

            # Add timestamp to the new entry
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            entry = f"[{timestamp}] {new_text}"

            if position == 'top':
                note.text = f"{entry}\n\n{note.text}" if note.text else entry
            else:
                note.text = f"{note.text}\n\n{entry}" if note.text else entry

            self.keep.sync()

            return {
                'id': note.id,
                'title': note.title,
                'text': note.text,
                'status': 'updated'
            }

        except Exception as e:
            print(f"Error adding to Keep note: {e}")
            return None

    async def update_note(self, note_id: str, title: str = None, text: str = None) -> Optional[Dict[str, Any]]:
        """
        Update a note's title or content.

        Args:
            note_id: Note ID to update
            title: New title (optional)
            text: New content (optional, replaces entire content)

        Returns:
            Updated note info or None
        """
        if not self.authenticated:
            return None

        try:
            self.sync()
            note = self.keep.get(note_id)

            if not note:
                return None

            if title is not None:
                note.title = title
            if text is not None:
                note.text = text

            self.keep.sync()

            return {
                'id': note.id,
                'title': note.title,
                'text': note.text,
                'status': 'updated'
            }

        except Exception as e:
            print(f"Error updating Keep note: {e}")
            return None

    async def delete_note(self, note_id: str) -> bool:
        """Delete (trash) a note."""
        if not self.authenticated:
            return False

        try:
            self.sync()
            note = self.keep.get(note_id)

            if note:
                note.delete()
                self.keep.sync()
                return True

            return False

        except Exception as e:
            print(f"Error deleting Keep note: {e}")
            return False

    async def archive_note(self, note_id: str) -> bool:
        """Archive a note."""
        if not self.authenticated:
            return False

        try:
            self.sync()
            note = self.keep.get(note_id)

            if note:
                note.archived = True
                self.keep.sync()
                return True

            return False

        except Exception as e:
            print(f"Error archiving Keep note: {e}")
            return False


# Singleton instance
_keep_service = None


def get_keep_service() -> Optional[KeepService]:
    """Get singleton Keep service instance."""
    global _keep_service

    if _keep_service is None:
        _keep_service = KeepService()

    return _keep_service
