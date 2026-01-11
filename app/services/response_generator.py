"""
Stage 4: Response Generator

Generates natural, honest responses based on action results.

Key design principles:
1. Explicit success/failure - never hallucinate success
2. Match user's energy - casual = casual, urgent = focused
3. Brief acknowledgments - 1-3 sentences unless detail requested
4. Warm but honest - apologize for failures, celebrate successes
"""

from typing import Dict, Any, List, Optional
from groq import Groq


class ResponseGenerator:
    """Generates natural responses based on action results."""

    RESPONSE_PROMPT = """You are responding to the user. Be warm, concise, and HONEST.

USER MESSAGE: "{user_message}"

CONVERSATION CONTEXT:
{conversation_context}

WHAT YOU KNOW ABOUT THEM:
{memories}

ACTION RESULTS:
{action_results}

RULES:
1. If actions SUCCEEDED, acknowledge briefly and naturally
2. If actions FAILED, apologize and explain what went wrong
3. If AWAITING CONFIRMATION, ask clearly and wait for response
4. Match their energy (casual = casual, urgent = focused)
5. Keep to 1-3 sentences unless they asked for detail

NEVER:
- Say "Done!" if an action failed
- Hallucinate success when action_results shows failure
- Start every response with "I"
- Add unnecessary follow-up questions
- Use emojis

Generate your response (plain text, no JSON):"""

    CHAT_PROMPT = """You are a helpful personal assistant having a conversation.

USER MESSAGE: "{user_message}"

RECENT CONVERSATION:
{conversation_context}

WHAT YOU KNOW ABOUT THEM:
{memories}

Be warm, concise, and helpful. Keep responses to 1-3 sentences for casual chat.
Match their energy. Don't be overly formal or robotic.
Don't add unnecessary follow-up questions.
Don't use emojis.

Respond naturally:"""

    def __init__(self, groq_api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.client = Groq(api_key=groq_api_key)
        self.model = model

    async def generate_response(
        self,
        user_message: str,
        action_results: Dict[str, Any],
        context: Dict[str, Any],
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """
        Generate a response after action execution.

        Args:
            user_message: The original user message
            action_results: Results from action execution
            context: Context from Stage 2
            conversation_history: Recent conversation

        Returns:
            Natural language response string
        """
        # Format context
        formatted_history = self._format_history(conversation_history[-5:])
        formatted_memories = self._format_memories(context.get("memories", []))
        formatted_results = self._format_action_results(action_results)

        prompt = self.RESPONSE_PROMPT.format(
            user_message=user_message,
            conversation_context=formatted_history or "(No recent conversation)",
            memories=formatted_memories or "(No personal info)",
            action_results=formatted_results
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.7
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"[ResponseGenerator] Error: {e}")
            # Fallback based on action success
            if action_results.get("success", False):
                return "Done."
            else:
                return "Sorry, something went wrong. Please try again."

    async def generate_chat_response(
        self,
        user_message: str,
        context: Dict[str, Any],
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """
        Generate a response for pure chat (no actions).

        Args:
            user_message: The user message
            context: Context from Stage 2
            conversation_history: Recent conversation

        Returns:
            Natural language response string
        """
        formatted_history = self._format_history(conversation_history[-5:])
        formatted_memories = self._format_memories(context.get("memories", []))

        prompt = self.CHAT_PROMPT.format(
            user_message=user_message,
            conversation_context=formatted_history or "(No recent conversation)",
            memories=formatted_memories or "(No personal info)"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.8
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"[ResponseGenerator] Chat error: {e}")
            return "Hey! How can I help you today?"

    async def generate_confirmation_prompt(
        self,
        action_plan: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """
        Generate a confirmation prompt for high-stakes actions.

        Args:
            action_plan: The planned action requiring confirmation
            context: Context for additional details

        Returns:
            Confirmation question string
        """
        # Use the LLM-generated confirmation message if available
        if action_plan.get("confirmation_message"):
            return action_plan["confirmation_message"]

        # Otherwise, generate based on action type
        actions = action_plan.get("actions", [])
        if not actions:
            return "I'm not sure what you'd like me to do. Could you clarify?"

        action = actions[0]  # Primary action
        domain = action.get("domain")
        action_name = action.get("action")
        params = action.get("params", {})

        # Generate confirmation based on action type
        if domain == "email":
            if action_name == "send_email":
                to = params.get("to", "someone")
                subject = params.get("subject", "your message")
                return f"Should I send this email to {to} about '{subject}'?"
            elif action_name == "reply_to_email":
                sender = params.get("sender_name", "them")
                return f"Should I send this reply to {sender}?"

        elif domain == "calendar":
            if action_name == "delete_event":
                find_by = params.get("find_by", "this event")
                return f"Should I delete '{find_by}' from your calendar?"
            elif action_name == "update_event":
                find_by = params.get("find_by", "this event")
                return f"Should I update '{find_by}'?"

        elif domain == "task":
            if action_name == "delete":
                find_by = params.get("find_by", "this task")
                return f"Should I delete the task '{find_by}'?"

        # Generic fallback
        return f"Should I proceed with this {domain} action?"

    async def generate_clarification_response(
        self,
        clarification_question: str
    ) -> str:
        """Generate a response asking for clarification."""
        if clarification_question:
            return clarification_question
        return "I'm not sure I understand. Could you give me more details?"

    def _format_history(self, messages: List[Dict]) -> str:
        """Format conversation history for the prompt."""
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = "User" if msg.get("message_type") == "user" else "Assistant"
            content = str(msg.get("content", ""))[:200]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _format_memories(self, memories: List[Dict]) -> str:
        """Format memories for the prompt."""
        if not memories:
            return ""

        lines = []
        for mem in memories[:3]:  # Limit to 3 most relevant
            lines.append(f"- {mem.get('key', 'unknown')}: {mem.get('value', '')}")

        return "\n".join(lines)

    def _format_action_results(self, results: Dict[str, Any]) -> str:
        """Format action results for honest acknowledgment."""
        if not results or not results.get("actions"):
            return "(No actions taken)"

        lines = []
        overall_success = results.get("success", True)

        for action_result in results.get("actions", []):
            domain = action_result.get("domain", "unknown")
            action = action_result.get("action", "unknown")
            success = action_result.get("success", False)
            error = action_result.get("error")
            result_data = action_result.get("result", {})

            if success:
                # Format success message based on action type
                if domain == "email" and action == "create_draft":
                    to = result_data.get("to", "recipient")
                    lines.append(f"SUCCESS: Email draft created for {to}")
                elif domain == "task" and action == "create":
                    title = result_data.get("title", "task")
                    lines.append(f"SUCCESS: Task '{title}' created")
                elif domain == "calendar" and action == "create_event":
                    summary = result_data.get("summary", "event")
                    lines.append(f"SUCCESS: Calendar event '{summary}' created")
                else:
                    lines.append(f"SUCCESS: {domain}.{action} completed")
            else:
                lines.append(f"FAILED: {domain}.{action} - {error or 'Unknown error'}")

        summary = "All actions succeeded." if overall_success else "Some actions failed."
        return f"{summary}\n" + "\n".join(lines)


# Quick test
if __name__ == "__main__":
    import asyncio
    import os
    from dotenv import load_dotenv

    load_dotenv()

    generator = ResponseGenerator(os.getenv("GROQ_API_KEY"))

    async def test():
        # Test chat response
        chat_response = await generator.generate_chat_response(
            "Hey, how's it going?",
            {"memories": []},
            []
        )
        print(f"Chat: {chat_response}")
        print()

        # Test action response
        action_response = await generator.generate_response(
            "Remind me to call mom tomorrow",
            {
                "success": True,
                "actions": [
                    {
                        "domain": "task",
                        "action": "create",
                        "success": True,
                        "result": {"title": "Call mom"},
                        "error": None
                    }
                ]
            },
            {"memories": []},
            []
        )
        print(f"Action: {action_response}")

    asyncio.run(test())
