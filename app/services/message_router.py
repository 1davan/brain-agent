"""
Stage 1: Message Router

Fast, minimal LLM call to determine:
1. Is this chat or does it need tools?
2. Which domains are needed?
3. Is this a followup to previous message?

Does NOT extract entities - that's Stage 3's job.
"""

import json
from typing import Dict, Any, List, Optional
from groq import Groq


class MessageRouter:
    """Routes messages to appropriate handlers without heavy processing."""

    ROUTER_PROMPT = """You route user messages to handlers. Output JSON only.

RECENT CONVERSATION:
{last_3_messages}

USER: "{user_message}"

DETERMINE:
1. Is this simple chat (greeting, thanks, small talk, questions about capabilities)?
2. Or does it need tools? Which ones?
3. Is this a short response continuing the previous topic?

TOOLS:
- task: Creating, updating, completing tasks/reminders
- calendar: Viewing or creating calendar events
- email: Drafting or sending emails
- memory: User sharing personal facts to remember
- keep: Google Keep notes

RULES:
- Short responses ("yes", "ok", "that one", "the first", numbers, single words) after a bot question = followup
- "Thanks!" alone = chat. "Thanks, and remind me..." = action
- Questions about schedule/availability = calendar
- "Remember that..." or sharing personal info = memory
- If unsure, default to chat

Output ONLY this JSON:
{{
  "type": "chat|action|followup",
  "domains": [],
  "is_followup": false
}}"""

    def __init__(self, groq_api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.client = Groq(api_key=groq_api_key)
        self.model = model

    async def route(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Route a message to determine handling path.

        Args:
            user_message: The current user message
            conversation_history: Recent messages for context

        Returns:
            {
                "type": "chat|action|followup",
                "domains": ["task", "calendar", ...],
                "is_followup": bool
            }
        """
        # Format recent conversation
        last_3 = conversation_history[-3:] if conversation_history else []
        formatted_history = self._format_history(last_3)

        prompt = self.ROUTER_PROMPT.format(
            last_3_messages=formatted_history or "(No recent messages)",
            user_message=user_message
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.1  # Low temperature for consistent routing
            )

            result_text = response.choices[0].message.content.strip()
            return self._parse_response(result_text, user_message, last_3)

        except Exception as e:
            print(f"[Router] Error: {e}")
            # Fallback to chat on error
            return {
                "type": "chat",
                "domains": [],
                "is_followup": False
            }

    def _format_history(self, messages: List[Dict]) -> str:
        """Format conversation history for the prompt."""
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = "User" if msg.get("message_type") == "user" else "Bot"
            content = str(msg.get("content", ""))[:200]  # Truncate long messages
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _parse_response(
        self,
        response_text: str,
        user_message: str,
        recent_messages: List[Dict]
    ) -> Dict[str, Any]:
        """Parse LLM response, with fallback heuristics."""
        try:
            # Try to extract JSON
            result = self._extract_json(response_text)
            if result:
                # Validate and normalize
                return {
                    "type": result.get("type", "chat"),
                    "domains": result.get("domains", []),
                    "is_followup": result.get("is_followup", False)
                }
        except Exception as e:
            print(f"[Router] JSON parse error: {e}")

        # Fallback: Use heuristics
        return self._heuristic_route(user_message, recent_messages)

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

    def _heuristic_route(
        self,
        user_message: str,
        recent_messages: List[Dict]
    ) -> Dict[str, Any]:
        """Fallback heuristic routing when LLM fails."""
        msg_lower = user_message.lower().strip()
        words = msg_lower.split()

        # Followup detection
        if len(words) <= 3:
            followup_words = ['yes', 'no', 'ok', 'okay', 'sure', 'yep', 'nope',
                              'that', 'this', 'first', 'second', 'done', 'skip']
            if any(w in words for w in followup_words) or msg_lower.isdigit():
                # Check if last bot message was a question
                if recent_messages:
                    last_bot = None
                    for msg in reversed(recent_messages):
                        if msg.get("message_type") == "assistant":
                            last_bot = msg.get("content", "")
                            break
                    if last_bot and "?" in last_bot:
                        return {"type": "followup", "domains": [], "is_followup": True}

        # Domain detection
        domains = []

        # Task keywords
        task_keywords = ['remind', 'task', 'todo', 'to-do', 'to do', 'deadline',
                         'complete', 'finish', 'done with']
        if any(kw in msg_lower for kw in task_keywords):
            domains.append("task")

        # Calendar keywords
        cal_keywords = ['calendar', 'schedule', 'meeting', 'appointment', 'event',
                        'busy', 'free', 'available', 'tomorrow', 'today', 'next week']
        if any(kw in msg_lower for kw in cal_keywords):
            domains.append("calendar")

        # Email keywords
        email_keywords = ['email', 'mail', 'send', 'draft', 'reply to']
        if any(kw in msg_lower for kw in email_keywords):
            domains.append("email")

        # Memory keywords
        memory_keywords = ['remember', 'my favorite', 'i like', 'i love', 'i hate',
                           'i prefer', 'i am', "i'm a", 'my name is']
        if any(kw in msg_lower for kw in memory_keywords):
            domains.append("memory")

        # Keep keywords
        keep_keywords = ['note', 'keep', 'add to note', 'shopping list']
        if any(kw in msg_lower for kw in keep_keywords):
            domains.append("keep")

        if domains:
            return {"type": "action", "domains": domains, "is_followup": False}

        # Default to chat
        return {"type": "chat", "domains": [], "is_followup": False}


# Quick test
if __name__ == "__main__":
    import asyncio
    import os
    from dotenv import load_dotenv

    load_dotenv()

    router = MessageRouter(os.getenv("GROQ_API_KEY"))

    test_messages = [
        ("Hey, how's it going?", []),
        ("Remind me to call mom tomorrow", []),
        ("What's on my calendar today?", []),
        ("yes", [{"message_type": "assistant", "content": "Should I send this email?"}]),
        ("Check my calendar and email Bob about being late", []),
    ]

    async def test():
        for msg, history in test_messages:
            result = await router.route(msg, history)
            print(f"'{msg}' -> {result}")

    asyncio.run(test())
