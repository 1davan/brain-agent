# Brain Agent AI Architecture

## Executive Summary

This document defines the multi-stage prompting architecture for Brain Agent. The core insight: **a single monolithic prompt cannot reliably understand intent, recall context, execute actions, AND generate natural responses**. We decompose this into specialized stages.

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
+------------------+
| Stage 1: INTENT  |  "What does the user want?"
| (Fast, focused)  |  Output: intent + entities + requires_action
+------------------+
     |
     v (if requires_action)
+------------------+
| Stage 2: CONTEXT |  "What do I know that's relevant?"
| (Semantic search)|  Output: relevant_memories, relevant_tasks, calendar_events
+------------------+
     |
     v (if action needed)
+------------------+
| Stage 3: ACTION  |  "What should I do?"
| (Tool selection) |  Output: action_plan[] with validated schemas
+------------------+
     |
     v (execute actions)
+------------------+
| Stage 4: RESPOND |  "How should I reply?"
| (Natural, warm)  |  Output: conversational response
+------------------+
     |
     v
User Response
```

---

## Stage 1: Intent Classification

### Purpose
Quickly determine what the user wants without loading full context or action schemas.

### Prompt (Minimal)

```
You classify user messages into intents. Output JSON only.

CONVERSATION CONTEXT:
{last_3_messages}

USER: "{user_message}"

INTENTS:
- chat: General conversation, greetings, thanks, small talk
- ask_info: Asking about something (calendar, tasks, memories, capabilities)
- request_action: Wants something done (create task, set reminder, send email)
- discuss_work: Wants to think through priorities, strategy, workload
- followup: Continuing previous topic ("yes", "that one", "tell me more", "the first option")

Output:
{
  "intent": "chat|ask_info|request_action|discuss_work|followup",
  "entities": ["extracted", "key", "phrases"],
  "requires_action": true|false,
  "action_domain": null|"memory"|"task"|"calendar"|"email"|"keep"
}
```

### Token Budget: ~300 tokens (prompt) + ~50 tokens (output)

### Key Behaviors

1. **Followup Detection**: Short responses like "yes", "ok", "that one", numbers, single words are almost always followups to the previous message.

2. **Chat vs Action**: "Thanks!" is chat. "Thanks, and remind me tomorrow" is request_action.

3. **Domain Routing**: If action needed, identify which domain(s) so we only load relevant schemas in Stage 3.

---

## Stage 2: Context Retrieval

### Purpose
Fetch relevant context based on intent and entities. No LLM call needed for most cases.

### Logic (Code, not prompt)

```python
async def retrieve_context(intent_result, user_id):
    context = {
        "memories": [],
        "tasks": [],
        "calendar": [],
        "conversation_history": []
    }

    # Always include recent conversation for continuity
    context["conversation_history"] = await get_last_n_conversations(user_id, n=10)

    # Route based on intent
    if intent_result["intent"] == "followup":
        # Heavy on conversation history, light on everything else
        context["memories"] = await semantic_search(
            intent_result["entities"],
            limit=3,
            threshold=0.4
        )

    elif intent_result["intent"] == "discuss_work":
        # Need ALL tasks for priority discussion
        context["tasks"] = await get_all_pending_tasks(user_id)
        context["calendar"] = await get_calendar_next_7_days(user_id)

    elif intent_result["intent"] == "ask_info":
        # Depends on domain
        if "calendar" in str(intent_result["entities"]).lower():
            context["calendar"] = await get_calendar_events(
                user_id,
                parse_time_reference(intent_result["entities"])
            )
        if "task" in str(intent_result["entities"]).lower():
            context["tasks"] = await search_tasks(
                user_id,
                intent_result["entities"]
            )
        # Always include some memories for personalization
        context["memories"] = await semantic_search(
            intent_result["entities"],
            limit=5,
            threshold=0.3
        )

    elif intent_result["intent"] == "request_action":
        # Light context - action stage will handle specifics
        context["memories"] = await semantic_search(
            intent_result["entities"],
            limit=3,
            threshold=0.5
        )

    return context
