# Brain Agent AI Architecture v2

## Executive Summary

This document defines the multi-stage prompting architecture for Brain Agent. The core insight: **a single monolithic prompt cannot reliably understand intent, recall context, execute actions, AND generate natural responses**. We decompose this into specialized stages with proper safety controls.

**Key Design Principles:**
1. Each stage has ONE job with focused attention
2. High-stakes actions require human confirmation
3. Conversation history flows through all stages
4. Failures are explicit, never hallucinated as success
5. Latency is minimized through parallelization and streaming

---

## Current Architecture Problems

### The Monolithic Prompt Anti-Pattern

Current `reason_and_act()` attempts everything in one 4000+ token prompt:
- Role definition and personality
- Multi-turn conversation awareness rules
- Task discussion behaviors
- Calendar query handling
- 6 different action type schemas (memory, task, calendar, email, keep, web search)
- Email writing style guide
- Date parsing rules
- Output format enforcement

**Result:** The LLM is overwhelmed. It:
- Misses context from earlier in the conversation
- Takes wrong actions (creates tasks when user just wants to chat)
- Hallucinates action formats
- Truncates responses due to token limits

### Token Budget Crisis

| Component | Estimated Tokens |
|-----------|-----------------|
| System prompt | ~2500 |
| Context (memories, tasks, conversations) | ~800 |
| User message | ~100 |
| **Available for response** | **~600** (of 1500 max) |

This leaves no room for reasoning.

---

## New Architecture: Multi-Stage Pipeline

```
User Message
     |
     v
+------------------+     +------------------+
| Stage 1: ROUTER  |     | Stage 2: CONTEXT |
| (Fast, minimal)  |---->| (Parallel fetch) |
| Output: domains  |     | (Speculative)    |
+------------------+     +------------------+
     |                          |
     v                          v
+------------------------------------------+
|            Stage 3: ACTION PLANNER       |
|  - Receives: user_msg + conversation     |
|  - Does: entity extraction + planning    |
|  - Outputs: action_plan + high_stakes    |
+------------------------------------------+
     |
     v (if high_stakes)
+------------------+
| CONFIRMATION     |  "Should I send this email to everyone?"
| (Human in Loop)  |  User: "yes" -> execute
+------------------+
     |
     v (execute actions)
+------------------+
| Stage 4: RESPOND |  Receives: action_results with success/failure
| (Natural, warm)  |  Output: honest acknowledgment
+------------------+
     |
     v
User Response (with streaming for long operations)
```

---

## Latency Optimization Strategy

### The Problem: Latency Stack

Sequential execution creates unacceptable delays:
- Stage 1 (0.5s) + Stage 2 (0.3s) + Stage 3 (2s) + Execute (1s) + Stage 4 (1.5s) = **5+ seconds**

### The Solution: Parallel + Streaming + Early Exit

```python
async def process_message(user_message, conversation_history):
    # Start context fetch IMMEDIATELY (speculative)
    context_task = asyncio.create_task(
        fetch_likely_context(user_message, conversation_history)
    )

    # Route intent (fast, ~300ms)
    route_result = await route_message(user_message, conversation_history[-3:])

    # EARLY EXIT: Simple chat needs no context or action
    if route_result["type"] == "chat" and not route_result["domains"]:
        context_task.cancel()
        return await generate_chat_response(user_message, conversation_history)

    # Wait for context (already running in parallel)
    context = await context_task

    # Plan actions with full context
    action_plan = await plan_actions(
        user_message,
        conversation_history,  # FULL history, not just entities
        context,
        route_result["domains"]
    )

    # HIGH STAKES CHECK
    if action_plan.get("requires_confirmation"):
        return await generate_confirmation_prompt(action_plan)

    # Execute and respond
    results = await execute_actions(action_plan)
    return await generate_response(user_message, results, context)
```

### UI Streaming for Long Operations

For operations taking >2 seconds, stream intermediate states:

