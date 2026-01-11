from typing import List, Dict, Any, Optional
import json
from datetime import datetime
from app.services.ai_service import AIService
from app.agents.memory_agent import MemoryAgent
from app.agents.task_agent import TaskAgent
from app.tools.web_search import get_web_search

# Max context limits to avoid token overflow
MAX_MEMORIES = 5
MAX_TASKS_DEFAULT = 5  # Normal requests
MAX_TASKS_DISCUSSION = 15  # When discussing tasks/priorities
MAX_CONVERSATIONS_DEFAULT = 5  # Normal requests
MAX_CONVERSATIONS_DISCUSSION = 8  # For multi-turn discussions
MAX_VALUE_LENGTH = 200

# Keywords that indicate user wants to discuss tasks
TASK_DISCUSSION_KEYWORDS = [
    'priorit', 'too many', 'too much', 'overwhelm', 'workload', 'what should i',
    'how do i', 'help me with', 'best way', 'which task', 'what task',
    'to do list', 'todo', 'to-do', 'my tasks', 'busy', 'get through',
    'tackle', 'approach', 'strategy', 'plan', 'focus on', 'juggle',
    'manage my', 'work is nuts', 'stressed', 'swamped'
]

class ConversationAgent:
    def __init__(self, ai_service: AIService, memory_agent: MemoryAgent, task_agent: TaskAgent,
                 vector_processor=None, calendar_service=None, email_service=None, keep_service=None):
        self.ai = ai_service
        self.memory = memory_agent
        self.tasks = task_agent
        self.web_search = get_web_search()
        self.vector = vector_processor  # Optional: enables semantic search for context
        self.calendar = calendar_service  # Optional: enables calendar integration
        self.email = email_service  # Optional: enables email drafts
        self.keep = keep_service  # Optional: enables Google Keep notes

    def _compress_context(self, context: Dict, user_message: str) -> Dict:
        """Compress context to fit within token limits using semantic relevance"""
        compressed = {
            "memories": [],
            "tasks": [],
            "conversations": [],
            "calendar_events": []
        }
        
        # Get upcoming calendar events if calendar is available and query seems relevant
        calendar_keywords = ['calendar', 'event', 'schedule', 'scheduled', 'meeting', 'appointment', 'busy', 'free', 'today', 'tomorrow', 'this week', 'next week', 'week']
        user_lower = user_message.lower()
        print(f"[DEBUG] Calendar check - user_lower: '{user_lower}'")
        print(f"[DEBUG] Calendar service available: {self.calendar is not None}")
        if self.calendar and any(kw in user_lower for kw in calendar_keywords):
            try:
                import asyncio
                import nest_asyncio
                import pytz
                from datetime import datetime, timedelta
                nest_asyncio.apply()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    brisbane_tz = pytz.timezone('Australia/Brisbane')
                    now = datetime.now(brisbane_tz)

                    # Determine date range based on query
                    if 'tomorrow' in user_lower:
                        target_date = now + timedelta(days=1)
                        events = loop.run_until_complete(self.calendar.get_events_for_date(target_date))
                        date_label = target_date.strftime('%A, %B %d')
                    elif 'today' in user_lower:
                        events = loop.run_until_complete(self.calendar.get_events_for_date(now))
                        date_label = "today"
                    else:
                        # General calendar query - get next 7 days
                        events = loop.run_until_complete(self.calendar.get_upcoming_events(max_results=10, days_ahead=7))
                        date_label = "next 7 days"

                    # Filter out daily recurring events (like Panchang, Yoga Nidra, Gratitude)
                    daily_recurring_keywords = ['panchang', 'yoga nidra', 'gratitude', 'meditation', 'daily']
                    filtered_events = []
                    for event in events:
                        title_lower = event.get('summary', '').lower()
                        # Skip if it matches daily recurring keywords
                        if any(kw in title_lower for kw in daily_recurring_keywords):
                            continue
                        filtered_events.append(event)

                    print(f"[DEBUG] Calendar events fetched: {len(events) if events else 0} total, {len(filtered_events)} after filtering daily recurring")
                    if filtered_events:
                        for event in filtered_events:
                            start_str = event.get('start', '')
                            # Format time nicely
                            try:
                                if 'T' in start_str:
                                    dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                                    time_display = dt.strftime('%I:%M%p on %a %b %d')
                                else:
                                    time_display = f"All day on {start_str}"
                            except:
                                time_display = start_str

                            compressed["calendar_events"].append({
                                "title": event.get('summary', 'Untitled')[:100],
                                "time": time_display,
                                "location": event.get('location', '')[:50] if event.get('location') else None
                            })
                            print(f"[DEBUG] Added calendar event: {event.get('summary', 'Untitled')} at {time_display}")
                    else:
                        # Explicitly note no events for the queried period
                        compressed["calendar_events"].append({
                            "note": f"No events scheduled for {date_label}"
                        })
                        print(f"[DEBUG] No events - added note: No events scheduled for {date_label}")
                finally:
                    loop.close()
            except Exception as e:
                print(f"Error getting calendar events: {e}")
        
        # Get relevant memories using semantic search if available
        memories = context.get('memories', [])
        if memories:
            if self.vector and len(memories) > MAX_MEMORIES:
                # Use semantic search for better relevance (async handled via sync wrapper)
                try:
                    import asyncio
                    import nest_asyncio
                    nest_asyncio.apply()
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        relevant = loop.run_until_complete(
                            self.vector.search_similar(user_message, memories, limit=MAX_MEMORIES, threshold=0.2)
                        )
                        for mem in relevant:
                            compressed["memories"].append({
                                "key": mem.get('key', '')[:50],
                                "value": str(mem.get('value', ''))[:MAX_VALUE_LENGTH],
                                "category": mem.get('category', 'knowledge'),
                                "relevance": round(mem.get('similarity_score', 0), 2)
                            })
                    finally:
                        loop.close()
                except Exception as e:
                    print(f"Semantic search failed, falling back to keyword: {e}")
                    # Fall through to keyword matching
                    
            # Fallback: keyword matching if no vector processor or semantic search failed
            if not compressed["memories"]:
                user_words = set(user_message.lower().split())
                scored_memories = []
                for mem in memories:
                    value = str(mem.get('value', '')).lower()
                    key = str(mem.get('key', '')).lower()
                    mem_words = set(value.split() + key.split())
                    overlap = len(user_words & mem_words)
                    scored_memories.append((overlap, mem))
                
                scored_memories.sort(key=lambda x: x[0], reverse=True)
                for _, mem in scored_memories[:MAX_MEMORIES]:
                    compressed["memories"].append({
                        "key": mem.get('key', '')[:50],
                        "value": str(mem.get('value', ''))[:MAX_VALUE_LENGTH],
                        "category": mem.get('category', 'knowledge')
                    })
        
        # Determine if this is a task discussion (use more context) or normal request
        is_task_discussion = any(kw in user_lower for kw in TASK_DISCUSSION_KEYWORDS)
        max_tasks = MAX_TASKS_DISCUSSION if is_task_discussion else MAX_TASKS_DEFAULT
        max_conversations = MAX_CONVERSATIONS_DISCUSSION if is_task_discussion else MAX_CONVERSATIONS_DEFAULT

        if is_task_discussion:
            print(f"[DEBUG] Task discussion detected - using expanded context (up to {max_tasks} tasks)")

        # Get relevant tasks (prioritize pending and high priority)
        tasks = context.get('tasks', [])
        if tasks:
            # Sort: pending first, then by priority
            priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
            sorted_tasks = sorted(tasks, key=lambda t: (
                0 if t.get('status') == 'pending' else 1,
                priority_order.get(t.get('priority', 'medium'), 2)
            ))
            for task in sorted_tasks[:max_tasks]:
                compressed["tasks"].append({
                    "title": task.get('title', '')[:100],
                    "status": task.get('status', 'pending'),
                    "priority": task.get('priority', 'medium'),
                    "deadline": task.get('deadline', '')[:20] if task.get('deadline') else None
                })

        # Get recent conversations - format as clear dialogue for multi-turn understanding
        conversations = context.get('conversations', [])
        if conversations:
            recent_convs = conversations[-max_conversations:]
            for conv in recent_convs:
                msg_type = conv.get('message_type', 'user')
                content = str(conv.get('content', ''))[:200]
                # Format as clear dialogue: "User: ..." or "Assistant: ..."
                speaker = "User" if msg_type == 'user' else "Assistant"
                compressed["conversations"].append(f"{speaker}: {content}")
        
        return compressed

    async def handle_conversation_flow(self, user_id: str, user_message: str, context: Dict) -> str:
        """Manage conversation flow and determine next actions"""
        try:
            # COMPRESS context to fit within token limits
            compressed_context = self._compress_context(context, user_message)
            print(f"Compressed context: {len(compressed_context['memories'])} memories, {len(compressed_context['tasks'])} tasks")
            
            # Get AI analysis of the user input with compressed context
            analysis = await self.ai.reason_and_act(compressed_context, user_message)

            # ALWAYS execute memory actions first, regardless of gaps
            for memory_action in analysis.get('memory_actions', []):
                await self._execute_memory_action(user_id, memory_action)

            # Store any extracted personal information as memories
            personal_info = analysis.get('personal_info_extracted', [])
            if personal_info:
                # Create a comprehensive memory about the user's business/role
                business_keywords = ['company', 'business', 'health', 'radiology', 'role', 'work', 'job', 'run', 'own', 'manage']
                business_info = [info for info in personal_info if any(keyword in info.lower() for keyword in business_keywords)]

                if business_info:
                    # Generate a unique key based on the content
                    key_base = business_info[0].lower().replace(' ', '_')[:30]
                    business_memory = f"The user is involved with {', '.join(business_info)}. Context: {user_message[:150]}..."
                    await self._execute_memory_action(user_id, {
                        'action': 'store',
                        'category': 'work',
                        'key': f'business_{key_base}',
                        'value': business_memory
                    })

                # Store all extracted facts as separate memories
                for i, info_item in enumerate(personal_info):
                    # Create a safe key from the info item
                    safe_key = info_item.lower().replace(' ', '_').replace("'", "")[:40]
                    await self._execute_memory_action(user_id, {
                        'action': 'store',
                        'category': 'knowledge',
                        'key': f'fact_{safe_key}',
                        'value': info_item
                    })

            # Execute task actions
            for task_action in analysis.get('task_actions', []):
                await self._execute_task_action(user_id, task_action)
            
            # Execute calendar actions
            for calendar_action in analysis.get('calendar_actions', []):
                result = await self._execute_calendar_action(calendar_action)
                if result:
                    # Append calendar result to response if not already mentioned
                    current_response = analysis.get('response', '')
                    if result not in current_response:
                        analysis['response'] = f"{current_response}\n\n{result}"

            # Execute email actions
            for email_action in analysis.get('email_actions', []):
                result = await self._execute_email_action(email_action)
                if result:
                    current_response = analysis.get('response', '')
                    if result not in current_response:
                        analysis['response'] = f"{current_response}\n\n{result}"

            # Execute Keep actions
            for keep_action in analysis.get('keep_actions', []):
                result = await self._execute_keep_action(keep_action)
                if result:
                    current_response = analysis.get('response', '')
                    if result not in current_response:
                        analysis['response'] = f"{current_response}\n\n{result}"

            # Handle follow-up answers (e.g., user providing end date for recurring task)
            if analysis.get('intent') == 'followup_answer':
                followup_context = analysis.get('followup_context') or ''
                print(f"Follow-up answer detected: {followup_context}")

                # If this is an end date answer for a recurring task, update the most recent recurring task
                if followup_context and ('end' in followup_context.lower() or 'recurrence' in followup_context.lower()):
                    # Look for task actions with recurrence_end_date to apply
                    for task_action in analysis.get('task_actions', []):
                        if task_action.get('action') == 'update':
                            end_date = task_action.get('data', {}).get('recurrence_end_date')
                            if end_date:
                                # Find most recent recurring task and update it
                                await self._update_recent_recurring_task_end_date(user_id, end_date)

            # Handle web search if requested
            web_search_request = analysis.get('web_search')
            search_results = None
            if web_search_request and web_search_request.get('needed'):
                search_query = web_search_request.get('query', user_message)
                print(f"Executing web search: {search_query}")
                search_results = await self.web_search.search_with_scraping(search_query, num_results=5)
                
                if search_results:
                    # Re-run AI with search results for better response
                    search_context = self.web_search.format_results_for_ai(search_results)
                    enhanced_context = {
                        **context,
                        'web_search_results': search_context
                    }
                    # Get enhanced response with search results
                    enhanced_analysis = await self.ai.reason_and_act(enhanced_context, 
                        f"{user_message}\n\n[Web Search Results]:\n{search_context}")
                    analysis = enhanced_analysis  # Use enhanced response

            # Handle information gaps - engage more naturally
            if analysis.get('gaps'):
                question = analysis['gaps'][0]  # Ask only one question

                # If we learned new personal information, acknowledge it first
                if personal_info:
                    # Create a natural acknowledgment based on what was learned
                    info_summary = ', '.join(personal_info[:2])
                    if len(personal_info) > 2:
                        info_summary += f' and {len(personal_info) - 2} more detail(s)'
                    ack_response = f"Got it! I've noted: {info_summary}. {question}"
                    return ack_response
                else:
                    return question

            # Check if conversation should end
            if analysis.get('should_end_conversation'):
                response = analysis.get('response', 'Conversation completed.')
                return f"{response}\n\n💭 If you need anything else, just let me know!"

            # Return the AI's response
            response = analysis.get('response', '')
            if not response or response.strip() == '':
                # If AI returned empty response, provide something useful
                response = "I received your message but I'm not sure how to help. Could you give me more details?"
            return response

        except Exception as e:
            print(f"Error in conversation flow: {e}")
            import traceback
            traceback.print_exc()
            return "Sorry, I ran into a problem processing that. Could you try rephrasing?"

    async def _execute_memory_action(self, user_id: str, action: Dict):
        """Execute memory-related actions including updates"""
        try:
            action_type = action.get('action')
            category = action.get('category', 'knowledge')
            key = action.get('key', f"info_{int(datetime.now().timestamp())}")
            value = action.get('value', '')
            find_by = action.get('find_by', '')  # Used for finding existing memories to update

            if action_type == 'store':
                result = await self.memory.store_memory(user_id, category, key, value)
                print(f"Memory store result: {result}")

            elif action_type == 'update':
                # First try to find by key directly
                result = await self.memory.update_memory(user_id, key, value)
                
                # If not found and find_by is provided, search for similar memory
                if 'not found' in result.lower() and find_by:
                    similar = await self.memory.retrieve_memories(user_id, find_by, limit=1)
                    if similar:
                        result = await self.memory.update_memory(user_id, similar[0]['key'], value)
                        print(f"Updated memory found by search: {similar[0]['key']}")
                
                print(f"Memory update result: {result}")

            elif action_type == 'merge':
                # Find similar memories and merge
                search_term = find_by if find_by else value
                similar = await self.memory.retrieve_memories(user_id, search_term, limit=1)
                if similar:
                    existing_value = similar[0]['value']
                    merged = await self.ai.merge_memories(existing_value, value)
                    result = await self.memory.update_memory(user_id, similar[0]['key'], merged)
                    print(f"Memory merge result: {result}")

            elif action_type == 'delete':
                result = await self.memory.delete_memory(user_id, key)
                print(f"Memory delete result: {result}")

        except Exception as e:
            print(f"Error executing memory action: {e}")

    async def _execute_task_action(self, user_id: str, action: Dict):
        """Execute task-related actions including updates by title search"""
        try:
            action_type = action.get('action')
            task_data = action.get('data', {})
            find_by = action.get('find_by', '')  # Used for finding existing tasks

            if action_type == 'create':
                title = task_data.get('title', 'New Task')
                description = task_data.get('description')
                priority = task_data.get('priority', 'medium')
                deadline = task_data.get('deadline')
                
                # Recurring task parameters
                is_recurring = task_data.get('is_recurring', False)
                recurrence_pattern = task_data.get('recurrence_pattern')
                recurrence_end_date = task_data.get('recurrence_end_date')

                result = await self.tasks.create_task(
                    user_id, title, description, priority, deadline,
                    is_recurring=is_recurring,
                    recurrence_pattern=recurrence_pattern,
                    recurrence_end_date=recurrence_end_date
                )
                print(f"Task create result: {result}")

            elif action_type == 'update':
                task_id = action.get('task_id')
                
                # If no task_id, try to find by title search
                if not task_id and find_by:
                    task_id = await self._find_task_by_title(user_id, find_by)
                
                if task_id:
                    # Update priority if specified
                    new_priority = task_data.get('priority')
                    if new_priority:
                        result = await self.tasks.update_task_priority(user_id, task_id, new_priority)
                        print(f"Task priority update: {result}")

                    # Update deadline if specified
                    new_deadline = task_data.get('deadline')
                    if new_deadline:
                        result = await self.tasks.update_task_deadline(user_id, task_id, new_deadline)
                        print(f"Task deadline update: {result}")
                    
                    # Update status if specified
                    new_status = task_data.get('status')
                    if new_status == 'complete':
                        result = await self.tasks.complete_task(user_id, task_id)
                        print(f"Task complete result: {result}")
                else:
                    print(f"Could not find task to update. find_by: {find_by}")

            elif action_type == 'complete':
                task_id = action.get('task_id')
                
                # If no task_id, try to find by title search
                if not task_id and find_by:
                    task_id = await self._find_task_by_title(user_id, find_by)
                
                if task_id:
                    result = await self.tasks.complete_task(user_id, task_id)
                    print(f"Task complete result: {result}")
                else:
                    print(f"Could not find task to complete. find_by: {find_by}")

        except Exception as e:
            print(f"Error executing task action: {e}")
    
    async def _find_task_by_title(self, user_id: str, search_term: str) -> str:
        """Find a task by searching its title"""
        try:
            tasks = await self.tasks.get_prioritized_tasks(user_id, limit=50, status='all')
            search_lower = search_term.lower()
            
            # First, try exact match
            for task in tasks:
                if task.get('title', '').lower() == search_lower:
                    return task.get('task_id')
            
            # Then try partial match
            for task in tasks:
                if search_lower in task.get('title', '').lower():
                    return task.get('task_id')
            
            # Finally, try word-by-word match
            search_words = search_lower.split()
            for task in tasks:
                title_lower = task.get('title', '').lower()
                if all(word in title_lower for word in search_words[:3]):  # Match first 3 words
                    return task.get('task_id')
            
            return None
        except Exception as e:
            print(f"Error finding task by title: {e}")
            return None

    async def _execute_calendar_action(self, action: Dict) -> Optional[str]:
        """Execute calendar-related actions"""
        if not self.calendar:
            return "Calendar not configured. Please set up Google Calendar integration."
        
        try:
            action_type = action.get('action')
            
            if action_type == 'list_events':
                days = action.get('days_ahead', 7)
                events = await self.calendar.get_upcoming_events(max_results=10, days_ahead=days)
                if events:
                    return "Upcoming events:\n" + self.calendar.format_events_for_display(events)
                return "No upcoming events found."
            
            elif action_type == 'create_event':
                from dateutil import parser as date_parser
                
                summary = action.get('summary', 'New Event')
                start_str = action.get('start_time')
                end_str = action.get('end_time')
                location = action.get('location')
                description = action.get('description')
                
                if not start_str:
                    return "Need a start time to create an event."
                
                # Parse times
                try:
                    start_time = date_parser.parse(start_str)
                    end_time = date_parser.parse(end_str) if end_str else None
                except:
                    return f"Couldn't parse the date/time: {start_str}"
                
                result = await self.calendar.create_event(
                    summary=summary,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    description=description
                )
                
                if result:
                    return f"Event created: {result.get('summary')} on {result.get('start', '')[:16]}"
                return "Failed to create event."
            
            elif action_type == 'delete_event':
                event_id = action.get('event_id')
                if event_id:
                    success = await self.calendar.delete_event(event_id)
                    return "Event deleted." if success else "Failed to delete event."
                return "Need an event ID to delete."
            
        except Exception as e:
            print(f"Error executing calendar action: {e}")
            return f"Calendar error: {str(e)}"

        return None

    async def _execute_email_action(self, action: Dict) -> Optional[str]:
        """Execute email-related actions (create draft, send, add contact, reply)"""
        if not self.email:
            return "Email not configured. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env"

        try:
            action_type = action.get('action')

            if action_type == 'create_draft':
                to = action.get('to', '')
                subject = action.get('subject', '')
                body = action.get('body', '')

                if not to:
                    return "Need a recipient to create a draft."
                if not subject and not body:
                    return "Need a subject or body for the email."

                result = await self.email.create_draft(to, subject, body)
                if result:
                    return f"Draft created: '{subject}' to {result.get('to')}"
                return "Failed to create draft. Check if contact exists."

            elif action_type == 'reply_to_email':
                # Reply to an existing email thread
                sender_name = action.get('sender_name', '')
                body = action.get('body', '')

                if not sender_name:
                    return "Need the sender's name to find the email to reply to."
                if not body:
                    return "Need a message body for the reply."

                # Find the original email from this sender (search last 30 emails)
                original_email = await self.email.find_email_from_sender(sender_name, max_results=30)
                if not original_email:
                    return f"Could not find a recent email from '{sender_name}' in your inbox."

                # Create the reply draft
                result = await self.email.create_reply_draft(original_email, body)
                if result:
                    return f"Reply draft created to {result.get('to')} - Re: {original_email.get('subject', 'No subject')}"
                return "Failed to create reply draft."

            elif action_type == 'get_recent_emails':
                max_emails = action.get('max_results', 10)
                emails = await self.email.get_recent_emails(max_results=max_emails)
                if emails:
                    email_list = []
                    for e in emails[:10]:
                        email_list.append(f"- From: {e.get('from_name', 'Unknown')} ({e.get('from_email', '')})")
                        email_list.append(f"  Subject: {e.get('subject', 'No subject')}")
                        email_list.append(f"  Snippet: {e.get('snippet', '')[:100]}...")
                    return "Recent emails:\n" + "\n".join(email_list)
                return "No recent emails found."

            elif action_type == 'send_email':
                to = action.get('to', '')
                subject = action.get('subject', '')
                body = action.get('body', '')

                if not to or not subject or not body:
                    return "Need recipient, subject, and body to send email."

                result = await self.email.send_email(to, subject, body)
                if result:
                    return f"Email sent to {result.get('to')}"
                return "Failed to send email."

            elif action_type == 'add_contact':
                name = action.get('name', '')
                email_addr = action.get('email', '')

                if not name or not email_addr:
                    return "Need both name and email to add a contact."

                self.email.add_contact(name, email_addr)
                return f"Contact added: {name} -> {email_addr}"

            elif action_type == 'list_contacts':
                contacts = self.email.list_contacts()
                if contacts:
                    contact_list = "\n".join([f"- {name}: {email}" for name, email in contacts.items()])
                    return f"Your contacts:\n{contact_list}"
                return "No contacts saved yet."

            elif action_type == 'list_drafts':
                drafts = await self.email.list_drafts(max_results=5)
                if drafts:
                    draft_list = "\n".join([f"- {d['subject']} (to: {d['to']})" for d in drafts])
                    return f"Your drafts:\n{draft_list}"
                return "No drafts found."

        except Exception as e:
            print(f"Error executing email action: {e}")
            return f"Email error: {str(e)}"

        return None

    async def _execute_keep_action(self, action: Dict) -> Optional[str]:
        """Execute Google Keep actions (list notes, add to note, create note)"""
        if not self.keep:
            return "Google Keep not configured. Add GOOGLE_KEEP_TOKEN to .env"

        try:
            action_type = action.get('action')

            if action_type == 'list_notes':
                max_notes = action.get('max_results', 10)
                notes = await self.keep.list_notes(max_results=max_notes)
                if notes:
                    note_list = []
                    for n in notes[:10]:
                        title = n.get('title', '(Untitled)')
                        pinned = ' [pinned]' if n.get('pinned') else ''
                        note_list.append(f"- {title}{pinned}")
                    return "Your Keep notes:\n" + "\n".join(note_list)
                return "No notes found in Google Keep."

            elif action_type == 'search_notes':
                query = action.get('query', '')
                if not query:
                    return "Need a search term to find notes."

                notes = await self.keep.search_notes(query, max_results=5)
                if notes:
                    note_list = []
                    for n in notes:
                        title = n.get('title', '(Untitled)')
                        note_list.append(f"- {title}")
                    return f"Notes matching '{query}':\n" + "\n".join(note_list)
                return f"No notes found matching '{query}'."

            elif action_type == 'add_to_note':
                # Add text to an existing note
                note_title = action.get('note_title', '')
                text_to_add = action.get('text', '')

                if not note_title:
                    return "Need a note title to add to."
                if not text_to_add:
                    return "Need text to add to the note."

                # Find the note by title
                note = await self.keep.find_note_by_title(note_title)
                if not note:
                    return f"Could not find a note matching '{note_title}'. Try listing your notes first."

                # Add the text to the note
                result = await self.keep.add_to_note(note['id'], text_to_add, position='top')
                if result:
                    return f"Added to '{note['title']}':\n\"{text_to_add}\"\n\nWould you like to add more details?"
                return "Failed to add to note."

            elif action_type == 'create_note':
                title = action.get('title', '')
                text = action.get('text', '')
                pinned = action.get('pinned', False)

                if not title:
                    return "Need a title to create a note."

                result = await self.keep.create_note(title, text, pinned)
                if result:
                    return f"Created note: '{title}'"
                return "Failed to create note."

            elif action_type == 'get_note':
                note_title = action.get('note_title', '')
                if not note_title:
                    return "Need a note title to view."

                note = await self.keep.find_note_by_title(note_title)
                if note:
                    text_preview = note.get('text', '')[:500]
                    if len(note.get('text', '')) > 500:
                        text_preview += '...'
                    return f"Note: {note['title']}\n\n{text_preview}"
                return f"Could not find a note matching '{note_title}'."

        except Exception as e:
            print(f"Error executing Keep action: {e}")
            return f"Keep error: {str(e)}"

        return None

    async def _update_recent_recurring_task_end_date(self, user_id: str, end_date: str):
        """Find the most recently created recurring task and update its end date"""
        try:
            tasks = await self.tasks.get_prioritized_tasks(user_id, limit=20, status='all')
            
            # Find recurring tasks without an end date, sorted by creation time (most recent first)
            recurring_tasks = [
                t for t in tasks 
                if str(t.get('is_recurring', 'false')).lower() == 'true'
                and not t.get('recurrence_end_date')
            ]
            
            if recurring_tasks:
                # Sort by created_at descending to get most recent
                recurring_tasks.sort(
                    key=lambda t: t.get('created_at', ''), 
                    reverse=True
                )
                task_to_update = recurring_tasks[0]
                task_id = task_to_update.get('task_id')
                
                if task_id:
                    # Update the task's recurrence end date
                    result = await self.tasks.update_task_field(
                        user_id, task_id, 'recurrence_end_date', end_date
                    )
                    print(f"Updated recurring task '{task_to_update.get('title')}' with end date: {end_date}")
                    return result
            else:
                print("No recurring task without end date found to update")
                
        except Exception as e:
            print(f"Error updating recurring task end date: {e}")

    async def detect_conversation_intent(self, user_message: str, context: Dict) -> str:
        """Detect the primary intent of the user's message"""
        prompt = f"""
        Analyze this user message and determine the primary intent:

        Message: "{user_message}"
        Recent context: {json.dumps(context.get('conversations', [])[-3:])}

        Possible intents:
        - task_creation: User wants to create a task or to-do
        - task_management: User wants to update, complete, or view tasks
        - memory_storage: User is sharing information to remember
        - memory_retrieval: User is asking about stored information
        - question_asking: User has a general question
        - conversation: General chat or clarification
        - goodbye: User wants to end conversation

        Return only the intent name:
        """

        try:
            response = await self.ai.client.chat.completions.create(
                model=self.ai.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1
            )
            intent = response.choices[0].message.content.strip().lower()
            return intent
        except Exception as e:
            print(f"Error detecting intent: {e}")
            return "conversation"

    async def generate_proactive_response(self, user_id: str, context: Dict) -> str:
        """Generate proactive suggestions based on user context"""
        try:
            # Check for overdue tasks
            overdue = await self.tasks.get_overdue_tasks(user_id)
            if overdue:
                return f"⚠️ You have {len(overdue)} overdue task(s). Would you like me to show them to you?"

            # Check for high-priority pending tasks
            pending = await self.tasks.get_prioritized_tasks(user_id, limit=3)
            high_priority = [t for t in pending if t.get('priority') == 'high']
            if high_priority:
                return f"🔥 You have {len(high_priority)} high-priority task(s) pending. Need help with them?"

            # Check if user has been inactive with memories
            memories = context.get('memories', [])
            if not memories:
                return "💭 I don't have any memories stored for you yet. Would you like to tell me something about yourself?"

            return None  # No proactive response needed

        except Exception as e:
            print(f"Error generating proactive response: {e}")
            return None

    async def should_end_conversation(self, conversation_history: List[Dict]) -> bool:
        """Determine if the conversation should naturally end"""
        if not conversation_history:
            return False

        # Check for goodbye keywords in recent messages
        recent_messages = [msg.get('content', '').lower() for msg in conversation_history[-3:]]
        goodbye_keywords = ['bye', 'goodbye', 'see you', 'thanks', 'thank you', 'that\'s all', 'done']

        for msg in recent_messages:
            if any(keyword in msg for keyword in goodbye_keywords):
                return True

        # Check conversation state
        state = await self.ai.detect_conversation_state(conversation_history)
        return state == 'completing'

    async def summarize_conversation(self, conversation_history: List[Dict]) -> str:
        """Generate a summary of the conversation"""
        if not conversation_history:
            return "No conversation to summarize."

        history_text = "\n".join([
            f"{'User' if msg.get('message_type') == 'user' else 'Assistant'}: {msg.get('content', '')}"
            for msg in conversation_history[-20:]  # Last 20 messages
        ])

        prompt = f"""
        Summarize this conversation between a user and an AI assistant:

        {history_text}

        Provide a brief summary of what was discussed and any actions taken:
        """

        try:
            response = await self.ai.client.chat.completions.create(
                model=self.ai.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error summarizing conversation: {e}")
            return "Conversation summary unavailable."