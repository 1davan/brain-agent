from groq import Groq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.tools import tool
from langchain_groq import ChatGroq
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta

class AIService:
    def _extract_json_from_response(self, text: str) -> Dict[str, Any]:
        """Extract JSON object from LLM response that may contain prose before/after JSON."""
        import re

        # First, try to parse the entire text as JSON (cleanest case)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Find the first { and try to extract complete JSON from there
        start_idx = text.find('{')
        if start_idx != -1:
            # Track brace depth to find matching closing brace
            depth = 0
            in_string = False
            escape_next = False

            for i, char in enumerate(text[start_idx:], start_idx):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue

                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = text[start_idx:i+1]
                        try:
                            result = json.loads(json_str)
                            print(f"[DEBUG] Successfully parsed JSON with {len(result.get('task_actions', []))} task_actions")
                            return result
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] JSON parse error: {e}")
                            break

        # If no valid JSON found, construct a fallback response
        clean_text = re.sub(r'\{[^}]*$', '', text).strip()
        clean_text = re.sub(r'^[^{]*\}', '', clean_text).strip()

        return {
            "intent": "general_chat",
            "followup_context": None,
            "needs_end_date": False,
            "memory_actions": [],
            "task_actions": [],
            "calendar_actions": [],
            "email_actions": [],
            "response": clean_text if clean_text else "I received your message but I'm not sure how to help. Could you give me more details?",
            "should_end_conversation": False
        }

    # Default email writing style - can be overridden via Config sheet
    DEFAULT_EMAIL_STYLE = """Write professional but warm emails with proper formatting:
- Use paragraphs separated by blank lines for readability
- Start with a greeting (Hi [Name],)
- Keep paragraphs short (2-3 sentences max)
- End with a clear call-to-action or next step
- Always include a sign-off (Best regards, Kind regards, Cheers, etc.)
- Be genuine and conversational, not corporate or robotic
- Match the tone to the relationship (more casual for colleagues, more formal for new contacts)"""

    def __init__(self, groq_api_key: str, model: str = "llama-3.3-70b-versatile", email_style: str = None):
        """
        Initialize Groq AI service.

        Groq model recommendations:
        - llama-3.3-70b-versatile (best for complex reasoning, recommended)
        - llama-3.1-8b-instant (faster, good for simple tasks)
        - mixtral-8x7b-32768 (good balance, large context)
        """
        self.client = Groq(api_key=groq_api_key)
        self.model = model
        self.email_style = email_style or self.DEFAULT_EMAIL_STYLE

        # LangChain integration for structured outputs - optimized for token limits
        self.llm = ChatGroq(
            groq_api_key=groq_api_key,
            model_name=model,
            temperature=0.3,
            max_tokens=1500,  # Reduced to stay within Groq free tier limits
        )

        # Initialize tool-enabled LLM for advanced reasoning
        self.tools = [self.parse_date_tool, self.calculate_priority_tool, self.analyze_urgency_tool]
        # Note: Full tool calling would require langchain agent setup, keeping simple for now

    @tool
    def parse_date_tool(self, date_string: str) -> str:
        """Parse natural language date strings into ISO format dates.

        Args:
            date_string: Natural language date like "tomorrow", "next week", "January 15th"

        Returns:
            ISO format date string or error message
        """
        try:
            # This would contain actual date parsing logic
            # For now, return a placeholder
            return f"Parsed date from: {date_string}"
        except Exception as e:
            return f"Could not parse date: {e}"

    @tool
    def calculate_priority_tool(self, title: str, description: str, deadline: str = None) -> str:
        """Calculate task priority based on content analysis.

        Args:
            title: Task title
            description: Task description
            deadline: Optional deadline information

        Returns:
            Priority level: high/medium/low
        """
        # Simple priority logic - would be enhanced with AI analysis
        title_lower = title.lower()
        desc_lower = description.lower() if description else ""

        high_keywords = ['urgent', 'critical', 'asap', 'emergency', 'deadline', 'important']
        if any(keyword in title_lower or keyword in desc_lower for keyword in high_keywords):
            return "high"

        medium_keywords = ['soon', 'week', 'meeting', 'project', 'review']
        if any(keyword in title_lower or keyword in desc_lower for keyword in medium_keywords):
            return "medium"

        return "low"

    @tool
    def analyze_urgency_tool(self, text: str) -> Dict[str, Any]:
        """Analyze text for urgency indicators and time sensitivity.

        Args:
            text: Text to analyze for urgency

        Returns:
            Dictionary with urgency analysis
        """
        # Simple urgency analysis
        text_lower = text.lower()
        urgent_indicators = ['urgent', 'asap', 'immediately', 'right away', 'emergency', 'critical']
        time_indicators = ['today', 'tomorrow', 'this week', 'deadline', 'due']

        urgency_score = 0
        if any(word in text_lower for word in urgent_indicators):
            urgency_score += 3
        if any(word in text_lower for word in time_indicators):
            urgency_score += 2

        return {
            "urgency_score": urgency_score,
            "is_urgent": urgency_score >= 3,
            "time_sensitive": any(word in text_lower for word in time_indicators)
        }

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embeddings using Groq (if supported) or fallback"""
        # Note: Groq doesn't have embedding models yet, so we'll use sentence-transformers
        # This is handled in VectorProcessor
        raise NotImplementedError("Use VectorProcessor for embeddings")

    async def reason_and_act(self, context: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Main reasoning function for agent behavior - optimized for token limits"""
        prompt = ChatPromptTemplate.from_template("""You are a smart, proactive assistant who helps the user think through problems and get things done. Act like a helpful colleague, not a task tracker.

CONTEXT:
Memories: {memories}
Tasks: {tasks}
Calendar: {calendar_events}
Recent conversation:
{conversations}

USER: "{user_input}"

MULTI-TURN CONVERSATION AWARENESS:
Look at the "Recent conversation" above. If the user's message seems like a follow-up to a previous discussion:
- Continue the discussion naturally without starting fresh
- Reference what was discussed before
- Don't treat short responses like "yes", "that one", "the first option", "tell me more" as new requests
- If user says "what about X?" after discussing tasks, they're asking about X in context of that discussion
- Keep the conversational thread going - you're having a dialogue, not answering isolated questions

TASK DISCUSSIONS:
When user wants to discuss their tasks, priorities, or workload:
- Look at ALL the Tasks in context above - you have their full task list
- Help them think through prioritization, sequencing, and strategy
- Ask clarifying questions: "What outcome are you trying to achieve?" "What's the deadline pressure?"
- Suggest which tasks to tackle first based on urgency, dependencies, and impact
- Offer to help break down overwhelming tasks into smaller steps
- Be a thinking partner, not just a task reporter

CALENDAR QUERIES:
When the user asks about their calendar, schedule, or events (today, tomorrow, this week, etc.):
- ALWAYS look at the Calendar context above first
- If Calendar shows events, list them with times in your response
- If Calendar is empty or [], say "You have no events scheduled for [time period]"
- For "tomorrow" questions, look for events with tomorrow's date in the Calendar data
- Use calendar_actions to fetch events if needed: {{"action": "list_events", "days_ahead": 1}}

CRITICAL BEHAVIOR FOR HELP REQUESTS:
When user asks "help me with X" or "what should I do" or "how do I approach this":
- Give SPECIFIC, ACTIONABLE steps (not vague like "identify the stakeholders")
- Break the task into 3-5 concrete steps with examples
- Suggest tools, templates, or approaches they could use
- Ask ONE targeted question if you need clarification
- DON'T just restate what they told you

CAPABILITIES:
- Help think through problems (primary!)
- Store memories about the user
- Create/update tasks
- View/create calendar events
- Create email drafts to contacts
- Manage Google Keep notes

TASK ACTIONS (CRITICAL - always include when user asks for reminders/tasks):
When user says "remind me", "add a task", "I need to", or describes something to do:
- CREATE: {{"action": "create", "data": {{"title": "Task title", "description": "details", "priority": "high", "deadline": "2026-01-10T18:00:00"}}}}
- UPDATE: {{"action": "update", "find_by": "task title keywords", "data": {{"status": "complete"}}}}
- COMPLETE: {{"action": "complete", "find_by": "task title keywords"}}

IMPORTANT - TIMED REMINDERS: When user says "remind me at [TIME]" or specifies a time:
- You MUST create BOTH a task AND a calendar event
- Add to task_actions: {{"action": "create", "data": {{"title": "...", "deadline": "TIME"}}}}
- ALSO add to calendar_actions: {{"action": "create_event", "summary": "...", "start_time": "TIME", "end_time": null}}
- Do NOT claim you created a calendar event unless you actually include it in calendar_actions

IMPORTANT: Use ISO format for deadlines (YYYY-MM-DDTHH:MM:SS).
Today is {current_date} ({current_day_of_week}).
- "this evening at 6" = today at 18:00
- "tomorrow" = {tomorrow_date}
- For weekday names, calculate the NEXT occurrence:
  - If today is {current_day_of_week} and user says "Friday", find the next Friday
  - DOUBLE-CHECK your date calculation - off-by-one errors are common

MEMORY ACTIONS (IMPORTANT - store facts about the user for future reference):
When user mentions personal details, preferences, life events, or context you should remember:
- STORE: {{"action": "store", "category": "personal|work|knowledge", "key": "descriptive_key", "value": "the information"}}

ALWAYS store memories when user mentions:
- Life events: property sales, moving, jobs, relationships, health
- Preferences: work style, communication preferences, schedules
- Context: projects they're working on, people in their life, goals
- Deadlines: important dates, settlements, appointments

Examples:
- User says "I'm selling my property" -> store: {{"action": "store", "category": "personal", "key": "property_sale_2026", "value": "User is selling a property, settlement Monday Jan 13"}}
- User says "I prefer morning meetings" -> store: {{"action": "store", "category": "work", "key": "meeting_preference", "value": "Prefers morning meetings"}}

USE EXISTING MEMORIES in your responses - look at the Memories context above and reference relevant info naturally.

CALENDAR ACTIONS:
- CREATE EVENT: {{"action": "create_event", "summary": "Event name", "start_time": "2026-01-10T18:00:00", "end_time": "2026-01-10T19:00:00"}}
- LIST EVENTS: {{"action": "list_events", "days_ahead": 7}}

EMAIL CAPABILITIES:
You can create email drafts, reply to emails, and manage contacts.

NEW EMAIL DRAFT (to someone in contacts or by email address):
- {{"action": "create_draft", "to": "name or email", "subject": "...", "body": "..."}}

REPLY TO EXISTING EMAIL (searches inbox for sender, creates threaded reply):
- {{"action": "reply_to_email", "sender_name": "John", "body": "your reply message..."}}
- Use this when user says "reply to [name]'s email" or "draft a reply to [name]"
- The system will find their most recent email and create a properly threaded reply draft

VIEW RECENT EMAILS:
- {{"action": "get_recent_emails", "max_results": 10}}

CONTACTS:
- Add: {{"action": "add_contact", "name": "John", "email": "john@example.com"}}
- List: {{"action": "list_contacts"}}
- List drafts: {{"action": "list_drafts"}}

GOOGLE KEEP NOTES:
You can view, search, and add to Google Keep notes.

LIST NOTES:
- {{"action": "list_notes", "max_results": 10}}

SEARCH NOTES (find by title or content):
- {{"action": "search_notes", "query": "modia health"}}

ADD TO EXISTING NOTE (finds note by title, adds text at top with timestamp):
- {{"action": "add_to_note", "note_title": "Modia Health To-Do", "text": "Create new website for courses"}}
- Use this when user says "add to my [note name] note" or "add a note to [title]"
- After adding, ask if they want to add more details

VIEW NOTE CONTENT:
- {{"action": "get_note", "note_title": "Shopping List"}}

CREATE NEW NOTE:
- {{"action": "create_note", "title": "New Note Title", "text": "Note content", "pinned": false}}

EMAIL WRITING STYLE (use this voice for all email drafts):
{email_style}

MEMORY CATEGORIES: personal | work | knowledge
TASK PRIORITY: high (<24h) | medium (this week) | low (no deadline)
RECURRING: format "weekly_saturday_1630" - ask for end date if not given

IMPORTANT: Output ONLY a valid JSON object. No text before or after the JSON. Start with {{ and end with }}.

OUTPUT FORMAT (respond with this exact structure):
{{
  "intent": "help_request|task_creation|task_update|memory_storage|calendar_request|email_request|keep_request|info_request|general_chat|followup_answer",
  "followup_context": null,
  "needs_end_date": false,
  "memory_actions": [],
  "task_actions": [],
  "calendar_actions": [],
  "email_actions": [],
  "keep_actions": [],
  "response": "your helpful, specific response here",
  "should_end_conversation": false
}}

BE HELPFUL. Don't just acknowledge - actually help solve the problem. Remember: OUTPUT ONLY JSON, nothing else.""")

        try:
            # Don't use JsonOutputParser - it fails when LLM outputs text before JSON
            # Instead, get raw output and extract JSON ourselves
            chain = prompt | self.llm

            calendar_data = json.dumps(context.get('calendar_events', []), default=str)
            print(f"[DEBUG AI] Calendar events being sent to LLM: {calendar_data}")

            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            raw_result = await chain.ainvoke({
                "memories": json.dumps(context.get('memories', []), default=str),
                "tasks": json.dumps(context.get('tasks', []), default=str),
                "calendar_events": calendar_data,
                "conversations": json.dumps(context.get('conversations', []), default=str),
                "user_input": user_input,
                "current_date": now.strftime("%Y-%m-%d"),
                "current_day_of_week": now.strftime("%A"),
                "tomorrow_date": tomorrow.strftime("%Y-%m-%d (%A)"),
                "email_style": self.email_style
            })

            # Extract content from AIMessage
            raw_text = raw_result.content if hasattr(raw_result, 'content') else str(raw_result)
            print(f"[DEBUG AI] Raw LLM response (first 500 chars): {raw_text[:500]}")

            # Extract JSON from the response (LLM sometimes outputs text before JSON)
            result = self._extract_json_from_response(raw_text)
            print(f"[DEBUG AI] Extracted response: {result.get('response', '')[:200]}")
            return result
        except Exception as e:
            print(f"Error in AI reasoning: {e}")
            import traceback
            traceback.print_exc()
            
            # Try a simpler fallback - direct chat without JSON parsing
            try:
                simple_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant. Give a brief, helpful response."},
                        {"role": "user", "content": user_input}
                    ],
                    max_tokens=300,
                    temperature=0.7
                )
                fallback_text = simple_response.choices[0].message.content.strip()
                return {
                    "intent": "general_chat",
                    "followup_context": None,
                    "needs_end_date": False,
                    "memory_actions": [],
                    "task_actions": [],
                    "response": fallback_text,
                    "should_end_conversation": False
                }
            except Exception as e2:
                print(f"Fallback also failed: {e2}")
                return {
                    "intent": "general_chat",
                    "followup_context": None,
                    "needs_end_date": False,
                    "memory_actions": [],
                    "task_actions": [],
                    "response": "I'm having trouble processing that. Could you try rephrasing your request?",
                    "should_end_conversation": False
                }

    async def merge_memories(self, existing_value: str, new_value: str) -> str:
        """Use AI to intelligently merge memories"""
        prompt = f"""
        Merge these two related memories into one coherent piece:

        Existing: {existing_value}
        New: {new_value}

        Provide only the merged result, keeping the most current and accurate information:
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error merging memories: {e}")
            return f"{existing_value} (Updated: {new_value})"

    async def determine_task_priority(self, title: str, description: str, deadline: str = None) -> str:
        """Use AI to determine task priority"""
        prompt = f"""
        Analyze this task and determine its priority (high/medium/low):

        Title: {title}
        Description: {description or 'No description'}
        Deadline: {deadline or 'No deadline'}

        Consider:
        - Urgency based on deadline proximity
        - Importance based on keywords (work, personal, health, etc.)
        - Business impact

        Return only: high, medium, or low
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1
            )
            priority = response.choices[0].message.content.strip().lower()
            return priority if priority in ['high', 'medium', 'low'] else 'medium'
        except Exception as e:
            print(f"Error determining priority: {e}")
            return 'medium'

    async def detect_conversation_state(self, conversation_history: List[Dict]) -> str:
        """Determine current conversation state"""
        if not conversation_history:
            return "init"

        history_text = "\n".join([
            f"{'User' if msg.get('message_type') == 'user' else 'Assistant'}: {msg.get('content', '')}"
            for msg in conversation_history[-10:]
        ])

        prompt = f"""
        Analyze this conversation and determine the current state:

        {history_text}

        States: init, questioning, executing, completing, waiting

        Return only the state name:
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1
            )
            state = response.choices[0].message.content.strip().lower()
            return state if state in ['init', 'questioning', 'executing', 'completing', 'waiting'] else 'init'
        except Exception as e:
            print(f"Error detecting conversation state: {e}")
            return 'init'