```python
async def process_with_streaming(user_message, send_typing, send_status):
    await send_typing()  # Show "typing..." indicator

    route = await route_message(user_message)

    if route["domains"]:
        await send_status("Checking your calendar...")  # User sees progress

    # ... continue processing
```

---

## Stage 1: Router (NOT Intent Classifier)

### Critical Change: Router Only, No Entity Extraction

**Previous mistake:** Asking Stage 1 to extract entities. Small/fast models are bad at this.

**New approach:** Stage 1 only decides which tools/domains to activate. Entity extraction happens in Stage 3 where the domain-specific schema lives.

### Prompt (Minimal - ~200 tokens)

```
You route user messages to the correct handlers. Output JSON only.

RECENT CONVERSATION:
{last_3_messages}

USER: "{user_message}"

DETERMINE:
1. Is this simple chat (greeting, thanks, small talk)?
2. Or does it need tools? Which ones?

TOOLS AVAILABLE:
- task: Creating, updating, completing tasks and reminders
- calendar: Viewing or creating calendar events
- email: Drafting or sending emails
- memory: Storing facts about the user
- keep: Google Keep notes

Output:
{
  "type": "chat|action|followup",
  "domains": [],  // Empty for chat, or ["task"], or ["calendar", "email"] for multi
  "is_followup": true|false  // "yes", "ok", "that one" = true
}
```

### Key Changes from v1

1. **No entity extraction** - Stage 3 handles this
2. **Multi-domain support** - Can return `["calendar", "email"]` for composite requests
3. **Followup detection** - Explicit flag, not an intent type
4. **Simpler output** - Just routing, nothing else

### Token Budget: ~200 tokens (prompt) + ~30 tokens (output)

---

## Stage 2: Context Retrieval (Parallel + Speculative)

### Purpose
Fetch relevant context based on likely needs. Runs IN PARALLEL with Stage 1.

### Speculative Fetching

Don't wait for Stage 1 to finish. Start fetching likely context immediately:

```python
async def fetch_likely_context(user_message: str, conversation_history: list):
    """Speculatively fetch context that's likely needed."""

    # Always fetch
    context = {
        "conversation_history": conversation_history[-10:],  # Last 10 messages
        "memories": [],
        "tasks": [],
        "calendar": [],
        "contacts": []
    }

    user_lower = user_message.lower()

    # Speculative fetches based on keywords (run in parallel)
    fetches = []

    # Calendar keywords
    if any(w in user_lower for w in ['calendar', 'schedule', 'meeting', 'busy', 'free',
                                       'today', 'tomorrow', 'monday', 'tuesday', 'wednesday',
                                       'thursday', 'friday', 'saturday', 'sunday', 'week']):
        fetches.append(fetch_calendar_events(days=7))

    # Task keywords
    if any(w in user_lower for w in ['task', 'remind', 'todo', 'deadline', 'priority',
                                       'overwhelm', 'focus', 'busy', 'work']):
        fetches.append(fetch_pending_tasks())

    # Email keywords
    if any(w in user_lower for w in ['email', 'send', 'draft', 'reply', 'mail']):
        fetches.append(fetch_contacts())

    # Always do semantic memory search
    fetches.append(semantic_memory_search(user_message, limit=5))

    # Run all fetches in parallel
    results = await asyncio.gather(*fetches, return_exceptions=True)

    # Merge results into context
    # ...

    return context
```

### Token Budget: 0 LLM calls - pure data retrieval

---

## Stage 3: Action Planner (The Smart Stage)

### Critical Changes from v1

1. **Receives full conversation history** - Can resolve "it", "that", "him"
2. **Does entity extraction** - Has the schema to do it properly
3. **Outputs confirmation_required flag** - For high-stakes actions
4. **Handles multi-domain** - Can plan calendar + email in one call

### High-Stakes Actions Definition