```

### Token Budget: 0 (no LLM call) - this is pure data retrieval

---

## Stage 3: Action Planning

### Purpose
If action is needed, determine exactly what actions to take with validated schemas.

### Key Principle: Domain-Specific Prompts

Instead of one prompt with ALL action schemas, load only the relevant schema:

```python
ACTION_PROMPTS = {
    "task": TASK_ACTION_PROMPT,
    "memory": MEMORY_ACTION_PROMPT,
    "calendar": CALENDAR_ACTION_PROMPT,
    "email": EMAIL_ACTION_PROMPT,
    "keep": KEEP_ACTION_PROMPT
}

async def plan_actions(intent_result, context, user_message):
    domain = intent_result.get("action_domain")
    if not domain:
        return []

    prompt = ACTION_PROMPTS[domain]
    # ... call LLM with domain-specific prompt
```

### Task Action Prompt

```
You plan task actions. Output JSON only.

EXISTING TASKS:
{tasks}

USER REQUEST: "{user_message}"
TODAY: {current_date}

ACTIONS YOU CAN TAKE:
- create: New task
- update: Change priority, deadline, or description
- complete: Mark as done
- none: No task action needed

DATE PARSING:
- "tomorrow" = {tomorrow_date}
- "next week" = {next_week_date}
- "Monday" = {next_monday_date}
- "this evening" = today at 18:00
- "in 2 hours" = {two_hours_from_now}

Output:
{
  "actions": [
    {
      "action": "create|update|complete|none",
      "title": "Task title",
      "description": "Optional details",
      "priority": "high|medium|low",
      "deadline": "2026-01-15T18:00:00",
      "find_by": "keywords to find existing task"
    }
  ],
  "reasoning": "Brief explanation of why these actions"
}
```

### Memory Action Prompt

```
You decide what to remember about the user. Output JSON only.

EXISTING MEMORIES:
{memories}

USER MESSAGE: "{user_message}"

WHAT TO REMEMBER:
- Personal facts: preferences, relationships, life events
- Work context: projects, colleagues, deadlines
- Knowledge: things they've learned or shared

