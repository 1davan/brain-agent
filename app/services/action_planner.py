"""
Stage 3: Action Planner

The "smart" stage that:
1. Receives full conversation history (for pronoun resolution)
2. Does entity extraction (has schema context to do it properly)
3. Plans actions with proper parameters
4. Flags high-stakes actions for confirmation

Key design principles:
1. Full conversation history - can resolve "it", "that", "him"
2. Domain-specific entity extraction - has the schema
3. HIGH_STAKES_ACTIONS require confirmation
4. Multi-domain support - can plan calendar + email in one call
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from groq import Groq
import pytz

BRISBANE_TZ = pytz.timezone('Australia/Brisbane')


# Actions that require human confirmation before execution
HIGH_STAKES_ACTIONS = {
    "email": {
        "send_email": True,       # Sending is permanent
        "create_draft": False,    # Drafts are safe
        "reply_to_email": True    # Replies go out
    },
    "calendar": {
        "delete_event": True,     # Deletion is permanent
        "create_event": False,    # Creating is usually safe
        "update_event": True      # Modifying existing
    },
    "task": {
        "delete_task": True,      # Deletion is permanent
        "create": False,          # Creating is safe
        "complete": False         # Completing is usually intended
    },
    "memory": {
        "delete": True,           # Deletion is permanent
        "store": False,           # Storing is safe
        "update": False           # Updates can be reversed
    },
    "keep": {
        "delete_note": True,      # Deletion is permanent
        "create_note": False,     # Creating is safe
        "update_note": False      # Updates can be reversed
    }
}


class ActionPlanner:
    """Plans actions based on user request with full conversation context."""

    PLANNER_PROMPT = """You plan actions based on the user's request. Output JSON only.

CONVERSATION HISTORY (resolve pronouns from this):
{conversation_history}

CURRENT MESSAGE: "{user_message}"

AVAILABLE CONTEXT:
- Tasks: {tasks}
- Calendar: {calendar_events}
- Contacts: {contacts}
- Memories: {memories}

TODAY: {today}
CURRENT TIME: {current_time}
TIMEZONE: {timezone}

DOMAINS TO HANDLE: {domains}

For each domain, plan the necessary action:

TASK ACTIONS:
- create: {{title, description, priority (high/medium/low), deadline}}
- update: {{find_by (title substring), changes}}
- complete: {{find_by (title substring)}}
- delete: {{find_by (title substring)}} [REQUIRES CONFIRMATION]

CALENDAR ACTIONS:
- create_event: {{summary, start_time (ISO format), end_time, location}}
- list_events: {{days_ahead}}
- delete_event: {{event_id or find_by}} [REQUIRES CONFIRMATION]
- update_event: {{event_id or find_by, changes}} [REQUIRES CONFIRMATION]

EMAIL ACTIONS:
- create_draft: {{to (name or email), subject, body}}
- send_email: {{to, subject, body}} [REQUIRES CONFIRMATION]
- reply_to_email: {{sender_name, body}} [REQUIRES CONFIRMATION]

MEMORY ACTIONS:
- store: {{category (preference/fact/relationship), key, value}}
- update: {{key, new_value}}
- delete: {{key}} [REQUIRES CONFIRMATION]

KEEP ACTIONS:
- create_note: {{title, content}}
- update_note: {{title_search, new_content}}
- delete_note: {{title_search}} [REQUIRES CONFIRMATION]

DATE PARSING (use these exact formats):
- "tomorrow" = {tomorrow}
- "next Monday" = calculate from today
- "at 5pm" = {today}T17:00:00
- "in 2 hours" = {in_2_hours}
- Always use ISO format: YYYY-MM-DDTHH:MM:SS

EMAIL FORMATTING:
- Start with appropriate greeting: "Hey [Name]," (casual) or "Hi [Name]," or "Dear [Name]," (formal)
- Break content into short paragraphs (2-3 sentences each)
- Use blank lines between paragraphs
- End with context-appropriate sign-off:
  - Casual: "Cheers,\nIvan" or just "Ivan"
  - Semi-formal: "Thanks,\nIvan" or "Best,\nIvan"
  - Formal: "Kind regards,\nIvan"
- Always sign as "Ivan"

IMPORTANT:
1. Resolve ALL pronouns ("it", "that meeting", "him") using conversation history
2. If action is marked [REQUIRES CONFIRMATION], set requires_confirmation: true
3. If you can't determine a required field, set needs_clarification: true
4. For email body, write a brief but complete message with proper structure (greeting, paragraphs, sign-off)

