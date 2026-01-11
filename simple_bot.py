#!/usr/bin/env python3
"""
Simple synchronous Telegram bot using requests - no asyncio issues
Clean architecture with proper message deduplication
Includes proactive features with Brisbane timezone
"""

import time
import requests
import json
import os
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz

load_dotenv()

# Brisbane timezone
BRISBANE_TZ = pytz.timezone('Australia/Brisbane')

class SimpleTelegramBot:
    def __init__(self):
        """Initialize the bot with all components and deduplication"""
        self.token = os.getenv('TELEGRAM_TOKEN')
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

        # Message deduplication to prevent multiple responses
        self.processed_messages = set()
        self.max_processed_cache = 1000

        # Rate limiting - prevent too many requests
        self.last_response_time = {}
        self.min_response_interval = 2  # Minimum 2 seconds between responses

        # Proactive features
        self.known_users = set()  # Track users we've interacted with
        self.last_daily_summary = {}  # Track when daily summaries were sent
        self.last_proactive_check = datetime.now(BRISBANE_TZ)
        self.last_task_checkin = {}  # Track when task check-ins were sent per user

        # Task discussion sessions (for 5-min timeout)
        self.task_discussion_sessions = {}  # user_id -> {'task_id': str, 'started_at': datetime}

        # Initialize bot components
        self.initialize_components()

    def initialize_components(self):
        """Initialize bot components synchronously"""
        print("=" * 60)
        print("BRAIN AGENT BOT - Starting up...")
        print("=" * 60)

        try:
            from app.database.sheets_client import SheetsClient
            from app.services.ai_service import AIService
            from app.agents.conversation_agent import ConversationAgent
            from app.agents.memory_agent import MemoryAgent
            from app.agents.task_agent import TaskAgent
            from app.utils.vector_processor import VectorProcessor
            from app.config import Settings

            self.config = Settings()

            print("[1/5] Connecting to Google Sheets...")
            self.sheets_client = SheetsClient(
                credentials_path=self.config.google_sheets_credentials,
                spreadsheet_id=self.config.spreadsheet_id
            )
            print("      SUCCESS: Google Sheets connected")

            print("[2/5] Initializing AI Service (llama-3.3-70b-versatile)...")
            self.ai_service = AIService(
                groq_api_key=self.config.groq_api_key,
                model=self.config.groq_model
            )
            print("      SUCCESS: AI service initialized")

            print("[3/5] Initializing Vector Processor...")
            self.vector_processor = VectorProcessor(model_name=self.config.embedding_model)
            print("      SUCCESS: Vector processor ready")

            print("[4/5] Initializing Memory Agent...")
            self.memory_agent = MemoryAgent(
                self.sheets_client,
                self.vector_processor,
                self.ai_service
            )
            print("      SUCCESS: Memory agent ready")

            print("[5/5] Initializing Task and Conversation Agents...")
            self.task_agent = TaskAgent(self.sheets_client, None, self.ai_service)
            
            # Initialize Calendar Service (optional - may fail if not configured)
            self.calendar_service = None
            try:
                from app.services.calendar_service import CalendarService
                self.calendar_service = CalendarService(
                    credentials_path=self.config.google_sheets_credentials,
                    calendar_id=self.config.google_calendar_id
                )
                print("      SUCCESS: Calendar service initialized")
            except Exception as e:
                print(f"      WARNING: Calendar service not available: {e}")
                print("      (To enable: Enable Calendar API and share calendar with service account)")

            # Initialize Email Service (optional)
            self.email_service = None
            try:
                from app.services.email_service import EmailService
                self.email_service = EmailService(sheets_client=self.sheets_client)
                if self.email_service.gmail_address:
                    print("      SUCCESS: Email service initialized")
                else:
                    self.email_service = None
            except Exception as e:
                print(f"      WARNING: Email service not available: {e}")

            # Initialize Google Keep Service (optional)
            self.keep_service = None
            try:
                from app.services.keep_service import KeepService
                self.keep_service = KeepService()
                if self.keep_service.authenticated:
                    print("      SUCCESS: Keep service initialized")
                else:
                    self.keep_service = None
                    print("      WARNING: Keep service not authenticated (add GOOGLE_KEEP_TOKEN to .env)")
            except Exception as e:
                print(f"      WARNING: Keep service not available: {e}")

            self.conversation_agent = ConversationAgent(
                self.ai_service,
                self.memory_agent,
                self.task_agent,
                self.vector_processor,  # Enable semantic search for context compression
                self.calendar_service,  # Enable calendar integration
                self.email_service,     # Enable email drafts
                self.keep_service       # Enable Google Keep notes
            )
            print("      SUCCESS: All agents initialized (semantic search enabled)")

            # Load known users from persistent storage
            print("[+] Loading known users from database...")
            self._load_known_users()
            print(f"      Loaded {len(self.known_users)} known user(s)")

            print("=" * 60)
            print("BOT READY - All systems operational")
            print("=" * 60)

        except Exception as e:
            print(f"FATAL ERROR: Failed to initialize components: {e}")
            import traceback
            traceback.print_exc()
            raise

    def get_updates(self):
        """Get updates from Telegram API"""
        try:
            params = {'offset': self.offset, 'timeout': 30}
            response = requests.get(
                f"{self.api_url}/getUpdates",
                params=params,
                timeout=35
            )
            return response.json()
        except requests.exceptions.Timeout:
            return None  # Normal timeout, not an error
        except Exception as e:
            print(f"Error getting updates: {e}")
            return None

    def send_message(self, chat_id, text):
        """Send message to Telegram"""
        try:
            # Truncate very long messages
            if len(text) > 4000:
                text = text[:3997] + "..."

            data = {'chat_id': chat_id, 'text': text}
            response = requests.post(
                f"{self.api_url}/sendMessage",
                data=data,
                timeout=10
            )
            result = response.json()
            if result.get('ok'):
                print(f"[TELEGRAM] Message sent successfully to {chat_id}")
            else:
                print(f"[TELEGRAM] Failed to send: {result}")
            return result
        except Exception as e:
            print(f"Error sending message: {e}")
            return None
            return None

    def should_process_message(self, message):
        """Check if message should be processed (deduplication + rate limiting)"""
        message_id = message.get('message_id')
        chat_id = message['chat']['id']
        current_time = time.time()

        # Skip if already processed
        if message_id in self.processed_messages:
            return False

        # Rate limiting per chat
        last_time = self.last_response_time.get(chat_id, 0)
        if current_time - last_time < self.min_response_interval:
            print(f"Rate limiting: Skipping message {message_id} (too soon)")
            return False

        return True

    def mark_message_processed(self, message):
        """Mark a message as processed"""
        message_id = message.get('message_id')
        chat_id = message['chat']['id']

        self.processed_messages.add(message_id)
        self.last_response_time[chat_id] = time.time()

        # Clean up old message IDs to prevent memory issues
        if len(self.processed_messages) > self.max_processed_cache:
            oldest = list(self.processed_messages)[:self.max_processed_cache // 2]
            for msg_id in oldest:
                self.processed_messages.discard(msg_id)

    def process_message(self, message):
        """Process a single message with proper deduplication"""
        # Check if we should process this message
        if not self.should_process_message(message):
            return

        # Mark as processed IMMEDIATELY to prevent race conditions
        self.mark_message_processed(message)

        try:
            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']
            text = message.get('text', '')
            username = message['from'].get('username', 'unknown')
            first_name = message['from'].get('first_name', 'there')

            print(f"\n{'='*50}")
            print(f"MESSAGE from @{username} ({user_id}):")
            print(f"  \"{text}\"")
            print(f"{'='*50}")

            # Handle commands
            if text.startswith('/'):
                response = self._handle_command(text, user_id, first_name)
                if response:
                    self.send_message(chat_id, response)
                    return

            # Check for active task discussion session and handle quick progress updates
            if user_id in self.task_discussion_sessions:
                session = self.task_discussion_sessions[user_id]
                task_id = session.get('task_id')
                task_title = session.get('task_title')

                # Extend session timeout on activity
                session['started_at'] = datetime.now(BRISBANE_TZ)

                # Check for quick progress responses
                text_lower = text.lower().strip()
                progress_response = self._handle_quick_progress_update(user_id, task_id, task_title, text_lower)
                if progress_response:
                    self.send_message(chat_id, progress_response)
                    return

            # Load user context
            context = self._load_user_context(user_id)
            print(f"Context loaded: {len(context.get('memories', []))} memories, {len(context.get('tasks', []))} tasks")

            # Process through AI conversation agent
            response = self._process_with_ai(user_id, text, context)

            # Send single response - ensure we only have one response
            print(f"[DEBUG BOT] Raw response length: {len(response)}")
            print(f"[DEBUG BOT] RESPONSE: {response[:200]}..." if len(response) > 200 else f"[DEBUG BOT] RESPONSE: {response}")
            self.send_message(chat_id, response)

            # Store conversation history
            self._store_conversation(user_id, "user", text)
            self._store_conversation(user_id, "assistant", response)

        except Exception as e:
            print(f"ERROR processing message: {e}")
            import traceback
            traceback.print_exc()
            try:
                self.send_message(message['chat']['id'], "Sorry, I encountered an error. Please try again.")
            except:
                pass

    def _handle_command(self, text: str, user_id: str, first_name: str) -> str:
        """Handle bot commands"""
        command = text.split()[0].lower()

        if command == '/start':
            return f"""Hello {first_name}! I'm your Brain Agent - an AI assistant with memory and task management.

CAPABILITIES:
- Remember important information about you
- Help manage your tasks and priorities
- Answer questions based on our conversation history
- View and create calendar events

COMMANDS:
- /tasks - View your current tasks
- /memories - See what I remember about you
- /calendar - View upcoming calendar events
- /status - Check system status
- /help - Show this help message

Just chat with me naturally - I'll understand what you need!"""

        elif command == '/help':
            return """BRAIN AGENT HELP

COMMANDS:
- /start - Welcome message
- /help - Show this help
- /status - Check system status
- /tasks - View and manage your tasks
- /memories - View stored memories
- /calendar - View upcoming events
- /check archives <term> - Search archived tasks
- /new session - End current task discussion

PROACTIVE FEATURES:
- I'll check in on your tasks 3x daily (10am, 2pm, 6pm)
- Quick replies: "50%", "done", "blocked", "skip"
- Tasks auto-archive 7 days after completion

HOW I WORK:
- I remember everything you tell me
- I can create and manage tasks for you
- I track your progress on tasks
- I learn from our conversations

EXAMPLES:
- "Remind me to buy groceries tomorrow"
- "What's in my calendar this week?"
- "I prefer meetings in the morning"
- "Mark the laundry task as complete"
- "/check archives meeting" - find old meeting tasks

Just chat naturally!"""

        elif command == '/status':
            try:
                context = self._load_user_context(user_id)
                memories_count = len(context.get('memories', []))
                tasks_count = len([t for t in context.get('tasks', []) if t.get('status') == 'pending'])
                calendar_status = "Connected" if self.calendar_service else "Not configured"

                return f"""BRAIN AGENT STATUS: Online

YOUR DATA:
- Memories stored: {memories_count}
- Active tasks: {tasks_count}

SYSTEM HEALTH:
- AI Service: Connected (Groq)
- Memory System: Active
- Google Sheets: Connected
- Calendar: {calendar_status}

Ready to assist you!"""
            except Exception as e:
                return f"Status check failed: {str(e)}"

        elif command == '/tasks':
            try:
                tasks = self._get_user_tasks_sync(user_id)
                pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []

                if not pending:
                    return "You don't have any active tasks. Try creating one by saying something like 'Remind me to buy groceries tomorrow'!"

                task_list = "YOUR TASKS:\n\n"
                priority_icons = {"high": "[!]", "medium": "[-]", "low": "[ ]"}

                for i, task in enumerate(pending[:10], 1):
                    icon = priority_icons.get(task.get('priority', 'medium'), "[-]")
                    deadline = task.get('deadline', '')
                    if deadline:
                        try:
                            dt = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                            deadline = dt.strftime("%Y-%m-%d %H:%M")
                        except:
                            pass

                    task_list += f"{i}. {icon} {task.get('title', 'Untitled')}\n"
                    if deadline:
                        task_list += f"   Due: {deadline}\n"

                return task_list
            except Exception as e:
                return f"Error loading tasks: {str(e)}"

        elif command == '/memories':
            try:
                context = self._load_user_context(user_id)
                memories = context.get('memories', [])

                if not memories:
                    return "I don't have any memories stored for you yet. Tell me something about yourself and I'll remember it!"

                memory_list = "WHAT I REMEMBER ABOUT YOU:\n\n"
                for i, mem in enumerate(memories[:10], 1):
                    category = mem.get('category', 'general')
                    key = mem.get('key', 'unknown')
                    value = str(mem.get('value', ''))[:150]

                    memory_list += f"{i}. [{category}] {key}\n"
                    memory_list += f"   {value}"
                    if len(str(mem.get('value', ''))) > 150:
                        memory_list += "..."
                    memory_list += "\n\n"

                return memory_list
            except Exception as e:
                return f"Error loading memories: {str(e)}"

        elif command == '/calendar':
            if not self.calendar_service:
                return "Calendar not configured. Enable Google Calendar API and share your calendar with the service account."

            try:
                events = self._get_upcoming_events_sync(days=7)
                if not events:
                    return "No upcoming events in the next 7 days."

                event_list = "UPCOMING CALENDAR EVENTS:\n\n"
                for event in events[:10]:
                    start_str = event.get('start', '')
                    try:
                        if 'T' in start_str:
                            dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                            time_str = dt.strftime('%a %b %d at %I:%M%p')
                        else:
                            time_str = f"All day on {start_str}"
                    except:
                        time_str = start_str

                    event_list += f"- {event.get('summary', 'Untitled')}\n"
                    event_list += f"  {time_str}\n"
                    if event.get('location'):
                        event_list += f"  @ {event.get('location')}\n"
                    event_list += "\n"

                return event_list
            except Exception as e:
                return f"Error loading calendar: {str(e)}"

        elif text.lower().startswith('/check archives') or text.lower().startswith('/archives'):
            # Search archived tasks
            parts = text.split(maxsplit=2)
            if len(parts) < 2 or (len(parts) == 2 and parts[1].lower() == 'archives'):
                return "Usage: /check archives <search term>\n\nExample: /check archives meeting"

            search_term = parts[-1] if len(parts) > 2 else parts[1]
            if search_term.lower() == 'archives':
                return "Please provide a search term.\n\nUsage: /check archives <search term>"

            try:
                archived = self._search_archives_sync(user_id, search_term)
                if not archived:
                    return f"No archived tasks found matching '{search_term}'"

                result = f"ARCHIVED TASKS matching '{search_term}':\n\n"
                for task in archived[:10]:
                    completed = task.get('completed_at', '')
                    if completed:
                        try:
                            dt = datetime.fromisoformat(completed.replace('Z', '+00:00'))
                            completed = dt.strftime('%Y-%m-%d')
                        except:
                            pass
                    result += f"- {task.get('title', 'Untitled')}\n"
                    if completed:
                        result += f"  Completed: {completed}\n"
                    if task.get('notes'):
                        notes_preview = task.get('notes', '')[:100]
                        result += f"  Notes: {notes_preview}...\n" if len(task.get('notes', '')) > 100 else f"  Notes: {notes_preview}\n"
                    result += "\n"

                return result
            except Exception as e:
                return f"Error searching archives: {str(e)}"

        elif text.lower() == '/new session' or text.lower() == '/newsession':
            # End current task discussion session
            if user_id in self.task_discussion_sessions:
                del self.task_discussion_sessions[user_id]
                return "Task discussion session ended. Ready for new requests!"
            return "No active task discussion session."

        return None  # Not a recognized command, process normally

    def _get_upcoming_events_sync(self, days: int = 7):
        """Get upcoming calendar events synchronously"""
        if not self.calendar_service:
            return []

        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def get_events():
                return await self.calendar_service.get_upcoming_events(max_results=10, days_ahead=days)
            return loop.run_until_complete(get_events())
        except Exception as e:
            print(f"Error getting upcoming events: {e}")
            return []
        finally:
            loop.close()

    def _process_with_ai(self, user_id, text, context):
        """Process message through AI agent - runs async code in sync context"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                self.conversation_agent.handle_conversation_flow(user_id, text, context)
            )
            return response
        except Exception as e:
            print(f"AI processing error: {e}")
            return "I understand. How can I help you with that?"
        finally:
            loop.close()

    def _load_user_context(self, user_id):
        """Load user context from Google Sheets"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def load():
                memories_df = await self.sheets_client.get_sheet_data("Memories", user_id)
                tasks_df = await self.sheets_client.get_sheet_data("Tasks", user_id)
                conversations_df = await self.sheets_client.get_sheet_data("Conversations", user_id)

                return {
                    "memories": memories_df.to_dict('records') if not memories_df.empty else [],
                    "tasks": tasks_df.to_dict('records') if not tasks_df.empty else [],
                    "conversations": conversations_df.tail(10).to_dict('records') if not conversations_df.empty else []
                }

            return loop.run_until_complete(load())
        except Exception as e:
            print(f"Error loading context: {e}")
            return {"memories": [], "tasks": [], "conversations": []}
        finally:
            loop.close()

    def _store_conversation(self, user_id, message_type, content):
        """Store conversation in Google Sheets"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def store():
                await self.sheets_client.append_row("Conversations", {
                    "user_id": user_id,
                    "session_id": f"session_{user_id}_{datetime.now().date()}",
                    "message_type": message_type,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "intent": "",
                    "entities": json.dumps([])
                })

            loop.run_until_complete(store())
        except Exception as e:
            print(f"Error storing conversation: {e}")
        finally:
            loop.close()

    def run(self):
        """Main bot loop with proper polling and proactive features"""
        print("\n" + "=" * 60)
        print("BOT IS RUNNING!")
        print(f"Timezone: Australia/Brisbane")
        print(f"Current time: {datetime.now(BRISBANE_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
        print("Send messages to your Telegram bot")
        print("Press Ctrl+C to stop")
        print("=" * 60 + "\n")

        # Start proactive checking thread
        proactive_thread = threading.Thread(target=self._proactive_loop, daemon=True)
        proactive_thread.start()
        print("Proactive features enabled (daily summaries, reminders)")

        while True:
            try:
                updates = self.get_updates()

                if updates and updates.get('ok') and updates.get('result'):
                    for update in updates['result']:
                        # Update offset FIRST to prevent reprocessing
                        self.offset = update['update_id'] + 1

                        if 'message' in update and 'text' in update['message']:
                            # Track known users for proactive features (persistent)
                            user_id = str(update['message']['from']['id'])
                            chat_id = update['message']['chat']['id']
                            username = update['message']['from'].get('username', '')
                            
                            # Add to in-memory set
                            if (user_id, chat_id) not in self.known_users:
                                self.known_users.add((user_id, chat_id))
                                # Save to persistent storage (new user)
                                self._save_user(user_id, chat_id, username)
                            else:
                                # Update last_active for existing user (in background)
                                threading.Thread(
                                    target=self._save_user, 
                                    args=(user_id, chat_id, username),
                                    daemon=True
                                ).start()

                            self.process_message(update['message'])

                # Small delay between polling cycles
                time.sleep(0.5)

            except KeyboardInterrupt:
                print("\nBot stopped by user")
                break
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(5)

    def _proactive_loop(self):
        """Background loop for proactive features"""
        while True:
            try:
                now = datetime.now(BRISBANE_TZ)

                # Check every 5 minutes
                time.sleep(300)

                # Daily summary at 9 AM
                if now.hour == 9 and now.minute < 5:
                    self._send_daily_summaries()

                # Proactive task check-ins 3x daily: 10 AM, 2 PM, 6 PM
                if now.hour in [10, 14, 18] and now.minute < 5:
                    self._send_task_checkins()

                # Check for upcoming deadlines
                self._check_upcoming_deadlines()

                # Handle recurring tasks - create next occurrence when completed
                self._process_recurring_tasks()

                # Auto-archive old completed tasks (check once per hour at minute 30)
                if now.minute >= 30 and now.minute < 35:
                    self._auto_archive_tasks()

                # Clean up expired task discussion sessions (5 min timeout)
                self._cleanup_expired_sessions()

            except Exception as e:
                print(f"Proactive loop error: {e}")

    def _send_daily_summaries(self):
        """Send daily task and calendar summaries to known users"""
        today = datetime.now(BRISBANE_TZ).date()

        for user_id, chat_id in self.known_users:
            # Only send once per day
            if self.last_daily_summary.get(user_id) == today:
                continue

            try:
                # Get user's tasks
                tasks = self._get_user_tasks_sync(user_id)
                pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []
                high_priority = [t for t in pending if t.get('priority') == 'high']

                # Get today's calendar events
                todays_events = self._get_todays_events_sync()

                # Only send if there's something to report
                if not pending and not todays_events:
                    continue

                message = f"Good morning! Here's your daily summary for {today.strftime('%A, %B %d')}:\n\n"

                # Calendar section
                if todays_events:
                    message += "TODAY'S CALENDAR:\n"
                    for event in todays_events[:5]:
                        start_str = event.get('start', '')
                        try:
                            if 'T' in start_str:
                                dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                                time_str = dt.strftime('%I:%M%p')
                            else:
                                time_str = "All day"
                        except:
                            time_str = start_str
                        message += f"  - {time_str}: {event.get('summary', 'Untitled')}\n"
                    message += "\n"

                # Tasks section
                if pending:
                    message += f"TASKS: {len(pending)} pending"
                    if high_priority:
                        message += f" ({len(high_priority)} high priority)"
                    message += "\n"

                    if high_priority:
                        message += "HIGH PRIORITY:\n"
                        for task in high_priority[:3]:
                            message += f"  - {task.get('title')}\n"

                message += "\nReply with 'show tasks' or 'show calendar' for details."

                self.send_message(chat_id, message)
                self.last_daily_summary[user_id] = today
                print(f"Sent daily summary to {user_id}")

            except Exception as e:
                print(f"Error sending daily summary to {user_id}: {e}")

    def _get_todays_events_sync(self):
        """Get today's calendar events synchronously"""
        if not self.calendar_service:
            return []

        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def get_events():
                today = datetime.now(BRISBANE_TZ)
                return await self.calendar_service.get_events_for_date(today)
            return loop.run_until_complete(get_events())
        except Exception as e:
            print(f"Error getting today's events: {e}")
            return []
        finally:
            loop.close()

    def _send_task_checkins(self):
        """Send proactive task check-in messages to users"""
        now = datetime.now(BRISBANE_TZ)
        today = now.date()
        current_hour = now.hour

        for user_id, chat_id in self.known_users:
            try:
                # Check if we already sent a check-in at this hour today
                last_checkin = self.last_task_checkin.get(user_id)
                if last_checkin:
                    last_date, last_hour = last_checkin
                    if last_date == today and last_hour == current_hour:
                        continue

                # Get a task to check in about
                tasks = self._get_tasks_for_checkin_sync(user_id)
                if not tasks:
                    continue

                task = tasks[0]
                title = task.get('title', 'your task')
                progress = int(task.get('progress_percent', '0') or '0')
                deadline = task.get('deadline', '')

                # Build a conversational check-in message
                greetings = [
                    f"Hey! Just checking in on '{title}'.",
                    f"Quick check-in: How's '{title}' going?",
                    f"Thinking about you! How's progress on '{title}'?",
                ]
                import random
                message = random.choice(greetings)

                if progress > 0:
                    message += f" Last I heard you were at {progress}%."
                else:
                    message += " Have you had a chance to start on it?"

                if deadline:
                    try:
                        deadline_dt = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                        days_until = (deadline_dt.date() - today).days
                        if days_until < 0:
                            message += f" (This was due {abs(days_until)} day(s) ago!)"
                        elif days_until == 0:
                            message += " (Due today!)"
                        elif days_until == 1:
                            message += " (Due tomorrow)"
                        elif days_until <= 3:
                            message += f" (Due in {days_until} days)"
                    except:
                        pass

                message += "\n\nReply with your progress (e.g., '50%', 'done', 'blocked') or '/new session' to skip."

                self.send_message(chat_id, message)
                self.last_task_checkin[user_id] = (today, current_hour)

                # Start a task discussion session
                self.task_discussion_sessions[user_id] = {
                    'task_id': task.get('task_id'),
                    'task_title': title,
                    'started_at': now
                }

                print(f"Sent task check-in to {user_id} for: {title}")

            except Exception as e:
                print(f"Error sending task check-in to {user_id}: {e}")

    def _auto_archive_tasks(self):
        """Auto-archive tasks completed more than 7 days ago"""
        for user_id, chat_id in self.known_users:
            try:
                archived_count = self._archive_old_tasks_sync(user_id)
                if archived_count > 0:
                    print(f"Auto-archived {archived_count} task(s) for user {user_id}")
            except Exception as e:
                print(f"Error auto-archiving tasks for {user_id}: {e}")

    def _cleanup_expired_sessions(self):
        """Clean up task discussion sessions that have timed out (5 minutes)"""
        now = datetime.now(BRISBANE_TZ)
        expired = []

        for user_id, session in self.task_discussion_sessions.items():
            started_at = session.get('started_at')
            if started_at:
                elapsed = (now - started_at).total_seconds()
                if elapsed > 300:  # 5 minutes
                    expired.append(user_id)

        for user_id in expired:
            del self.task_discussion_sessions[user_id]
            print(f"Expired task discussion session for {user_id}")

    def _check_upcoming_deadlines(self):
        """Check for tasks with deadlines approaching"""
        now = datetime.now(BRISBANE_TZ)

        for user_id, chat_id in self.known_users:
            try:
                tasks = self._get_user_tasks_sync(user_id)
                if not tasks:
                    continue

                for task in tasks:
                    if task.get('status') != 'pending':
                        continue

                    deadline_str = task.get('deadline')
                    if not deadline_str:
                        continue

                    try:
                        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                        if deadline.tzinfo is None:
                            deadline = BRISBANE_TZ.localize(deadline)

                        # Check if deadline is within the next hour
                        time_until = deadline - now
                        if timedelta(minutes=0) < time_until < timedelta(hours=1):
                            reminder_key = f"{user_id}_{task.get('task_id')}"
                            if reminder_key not in self.processed_messages:
                                self.processed_messages.add(reminder_key)
                                message = f"REMINDER: '{task.get('title')}' is due in less than an hour!"
                                self.send_message(chat_id, message)
                                print(f"Sent reminder to {user_id} for task: {task.get('title')}")
                    except:
                        pass

            except Exception as e:
                print(f"Error checking deadlines for {user_id}: {e}")

    def _process_recurring_tasks(self):
        """Check for completed recurring tasks and create next occurrence"""
        from dateutil import parser as date_parser
        from dateutil.relativedelta import relativedelta
        
        now = datetime.now(BRISBANE_TZ)
        
        for user_id, chat_id in self.known_users:
            try:
                tasks = self._get_user_tasks_sync(user_id)
                if not tasks:
                    continue
                
                for task in tasks:
                    # Only process completed recurring tasks
                    if task.get('status') != 'complete':
                        continue
                    if str(task.get('is_recurring', 'false')).lower() != 'true':
                        continue
                    
                    recurrence_pattern = task.get('recurrence_pattern', '')
                    recurrence_end_str = task.get('recurrence_end_date', '')
                    task_id = task.get('task_id', '')
                    
                    if not recurrence_pattern:
                        continue
                    
                    # Check if we already created next occurrence
                    processed_key = f"recurring_{task_id}"
                    if processed_key in self.processed_messages:
                        continue
                    
                    # Check end date
                    if recurrence_end_str:
                        try:
                            end_date = date_parser.parse(recurrence_end_str)
                            if end_date.tzinfo is None:
                                end_date = BRISBANE_TZ.localize(end_date)
                            if now > end_date:
                                print(f"Recurring task ended: {task.get('title')}")
                                continue
                        except:
                            pass
                    
                    # Calculate next deadline
                    next_deadline = self._calculate_next_occurrence(recurrence_pattern, now)
                    
                    if next_deadline:
                        # Check if next occurrence is before end date
                        if recurrence_end_str:
                            try:
                                end_date = date_parser.parse(recurrence_end_str)
                                if end_date.tzinfo is None:
                                    end_date = BRISBANE_TZ.localize(end_date)
                                if next_deadline > end_date:
                                    print(f"Next occurrence after end date, stopping: {task.get('title')}")
                                    continue
                            except:
                                pass
                        
                        # Create next occurrence
                        self._create_next_recurring_task(
                            user_id, task, next_deadline, recurrence_pattern, recurrence_end_str
                        )
                        self.processed_messages.add(processed_key)
                        
                        # Notify user
                        self.send_message(
                            chat_id, 
                            f"Next '{task.get('title')}' scheduled for {next_deadline.strftime('%a %b %d at %I:%M%p')}"
                        )
                        
            except Exception as e:
                print(f"Error processing recurring tasks for {user_id}: {e}")

    def _calculate_next_occurrence(self, recurrence_pattern: str, from_date: datetime):
        """Calculate next occurrence based on recurrence pattern"""
        try:
            from dateutil.relativedelta import relativedelta
            
            if recurrence_pattern.startswith("weekly_"):
                # Format: weekly_thursday_1630
                parts = recurrence_pattern.split("_")
                if len(parts) >= 3:
                    day_name = parts[1].lower()
                    time_str = parts[2]
                    
                    days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
                            "friday": 4, "saturday": 5, "sunday": 6}
                    target_day = days.get(day_name, 0)
                    
                    hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                    minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                    
                    days_ahead = target_day - from_date.weekday()
                    if days_ahead <= 0:
                        days_ahead += 7
                    
                    next_date = from_date + timedelta(days=days_ahead)
                    return next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            elif recurrence_pattern.startswith("daily_"):
                time_str = recurrence_pattern.split("_")[1] if "_" in recurrence_pattern else "0900"
                hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                
                next_date = from_date + timedelta(days=1)
                return next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            elif recurrence_pattern.startswith("monthly_"):
                parts = recurrence_pattern.split("_")
                day = int(parts[1]) if len(parts) >= 2 else 1
                time_str = parts[2] if len(parts) >= 3 else "0900"
                hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                
                next_date = from_date + relativedelta(months=1)
                return next_date.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        
        except Exception as e:
            print(f"Error calculating next occurrence: {e}")
        
        return None

    def _create_next_recurring_task(self, user_id: str, original_task: dict, 
                                     next_deadline: datetime, recurrence_pattern: str, 
                                     recurrence_end_date: str):
        """Create the next occurrence of a recurring task"""
        import asyncio
        import nest_asyncio
        import uuid
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def create():
                task_id = f"task_{user_id}_{uuid.uuid4().hex[:8]}"
                
                task_data = {
                    "user_id": user_id,
                    "task_id": task_id,
                    "title": original_task.get('title', 'Recurring Task'),
                    "description": original_task.get('description', ''),
                    "priority": original_task.get('priority', 'medium'),
                    "status": "pending",
                    "deadline": next_deadline.isoformat(),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "dependencies": "[]",
                    "notes": "",
                    "is_recurring": "true",
                    "recurrence_pattern": recurrence_pattern,
                    "recurrence_end_date": recurrence_end_date,
                    "parent_task_id": original_task.get('task_id', '')
                }
                
                await self.sheets_client.append_row("Tasks", task_data)
                print(f"Created next recurring task: {original_task.get('title')} for {next_deadline}")
                
            loop.run_until_complete(create())
        except Exception as e:
            print(f"Error creating next recurring task: {e}")
        finally:
            loop.close()

    def _get_user_tasks_sync(self, user_id):
        """Get user's tasks synchronously"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def get_tasks():
                tasks_df = await self.sheets_client.get_sheet_data("Tasks", user_id)
                return tasks_df.to_dict('records') if not tasks_df.empty else []
            return loop.run_until_complete(get_tasks())
        except:
            return []
        finally:
            loop.close()

    def _handle_quick_progress_update(self, user_id: str, task_id: str, task_title: str, text: str) -> str:
        """Handle quick progress update responses during task discussion sessions"""
        import re

        # Check for percentage patterns: "50%", "50 percent", "at 50", "about 50%"
        percent_match = re.search(r'(\d+)\s*%|(\d+)\s*percent|at\s+(\d+)|about\s+(\d+)', text.lower())
        if percent_match:
            progress = int(next(g for g in percent_match.groups() if g is not None))
            result = self._update_task_progress_sync(user_id, task_id, progress)
            if progress >= 100:
                # End session on completion
                if user_id in self.task_discussion_sessions:
                    del self.task_discussion_sessions[user_id]
                return f"Awesome! '{task_title}' marked as complete! I'll archive it in 7 days."
            return f"Got it - '{task_title}' is now at {progress}%. Keep it up!"

        # Check for completion words
        completion_words = ['done', 'complete', 'completed', 'finished', 'finish']
        if any(word in text.lower() for word in completion_words):
            result = self._update_task_progress_sync(user_id, task_id, 100)
            if user_id in self.task_discussion_sessions:
                del self.task_discussion_sessions[user_id]
            return f"Excellent! '{task_title}' marked as complete! Great work!"

        # Check for blocked/stuck
        blocked_words = ['blocked', 'stuck', 'waiting', 'can\'t', 'problem', 'issue', 'help']
        if any(word in text.lower() for word in blocked_words):
            notes = f"Blocked: {text[:100]}"
            self._update_task_progress_sync(user_id, task_id, None, notes)
            return f"I've noted that you're blocked on '{task_title}'. What's the main obstacle? Maybe I can help brainstorm solutions."

        # Check for not started
        not_started_words = ['not started', 'haven\'t started', 'no progress', 'nothing yet', 'zero']
        if any(phrase in text.lower() for phrase in not_started_words):
            return f"No worries! Would you like help breaking down '{task_title}' into smaller steps to get started?"

        # Check for skip/defer responses
        skip_words = ['skip', 'later', 'not now', 'busy', 'too busy']
        if any(word in text.lower() for word in skip_words):
            if user_id in self.task_discussion_sessions:
                del self.task_discussion_sessions[user_id]
            return "No problem! I'll check in again later. Say '/new session' anytime to start fresh."

        # Not a quick progress update - return None to let AI handle it
        return None

    def _update_task_progress_sync(self, user_id: str, task_id: str, progress: int = None, notes: str = None):
        """Update task progress synchronously"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def update():
                if progress is not None:
                    return await self.task_agent.update_task_progress(user_id, task_id, progress, notes)
                elif notes:
                    # Just update notes without changing progress
                    row_index = await self.sheets_client.find_row_by_id("Tasks", user_id, task_id)
                    if row_index:
                        tasks_df = await self.sheets_client.get_sheet_data("Tasks", user_id)
                        task = tasks_df[tasks_df['task_id'] == task_id]
                        if not task.empty:
                            existing_notes = task.iloc[0].get('notes', '')
                            timestamp = datetime.now(BRISBANE_TZ).strftime('%m/%d %H:%M')
                            new_note = f"[{timestamp}] {notes}"
                            full_notes = f"{existing_notes}\n{new_note}" if existing_notes else new_note
                            await self.sheets_client.update_row("Tasks", row_index, {
                                "notes": full_notes,
                                "last_discussed": datetime.now().isoformat()
                            })
                    return "Notes updated"
                return "No update"
            return loop.run_until_complete(update())
        except Exception as e:
            print(f"Error updating task progress: {e}")
            return f"Error: {e}"
        finally:
            loop.close()

    def _search_archives_sync(self, user_id: str, search_term: str):
        """Search archived tasks synchronously"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def search():
                return await self.task_agent.search_archived_tasks(user_id, search_term)
            return loop.run_until_complete(search())
        except:
            return []
        finally:
            loop.close()

    def _get_tasks_for_checkin_sync(self, user_id: str):
        """Get tasks for proactive check-in synchronously"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def get_tasks():
                return await self.task_agent.get_tasks_for_checkin(user_id, limit=1)
            return loop.run_until_complete(get_tasks())
        except:
            return []
        finally:
            loop.close()

    def _archive_old_tasks_sync(self, user_id: str):
        """Archive old completed tasks synchronously"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def archive():
                return await self.task_agent.archive_old_completed_tasks(user_id, days_threshold=7)
            return loop.run_until_complete(archive())
        except:
            return 0
        finally:
            loop.close()

    def _load_known_users(self):
        """Load known users from persistent storage (Users sheet)"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def load():
                users_df = await self.sheets_client.get_sheet_data("Users")
                if users_df.empty:
                    return set()
                users = set()
                for _, row in users_df.iterrows():
                    user_id = str(row.get('user_id', ''))
                    chat_id = row.get('chat_id', '')
                    if user_id and chat_id:
                        try:
                            users.add((user_id, int(chat_id)))
                        except (ValueError, TypeError):
                            pass
                return users
            self.known_users = loop.run_until_complete(load())
        except Exception as e:
            print(f"Error loading known users: {e}")
            self.known_users = set()
        finally:
            loop.close()

    def _save_user(self, user_id: str, chat_id: int, username: str = ""):
        """Save or update user in persistent storage"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def save():
                # Check if user already exists
                users_df = await self.sheets_client.get_sheet_data("Users")
                now = datetime.now(BRISBANE_TZ).isoformat()
                
                if not users_df.empty:
                    existing = users_df[users_df['user_id'].astype(str) == str(user_id)]
                    if not existing.empty:
                        # Update last_active for existing user
                        row_idx = existing.index[0] + 2  # +2 for header and 0-index
                        await self.sheets_client.update_row("Users", row_idx, {
                            "last_active": now
                        })
                        return
                
                # New user - add them
                await self.sheets_client.append_row("Users", {
                    "user_id": user_id,
                    "chat_id": str(chat_id),
                    "username": username,
                    "first_seen": now,
                    "last_active": now,
                    "preferences": "{}"
                })
                print(f"New user registered: {user_id} (@{username})")
                
            loop.run_until_complete(save())
        except Exception as e:
            print(f"Error saving user: {e}")
        finally:
            loop.close()


def main():
    """Main entry point"""
    print("\n" + "=" * 60)
    print("STARTING BRAIN AGENT BOT")
    print("=" * 60 + "\n")

    try:
        bot = SimpleTelegramBot()
        bot.run()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()