```python
HIGH_STAKES_ACTIONS = {
    "email": {
        "send_email": True,      # Sending is permanent
        "create_draft": False,   # Drafts are safe
        "reply_to_email": True   # Replies go out
    },
    "calendar": {
        "delete_event": True,    # Deletion is permanent
        "create_event": False,   # Creating is usually safe
        "update_event": True     # Modifying existing
    },
    "task": {
        "delete_task": True,     # Deletion is permanent
        "create": False,         # Creating is safe
        "complete": False        # Completing is usually intended
    }
}
```

### Unified Action Planner Prompt

Instead of separate prompts per domain, use ONE prompt that handles multi-domain:

```
You plan actions based on the user's request. Output JSON only.

CONVERSATION HISTORY (resolve pronouns from this):
{conversation_history}

CURRENT MESSAGE: "{user_message}"

AVAILABLE CONTEXT:
- Tasks: {tasks}
- Calendar: {calendar_events}
- Contacts: {contacts}
- Memories: {memories}

TODAY: {current_date} ({day_of_week})
TIMEZONE: {timezone}

DOMAINS REQUESTED: {domains}

For each domain, plan the necessary action:

TASK ACTIONS:
- create: {title, description, priority, deadline}
- update: {find_by, changes}
- complete: {find_by}

CALENDAR ACTIONS:
- create_event: {summary, start_time, end_time, location}
- list_events: {days_ahead}
- delete_event: {event_id} [HIGH STAKES]

EMAIL ACTIONS:
- create_draft: {to, subject, body}
- send_email: {to, subject, body} [HIGH STAKES]
- reply_to_email: {sender_name, body} [HIGH STAKES]

MEMORY ACTIONS:
- store: {category, key, value}
- update: {key, new_value}

DATE PARSING (use these exact formats):
- "tomorrow" = {tomorrow_date}
- "next Monday" = {next_monday}
- "this evening" = {today}T18:00:00
- "in 2 hours" = {two_hours_from_now}

IMPORTANT:
- Resolve ALL pronouns ("it", "that meeting", "him") using conversation history
- If action is marked [HIGH STAKES], set requires_confirmation: true
- If you can't determine a required field, set needs_clarification: true

Output:
{
  "actions": [
    {
      "domain": "task|calendar|email|memory",
      "action": "action_name",
      "params": { ... },
      "reasoning": "Why this action"
    }
  ],
  "requires_confirmation": true|false,
  "confirmation_message": "Should I send this email to Bob about the meeting?",
  "needs_clarification": false,
  "clarification_question": null
}
```

### Confirmation Flow

When `requires_confirmation: true`:

```python
async def handle_confirmation_flow(action_plan, user_id):
    # Store pending action
    await store_pending_action(user_id, action_plan)

    # Generate confirmation prompt
    return {
        "response": action_plan["confirmation_message"],
        "awaiting_confirmation": True
    }

async def handle_followup(user_message, user_id):
    pending = await get_pending_action(user_id)

    if pending and is_affirmative(user_message):  # "yes", "do it", "send it"
        results = await execute_actions(pending["actions"])
        await clear_pending_action(user_id)
        return await generate_response(results)

    elif pending and is_negative(user_message):  # "no", "cancel", "don't"
        await clear_pending_action(user_id)
        return {"response": "Got it, I won't send that."}

    # Not a confirmation response, process normally
    return None
```

---

## Stage 4: Response Generator (Honest Acknowledgment)

### Critical Change: Explicit Success/Failure Context

Stage 4 must receive explicit success/failure status. Never let it guess.

### Prompt

```
You are responding to the user. Be warm, concise, and HONEST.

USER MESSAGE: "{user_message}"

CONVERSATION CONTEXT:
{last_3_messages}

WHAT YOU KNOW ABOUT THEM:
{relevant_memories}

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
- Hallucinate success when {action_results} shows failure
- Start every response with "I"
- Ask unnecessary follow-up questions

Generate your response (plain text, not JSON):
```