Output ONLY this JSON:
{{
  "actions": [
    {{
      "domain": "task|calendar|email|memory|keep",
      "action": "action_name",
      "params": {{ ... }},
      "reasoning": "Why this action"
    }}
  ],
  "requires_confirmation": true|false,
  "confirmation_message": "Should I send this email to Bob about the meeting?",
  "needs_clarification": false,
  "clarification_question": null
}}"""

    def __init__(self, groq_api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.client = Groq(api_key=groq_api_key)
        self.model = model

    async def plan_actions(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        context: Dict[str, Any],
        domains: List[str]
    ) -> Dict[str, Any]:
        """
        Plan actions for the given message and domains.

        Args:
            user_message: The current user message
            conversation_history: Full conversation history for pronoun resolution
            context: Context from Stage 2 (tasks, calendar, contacts, memories)
            domains: List of domains to plan for ["task", "email", etc.]

        Returns:
            {
                "actions": [...],
                "requires_confirmation": bool,
                "confirmation_message": str or None,
                "needs_clarification": bool,
                "clarification_question": str or None
            }
        """
        if not domains:
            return {
                "actions": [],
                "requires_confirmation": False,
                "confirmation_message": None,
                "needs_clarification": False,
                "clarification_question": None
            }

        # Build date helpers
        now = datetime.now(BRISBANE_TZ)
        tomorrow = now + timedelta(days=1)
        in_2_hours = now + timedelta(hours=2)

        # Format conversation history
        formatted_history = self._format_history(conversation_history[-10:])

        # Format context items
        tasks_str = self._format_tasks(context.get("tasks", []))
        calendar_str = self._format_calendar(context.get("calendar_events", []))
        contacts_str = self._format_contacts(context.get("contacts", {}))
        memories_str = self._format_memories(context.get("memories", []))

        prompt = self.PLANNER_PROMPT.format(
            conversation_history=formatted_history or "(No recent conversation)",
            user_message=user_message,
            tasks=tasks_str or "(No pending tasks)",
            calendar_events=calendar_str or "(No calendar events)",
            contacts=contacts_str or "(No contacts)",
            memories=memories_str or "(No relevant memories)",
            today=now.strftime("%A, %B %d, %Y"),
            current_time=now.strftime("%I:%M%p"),
            timezone="Australia/Brisbane",
            domains=", ".join(domains),
            tomorrow=tomorrow.strftime("%Y-%m-%dT%H:%M:%S"),
            in_2_hours=in_2_hours.strftime("%Y-%m-%dT%H:%M:%S")
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.2
            )

            result_text = response.choices[0].message.content.strip()
            return self._parse_response(result_text, domains)

        except Exception as e:
            print(f"[ActionPlanner] Error: {e}")
            return {
                "actions": [],
                "requires_confirmation": False,
                "confirmation_message": None,
                "needs_clarification": True,
                "clarification_question": "I had trouble understanding. Could you rephrase that?"
            }

    def _format_history(self, messages: List[Dict]) -> str:
        """Format conversation history for the prompt."""
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = "User" if msg.get("message_type") == "user" else "Assistant"
            content = str(msg.get("content", ""))[:300]  # Truncate long messages
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _format_tasks(self, tasks: List[Dict]) -> str:
        """Format tasks for the prompt."""
        if not tasks:
            return ""

        lines = []
        for task in tasks[:5]:  # Limit to 5 tasks
            deadline = task.get("deadline", "")
            if deadline:
                deadline = f" (due: {deadline})"
            lines.append(f"- {task.get('title', 'Untitled')} [{task.get('priority', 'medium')}]{deadline}")

        return "\n".join(lines)

    def _format_calendar(self, events: List[Dict]) -> str:
        """Format calendar events for the prompt."""
        if not events:
            return ""

        lines = []
        for event in events[:5]:  # Limit to 5 events
            loc = f" @ {event.get('location')}" if event.get('location') else ""
            lines.append(f"- {event.get('title', 'Untitled')} at {event.get('time', 'unknown time')}{loc}")

        return "\n".join(lines)

    def _format_contacts(self, contacts: Dict[str, str]) -> str:
        """Format contacts for the prompt."""
        if not contacts:
            return ""

        lines = []
        for name, email in list(contacts.items())[:10]:  # Limit to 10 contacts
            lines.append(f"- {name}: {email}")

        return "\n".join(lines)

    def _format_memories(self, memories: List[Dict]) -> str:
        """Format memories for the prompt."""
        if not memories:
            return ""

        lines = []
        for mem in memories[:5]:  # Limit to 5 memories
            lines.append(f"- {mem.get('key', 'unknown')}: {mem.get('value', '')}")

        return "\n".join(lines)

    def _parse_response(self, response_text: str, domains: List[str]) -> Dict[str, Any]:
        """Parse LLM response and validate actions."""
        default_result = {
            "actions": [],
            "requires_confirmation": False,
            "confirmation_message": None,
            "needs_clarification": True,
            "clarification_question": "I had trouble understanding. Could you rephrase that?"
        }

        try:
            # Extract JSON from response
            result = self._extract_json(response_text)
            if not result:
                print(f"[ActionPlanner] Failed to extract JSON from: {response_text[:200]}")
                return default_result

            # Validate and normalize actions
            actions = result.get("actions", [])
            validated_actions = []
            requires_confirmation = False

            for action in actions:
                domain = action.get("domain")
                action_name = action.get("action")

                if domain not in domains:
                    print(f"[ActionPlanner] Skipping action for domain {domain} (not requested)")
                    continue

                # Check if action requires confirmation
                if self._is_high_stakes(domain, action_name):
                    requires_confirmation = True

                validated_actions.append({
                    "domain": domain,
                    "action": action_name,
                    "params": action.get("params", {}),
                    "reasoning": action.get("reasoning", "")
                })

            return {
                "actions": validated_actions,
                "requires_confirmation": requires_confirmation or result.get("requires_confirmation", False),
                "confirmation_message": result.get("confirmation_message") if requires_confirmation else None,
                "needs_clarification": result.get("needs_clarification", False),
                "clarification_question": result.get("clarification_question")
            }

        except Exception as e:
            print(f"[ActionPlanner] Parse error: {e}")
            return default_result

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract JSON from response text."""
        # Try direct parse
        try:
            return json.loads(text.strip())
        except:
            pass

        # Find JSON in text
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except:
                pass

        return None

    def _is_high_stakes(self, domain: str, action: str) -> bool:
        """Check if an action requires confirmation."""
        domain_actions = HIGH_STAKES_ACTIONS.get(domain, {})
        return domain_actions.get(action, False)


