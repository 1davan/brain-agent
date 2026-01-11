"""
Stage 2: Context Fetcher

Parallel/speculative context retrieval based on likely needs.
Runs IN PARALLEL with Stage 1 router for latency optimization.

Key design principles:
1. Speculative fetching - start fetching likely context before routing completes
2. Parallel execution - all context sources fetched concurrently
3. Graceful degradation - failures return empty context, not errors
4. No LLM calls - pure data retrieval
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import pytz

BRISBANE_TZ = pytz.timezone('Australia/Brisbane')

# Keywords that trigger speculative fetching for each domain
CALENDAR_KEYWORDS = [
    'calendar', 'schedule', 'meeting', 'busy', 'free', 'available',
    'today', 'tomorrow', 'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday', 'week', 'appointment', 'event'
]

TASK_KEYWORDS = [
    'task', 'remind', 'reminder', 'todo', 'to-do', 'to do', 'deadline',
    'priority', 'overwhelm', 'focus', 'busy', 'work', 'complete', 'done',
    'finish', 'pending'
]

EMAIL_KEYWORDS = [
    'email', 'mail', 'send', 'draft', 'reply', 'message', 'write to',
    'contact'
]

MEMORY_KEYWORDS = [
    'remember', 'my', 'i like', 'i love', 'i hate', 'favorite', 'prefer',
    'know about me', 'what do you know'
]


class ContextFetcher:
    """Fetches relevant context in parallel based on likely needs."""

    def __init__(
        self,
        memory_agent=None,
        task_agent=None,
        calendar_service=None,
        email_service=None,
        vector_processor=None,
        sheets_client=None
    ):
        self.memory = memory_agent
        self.tasks = task_agent
        self.calendar = calendar_service
        self.email = email_service
        self.vector = vector_processor
        self.sheets = sheets_client

    async def fetch_context(
        self,
        user_message: str,
        user_id: str,
        conversation_history: List[Dict[str, str]],
        domains: List[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch all relevant context for the message.

        Args:
            user_message: The current user message
            user_id: User identifier
            conversation_history: Recent messages for context
            domains: Optional explicit domains from router (if available)

        Returns:
            {
                "conversation_history": [...],
                "memories": [...],
                "tasks": [...],
                "calendar_events": [...],
                "contacts": {...},
                "current_time": "...",
                "today": "...",
                "timezone": "..."
            }
        """
        # Always include basic context
        context = {
            "conversation_history": conversation_history[-10:] if conversation_history else [],
            "memories": [],
            "tasks": [],
            "calendar_events": [],
            "contacts": {},
            "current_time": datetime.now(BRISBANE_TZ).strftime("%I:%M%p"),
            "today": datetime.now(BRISBANE_TZ).strftime("%A, %B %d, %Y"),
            "timezone": "Australia/Brisbane"
        }

        user_lower = user_message.lower()

        # Determine what to fetch (speculative or explicit)
        fetch_calendar = False
        fetch_tasks = False
        fetch_email = False
        fetch_memories = True  # Always fetch memories for personalization

        if domains:
            # Explicit domains from router
            fetch_calendar = "calendar" in domains
            fetch_tasks = "task" in domains
            fetch_email = "email" in domains
        else:
            # Speculative fetching based on keywords
            fetch_calendar = any(kw in user_lower for kw in CALENDAR_KEYWORDS)
            fetch_tasks = any(kw in user_lower for kw in TASK_KEYWORDS)
            fetch_email = any(kw in user_lower for kw in EMAIL_KEYWORDS)

        # Build fetch tasks
        fetch_tasks_list = []

        if fetch_calendar and self.calendar:
            fetch_tasks_list.append(self._fetch_calendar_events(user_lower))

        if fetch_tasks and self.tasks:
            fetch_tasks_list.append(self._fetch_pending_tasks(user_id))

        if fetch_email and self.email:
            fetch_tasks_list.append(self._fetch_contacts())

        if fetch_memories and self.memory:
            fetch_tasks_list.append(self._fetch_memories(user_id, user_message))

        # Execute all fetches in parallel
        if fetch_tasks_list:
            results = await asyncio.gather(*fetch_tasks_list, return_exceptions=True)

            # Merge results into context
            for result in results:
                if isinstance(result, Exception):
                    print(f"[ContextFetcher] Fetch error: {result}")
                    continue
                if isinstance(result, dict):
                    for key, value in result.items():
                        if value:  # Only update if non-empty
                            context[key] = value

        return context

    async def _fetch_calendar_events(self, user_lower: str) -> Dict[str, Any]:
        """Fetch calendar events based on query context."""
        try:
            now = datetime.now(BRISBANE_TZ)

            # Determine date range based on query
            if 'tomorrow' in user_lower:
                target_date = now + timedelta(days=1)
                events = await self.calendar.get_events_for_date(target_date)
            elif 'today' in user_lower:
                events = await self.calendar.get_events_for_date(now)
            else:
                # Default: next 7 days
                events = await self.calendar.get_upcoming_events(max_results=10, days_ahead=7)

            # Filter out daily recurring events
            daily_recurring = ['panchang', 'yoga nidra', 'gratitude', 'meditation', 'daily']
            filtered = []
            for event in events:
                title_lower = event.get('summary', '').lower()
                if not any(kw in title_lower for kw in daily_recurring):
                    filtered.append(self._format_calendar_event(event))

            return {"calendar_events": filtered}

        except Exception as e:
            print(f"[ContextFetcher] Calendar fetch error: {e}")
            return {"calendar_events": []}

    def _format_calendar_event(self, event: Dict) -> Dict:
        """Format a calendar event for context."""
        start_str = event.get('start', '')
        try:
            if 'T' in start_str:
                dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                time_display = dt.strftime('%I:%M%p on %a %b %d')
            else:
                time_display = f"All day on {start_str}"
        except:
            time_display = start_str

        return {
            "id": event.get('id'),
            "title": event.get('summary', 'Untitled')[:100],
            "time": time_display,
            "location": event.get('location', '')[:50] if event.get('location') else None,
            "start": start_str
        }

    async def _fetch_pending_tasks(self, user_id: str) -> Dict[str, Any]:
        """Fetch pending tasks for the user."""
        try:
            tasks = await self.tasks.get_prioritized_tasks(user_id, limit=10, status="pending")

            formatted = []
            for task in tasks:
                formatted.append({
                    "id": task.get('task_id'),
                    "title": task.get('title', '')[:100],
                    "priority": task.get('priority', 'medium'),
                    "deadline": task.get('deadline'),
                    "status": task.get('status', 'pending')
                })

            return {"tasks": formatted}

        except Exception as e:
            print(f"[ContextFetcher] Tasks fetch error: {e}")
            return {"tasks": []}

    async def _fetch_contacts(self) -> Dict[str, Any]:
        """Fetch email contacts."""
        try:
            contacts = self.email.list_contacts()
            return {"contacts": contacts}
        except Exception as e:
            print(f"[ContextFetcher] Contacts fetch error: {e}")
            return {"contacts": {}}

    async def _fetch_memories(self, user_id: str, query: str) -> Dict[str, Any]:
        """Fetch relevant memories using semantic search."""
        try:
            memories = await self.memory.retrieve_memories(user_id, query, limit=5)

            formatted = []
            for mem in memories:
                formatted.append({
                    "key": mem.get('key', '')[:50],
                    "value": str(mem.get('value', ''))[:200],
                    "category": mem.get('category', 'knowledge'),
                    "relevance": round(mem.get('similarity_score', 0), 2)
                })

            return {"memories": formatted}

        except Exception as e:
            print(f"[ContextFetcher] Memories fetch error: {e}")
            return {"memories": []}

    async def fetch_all_context(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """
        Aggressive fetch - get everything when intent is ambiguous.
        Used as fallback when router is uncertain.
        """
        context = {
            "conversation_history": [],
            "memories": [],
            "tasks": [],
            "calendar_events": [],
            "contacts": {},
            "current_time": datetime.now(BRISBANE_TZ).strftime("%I:%M%p"),
            "today": datetime.now(BRISBANE_TZ).strftime("%A, %B %d, %Y"),
            "timezone": "Australia/Brisbane"
        }

        fetch_tasks = []

        if self.calendar:
            fetch_tasks.append(self._fetch_calendar_events(""))

        if self.tasks:
            fetch_tasks.append(self._fetch_pending_tasks(user_id))

        if self.email:
            fetch_tasks.append(self._fetch_contacts())

        if self.memory:
            fetch_tasks.append(self._fetch_memories(user_id, user_message))

        if fetch_tasks:
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    continue
                if isinstance(result, dict):
                    for key, value in result.items():
                        if value:
                            context[key] = value

        return context


def create_context_fetcher(
    memory_agent=None,
    task_agent=None,
    calendar_service=None,
    email_service=None,
    vector_processor=None,
    sheets_client=None
) -> ContextFetcher:
    """Factory function to create a context fetcher with available services."""
    return ContextFetcher(
        memory_agent=memory_agent,
        task_agent=task_agent,
        calendar_service=calendar_service,
        email_service=email_service,
        vector_processor=vector_processor,
        sheets_client=sheets_client
    )