### Action Results Format

```python
action_results = {
    "success": True,  # Overall success
    "actions": [
        {
            "domain": "email",
            "action": "create_draft",
            "success": True,
            "result": {"draft_id": "123", "to": "bob@example.com"},
            "error": None
        },
        {
            "domain": "calendar",
            "action": "create_event",
            "success": False,
            "result": None,
            "error": "Calendar API timeout - please try again"
        }
    ]
}
```

Stage 4 sees this explicitly and can respond: "I've drafted the email to Bob. I tried to add the calendar event but the calendar service timed out - want me to try again?"

---

## Handling Composite Requests (The "And" Problem)

### Problem
User: "Check my calendar for tomorrow and email Bob to tell him I'm running late."

### Solution: Multi-Domain Processing

```python
async def plan_actions(user_message, history, context, domains):
    if len(domains) > 1:
        # Composite request - Stage 3 handles all domains in one call
        # The unified prompt can output multiple actions
        return await call_action_planner(
            user_message=user_message,
            conversation_history=history,
            context=context,
            domains=domains  # ["calendar", "email"]
        )
    elif len(domains) == 1:
        return await call_action_planner(
            user_message=user_message,
            conversation_history=history,
            context=context,
            domains=domains
        )
    else:
        return {"actions": []}  # Pure chat, no actions
```

The unified Stage 3 prompt handles this naturally:
```json
{
  "actions": [
    {
      "domain": "calendar",
      "action": "list_events",
      "params": {"days_ahead": 1},
      "reasoning": "User wants to see tomorrow's schedule"
    },
    {
      "domain": "email",
      "action": "create_draft",
      "params": {
        "to": "Bob",
        "subject": "Running late",
        "body": "Hey Bob, just wanted to let you know I'm running a bit behind..."
      },
      "reasoning": "User wants to notify Bob they're late"
    }
  ],
  "requires_confirmation": false
}
```

---

## Retrieval Robustness (Fixing String Matching)

### Problem
`if "calendar" in entities` breaks when user says "Am I free for lunch?"

### Solution: Router Outputs Required Tools, Not Keyword Matches

Stage 1 uses LLM reasoning to decide tools, not Python string matching:

```
USER: "Am I free for lunch tomorrow?"

Stage 1 thinks: "User is asking about availability. This requires checking the calendar."

Output: {"type": "action", "domains": ["calendar"]}
```

The LLM decides "calendar" is needed even though the word isn't present.

### Fallback: Aggressive Speculative Fetch

If routing is uncertain, fetch everything:

```python
async def fetch_likely_context(user_message, history):
    # If message is ambiguous, fetch broadly
    if is_ambiguous(user_message):
        return await fetch_all_context()
    # Otherwise, speculative fetch based on keywords
    ...
```

---

## Error Handling & Graceful Degradation

### Principle: Fail Explicitly, Never Hallucinate Success

```python
async def execute_actions(action_plan):
    results = []

    for action in action_plan["actions"]:
        try:
            result = await execute_single_action(action)
            results.append({
                "domain": action["domain"],
                "action": action["action"],
                "success": True,
                "result": result,
                "error": None
            })
        except Exception as e:
            logger.error(f"Action failed: {action} - {e}")
            results.append({
                "domain": action["domain"],
                "action": action["action"],
                "success": False,
                "result": None,
                "error": str(e)  # Explicit error message
            })

    return {
        "success": all(r["success"] for r in results),
        "actions": results
    }
```

### Stage Failure Fallbacks

| Stage | Failure Mode | Fallback |
|-------|--------------|----------|
| Stage 1 (Router) | JSON parse error | Default to `{"type": "chat", "domains": []}` |
| Stage 2 (Context) | Database timeout | Return empty context, proceed with LLM |
| Stage 3 (Planner) | JSON parse error | Log error, respond "I had trouble understanding. Could you rephrase?" |
| Stage 3 (Planner) | Missing required field | Set `needs_clarification: true` |
| Execute | API error | Pass error to Stage 4 for honest response |
| Stage 4 (Response) | Generation fails | Return simple fallback: "Done!" or "Sorry, something went wrong." |