class ConfirmationManager:
    """Manages pending actions awaiting user confirmation."""

    def __init__(self):
        # In-memory store (for production, use Redis or database)
        self._pending_actions: Dict[str, Dict[str, Any]] = {}

    async def store_pending_action(self, user_id: str, action_plan: Dict[str, Any]) -> str:
        """Store an action plan awaiting confirmation."""
        confirmation_id = f"confirm_{user_id}_{datetime.now().timestamp()}"
        self._pending_actions[user_id] = {
            "id": confirmation_id,
            "action_plan": action_plan,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=5)).isoformat()
        }
        return confirmation_id

    async def get_pending_action(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get pending action for a user."""
        pending = self._pending_actions.get(user_id)
        if pending:
            # Check expiration
            expires_at = datetime.fromisoformat(pending["expires_at"])
            if datetime.now() > expires_at:
                await self.clear_pending_action(user_id)
                return None
        return pending

    async def clear_pending_action(self, user_id: str) -> None:
        """Clear pending action for a user."""
        if user_id in self._pending_actions:
            del self._pending_actions[user_id]

    def is_affirmative(self, message: str) -> bool:
        """Check if message is an affirmative response."""
        affirmatives = [
            'yes', 'yeah', 'yep', 'yup', 'sure', 'ok', 'okay',
            'do it', 'send it', 'send', 'go ahead', 'confirm', 'approved',
            'absolutely', 'definitely', 'please do', 'proceed'
        ]
        msg_lower = message.lower().strip()
        return any(aff in msg_lower for aff in affirmatives)

    def is_negative(self, message: str) -> bool:
        """Check if message is a negative response."""
        negatives = [
            'no', 'nope', 'nah', 'cancel', "don't", 'dont',
            'stop', 'wait', 'hold on', 'never mind', 'nevermind',
            'skip', 'forget it', 'abort'
        ]
        msg_lower = message.lower().strip()
        return any(neg in msg_lower for neg in negatives)


# Singleton confirmation manager
_confirmation_manager = None


def get_confirmation_manager() -> ConfirmationManager:
    """Get singleton confirmation manager."""
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager


# Quick test
if __name__ == "__main__":
    import asyncio
    import os
    from dotenv import load_dotenv

    load_dotenv()

    planner = ActionPlanner(os.getenv("GROQ_API_KEY"))

    test_cases = [
        {
            "message": "Remind me to call mom tomorrow at 5pm",
            "history": [],
            "context": {"tasks": [], "calendar_events": [], "contacts": {}, "memories": []},
            "domains": ["task"]
        },
        {
            "message": "Send an email to Bob about the meeting",
            "history": [],
            "context": {"contacts": {"bob": "bob@example.com"}},
            "domains": ["email"]
        },
    ]

    async def test():
        for case in test_cases:
            result = await planner.plan_actions(
                case["message"],
                case["history"],
                case["context"],
                case["domains"]
            )
            print(f"'{case['message']}' -> {json.dumps(result, indent=2)}")
            print()

    asyncio.run(test())
