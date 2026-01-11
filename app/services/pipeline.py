"""
Multi-Stage Pipeline Orchestrator

Coordinates the 4-stage processing pipeline:
1. Router (fast intent classification)
2. Context Fetcher (parallel context retrieval)
3. Action Planner (entity extraction + action planning)
4. Response Generator (natural response)

Key optimizations:
- Parallel context fetching (starts before routing completes)
- Early exit for simple chat
- Confirmation flow for high-stakes actions
- Explicit success/failure tracking
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import pytz

from app.services.message_router import MessageRouter
from app.services.context_fetcher import ContextFetcher, create_context_fetcher
from app.services.action_planner import ActionPlanner, ConfirmationManager, get_confirmation_manager
from app.services.response_generator import ResponseGenerator

BRISBANE_TZ = pytz.timezone('Australia/Brisbane')


class Pipeline:
    """
    Orchestrates the multi-stage message processing pipeline.

    Usage:
        pipeline = Pipeline(groq_api_key=key, ...)
        response = await pipeline.process_message(user_id, message, history)
    """

    def __init__(
        self,
        groq_api_key: str,
        router_model: str = "llama-3.3-70b-versatile",
        planner_model: str = "llama-3.3-70b-versatile",
        response_model: str = "llama-3.3-70b-versatile",
        memory_agent=None,
        task_agent=None,
        calendar_service=None,
        email_service=None,
        keep_service=None,
        vector_processor=None,
        sheets_client=None,
        on_status: Callable[[str], None] = None
    ):
        """
        Initialize the pipeline.

        Args:
            groq_api_key: API key for Groq
            router_model: Model for Stage 1
            planner_model: Model for Stage 3
            response_model: Model for Stage 4
            memory_agent: MemoryAgent instance
            task_agent: TaskAgent instance
            calendar_service: CalendarService instance
            email_service: EmailService instance
            keep_service: KeepService instance
            vector_processor: VectorProcessor instance
            sheets_client: SheetsClient instance
            on_status: Optional callback for status updates (for UI feedback)
        """
        self.router = MessageRouter(groq_api_key, model=router_model)
        self.context_fetcher = create_context_fetcher(
            memory_agent=memory_agent,
            task_agent=task_agent,
            calendar_service=calendar_service,
            email_service=email_service,
            vector_processor=vector_processor,
            sheets_client=sheets_client
        )
        self.planner = ActionPlanner(groq_api_key, model=planner_model)
        self.responder = ResponseGenerator(groq_api_key, model=response_model)
        self.confirmation_manager = get_confirmation_manager()

        # Store service references for action execution
        self.memory_agent = memory_agent
        self.task_agent = task_agent
        self.calendar_service = calendar_service
        self.email_service = email_service
        self.keep_service = keep_service

        self.on_status = on_status or (lambda s: None)

    async def process_message(
        self,
        user_id: str,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Process a user message through the pipeline.

        Args:
            user_id: User identifier
            user_message: The user's message
            conversation_history: Recent conversation messages

        Returns:
            {
                "response": str,
                "awaiting_confirmation": bool,
                "actions_executed": [...],
                "route": {...}
            }
        """
        # Check for pending confirmation first
        pending = await self.confirmation_manager.get_pending_action(user_id)
        if pending:
            return await self._handle_confirmation_response(user_id, user_message, pending)

        # Start context fetching speculatively (parallel with routing)
        context_task = asyncio.create_task(
            self.context_fetcher.fetch_context(
                user_message, user_id, conversation_history
            )
        )

        # Stage 1: Route the message
        self.on_status("Analyzing message...")
        route_result = await self.router.route(user_message, conversation_history)
        print(f"[Pipeline] Route: {route_result}")

        # Early exit: Simple chat needs no context or actions
        if route_result["type"] == "chat" and not route_result["domains"]:
            context_task.cancel()
            try:
                await context_task
            except asyncio.CancelledError:
                pass

            # Generate chat response
            response = await self.responder.generate_chat_response(
                user_message,
                {"memories": []},  # Minimal context for chat
                conversation_history
            )
            return {
                "response": response,
                "awaiting_confirmation": False,
                "actions_executed": [],
                "route": route_result
            }

        # Handle followup type
        if route_result["type"] == "followup" and route_result["is_followup"]:
            # This might be answering a clarification question
            # Process as normal action with context from history
            pass

        # Wait for context (already running in parallel)
        self.on_status("Gathering context...")
        context = await context_task
        print(f"[Pipeline] Context fetched: {len(context.get('memories', []))} memories, {len(context.get('tasks', []))} tasks, {len(context.get('calendar_events', []))} events")

        # Stage 3: Plan actions
        if route_result["domains"]:
            self.on_status("Planning actions...")
            action_plan = await self.planner.plan_actions(
                user_message,
                conversation_history,
                context,
                route_result["domains"]
            )
            print(f"[Pipeline] Action plan: {action_plan}")

            # Handle clarification needed
            if action_plan.get("needs_clarification"):
                response = await self.responder.generate_clarification_response(
                    action_plan.get("clarification_question")
                )
                return {
                    "response": response,
                    "awaiting_confirmation": False,
                    "actions_executed": [],
                    "route": route_result
                }

            # Handle high-stakes confirmation
            if action_plan.get("requires_confirmation"):
                await self.confirmation_manager.store_pending_action(user_id, action_plan)
                response = await self.responder.generate_confirmation_prompt(
                    action_plan, context
                )
                return {
                    "response": response,
                    "awaiting_confirmation": True,
                    "actions_executed": [],
                    "route": route_result
                }

            # Execute actions
            self.on_status("Executing actions...")
            action_results = await self._execute_actions(user_id, action_plan)
            print(f"[Pipeline] Action results: {action_results}")

            # Stage 4: Generate response
            response = await self.responder.generate_response(
                user_message,
                action_results,
                context,
                conversation_history
            )

            return {
                "response": response,
                "awaiting_confirmation": False,
                "actions_executed": action_results.get("actions", []),
                "route": route_result
            }

        # No domains but not chat - just respond
        response = await self.responder.generate_chat_response(
            user_message, context, conversation_history
        )
        return {
            "response": response,
            "awaiting_confirmation": False,
            "actions_executed": [],
            "route": route_result
        }

    async def _handle_confirmation_response(
        self,
        user_id: str,
        user_message: str,
        pending: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle response to a pending confirmation."""
        action_plan = pending.get("action_plan", {})

        if self.confirmation_manager.is_affirmative(user_message):
            # Execute the pending action
            self.on_status("Executing confirmed action...")
            action_results = await self._execute_actions(user_id, action_plan)
            await self.confirmation_manager.clear_pending_action(user_id)

            response = await self.responder.generate_response(
                "Confirmed action",
                action_results,
                {},
                []
            )
            return {
                "response": response,
                "awaiting_confirmation": False,
                "actions_executed": action_results.get("actions", []),
                "route": {"type": "followup", "domains": [], "is_followup": True}
            }

        elif self.confirmation_manager.is_negative(user_message):
            # Cancel the pending action
            await self.confirmation_manager.clear_pending_action(user_id)
            return {
                "response": "Got it, I won't do that.",
                "awaiting_confirmation": False,
                "actions_executed": [],
                "route": {"type": "followup", "domains": [], "is_followup": True}
            }

        else:
            # Not a clear yes/no - ask again
            return {
                "response": f"I wasn't sure if that was a yes or no. {action_plan.get('confirmation_message', 'Should I proceed?')}",
                "awaiting_confirmation": True,
                "actions_executed": [],
                "route": {"type": "followup", "domains": [], "is_followup": True}
            }

    async def _execute_actions(
        self,
        user_id: str,
        action_plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute planned actions and return results.

        Returns:
            {
                "success": bool (all actions succeeded),
                "actions": [
                    {
                        "domain": str,
                        "action": str,
                        "success": bool,
                        "result": {...},
                        "error": str or None
                    }
                ]
            }
        """
        results = []

        for action in action_plan.get("actions", []):
            domain = action.get("domain")
            action_name = action.get("action")
            params = action.get("params", {})

            try:
                if domain == "task":
                    result = await self._execute_task_action(user_id, action_name, params)
                elif domain == "calendar":
                    result = await self._execute_calendar_action(action_name, params)
                elif domain == "email":
                    result = await self._execute_email_action(action_name, params)
                elif domain == "memory":
                    result = await self._execute_memory_action(user_id, action_name, params)
                elif domain == "keep":
                    result = await self._execute_keep_action(action_name, params)
                else:
                    result = {"success": False, "error": f"Unknown domain: {domain}"}

                results.append({
                    "domain": domain,
                    "action": action_name,
                    "success": result.get("success", False),
                    "result": result.get("data"),
                    "error": result.get("error")
                })

            except Exception as e:
                print(f"[Pipeline] Action error: {domain}.{action_name} - {e}")
                results.append({
                    "domain": domain,
                    "action": action_name,
                    "success": False,
                    "result": None,
                    "error": str(e)
                })

        return {
            "success": all(r["success"] for r in results),
            "actions": results
        }

    async def _execute_task_action(
        self,
        user_id: str,
        action_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a task action."""
        if not self.task_agent:
            return {"success": False, "error": "Task service not configured"}

        try:
            if action_name == "create":
                result = await self.task_agent.create_task(
                    user_id=user_id,
                    title=params.get("title", "New Task"),
                    description=params.get("description"),
                    priority=params.get("priority", "medium"),
                    deadline=params.get("deadline")
                )
                return {"success": True, "data": {"title": params.get("title"), "result": result}}

            elif action_name == "complete":
                task_id = await self._find_task_by_title(user_id, params.get("find_by", ""))
                if task_id:
                    result = await self.task_agent.complete_task(user_id, task_id)
                    return {"success": True, "data": {"result": result}}
                return {"success": False, "error": "Task not found"}

            elif action_name == "update":
                task_id = await self._find_task_by_title(user_id, params.get("find_by", ""))
                if task_id:
                    changes = params.get("changes", {})
                    if "priority" in changes:
                        await self.task_agent.update_task_priority(user_id, task_id, changes["priority"])
                    if "deadline" in changes:
                        await self.task_agent.update_task_deadline(user_id, task_id, changes["deadline"])
                    return {"success": True, "data": {"result": "Task updated"}}
                return {"success": False, "error": "Task not found"}

            else:
                return {"success": False, "error": f"Unknown task action: {action_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _find_task_by_title(self, user_id: str, search_term: str) -> Optional[str]:
        """Find a task by searching its title."""
        if not search_term:
            return None

        try:
            tasks = await self.task_agent.get_prioritized_tasks(user_id, limit=50, status='all')
            search_lower = search_term.lower()

            # Exact match first
            for task in tasks:
                if task.get('title', '').lower() == search_lower:
                    return task.get('task_id')

            # Partial match
            for task in tasks:
                if search_lower in task.get('title', '').lower():
                    return task.get('task_id')

            return None
        except Exception as e:
            print(f"[Pipeline] Error finding task: {e}")
            return None

    async def _execute_calendar_action(
        self,
        action_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a calendar action."""
        if not self.calendar_service:
            return {"success": False, "error": "Calendar service not configured"}

        try:
            if action_name == "list_events":
                events = await self.calendar_service.get_upcoming_events(
                    max_results=10,
                    days_ahead=params.get("days_ahead", 7)
                )
                return {"success": True, "data": {"events": events}}

            elif action_name == "create_event":
                from dateutil import parser as date_parser

                start_str = params.get("start_time")
                if not start_str:
                    return {"success": False, "error": "Start time required"}

                start_time = date_parser.parse(start_str)
                end_time = date_parser.parse(params["end_time"]) if params.get("end_time") else None

                result = await self.calendar_service.create_event(
                    summary=params.get("summary", "New Event"),
                    start_time=start_time,
                    end_time=end_time,
                    location=params.get("location"),
                    description=params.get("description")
                )

                if result:
                    return {"success": True, "data": {"summary": result.get("summary")}}
                return {"success": False, "error": "Failed to create event"}

            elif action_name == "delete_event":
                event_id = params.get("event_id")
                if event_id:
                    success = await self.calendar_service.delete_event(event_id)
                    return {"success": success, "error": None if success else "Failed to delete"}
                return {"success": False, "error": "Event ID required"}

            else:
                return {"success": False, "error": f"Unknown calendar action: {action_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_email_action(
        self,
        action_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an email action."""
        if not self.email_service:
            return {"success": False, "error": "Email service not configured"}

        try:
            if action_name == "create_draft":
                result = await self.email_service.create_draft(
                    to=params.get("to", ""),
                    subject=params.get("subject", ""),
                    body=params.get("body", "")
                )
                if result:
                    return {"success": True, "data": {"to": result.get("to"), "subject": params.get("subject")}}
                return {"success": False, "error": "Failed to create draft. Check if contact exists."}

            elif action_name == "send_email":
                result = await self.email_service.send_email(
                    to=params.get("to", ""),
                    subject=params.get("subject", ""),
                    body=params.get("body", "")
                )
                if result:
                    return {"success": True, "data": {"to": result.get("to"), "subject": params.get("subject")}}
                return {"success": False, "error": "Failed to send email"}

            elif action_name == "reply_to_email":
                sender_name = params.get("sender_name", "")
                original_email = await self.email_service.find_email_from_sender(sender_name)
                if not original_email:
                    return {"success": False, "error": f"No recent email from '{sender_name}' found"}

                result = await self.email_service.create_reply_draft(
                    original_email,
                    params.get("body", "")
                )
                if result:
                    return {"success": True, "data": {"to": result.get("to")}}
                return {"success": False, "error": "Failed to create reply draft"}

            else:
                return {"success": False, "error": f"Unknown email action: {action_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_memory_action(
        self,
        user_id: str,
        action_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a memory action."""
        if not self.memory_agent:
            return {"success": False, "error": "Memory service not configured"}

        try:
            if action_name == "store":
                result = await self.memory_agent.store_memory(
                    user_id=user_id,
                    category=params.get("category", "knowledge"),
                    key=params.get("key", f"fact_{datetime.now().timestamp()}"),
                    value=params.get("value", "")
                )
                return {"success": True, "data": {"result": result}}

            elif action_name == "update":
                result = await self.memory_agent.update_memory(
                    user_id=user_id,
                    key=params.get("key", ""),
                    new_value=params.get("new_value", "")
                )
                return {"success": True, "data": {"result": result}}

            else:
                return {"success": False, "error": f"Unknown memory action: {action_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_keep_action(
        self,
        action_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a Google Keep action."""
        if not self.keep_service:
            return {"success": False, "error": "Keep service not configured"}

        try:
            if action_name == "create_note":
                result = await self.keep_service.create_note(
                    title=params.get("title", "New Note"),
                    content=params.get("content", "")
                )
                if result:
                    return {"success": True, "data": {"title": params.get("title")}}
                return {"success": False, "error": "Failed to create note"}

            else:
                return {"success": False, "error": f"Unknown keep action: {action_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}


def create_pipeline(
    groq_api_key: str,
    memory_agent=None,
    task_agent=None,
    calendar_service=None,
    email_service=None,
    keep_service=None,
    vector_processor=None,
    sheets_client=None,
    on_status: Callable[[str], None] = None
) -> Pipeline:
    """Factory function to create a pipeline with available services."""
    return Pipeline(
        groq_api_key=groq_api_key,
        memory_agent=memory_agent,
        task_agent=task_agent,
        calendar_service=calendar_service,
        email_service=email_service,
        keep_service=keep_service,
        vector_processor=vector_processor,
        sheets_client=sheets_client,
        on_status=on_status
    )