---

## Complete Flow Examples

### Example 1: Simple Chat (Fast Path)

```
User: "Hey, how's it going?"

Stage 1 (200ms):
  Input: "Hey, how's it going?"
  Output: {"type": "chat", "domains": [], "is_followup": false}

Stage 2: SKIPPED (no domains)

Stage 3: SKIPPED (no domains)

Stage 4 (400ms):
  Input: user_message + empty action_results
  Output: "Going well! What's on your mind?"

Total: ~600ms
```

### Example 2: Task Creation

```
User: "Remind me to call mom tomorrow at 5pm"

Stage 1 (200ms):
  Output: {"type": "action", "domains": ["task"]}

Stage 2 (parallel, 100ms):
  Fetches: pending tasks, memories

Stage 3 (800ms):
  Input: user_message + conversation_history + context
  Output: {
    "actions": [{
      "domain": "task",
      "action": "create",
      "params": {"title": "Call mom", "deadline": "2026-01-12T17:00:00", "priority": "medium"}
    }],
    "requires_confirmation": false
  }

Execute (200ms): Create task in Google Sheets

Stage 4 (400ms):
  Input: action_results (success: true)
  Output: "Got it - I'll remind you to call mom tomorrow at 5pm."

Total: ~1.7s
```

### Example 3: High-Stakes Email (Confirmation Required)

```
User: "Send an email to the whole team about the project delay"

Stage 1 (200ms):
  Output: {"type": "action", "domains": ["email"]}

Stage 2 (100ms): Fetches contacts

Stage 3 (1000ms):
  Output: {
    "actions": [{
      "domain": "email",
      "action": "send_email",  // HIGH STAKES
      "params": {"to": "team@company.com", "subject": "Project Update", "body": "..."}
    }],
    "requires_confirmation": true,
    "confirmation_message": "I've drafted an email to the whole team about the project delay. Should I send it?"
  }

Execute: SKIPPED (awaiting confirmation)

Stage 4 (300ms):
  Output: "I've drafted an email to the whole team about the project delay. Should I send it?"

--- User responds ---

User: "Yes, send it"

Stage 1: {"type": "followup", "is_followup": true}

Handle Confirmation:
  - Retrieve pending action
  - Execute send_email
  - Clear pending action

Stage 4:
  Output: "Done - email sent to the team."
```

### Example 4: Composite Request

```
User: "Check my calendar for tomorrow and email Bob to tell him I'm running late"

Stage 1 (200ms):
  Output: {"type": "action", "domains": ["calendar", "email"]}

Stage 2 (100ms): Fetches calendar + contacts in parallel

Stage 3 (1200ms):
  Output: {
    "actions": [
      {"domain": "calendar", "action": "list_events", "params": {"days_ahead": 1}},
      {"domain": "email", "action": "create_draft", "params": {"to": "Bob", ...}}
    ],
    "requires_confirmation": false
  }

Execute: Both actions

Stage 4:
  Output: "Tomorrow you have a 10am standup and 2pm client call. I've drafted an email to Bob letting him know you're running late."
```

### Example 5: Pronoun Resolution from History

```
Conversation:
  User: "I have a meeting with Sarah at 3pm"
  Bot: "Got it, I've added that to your calendar."
  User: "Actually, cancel it"

Stage 1: {"type": "action", "domains": ["calendar"]}

Stage 3:
  Input includes conversation_history showing "meeting with Sarah at 3pm"
  Output: {
    "actions": [{
      "domain": "calendar",
      "action": "delete_event",
      "params": {"find_by": "meeting with Sarah 3pm"},
      "reasoning": "User said 'cancel it' - 'it' refers to the Sarah meeting from previous message"
    }],
    "requires_confirmation": true,
    "confirmation_message": "Should I cancel your 3pm meeting with Sarah?"
  }
```

