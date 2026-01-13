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

        # Configurable check-in times (default: 10am, 2pm, 6pm)
        # Can be overridden via env var CHECKIN_HOURS (comma-separated, e.g., "9,13,17")
        # Or per-user via /settings command
        default_hours = os.getenv('CHECKIN_HOURS', '10,14,18')
        self.default_checkin_hours = [int(h.strip()) for h in default_hours.split(',')]
        self.user_checkin_hours = {}  # user_id -> list of hours

        # Daily summary hour (default: 9am)
        self.daily_summary_hour = int(os.getenv('DAILY_SUMMARY_HOUR', '9'))

        # Calendar event filters (events to skip in summaries)
        # user_id -> set of event title substrings to skip
        self.skipped_calendar_events = {}
        # Pending skip suggestions awaiting confirmation
        self.pending_skip_suggestions = {}  # user_id -> list of suggested event titles

        # Task discussion sessions (for 5-min timeout)
        self.task_discussion_sessions = {}  # user_id -> {'task_id': str, 'started_at': datetime}

        # Pinned dashboard message IDs per user (chat_id -> message_id)
        self.pinned_dashboards = {}

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

            # Load model settings from Config sheet (with defaults)
            groq_model = self.sheets_client.get_config_sync("groq_model") or "llama-3.3-70b-versatile"
            embedding_model = self.sheets_client.get_config_sync("embedding_model") or "all-MiniLM-L6-v2"

            print(f"[2/5] Initializing AI Service ({groq_model})...")
            # Load email writing styles from config if available
            email_style_professional = self.sheets_client.get_config_sync("email_writing_style_professional")
            email_style_casual = self.sheets_client.get_config_sync("email_writing_style_casual")
            if email_style_professional:
                print("      Using custom professional email style from Config sheet")
            if email_style_casual:
                print("      Using custom casual email style from Config sheet")
            self.ai_service = AIService(
                groq_api_key=self.config.groq_api_key,
                model=groq_model,
                email_style_professional=email_style_professional,
                email_style_casual=email_style_casual
            )
            print("      SUCCESS: AI service initialized")

            print("[3/5] Initializing Vector Processor...")
            self.vector_processor = VectorProcessor(model_name=embedding_model)
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
                self.keep_service,      # Enable Google Keep notes
                self.sheets_client      # Enable pipeline context fetching
            )
            # Check if pipeline is enabled
            if self.conversation_agent.use_pipeline:
                print("      SUCCESS: All agents initialized (MULTI-STAGE PIPELINE ENABLED)")
            else:
                print("      SUCCESS: All agents initialized (legacy mode)")

            # Initialize default config if needed
            print("[+] Checking Config sheet...")
            self.sheets_client.initialize_default_config()

            # Load known users from persistent storage
            print("[+] Loading known users from database...")
            self._load_known_users()
            print(f"      Loaded {len(self.known_users)} known user(s)")

            # Load user settings from persistent storage
            print("[+] Loading user settings from database...")
            self._load_user_settings()
            print(f"      Loaded settings for {len(self.user_checkin_hours)} user(s)")

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

    def send_chat_action(self, chat_id, action="typing"):
        """Send chat action (typing indicator) to Telegram.

        Actions: typing, upload_photo, upload_document, upload_video,
                 record_voice, upload_voice, find_location, record_video_note
        """
        try:
            data = {'chat_id': chat_id, 'action': action}
            response = requests.post(
                f"{self.api_url}/sendChatAction",
                data=data,
                timeout=5
            )
            return response.json().get('ok', False)
        except Exception as e:
            print(f"Error sending chat action: {e}")
            return False

    def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        """Send message to Telegram with optional inline keyboard"""
        try:
            # Truncate very long messages
            if len(text) > 4000:
                text = text[:3997] + "..."

            data = {'chat_id': chat_id, 'text': text}
            if reply_markup:
                import json
                data['reply_markup'] = json.dumps(reply_markup)
            if parse_mode:
                data['parse_mode'] = parse_mode

            response = requests.post(
                f"{self.api_url}/sendMessage",
                data=data,
                timeout=10
            )
            result = response.json()
            if result.get('ok'):
                print(f"[TELEGRAM] Message sent successfully to {chat_id}")
                return result
            else:
                print(f"[TELEGRAM] Failed to send: {result}")
            return result
        except Exception as e:
            print(f"Error sending message: {e}")
            return None

    def edit_message(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        """Edit an existing message"""
        try:
            if len(text) > 4000:
                text = text[:3997] + "..."

            data = {
                'chat_id': chat_id,
                'message_id': message_id,
                'text': text
            }
            if reply_markup:
                import json
                data['reply_markup'] = json.dumps(reply_markup)
            if parse_mode:
                data['parse_mode'] = parse_mode

            response = requests.post(
                f"{self.api_url}/editMessageText",
                data=data,
                timeout=10
            )
            result = response.json()
            if result.get('ok'):
                print(f"[TELEGRAM] Message edited successfully")
            return result
        except Exception as e:
            print(f"Error editing message: {e}")
            return None

    def pin_message(self, chat_id, message_id, disable_notification=True):
        """Pin a message in the chat"""
        try:
            data = {
                'chat_id': chat_id,
                'message_id': message_id,
                'disable_notification': disable_notification
            }
            response = requests.post(
                f"{self.api_url}/pinChatMessage",
                data=data,
                timeout=10
            )
            result = response.json()
            if result.get('ok'):
                print(f"[TELEGRAM] Message pinned successfully")
            return result
        except Exception as e:
            print(f"Error pinning message: {e}")
            return None

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        """Answer a callback query (stops button spinner)"""
        try:
            data = {'callback_query_id': callback_query_id}
            if text:
                data['text'] = text
            data['show_alert'] = show_alert

            response = requests.post(
                f"{self.api_url}/answerCallbackQuery",
                data=data,
                timeout=5
            )
            return response.json().get('ok', False)
        except Exception as e:
            print(f"Error answering callback query: {e}")
            return False

    def _generate_dashboard_text(self, user_id):
        """Generate the live dashboard text for a user"""
        try:
            import asyncio
            import nest_asyncio
            nest_asyncio.apply()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                async def get_data():
                    tasks = await self.task_agent.get_prioritized_tasks(user_id, limit=10, status='pending')
                    calendar_events = []
                    if hasattr(self, 'calendar_service') and self.calendar_service:
                        calendar_events = await self.calendar_service.get_upcoming_events(max_results=10, days_ahead=1)
                    return tasks, calendar_events

                tasks, events = loop.run_until_complete(get_data())
            finally:
                loop.close()

            # Filter out skipped events
            events = self._filter_skipped_events(user_id, events)

            now = datetime.now(BRISBANE_TZ)
            lines = [
                f"BRAIN AGENT DASHBOARD",
                f"{now.strftime('%A, %B %d')} - {now.strftime('%I:%M %p')}",
                "",
                "TODAY'S SCHEDULE:"
            ]

            if events:
                for event in events[:5]:
                    time_str = event.get('time', 'All day')
                    title = event.get('title', 'Untitled')
                    lines.append(f"  {time_str} - {title}")
            else:
                lines.append("  No events scheduled")

            lines.extend(["", "PRIORITY TASKS:"])

            if tasks:
                for i, task in enumerate(tasks[:5], 1):
                    title = task.get('title', 'Untitled')
                    priority = task.get('priority', 'medium')
                    status = task.get('status', 'pending')
                    priority_icon = {'high': '!', 'medium': '-', 'low': ' '}.get(priority, '-')
                    check = 'x' if status == 'completed' else ' '
                    lines.append(f"  [{check}] {priority_icon} {title}")
            else:
                lines.append("  No pending tasks")

            lines.extend([
                "",
                f"Last updated: {now.strftime('%H:%M')}"
            ])

            return "\n".join(lines)

        except Exception as e:
            print(f"Error generating dashboard: {e}")
            return f"Dashboard unavailable - {e}"

    def send_or_update_dashboard(self, user_id, chat_id):
        """Send a new dashboard or update existing pinned one"""
        try:
            dashboard_text = self._generate_dashboard_text(user_id)

            # Check if we have an existing pinned dashboard
            if chat_id in self.pinned_dashboards:
                message_id = self.pinned_dashboards[chat_id]
                # Try to update it
                result = self.edit_message(chat_id, message_id, dashboard_text)
                if result and result.get('ok'):
                    print(f"[DASHBOARD] Updated pinned dashboard for {chat_id}")
                    return result
                # If update failed (message deleted?), remove from cache
                del self.pinned_dashboards[chat_id]

            # Send new dashboard
            result = self.send_message(chat_id, dashboard_text)
            if result and result.get('ok'):
                message_id = result['result']['message_id']
                # Pin it
                pin_result = self.pin_message(chat_id, message_id)
                if pin_result and pin_result.get('ok'):
                    self.pinned_dashboards[chat_id] = message_id
                    print(f"[DASHBOARD] Created and pinned new dashboard for {chat_id}")
                return result

            return None

        except Exception as e:
            print(f"Error with dashboard: {e}")
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

            # Show typing indicator immediately (masks latency)
            self.send_chat_action(chat_id, "typing")

            # Handle commands
            if text.startswith('/'):
                response = self._handle_command(text, user_id, first_name)
                if response == "__DASHBOARD__":
                    # Special handling for dashboard command
                    self.send_or_update_dashboard(user_id, chat_id)
                    return
                elif response == "__SKIP_SUGGEST__":
                    # Special handling for skip suggestion flow
                    self._suggest_calendar_skips(user_id, chat_id)
                    return
                elif response:
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
            result = self._process_with_ai(user_id, text, context)

            # Handle both string responses and dict responses (from pipeline)
            if isinstance(result, dict):
                response = result.get('response', '')
                awaiting_confirmation = result.get('awaiting_confirmation', False)
            else:
                response = result
                awaiting_confirmation = False

            # Send single response - ensure we only have one response
            print(f"[DEBUG BOT] Raw response length: {len(response)}")
            print(f"[DEBUG BOT] RESPONSE: {response[:200]}..." if len(response) > 200 else f"[DEBUG BOT] RESPONSE: {response}")
            print(f"[Pipeline] Awaiting confirmation: {awaiting_confirmation}")

            # Add confirmation buttons if awaiting confirmation
            if awaiting_confirmation:
                reply_markup = {
                    'inline_keyboard': [[
                        {'text': 'Yes, do it', 'callback_data': 'confirm_yes'},
                        {'text': 'No, cancel', 'callback_data': 'confirm_no'}
                    ]]
                }
                self.send_message(chat_id, response, reply_markup=reply_markup)
            else:
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

    def _handle_callback_query(self, callback_query):
        """Handle inline keyboard button presses"""
        try:
            query_id = callback_query['id']
            user_id = str(callback_query['from']['id'])
            chat_id = callback_query['message']['chat']['id']
            message_id = callback_query['message']['message_id']
            data = callback_query.get('data', '')

            print(f"[CALLBACK] User {user_id} pressed: {data}")

            # Answer callback immediately to stop spinner
            self.answer_callback_query(query_id)

            # Parse callback data (format: action:param1:param2)
            parts = data.split(':')
            action = parts[0] if parts else ''

            if action == 'confirm_yes':
                # User confirmed a high-stakes action
                self._execute_pending_confirmation(user_id, chat_id, message_id, confirmed=True)

            elif action == 'confirm_no':
                # User cancelled
                self._execute_pending_confirmation(user_id, chat_id, message_id, confirmed=False)

            elif action == 'task_done':
                # Mark task as complete
                task_id = parts[1] if len(parts) > 1 else None
                if task_id:
                    self._complete_task_via_button(user_id, chat_id, message_id, task_id)

            elif action == 'snooze':
                # Snooze reminder
                minutes = int(parts[1]) if len(parts) > 1 else 60
                self._snooze_reminder(user_id, chat_id, message_id, minutes)

            elif action == 'ack':
                # Acknowledge reminder (dismiss)
                self.edit_message(chat_id, message_id, "Got it, acknowledged.")

            elif action == 'skip_event':
                # Skip a calendar event from suggestions
                event_title = ':'.join(parts[1:]) if len(parts) > 1 else ''
                self._handle_skip_event(user_id, chat_id, message_id, event_title, skip=True)

            elif action == 'keep_event':
                # Keep (don't skip) a calendar event
                event_title = ':'.join(parts[1:]) if len(parts) > 1 else ''
                self._handle_skip_event(user_id, chat_id, message_id, event_title, skip=False)

            elif action == 'skip_all_suggested':
                # Skip all suggested recurring events
                self._handle_skip_all_suggested(user_id, chat_id, message_id)

            elif action == 'keep_all_suggested':
                # Keep all suggested recurring events (cancel suggestion)
                self._handle_keep_all_suggested(user_id, chat_id, message_id)

            elif action == 'task_done':
                # Mark task as complete from check-in button
                task_id = parts[1] if len(parts) > 1 else ''
                if task_id:
                    self._handle_task_button(user_id, chat_id, message_id, task_id, 'done')

            elif action == 'task_progress':
                # Update task progress from check-in button
                task_id = parts[1] if len(parts) > 1 else ''
                progress = int(parts[2]) if len(parts) > 2 else 50
                if task_id:
                    self._handle_task_button(user_id, chat_id, message_id, task_id, 'progress', progress)

            elif action == 'task_blocked':
                # Mark task as blocked from check-in button
                task_id = parts[1] if len(parts) > 1 else ''
                if task_id:
                    self._handle_task_button(user_id, chat_id, message_id, task_id, 'blocked')

            elif action == 'task_skip':
                # Skip task check-in from button
                task_id = parts[1] if len(parts) > 1 else ''
                self._handle_task_button(user_id, chat_id, message_id, task_id, 'skip')

            # New callback handlers for improved summary/deadline buttons
            elif action == 'view_overdue':
                self._handle_view_overdue(user_id, chat_id, message_id)

            elif action == 'snooze_all_overdue':
                self._handle_snooze_overdue(user_id, chat_id, message_id)

            elif action == 'focus_today':
                self._handle_focus_today(user_id, chat_id, message_id)

            elif action == 'start_task':
                task_id = parts[1] if len(parts) > 1 else ''
                if task_id:
                    self._handle_start_task(user_id, chat_id, message_id, task_id)

            elif action == 'show_priority':
                priority = parts[1] if len(parts) > 1 else 'high'
                self._handle_show_priority(user_id, chat_id, message_id, priority)

            elif action == 'show_all_tasks':
                self._handle_show_all_tasks(user_id, chat_id, message_id)

        except Exception as e:
            print(f"Error handling callback query: {e}")
            import traceback
            traceback.print_exc()

    def _execute_pending_confirmation(self, user_id, chat_id, message_id, confirmed):
        """Execute or cancel a pending confirmation"""
        try:
            # Get pending action from pipeline's confirmation manager
            if hasattr(self, 'conversation_agent') and hasattr(self.conversation_agent, 'pipeline'):
                pipeline = self.conversation_agent.pipeline
                if pipeline and hasattr(pipeline, 'confirmation_manager'):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    pending = loop.run_until_complete(
                        pipeline.confirmation_manager.get_pending_action(user_id)
                    )

                    if pending and confirmed:
                        # Execute the action
                        action_plan = pending.get('action_plan', {})
                        result = loop.run_until_complete(
                            pipeline._execute_actions(user_id, action_plan)
                        )
                        loop.run_until_complete(
                            pipeline.confirmation_manager.clear_pending_action(user_id)
                        )

                        if result.get('success'):
                            self.edit_message(chat_id, message_id, "Done! Action completed successfully.")
                        else:
                            errors = [a.get('error', 'Unknown error') for a in result.get('actions', []) if not a.get('success')]
                            self.edit_message(chat_id, message_id, f"Action failed: {'; '.join(errors)}")

                    elif pending and not confirmed:
                        loop.run_until_complete(
                            pipeline.confirmation_manager.clear_pending_action(user_id)
                        )
                        self.edit_message(chat_id, message_id, "Cancelled. I won't do that.")

                    else:
                        self.edit_message(chat_id, message_id, "No pending action found (may have expired).")

                    loop.close()
                    return

            # Fallback if pipeline not available
            if confirmed:
                self.edit_message(chat_id, message_id, "Confirmed (but no pending action found).")
            else:
                self.edit_message(chat_id, message_id, "Cancelled.")

        except Exception as e:
            print(f"Error executing confirmation: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _complete_task_via_button(self, user_id, chat_id, message_id, task_id):
        """Complete a task via inline button"""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.task_agent.complete_task(user_id, task_id))
            loop.close()

            self.edit_message(chat_id, message_id, f"Task completed! {result}")
        except Exception as e:
            print(f"Error completing task: {e}")
            self.edit_message(chat_id, message_id, f"Failed to complete task: {e}")

    def _snooze_reminder(self, user_id, chat_id, message_id, minutes):
        """Snooze a reminder"""
        self.edit_message(chat_id, message_id, f"Snoozed for {minutes} minutes. I'll remind you again.")
        # TODO: Implement actual snooze logic with scheduler

    def _handle_task_button(self, user_id, chat_id, message_id, task_id, action, progress=None):
        """Handle task check-in button presses"""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Get task title for response message
            tasks = loop.run_until_complete(self.task_agent.get_prioritized_tasks(user_id, limit=50, status='all'))
            task = next((t for t in tasks if t.get('task_id') == task_id), None)
            task_title = task.get('title', 'Task') if task else 'Task'

            if action == 'done':
                result = loop.run_until_complete(self.task_agent.complete_task(user_id, task_id))
                self.edit_message(chat_id, message_id, f"Excellent! '{task_title}' marked as complete! Great work!")
                # Clear any active session
                if user_id in self.task_discussion_sessions:
                    del self.task_discussion_sessions[user_id]

            elif action == 'progress':
                result = self._update_task_progress_sync(user_id, task_id, progress)
                self.edit_message(chat_id, message_id, f"Got it - '{task_title}' is now at {progress}%. Keep it up!")

            elif action == 'blocked':
                self.edit_message(chat_id, message_id, f"I see you're blocked on '{task_title}'. What's holding you up? I can help brainstorm solutions.")
                # Keep session active for follow-up
                self.task_discussion_sessions[user_id] = {
                    'task_id': task_id,
                    'task_title': task_title,
                    'started_at': datetime.now(BRISBANE_TZ)
                }

            elif action == 'skip':
                self.edit_message(chat_id, message_id, f"No problem! I'll check in on '{task_title}' later.")
                # Clear session
                if user_id in self.task_discussion_sessions:
                    del self.task_discussion_sessions[user_id]

            loop.close()

        except Exception as e:
            print(f"Error handling task button: {e}")
            import traceback
            traceback.print_exc()
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _suggest_calendar_skips(self, user_id, chat_id):
        """Suggest recurring calendar events to skip in summaries"""
        try:
            # Get upcoming events (next 7 days)
            events = self._get_upcoming_events_sync(days=7)
            if not events:
                self.send_message(chat_id, "No upcoming calendar events found to analyze.")
                return

            # Detect recurring events by finding duplicates (same title appears multiple times)
            # or events with recurrence indicators
            title_counts = {}
            for event in events:
                title = event.get('summary', 'Untitled')
                title_counts[title] = title_counts.get(title, 0) + 1

            # Find likely recurring events (appear 2+ times or have recurring flag)
            recurring_events = []
            seen_titles = set()
            for event in events:
                title = event.get('summary', 'Untitled')
                is_recurring = event.get('recurringEventId') is not None
                appears_multiple = title_counts.get(title, 0) >= 2

                # Skip if already in user's skip list
                user_skips = self.skipped_calendar_events.get(user_id, set())
                already_skipped = any(skip.lower() in title.lower() for skip in user_skips)

                if (is_recurring or appears_multiple) and title not in seen_titles and not already_skipped:
                    recurring_events.append(title)
                    seen_titles.add(title)

            if not recurring_events:
                self.send_message(chat_id, "No recurring events found to suggest skipping. All recurring events are either already skipped or none were detected.")
                return

            # Store suggestions for this user
            self.pending_skip_suggestions[user_id] = recurring_events[:5]  # Limit to 5 suggestions

            # Build message with inline buttons for each event
            message = "RECURRING EVENTS DETECTED:\n\nThese events repeat regularly. Skip them in daily summaries?\n\n"
            buttons = []

            for title in recurring_events[:5]:
                message += f"- {title}\n"
                # Truncate title for callback data (max 64 bytes)
                short_title = title[:40] if len(title) > 40 else title
                buttons.append([
                    {'text': f'Skip: {short_title[:20]}...', 'callback_data': f'skip_event:{short_title}'},
                    {'text': 'Keep', 'callback_data': f'keep_event:{short_title}'}
                ])

            # Add "Skip All" and "Keep All" buttons
            buttons.append([
                {'text': 'Skip All Listed', 'callback_data': 'skip_all_suggested'},
                {'text': 'Keep All', 'callback_data': 'keep_all_suggested'}
            ])

            reply_markup = {'inline_keyboard': buttons}
            self.send_message(chat_id, message, reply_markup=reply_markup)

        except Exception as e:
            print(f"Error suggesting calendar skips: {e}")
            import traceback
            traceback.print_exc()
            self.send_message(chat_id, f"Error analyzing calendar: {e}")

    def _handle_skip_event(self, user_id, chat_id, message_id, event_title, skip=True):
        """Handle skipping or keeping a single event"""
        if skip:
            if user_id not in self.skipped_calendar_events:
                self.skipped_calendar_events[user_id] = set()
            self.skipped_calendar_events[user_id].add(event_title)
            self.answer_callback_query(None, f"Will skip '{event_title[:30]}...'")

            # Remove from pending if present
            if user_id in self.pending_skip_suggestions:
                self.pending_skip_suggestions[user_id] = [
                    t for t in self.pending_skip_suggestions[user_id]
                    if not (event_title.lower() in t.lower() or t.lower() in event_title.lower())
                ]
        else:
            # User chose to keep - just remove from pending
            if user_id in self.pending_skip_suggestions:
                self.pending_skip_suggestions[user_id] = [
                    t for t in self.pending_skip_suggestions[user_id]
                    if not (event_title.lower() in t.lower() or t.lower() in event_title.lower())
                ]

        # Update message to show current status
        skipped = self.skipped_calendar_events.get(user_id, set())
        if skipped:
            status = "SKIPPED EVENTS:\n" + "\n".join([f"- {s}" for s in skipped])
        else:
            status = "No events are currently being skipped."

        self.edit_message(chat_id, message_id, f"{'Skipped' if skip else 'Keeping'}: {event_title}\n\n{status}")

    def _handle_skip_all_suggested(self, user_id, chat_id, message_id):
        """Skip all suggested recurring events"""
        suggestions = self.pending_skip_suggestions.get(user_id, [])
        if not suggestions:
            self.edit_message(chat_id, message_id, "No suggestions to skip.")
            return

        if user_id not in self.skipped_calendar_events:
            self.skipped_calendar_events[user_id] = set()

        for title in suggestions:
            self.skipped_calendar_events[user_id].add(title)

        # Clear pending
        del self.pending_skip_suggestions[user_id]

        skipped_list = "\n".join([f"- {s}" for s in self.skipped_calendar_events[user_id]])
        self.edit_message(chat_id, message_id, f"All suggested events will be skipped in summaries.\n\nSKIPPED EVENTS:\n{skipped_list}\n\nUse '/settings unskip \"Event Name\"' to show them again.")

    def _handle_keep_all_suggested(self, user_id, chat_id, message_id):
        """Cancel skip suggestions - keep all events"""
        if user_id in self.pending_skip_suggestions:
            del self.pending_skip_suggestions[user_id]

        self.edit_message(chat_id, message_id, "Keeping all events in summaries. No changes made.")

    def _filter_skipped_events(self, user_id, events):
        """Filter out skipped events from a list of calendar events"""
        if not events:
            return events

        user_skips = self.skipped_calendar_events.get(user_id, set())
        if not user_skips:
            return events

        filtered = []
        for event in events:
            title = event.get('summary', '') or event.get('title', '')
            # Check if any skip pattern matches (case-insensitive substring match)
            should_skip = any(skip.lower() in title.lower() for skip in user_skips)
            if not should_skip:
                filtered.append(event)

        return filtered

    def _handle_voice_message(self, message):
        """Handle voice messages - transcribe with Whisper and process"""
        try:
            user_id = str(message['from']['id'])
            chat_id = message['chat']['id']
            username = message['from'].get('username', 'unknown')
            voice = message['voice']
            file_id = voice['file_id']
            duration = voice.get('duration', 0)

            print(f"\n{'='*50}")
            print(f"VOICE from @{username} ({user_id}): {duration}s")
            print(f"{'='*50}")

            # Show typing indicator
            self.send_chat_action(chat_id, "typing")

            # Get file path from Telegram
            file_info = self._get_file_info(file_id)
            if not file_info:
                self.send_message(chat_id, "Sorry, I couldn't process that voice message.")
                return

            file_path = file_info.get('result', {}).get('file_path')
            if not file_path:
                self.send_message(chat_id, "Sorry, I couldn't download that voice message.")
                return

            # Download the file
            file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            audio_data = self._download_file(file_url)
            if not audio_data:
                self.send_message(chat_id, "Sorry, I couldn't download that voice message.")
                return

            # Transcribe with Groq Whisper
            transcription = self._transcribe_audio(audio_data, file_path)
            if not transcription:
                self.send_message(chat_id, "Sorry, I couldn't transcribe that voice message. Please try again or type your message.")
                return

            print(f"[TRANSCRIPTION] {transcription}")

            # Process the transcribed text like a normal message
            context = self._load_user_context(user_id)
            result = self._process_with_ai(user_id, transcription, context)

            # Handle both string responses and dict responses (from pipeline)
            if isinstance(result, dict):
                response_text = result.get('response', '')
                awaiting_confirmation = result.get('awaiting_confirmation', False)
            else:
                response_text = result
                awaiting_confirmation = False

            # Send response with transcription preview
            full_response = f'I heard: "{transcription[:100]}{"..." if len(transcription) > 100 else ""}"\n\n{response_text}'

            if awaiting_confirmation:
                reply_markup = {
                    'inline_keyboard': [[
                        {'text': 'Yes, do it', 'callback_data': 'confirm_yes'},
                        {'text': 'No, cancel', 'callback_data': 'confirm_no'}
                    ]]
                }
                self.send_message(chat_id, full_response, reply_markup=reply_markup)
            else:
                self.send_message(chat_id, full_response)

            # Store conversation
            self._store_conversation(user_id, "user", f"[Voice] {transcription}")
            self._store_conversation(user_id, "assistant", response_text)

        except Exception as e:
            print(f"Error handling voice message: {e}")
            import traceback
            traceback.print_exc()
            self.send_message(message['chat']['id'], "Sorry, I had trouble processing that voice message.")

    def _get_file_info(self, file_id):
        """Get file info from Telegram"""
        try:
            response = requests.post(
                f"{self.api_url}/getFile",
                data={'file_id': file_id},
                timeout=10
            )
            return response.json()
        except Exception as e:
            print(f"Error getting file info: {e}")
            return None

    def _download_file(self, file_url):
        """Download a file from Telegram"""
        try:
            response = requests.get(file_url, timeout=30)
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            print(f"Error downloading file: {e}")
            return None

    def _transcribe_audio(self, audio_data, filename):
        """Transcribe audio using Groq Whisper"""
        try:
            import tempfile
            import os

            # Telegram voice messages are .oga (Ogg with Opus codec)
            # Groq accepts: flac mp3 mp4 mpeg mpga m4a ogg opus wav webm
            # .oga files are Ogg format, so use .ogg extension
            if filename.endswith('.oga') or filename.endswith('.ogg'):
                suffix = '.ogg'
                groq_filename = 'voice.ogg'  # Groq checks filename extension
            else:
                suffix = '.mp3'
                groq_filename = 'audio.mp3'

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(audio_data)
                temp_path = f.name

            try:
                # Use Groq's Whisper API
                from groq import Groq
                client = Groq(api_key=os.getenv('GROQ_API_KEY'))

                with open(temp_path, 'rb') as audio_file:
                    transcription = client.audio.transcriptions.create(
                        file=(groq_filename, audio_file),  # Use valid extension for Groq
                        model="whisper-large-v3",
                        response_format="text"
                    )

                return transcription.strip() if transcription else None

            finally:
                # Clean up temp file
                os.unlink(temp_path)

        except Exception as e:
            print(f"Error transcribing audio: {e}")
            import traceback
            traceback.print_exc()
            return None

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
- /dashboard - Show/update pinned dashboard
- /settings - Configure check-in times
- /check archives <term> - Search archived tasks
- /new session - End current task discussion

QUICK ACTIONS:
- /summary - Get your daily summary now
- /deadlines - Show overdue and upcoming tasks
- /archive - Archive old completed tasks

PROACTIVE FEATURES:
- I'll check in on your tasks at configurable times
- Use /settings to change check-in schedule
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

        elif command == '/dashboard':
            # Dashboard is handled specially - returns None to trigger dashboard send
            return "__DASHBOARD__"

        elif command == '/settings' or text.lower().startswith('/settings'):
            parts = text.split()
            if len(parts) == 1:
                # Show current settings
                user_hours = self.user_checkin_hours.get(user_id, self.default_checkin_hours)
                hours_str = ', '.join([f"{h}:00" for h in user_hours])
                skipped = self.skipped_calendar_events.get(user_id, set())
                skipped_str = ', '.join(skipped) if skipped else 'None'
                return f"""SETTINGS

CHECK-IN TIMES:
Currently: {hours_str}

DAILY SUMMARY:
Time: {self.daily_summary_hour}:00 AM

SKIPPED CALENDAR EVENTS:
{skipped_str}

QUICK ACTIONS:
- /summary - Get your daily summary now
- /deadlines - Show overdue and upcoming tasks
- /archive - Archive completed tasks (7+ days old)

CONFIGURE:
- /settings checkin 8,12,18 - set check-in hours
- /settings checkin off - disable check-ins
- /settings skip "Team Standup" - skip event in summaries
- /settings unskip "Team Standup" - show event again
- /settings skip suggest - suggest recurring events to skip"""

            elif len(parts) >= 3 and parts[1].lower() == 'checkin':
                setting = parts[2].lower()
                if setting == 'off':
                    self.user_checkin_hours[user_id] = []
                    self._save_user_setting(user_id, 'checkin_hours', 'off')
                    return "Task check-ins disabled. Use '/settings checkin default' to re-enable."
                elif setting == 'default':
                    if user_id in self.user_checkin_hours:
                        del self.user_checkin_hours[user_id]
                    self._save_user_setting(user_id, 'checkin_hours', ','.join(map(str, self.default_checkin_hours)))
                    return f"Check-in times reset to default: {', '.join([f'{h}:00' for h in self.default_checkin_hours])}"
                else:
                    try:
                        hours = [int(h.strip()) for h in setting.split(',')]
                        # Validate hours (0-23)
                        if all(0 <= h <= 23 for h in hours):
                            self.user_checkin_hours[user_id] = sorted(hours)
                            self._save_user_setting(user_id, 'checkin_hours', ','.join(map(str, sorted(hours))))
                            hours_str = ', '.join([f"{h}:00" for h in sorted(hours)])
                            return f"Check-in times updated to: {hours_str}"
                        else:
                            return "Invalid hours. Use 0-23 (24-hour format)."
                    except ValueError:
                        return "Invalid format. Use comma-separated hours, e.g., /settings checkin 9,14,18"

            elif len(parts) >= 2 and parts[1].lower() == 'skip':
                if len(parts) == 2:
                    return "Usage: /settings skip \"Event Name\" or /settings skip suggest"

                setting = ' '.join(parts[2:]).strip('"\'')

                if setting.lower() == 'suggest':
                    # Trigger suggestion flow - return special marker
                    return "__SKIP_SUGGEST__"
                else:
                    # Add to skip list
                    if user_id not in self.skipped_calendar_events:
                        self.skipped_calendar_events[user_id] = set()
                    self.skipped_calendar_events[user_id].add(setting)
                    # Persist to sheets
                    self._save_user_setting(user_id, 'skipped_events', '|'.join(self.skipped_calendar_events[user_id]))
                    return f"Will skip '{setting}' in daily summaries.\n\nUse '/settings unskip \"{setting}\"' to show it again."

            elif len(parts) >= 3 and parts[1].lower() == 'unskip':
                event_name = ' '.join(parts[2:]).strip('"\'')
                if user_id in self.skipped_calendar_events:
                    self.skipped_calendar_events[user_id].discard(event_name)
                    if not self.skipped_calendar_events[user_id]:
                        del self.skipped_calendar_events[user_id]
                        self._save_user_setting(user_id, 'skipped_events', '')
                    else:
                        self._save_user_setting(user_id, 'skipped_events', '|'.join(self.skipped_calendar_events[user_id]))
                return f"'{event_name}' will now appear in summaries again."

            else:
                return "Unknown setting. Try /settings to see available options."

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

        elif command == '/summary':
            # Trigger immediate daily summary
            return self._send_summary_command(user_id, chat_id)

        elif command == '/deadlines':
            # Show upcoming deadlines
            return self._show_deadlines_command(user_id, chat_id)

        elif command == '/archive':
            # Run auto-archive now
            return self._run_archive_command(user_id, chat_id)

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

                        # Handle callback queries (inline button presses)
                        if 'callback_query' in update:
                            self._handle_callback_query(update['callback_query'])

                        elif 'message' in update and 'text' in update['message']:
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

                        # Handle voice messages
                        elif 'message' in update and 'voice' in update['message']:
                            self._handle_voice_message(update['message'])

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
        print(f"[PROACTIVE] Loop started at {datetime.now(BRISBANE_TZ).strftime('%H:%M:%S')}")
        print(f"[PROACTIVE] Check-in hours: {self.default_checkin_hours}")
        print(f"[PROACTIVE] Daily summary hour: {self.daily_summary_hour}")

        last_checkin_hour = None  # Track the last hour we sent check-ins
        last_summary_date = None  # Track the last date we sent summaries

        while True:
            try:
                now = datetime.now(BRISBANE_TZ)
                current_hour = now.hour
                current_date = now.date()

                # Daily summary (once per day at configured hour)
                if current_hour == self.daily_summary_hour and last_summary_date != current_date:
                    print(f"[PROACTIVE] Triggering daily summaries at {now.strftime('%H:%M')}")
                    self._send_daily_summaries()
                    last_summary_date = current_date

                # Proactive task check-ins (once per configured hour)
                # Only trigger if current hour is in check-in hours and we haven't sent this hour yet
                if current_hour in self.default_checkin_hours and last_checkin_hour != current_hour:
                    print(f"[PROACTIVE] Triggering task check-ins at {now.strftime('%H:%M')} (hour {current_hour})")
                    self._send_task_checkins()
                    last_checkin_hour = current_hour

                # Check for upcoming deadlines (every cycle)
                self._check_upcoming_deadlines()

                # Handle recurring tasks - create next occurrence when completed
                self._process_recurring_tasks()

                # Auto-archive old completed tasks (check once per hour at minute 30-35)
                if 30 <= now.minute < 35:
                    self._auto_archive_tasks()

                # Clean up expired task discussion sessions
                self._cleanup_expired_sessions()

            except Exception as e:
                print(f"[PROACTIVE] Loop error: {e}")
                import traceback
                traceback.print_exc()

            # Sleep at the END of the loop - check every minute for more responsive check-ins
            time.sleep(60)

    def _send_daily_summaries(self):
        """Send daily task and calendar summaries to known users - improved format"""
        now = datetime.now(BRISBANE_TZ)
        today = now.date()

        for user_id, chat_id in self.known_users:
            # Only send once per day
            if self.last_daily_summary.get(user_id) == today:
                continue

            try:
                # Get user's tasks
                tasks = self._get_user_tasks_sync(user_id)
                pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []

                # Get today's calendar events (and filter out skipped ones)
                todays_events = self._get_todays_events_sync()
                todays_events = self._filter_skipped_events(user_id, todays_events)

                # Only send if there's something to report
                if not pending and not todays_events:
                    continue

                # Calculate overdue, due today, high priority
                overdue = []
                due_today = []
                high_priority = []

                for task in pending:
                    deadline_str = task.get('deadline', '')
                    priority = task.get('priority', '')

                    if priority in ('high', 'critical'):
                        high_priority.append(task)

                    if deadline_str:
                        try:
                            deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                            if deadline_dt.tzinfo is None:
                                deadline_dt = BRISBANE_TZ.localize(deadline_dt)
                            if deadline_dt.date() < today:
                                overdue.append(task)
                            elif deadline_dt.date() == today:
                                due_today.append(task)
                        except:
                            pass

                # Build improved message
                day_name = now.strftime('%A, %B %d')
                message = f"GOOD MORNING - {day_name}\n\n"

                # Today's Focus section (pick 1-3 most important)
                focus_tasks = []
                for t in overdue[:2]:
                    focus_tasks.append((t, 'overdue'))
                for t in due_today[:2]:
                    if len(focus_tasks) < 3:
                        focus_tasks.append((t, 'today'))
                for t in high_priority[:2]:
                    if len(focus_tasks) < 3 and t not in [x[0] for x in focus_tasks]:
                        focus_tasks.append((t, 'priority'))

                if focus_tasks:
                    message += "TODAY'S FOCUS:\n"
                    for i, (task, reason) in enumerate(focus_tasks[:3], 1):
                        suffix = " (overdue!)" if reason == 'overdue' else ""
                        message += f"  {i}. {task.get('title')}{suffix}\n"
                    message += "\n"

                # Calendar section
                if todays_events:
                    message += "CALENDAR:\n"
                    for event in todays_events[:4]:
                        start_str = event.get('start', '')
                        try:
                            if 'T' in start_str:
                                dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                                time_str = dt.strftime('%I:%M%p').lstrip('0')
                            else:
                                time_str = "All day"
                        except:
                            time_str = start_str
                        message += f"  - {time_str}: {event.get('summary', 'Untitled')}\n"
                    message += "\n"

                # Warnings section
                if overdue:
                    message += f"WARNING: {len(overdue)} overdue task(s)\n"
                    message += "  Use /deadlines to see them\n\n"

                # Stats summary
                message += "STATS:\n"
                message += f"  - {len(pending)} pending tasks"
                if high_priority:
                    message += f" ({len(high_priority)} high priority)"
                message += "\n"
                if due_today:
                    message += f"  - {len(due_today)} due today\n"
                if overdue:
                    message += f"  - {len(overdue)} overdue\n"

                # Buttons
                buttons = []
                if focus_tasks:
                    first_task = focus_tasks[0][0]
                    buttons.append([
                        {'text': f'Start: {first_task.get("title", "Task")[:20]}', 'callback_data': f'start_task:{first_task.get("task_id")}'}
                    ])
                if high_priority:
                    buttons.append([
                        {'text': 'Show High Priority', 'callback_data': 'show_priority:high'},
                        {'text': 'Show All Tasks', 'callback_data': 'show_all_tasks'}
                    ])
                if overdue:
                    buttons.append([
                        {'text': 'View Overdue', 'callback_data': 'view_overdue'},
                        {'text': 'Snooze All +1 Day', 'callback_data': 'snooze_all_overdue'}
                    ])

                if buttons:
                    reply_markup = {'inline_keyboard': buttons}
                    self.send_message(chat_id, message, reply_markup=reply_markup)
                else:
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

        print(f"[CHECK-IN] Starting check-ins at {now.strftime('%H:%M')} for {len(self.known_users)} users")

        for user_id, chat_id in self.known_users:
            try:
                # Get user's configured check-in hours (or default)
                user_hours = self.user_checkin_hours.get(user_id, self.default_checkin_hours)
                print(f"[CHECK-IN] User {user_id}: hours={user_hours}, current_hour={current_hour}")

                # Skip if current hour is not in user's check-in schedule
                if current_hour not in user_hours:
                    print(f"[CHECK-IN] User {user_id}: Skipping - not in user's check-in hours")
                    continue

                # Check if we already sent a check-in at this hour today
                last_checkin = self.last_task_checkin.get(user_id)
                if last_checkin:
                    last_date, last_hour = last_checkin
                    if last_date == today and last_hour == current_hour:
                        print(f"[CHECK-IN] User {user_id}: Skipping - already sent check-in this hour")
                        continue

                # Get a task to check in about
                print(f"[CHECK-IN] User {user_id}: Looking for tasks to check in about...")
                tasks = self._get_tasks_for_checkin_sync(user_id)
                if not tasks:
                    print(f"[CHECK-IN] User {user_id}: No pending tasks found for check-in")
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

                message += "\n\nReply with your progress or tap a button below:"

                # Add inline buttons for quick responses
                task_id = task.get('task_id', '')
                reply_markup = {
                    'inline_keyboard': [
                        [
                            {'text': 'Done!', 'callback_data': f'task_done:{task_id}'},
                            {'text': '50%', 'callback_data': f'task_progress:{task_id}:50'},
                            {'text': '25%', 'callback_data': f'task_progress:{task_id}:25'}
                        ],
                        [
                            {'text': 'Blocked', 'callback_data': f'task_blocked:{task_id}'},
                            {'text': 'Skip', 'callback_data': f'task_skip:{task_id}'}
                        ]
                    ]
                }

                self.send_message(chat_id, message, reply_markup=reply_markup)
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
        """Clean up task discussion sessions - NO TIMEOUT, sessions persist until explicitly cleared.

        Sessions are cleared when:
        - User completes a task (via button or text)
        - User skips a check-in (via button)
        - User starts /new session command
        - A new check-in replaces the old session

        The buttons work independently of sessions (task_id in callback data),
        so sessions are only needed for text replies like "done" or "50%".
        """
        # No automatic timeout - let sessions persist
        # They get replaced when a new check-in is sent anyway
        pass

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

    def _send_summary_command(self, user_id, chat_id):
        """Handle /summary command - send improved daily summary immediately."""
        try:
            # Get user's tasks
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []

            # Get today's calendar events
            todays_events = self._get_todays_events_sync()
            todays_events = self._filter_skipped_events(user_id, todays_events)

            now = datetime.now(BRISBANE_TZ)
            today = now.date()

            # Calculate overdue and upcoming
            overdue = []
            due_today = []
            high_priority = []

            for task in pending:
                deadline_str = task.get('deadline', '')
                priority = task.get('priority', '')

                if priority in ('high', 'critical'):
                    high_priority.append(task)

                if deadline_str:
                    try:
                        deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                        if deadline_dt.tzinfo is None:
                            deadline_dt = BRISBANE_TZ.localize(deadline_dt)
                        if deadline_dt.date() < today:
                            overdue.append(task)
                        elif deadline_dt.date() == today:
                            due_today.append(task)
                    except:
                        pass

            # Build improved message
            day_name = now.strftime('%A, %B %d')
            message = f"DAILY SUMMARY - {day_name}\n\n"

            # Today's Focus section (pick 1-3 most important)
            focus_tasks = []
            # Priority: overdue first, then due today, then high priority
            for t in overdue[:2]:
                focus_tasks.append((t, 'overdue'))
            for t in due_today[:2]:
                if len(focus_tasks) < 3:
                    focus_tasks.append((t, 'today'))
            for t in high_priority[:2]:
                if len(focus_tasks) < 3 and t not in [x[0] for x in focus_tasks]:
                    focus_tasks.append((t, 'priority'))

            if focus_tasks:
                message += "TODAY'S FOCUS:\n"
                for i, (task, reason) in enumerate(focus_tasks[:3], 1):
                    suffix = " (overdue!)" if reason == 'overdue' else ""
                    message += f"  {i}. {task.get('title')}{suffix}\n"
                message += "\n"

            # Calendar section
            if todays_events:
                message += "CALENDAR:\n"
                for event in todays_events[:4]:
                    start_str = event.get('start', '')
                    try:
                        if 'T' in start_str:
                            dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                            time_str = dt.strftime('%I:%M%p').lstrip('0')
                        else:
                            time_str = "All day"
                    except:
                        time_str = start_str
                    message += f"  - {time_str}: {event.get('summary', 'Untitled')}\n"
                message += "\n"

            # Warnings section
            if overdue:
                message += f"WARNING: {len(overdue)} overdue task(s)\n"
                message += "  Use /deadlines to see them\n\n"

            # Stats summary
            message += "STATS:\n"
            message += f"  - {len(pending)} pending tasks"
            if high_priority:
                message += f" ({len(high_priority)} high priority)"
            message += "\n"
            if due_today:
                message += f"  - {len(due_today)} due today\n"
            if overdue:
                message += f"  - {len(overdue)} overdue\n"

            # Buttons
            buttons = []
            if focus_tasks:
                first_task = focus_tasks[0][0]
                buttons.append([
                    {'text': f'Start: {first_task.get("title", "Task")[:20]}', 'callback_data': f'start_task:{first_task.get("task_id")}'}
                ])
            if high_priority:
                buttons.append([
                    {'text': 'Show High Priority', 'callback_data': 'show_priority:high'},
                    {'text': 'Show All Tasks', 'callback_data': 'show_all_tasks'}
                ])
            if overdue:
                buttons.append([
                    {'text': 'View Overdue', 'callback_data': 'view_overdue'},
                    {'text': 'Snooze All +1 Day', 'callback_data': 'snooze_all_overdue'}
                ])

            if buttons:
                reply_markup = {'inline_keyboard': buttons}
                self.send_message(chat_id, message, reply_markup=reply_markup)
            else:
                self.send_message(chat_id, message)

            return None  # Already sent message

        except Exception as e:
            print(f"Error in /summary command: {e}")
            import traceback
            traceback.print_exc()
            return f"Error generating summary: {e}"

    def _show_deadlines_command(self, user_id, chat_id):
        """Handle /deadlines command - show grouped deadline list."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            if not tasks:
                return "No tasks found."

            pending = [t for t in tasks if t.get('status') == 'pending']
            now = datetime.now(BRISBANE_TZ)
            today = now.date()

            overdue = []
            due_today = []
            due_tomorrow = []
            due_this_week = []

            for task in pending:
                deadline_str = task.get('deadline', '')
                if not deadline_str:
                    continue

                try:
                    deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    if deadline_dt.tzinfo is None:
                        deadline_dt = BRISBANE_TZ.localize(deadline_dt)

                    days_diff = (deadline_dt.date() - today).days
                    task_info = {
                        'task': task,
                        'days': days_diff,
                        'deadline': deadline_dt
                    }

                    if days_diff < 0:
                        overdue.append(task_info)
                    elif days_diff == 0:
                        due_today.append(task_info)
                    elif days_diff == 1:
                        due_tomorrow.append(task_info)
                    elif days_diff <= 7:
                        due_this_week.append(task_info)
                except:
                    continue

            if not overdue and not due_today and not due_tomorrow and not due_this_week:
                return "No upcoming deadlines within the next week."

            message = "DEADLINE CHECK\n\n"

            # Overdue section
            if overdue:
                overdue.sort(key=lambda x: x['days'])  # Most overdue first
                message += f"CRITICAL - Overdue ({len(overdue)} task{'s' if len(overdue) != 1 else ''}):\n"
                for item in overdue[:4]:
                    days_ago = abs(item['days'])
                    message += f"  - {item['task'].get('title')} ({days_ago}d ago)\n"
                if len(overdue) > 4:
                    message += f"  ... and {len(overdue) - 4} more\n"
                message += "\n"

            # Today section
            if due_today:
                message += f"TODAY ({len(due_today)} task{'s' if len(due_today) != 1 else ''}):\n"
                for item in due_today[:4]:
                    message += f"  - {item['task'].get('title')}\n"
                if len(due_today) > 4:
                    message += f"  ... and {len(due_today) - 4} more\n"
                message += "\n"

            # Tomorrow section
            if due_tomorrow:
                message += f"TOMORROW ({len(due_tomorrow)} task{'s' if len(due_tomorrow) != 1 else ''}):\n"
                for item in due_tomorrow[:3]:
                    message += f"  - {item['task'].get('title')}\n"
                if len(due_tomorrow) > 3:
                    message += f"  ... and {len(due_tomorrow) - 3} more\n"
                message += "\n"

            # This week section
            if due_this_week:
                message += f"THIS WEEK ({len(due_this_week)} task{'s' if len(due_this_week) != 1 else ''}):\n"
                for item in due_this_week[:3]:
                    day_name = item['deadline'].strftime('%a')
                    message += f"  - {item['task'].get('title')} ({day_name})\n"
                if len(due_this_week) > 3:
                    message += f"  ... and {len(due_this_week) - 3} more\n"
                message += "\n"

            message += "Tip: Reply with a task name to update its deadline."

            # Buttons
            buttons = []
            if overdue:
                buttons.append([
                    {'text': 'View All Overdue', 'callback_data': 'view_overdue'},
                    {'text': 'Snooze All +1 Day', 'callback_data': 'snooze_all_overdue'}
                ])
            if due_today:
                buttons.append([
                    {'text': 'Focus on Today', 'callback_data': 'focus_today'}
                ])
            buttons.append([
                {'text': 'Show All Tasks', 'callback_data': 'show_all_tasks'}
            ])

            reply_markup = {'inline_keyboard': buttons}
            self.send_message(chat_id, message, reply_markup=reply_markup)
            return None  # Already sent message

        except Exception as e:
            print(f"Error in /deadlines command: {e}")
            import traceback
            traceback.print_exc()
            return f"Error checking deadlines: {e}"

    def _run_archive_command(self, user_id, chat_id):
        """Handle /archive command - run auto-archive now."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            if not tasks:
                return "No tasks found."

            now = datetime.now(BRISBANE_TZ)
            archived_count = 0

            for task in tasks:
                if task.get('status') != 'complete':
                    continue
                if str(task.get('archived', 'false')).lower() == 'true':
                    continue

                # Check completion date
                completed_at_str = task.get('completed_at', '')
                if not completed_at_str:
                    continue

                try:
                    completed_at = datetime.fromisoformat(completed_at_str.replace('Z', '+00:00'))
                    if completed_at.tzinfo is None:
                        completed_at = BRISBANE_TZ.localize(completed_at)

                    days_since = (now - completed_at).days

                    if days_since >= 7:
                        # Archive this task
                        task_id = task.get('task_id')
                        if task_id:
                            import asyncio
                            import nest_asyncio
                            nest_asyncio.apply()

                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(
                                    self.task_agent.update_task(user_id, task_id, {'archived': 'true'})
                                )
                                archived_count += 1
                                print(f"Archived task: {task.get('title')}")
                            finally:
                                loop.close()
                except:
                    continue

            if archived_count == 0:
                return "No tasks to archive. Tasks are archived when completed for 7+ days."

            return f"Archived {archived_count} completed task{'s' if archived_count != 1 else ''} (completed 7+ days ago)."

        except Exception as e:
            print(f"Error in /archive command: {e}")
            import traceback
            traceback.print_exc()
            return f"Error archiving tasks: {e}"

    def _handle_view_overdue(self, user_id, chat_id, message_id):
        """Show full list of overdue tasks."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []
            now = datetime.now(BRISBANE_TZ)
            today = now.date()

            overdue = []
            for task in pending:
                deadline_str = task.get('deadline', '')
                if not deadline_str:
                    continue
                try:
                    deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    if deadline_dt.tzinfo is None:
                        deadline_dt = BRISBANE_TZ.localize(deadline_dt)
                    if deadline_dt.date() < today:
                        days_ago = (today - deadline_dt.date()).days
                        overdue.append({'task': task, 'days': days_ago})
                except:
                    continue

            if not overdue:
                self.edit_message(chat_id, message_id, "No overdue tasks!")
                return

            overdue.sort(key=lambda x: -x['days'])  # Most overdue first

            message = "ALL OVERDUE TASKS:\n\n"
            for i, item in enumerate(overdue, 1):
                message += f"{i}. {item['task'].get('title')} ({item['days']}d ago)\n"

            # Add done buttons for top 5
            buttons = []
            for item in overdue[:5]:
                task = item['task']
                short_title = task.get('title', 'Task')[:20]
                buttons.append([
                    {'text': f'Done: {short_title}', 'callback_data': f'task_done:{task.get("task_id")}'}
                ])

            reply_markup = {'inline_keyboard': buttons}
            self.edit_message(chat_id, message_id, message, reply_markup=reply_markup)

        except Exception as e:
            print(f"Error in view_overdue: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _handle_snooze_overdue(self, user_id, chat_id, message_id):
        """Push all overdue task deadlines forward by 1 day."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []
            now = datetime.now(BRISBANE_TZ)
            today = now.date()

            overdue = []
            for task in pending:
                deadline_str = task.get('deadline', '')
                if not deadline_str:
                    continue
                try:
                    deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    if deadline_dt.tzinfo is None:
                        deadline_dt = BRISBANE_TZ.localize(deadline_dt)
                    if deadline_dt.date() < today:
                        overdue.append(task)
                except:
                    continue

            if not overdue:
                self.edit_message(chat_id, message_id, "No overdue tasks to snooze.")
                return

            import asyncio
            import nest_asyncio
            nest_asyncio.apply()

            count = 0
            tomorrow = now + timedelta(days=1)
            tomorrow = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)  # Set to 9 AM

            for task in overdue:
                task_id = task.get('task_id')
                if not task_id:
                    continue

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self.task_agent.update_task(user_id, task_id, {'deadline': tomorrow.isoformat()})
                    )
                    count += 1
                finally:
                    loop.close()

            self.edit_message(chat_id, message_id, f"Snoozed {count} overdue task{'s' if count != 1 else ''} to tomorrow (9:00 AM).")

        except Exception as e:
            print(f"Error in snooze_overdue: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _handle_focus_today(self, user_id, chat_id, message_id):
        """Show only today's tasks."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []
            now = datetime.now(BRISBANE_TZ)
            today = now.date()

            due_today = []
            for task in pending:
                deadline_str = task.get('deadline', '')
                if not deadline_str:
                    continue
                try:
                    deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    if deadline_dt.tzinfo is None:
                        deadline_dt = BRISBANE_TZ.localize(deadline_dt)
                    if deadline_dt.date() == today:
                        due_today.append(task)
                except:
                    continue

            if not due_today:
                self.edit_message(chat_id, message_id, "No tasks due today.")
                return

            message = f"TODAY'S TASKS ({len(due_today)}):\n\n"
            for i, task in enumerate(due_today, 1):
                message += f"{i}. {task.get('title')}\n"

            # Add done buttons
            buttons = []
            for task in due_today[:5]:
                short_title = task.get('title', 'Task')[:20]
                buttons.append([
                    {'text': f'Done: {short_title}', 'callback_data': f'task_done:{task.get("task_id")}'}
                ])

            reply_markup = {'inline_keyboard': buttons}
            self.edit_message(chat_id, message_id, message, reply_markup=reply_markup)

        except Exception as e:
            print(f"Error in focus_today: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _handle_start_task(self, user_id, chat_id, message_id, task_id):
        """Start a task discussion session for specific task."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            task = None
            for t in tasks:
                if t.get('task_id') == task_id:
                    task = t
                    break

            if not task:
                self.edit_message(chat_id, message_id, "Task not found.")
                return

            # Start task discussion session
            self.task_discussion_sessions[user_id] = {
                'task_id': task_id,
                'task_title': task.get('title'),
                'started_at': datetime.now(BRISBANE_TZ)
            }

            message = f"Let's work on: {task.get('title')}\n\n"
            if task.get('description'):
                message += f"Description: {task.get('description')}\n"
            message += f"Current progress: {task.get('progress_percent', 0)}%\n\n"
            message += "Tell me how it's going or what you need help with!\n"
            message += "Quick replies: 'done', '50%', 'blocked', 'skip'"

            self.edit_message(chat_id, message_id, message)

        except Exception as e:
            print(f"Error in start_task: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _handle_show_priority(self, user_id, chat_id, message_id, priority='high'):
        """Filter tasks by priority."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []

            if priority == 'high':
                filtered = [t for t in pending if t.get('priority') in ('high', 'critical')]
            else:
                filtered = [t for t in pending if t.get('priority') == priority]

            if not filtered:
                self.edit_message(chat_id, message_id, f"No {priority} priority tasks found.")
                return

            message = f"HIGH PRIORITY TASKS ({len(filtered)}):\n\n"
            for i, task in enumerate(filtered, 1):
                priority_label = task.get('priority', 'normal').upper()
                message += f"{i}. [{priority_label}] {task.get('title')}\n"

            # Add done buttons
            buttons = []
            for task in filtered[:5]:
                short_title = task.get('title', 'Task')[:18]
                buttons.append([
                    {'text': f'Done: {short_title}', 'callback_data': f'task_done:{task.get("task_id")}'}
                ])

            reply_markup = {'inline_keyboard': buttons}
            self.edit_message(chat_id, message_id, message, reply_markup=reply_markup)

        except Exception as e:
            print(f"Error in show_priority: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

    def _handle_show_all_tasks(self, user_id, chat_id, message_id):
        """Redirect to /tasks command output."""
        try:
            tasks = self._get_user_tasks_sync(user_id)
            pending = [t for t in tasks if t.get('status') == 'pending'] if tasks else []

            if not pending:
                self.edit_message(chat_id, message_id, "No pending tasks.")
                return

            message = f"ALL PENDING TASKS ({len(pending)}):\n\n"

            # Group by priority
            critical = [t for t in pending if t.get('priority') == 'critical']
            high = [t for t in pending if t.get('priority') == 'high']
            medium = [t for t in pending if t.get('priority') == 'medium']
            low = [t for t in pending if t.get('priority') == 'low']
            normal = [t for t in pending if t.get('priority') not in ('critical', 'high', 'medium', 'low')]

            count = 0
            for group, label in [(critical, 'CRITICAL'), (high, 'HIGH'), (medium, 'MEDIUM'), (normal, ''), (low, 'LOW')]:
                for task in group:
                    if count >= 15:
                        break
                    prefix = f"[{label}] " if label else ""
                    message += f"- {prefix}{task.get('title')}\n"
                    count += 1

            if len(pending) > 15:
                message += f"\n... and {len(pending) - 15} more tasks"

            self.edit_message(chat_id, message_id, message)

        except Exception as e:
            print(f"Error in show_all_tasks: {e}")
            self.edit_message(chat_id, message_id, f"Error: {e}")

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

        text_lower = text.lower()

        # Skip if message contains time-related words - let AI handle scheduling requests
        time_indicators = ['am', 'pm', 'tomorrow', 'today', 'morning', 'afternoon', 'evening',
                          'remind', 'calendar', 'schedule', 'deadline', 'by ', 'at ', 'o\'clock',
                          'email', 'task', 'add', 'create', 'new']
        if any(indicator in text_lower for indicator in time_indicators):
            return None  # Let AI handle it

        # Check for percentage patterns: "50%", "50 percent", "about 50%"
        # Removed "at X" pattern as it conflicts with time expressions like "at 9am"
        percent_match = re.search(r'(\d+)\s*%|(\d+)\s*percent|about\s+(\d+)\s*%', text_lower)
        if percent_match:
            progress = int(next(g for g in percent_match.groups() if g is not None))
            result = self._update_task_progress_sync(user_id, task_id, progress)
            if progress >= 100:
                # End session on completion
                if user_id in self.task_discussion_sessions:
                    del self.task_discussion_sessions[user_id]
                return f"Awesome! '{task_title}' marked as complete! I'll archive it in 7 days."
            return f"Got it - '{task_title}' is now at {progress}%. Keep it up!"

        # Check for completion words - but only if they appear to be direct progress updates
        # Skip if the message is longer (likely a different request) or contains scheduling words
        completion_words = ['done', 'complete', 'completed', 'finished']
        # "finish" removed - too easily triggered by "finish this by X"
        if len(text_lower.split()) <= 3 and any(word in text_lower for word in completion_words):
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

    def _load_user_settings(self):
        """Load user settings from persistent storage (Settings sheet)"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def load():
                settings_df = await self.sheets_client.get_sheet_data("Settings")
                if settings_df.empty:
                    return {}, {}

                checkin_hours = {}
                skipped_events = {}

                for _, row in settings_df.iterrows():
                    user_id = str(row.get('user_id', ''))
                    key = str(row.get('setting_key', ''))
                    value = str(row.get('setting_value', ''))

                    if not user_id or not key:
                        continue

                    if key == 'checkin_hours':
                        if value == 'off':
                            checkin_hours[user_id] = []
                        elif value:
                            try:
                                checkin_hours[user_id] = [int(h.strip()) for h in value.split(',')]
                            except ValueError:
                                pass

                    elif key == 'skipped_events':
                        if value:
                            skipped_events[user_id] = set(value.split('|'))

                return checkin_hours, skipped_events

            self.user_checkin_hours, self.skipped_calendar_events = loop.run_until_complete(load())
        except Exception as e:
            print(f"Error loading user settings: {e}")
            self.user_checkin_hours = {}
            self.skipped_calendar_events = {}
        finally:
            loop.close()

    def _save_user_setting(self, user_id: str, setting_key: str, setting_value: str):
        """Save a user setting to persistent storage"""
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self.sheets_client.set_user_setting(user_id, setting_key, setting_value)
            )
        except Exception as e:
            print(f"Error saving user setting: {e}")
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