WHAT NOT TO REMEMBER:
- Transient requests ("remind me tomorrow" - that's a task, not memory)
- Questions they're asking (they want answers, not storage)
- Acknowledgments ("ok", "thanks", "got it")

Output:
{
  "actions": [
    {
      "action": "store|update|none",
      "category": "personal|work|knowledge",
      "key": "descriptive_key",
      "value": "what to remember",
      "reason": "why this matters"
    }
  ]
}
```

### Calendar Action Prompt

```
You plan calendar actions. Output JSON only.

EXISTING EVENTS:
{calendar_events}

USER REQUEST: "{user_message}"
TODAY: {current_date}

ACTIONS:
- create_event: Schedule something new
- list_events: User wants to see their schedule
- none: No calendar action needed

Output:
{
  "actions": [
    {
      "action": "create_event|list_events|none",
      "summary": "Event title",
      "start_time": "2026-01-15T14:00:00",
      "end_time": "2026-01-15T15:00:00",
      "location": "Optional location"
    }
  ]
}
```

### Email Action Prompt

```
You plan email actions. Output JSON only.

CONTACTS:
{contacts}

USER REQUEST: "{user_message}"

ACTIONS:
- create_draft: Write a new email
- reply_to_email: Reply to someone's email
- none: No email action needed

EMAIL VOICE (use this style):
Conversational, first-person, informal. Contractions allowed. Start sentences with "And" or "But" when natural. Parenthetical asides for humor. Warm sign-offs.

Output:
{
  "actions": [
    {
      "action": "create_draft|reply_to_email|none",
      "to": "recipient name or email",
      "subject": "Subject line",
      "body": "Full email body in the voice described above"
    }
  ]
}
```

### Token Budget: ~400-600 tokens per domain (much smaller than monolithic prompt)

---

## Stage 4: Response Generation

### Purpose
Generate a natural, warm response that acknowledges what was done and continues the conversation.

### Prompt

```
You are a helpful assistant responding to the user. Be warm, concise, and natural.

CONTEXT:
- User asked: "{user_message}"
- You know about them: {relevant_memories}
- Actions taken: {action_results}

CONVERSATION STYLE:
- Acknowledge what you did briefly
- Don't over-explain
- If they asked a question, answer it
- If you took action, confirm it naturally
- Keep it to 1-3 sentences unless they asked for detail
- Match their energy (casual message = casual response)

AVOID:
- Starting with "I" every time
- Robotic confirmations ("Task created successfully")
- Repeating back exactly what they said
- Asking unnecessary follow-up questions

Generate your response (plain text, not JSON):
```

### Token Budget: ~200 tokens (prompt) + ~200 tokens (response)

---

## Total Token Usage Comparison

| Stage | Old Architecture | New Architecture |
|-------|------------------|------------------|
| Intent | - | ~350 |
| Context | (in main prompt) | 0 (code) |
| Action | (in main prompt) | ~500 (domain-specific) |
| Response | (in main prompt) | ~400 |
| **Total per request** | ~1500 (cramped) | ~1250 (spacious) |

But more importantly: each stage has **focused attention** on its task.

---

## Implementation Guide

### Phase 1: Intent Classification (Day 1)

1. Create `app/services/intent_classifier.py`:

```python
class IntentClassifier:
    INTENT_PROMPT = """..."""  # As defined above

    async def classify(self, user_message: str, recent_messages: list) -> dict:
        # Fast classification call
        response = await self.llm.generate(
            self.INTENT_PROMPT.format(
                last_3_messages=recent_messages[-3:],
                user_message=user_message
            ),
            max_tokens=100,
            temperature=0.1
        )
        return json.loads(response)
```

2. Update `ConversationAgent.handle_conversation_flow()` to call intent classifier first.

### Phase 2: Context Retrieval Refactor (Day 2)

1. Move compression logic to dedicated `app/services/context_retriever.py`
2. Implement intent-aware retrieval as shown above
3. Remove hardcoded limits - make them dynamic based on intent

### Phase 3: Domain-Specific Action Prompts (Day 3-4)

1. Create `app/prompts/` directory with:
   - `task_actions.py`
   - `memory_actions.py`
   - `calendar_actions.py`
   - `email_actions.py`
   - `keep_actions.py`

2. Each file contains ONE focused prompt

3. Action planner routes to correct prompt based on Stage 1 output

### Phase 4: Response Generator (Day 5)

1. Create `app/services/response_generator.py`
2. Separate response generation from action execution
3. Response knows what actions were taken and incorporates naturally

---

## Fallback Behaviors

### If Intent Classification Fails

Default to `{"intent": "chat", "requires_action": false}` and generate conversational response.

### If Action Planning Fails

Log the error, skip actions, and respond with:
"I understood you wanted to [intent], but I had trouble figuring out the details. Could you rephrase?"

### If Response Generation Fails

Return action confirmations in simple format:
"Done! I [action description]."

---

## Chain-of-Thought Patterns

### Pattern 1: Simple Chat

```
User: "Hey, how's it going?"
     |
Stage 1: intent=chat, requires_action=false
     |
Stage 4: Generate friendly response
     |
Response: "Going well! What's on your mind?"
```

### Pattern 2: Task Creation

```
User: "Remind me to call mom tomorrow at 5pm"
     |
Stage 1: intent=request_action, action_domain=task
     |
Stage 2: Fetch relevant context (light)
     |
Stage 3 (Task): action=create, title="Call mom", deadline="tomorrow 17:00"
     |
Execute: Create task in Google Sheets
     |
Stage 4: "Got it - I'll remind you to call mom tomorrow at 5pm."
```

### Pattern 3: Priority Discussion

```
User: "I'm overwhelmed, help me figure out what to focus on"
     |
Stage 1: intent=discuss_work, requires_action=false (discussion, not action)
     |
Stage 2: Fetch ALL pending tasks, calendar, relevant memories
     |
Stage 4: Generate thoughtful response about priorities
     |
Response: "Looking at your tasks, you've got [X high-priority items].
The most urgent is [task] due [date]. Want to talk through any of these?"
```

### Pattern 4: Followup

```
User: "yes"
     |
Stage 1: intent=followup (detected from short message + context)
     |
Stage 2: Heavy weight on conversation history
     |
Stage 4: Continue previous topic naturally
     |
Response: (depends on what was being discussed)
```

### Pattern 5: Memory + Action

```
User: "I just closed on my house! Add it to my calendar for celebration dinner Saturday"
     |
Stage 1: intent=request_action, action_domain=calendar, entities=["house", "closed", "celebration", "Saturday"]
     |
Stage 2: Fetch context
     |
Stage 3 (Memory): action=store, category=personal, key="house_purchase_2026", value="Closed on house in January 2026"
Stage 3 (Calendar): action=create_event, summary="Celebration dinner", start_time="Saturday 19:00"
     |
Execute: Both actions
     |
Stage 4: "Congratulations on the house! I've added a celebration dinner to Saturday evening. Exciting times!"
```

---

## Metrics to Track

1. **Intent accuracy**: % of intents correctly classified (requires human labeling)
2. **Action precision**: % of actions that were actually wanted by user
3. **Action recall**: % of desired actions that were taken
4. **Response quality**: User satisfaction (implicit from conversation continuation)
5. **Token efficiency**: Tokens used per successful interaction
6. **Latency**: Time from message received to response sent

---

## Migration Strategy

### Week 1: Shadow Mode
- Run new pipeline in parallel with old
- Log both outputs, don't serve new output yet
- Compare intent classification accuracy

### Week 2: Gradual Rollout
- Serve new pipeline for `chat` intents (lowest risk)
- Keep old pipeline for action intents
- Monitor error rates

### Week 3: Full Rollout
- Switch all intents to new pipeline
- Keep old pipeline as fallback (if new fails, fall back to old)

### Week 4: Cleanup
- Remove old monolithic prompt
- Remove fallback to old pipeline
- Full new architecture

---

## Appendix: Current vs New Prompt Comparison

### Current (Monolithic)

```
You are a smart, proactive assistant who helps...

CONTEXT:
Memories: {memories}
Tasks: {tasks}
Calendar: {calendar_events}
Recent conversation: {conversations}

USER: "{user_input}"

MULTI-TURN CONVERSATION AWARENESS:
Look at the "Recent conversation" above...
[30 lines of instructions]

TASK DISCUSSIONS:
When user wants to discuss their tasks...
[20 lines of instructions]

CALENDAR QUERIES:
When the user asks about their calendar...
[15 lines of instructions]

CRITICAL BEHAVIOR FOR HELP REQUESTS:
[15 lines of instructions]

CAPABILITIES:
[10 lines listing capabilities]

TASK ACTIONS:
[30 lines of schema and examples]

MEMORY ACTIONS:
[25 lines of schema and examples]

CALENDAR ACTIONS:
[15 lines of schema and examples]

EMAIL CAPABILITIES:
[40 lines of schema, examples, and voice guide]

GOOGLE KEEP NOTES:
[25 lines of schema and examples]

OUTPUT FORMAT:
{...JSON schema...}

BE HELPFUL. Don't just acknowledge...
```

**Total: ~300 lines, ~2500 tokens**

### New (Staged)

**Stage 1 Intent (when used):** ~30 lines, ~300 tokens
**Stage 3 Action (domain-specific, one at a time):** ~40 lines, ~400 tokens
**Stage 4 Response:** ~20 lines, ~200 tokens

**Used together:** ~900 tokens with focused attention at each stage

---

## Conclusion

The multi-stage architecture solves the core problem: **a single prompt trying to do too much**. By decomposing into intent -> context -> action -> response, we:

1. **Reduce cognitive load** on the LLM at each stage
2. **Use tokens efficiently** by only loading relevant schemas
3. **Improve accuracy** through focused prompts
4. **Enable better debugging** with clear stage boundaries
5. **Allow independent optimization** of each stage

The implementation is incremental - we can ship Stage 1 alone and immediately improve intent detection, then add stages progressively.