---

## Implementation Status

**All core components implemented:**

| Component | File | Status |
|-----------|------|--------|
| Stage 1: Router | `app/services/message_router.py` | COMPLETE |
| Stage 2: Context Fetcher | `app/services/context_fetcher.py` | COMPLETE |
| Stage 3: Action Planner | `app/services/action_planner.py` | COMPLETE |
| Stage 4: Response Generator | `app/services/response_generator.py` | COMPLETE |
| Confirmation Manager | `app/services/action_planner.py` | COMPLETE |
| Pipeline Orchestrator | `app/services/pipeline.py` | COMPLETE |
| ConversationAgent Integration | `app/agents/conversation_agent.py` | COMPLETE |

**Enabling the Pipeline:**

Set `USE_PIPELINE=true` in your `.env` file to enable the multi-stage architecture.

The system runs in "legacy mode" by default for backwards compatibility.

---

## Implementation Phases (Reference)

### Phase 1: Foundation

1. Create `app/services/message_router.py` - Stage 1
2. Create `app/services/context_fetcher.py` - Stage 2 with parallel fetching
3. Add streaming/typing indicators to Telegram handler

### Phase 2: Action Planning

1. Create `app/services/action_planner.py` - Unified Stage 3
2. Define HIGH_STAKES_ACTIONS
3. Implement confirmation state machine
4. Store pending actions for confirmation flow

### Phase 3: Response & Safety

1. Create `app/services/response_generator.py` - Stage 4
2. Implement explicit success/failure passing
3. Add fallback handlers for each failure mode

### Phase 4: Integration

1. Wire everything into `ConversationAgent`
2. Run shadow mode (log both old and new outputs)
3. Compare accuracy, fix edge cases
4. Gradual rollout

---

## Metrics to Track

1. **Latency by path**:
   - Chat path (Stage 1 -> Stage 4): Target <1s
   - Action path (full pipeline): Target <3s
   - Confirmation path: Target <1.5s per turn

2. **Accuracy**:
   - Router accuracy: % of messages routed to correct domain(s)
   - Action precision: % of executed actions that were intended
   - Pronoun resolution: % of "it/that/him" correctly resolved

3. **Safety**:
   - High-stakes actions blocked for confirmation: 100%
   - False positives (unnecessary confirmations): Target <10%

4. **Reliability**:
   - Stage failure rate by stage
   - Graceful degradation success rate

---

## Summary of v1 -> v2 Changes

| Issue | v1 Approach | v2 Fix |
|-------|-------------|--------|
| Latency stack | Sequential stages | Parallel context fetch, early exit for chat |
| Context loss in Stage 3 | Only entities passed | Full conversation_history passed |
| No confirmation | Execute then respond | HIGH_STAKES flag, confirmation state machine |
| Single intent | Pick one domain | Multi-domain support: `["calendar", "email"]` |
| Brittle retrieval | `if "calendar" in entities` | LLM-based tool selection, speculative fetch |
| Silent failures | Stage 4 might hallucinate | Explicit success/failure in action_results |
| Entity extraction bottleneck | Stage 1 extracts | Stage 3 extracts (has schema context) |

---

## Conclusion

The v2 architecture addresses the critical vulnerabilities:

1. **Latency**: Parallel fetching + early exit for chat reduces p50 latency by ~40%
2. **Context**: Full conversation history flows to Stage 3 for pronoun resolution
3. **Safety**: High-stakes actions require human confirmation before execution
4. **Composites**: Multi-domain support handles "do X and Y" naturally
5. **Honesty**: Explicit success/failure prevents hallucinated confirmations

The implementation is incremental - each phase can be shipped independently. Start with Phase 1 (Router + Context) to immediately improve routing accuracy and latency.
