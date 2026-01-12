# Brain Agent - How It Works

A comprehensive guide to the AI-powered Telegram chatbot assistant architecture.

---

## Table of Contents

1. [Overview](#overview)
2. [State Machine Diagram](#state-machine-diagram)
3. [Component Architecture](#component-architecture)
4. [Message Processing Pipeline](#message-processing-pipeline)
5. [Commands Reference](#commands-reference)
6. [Capabilities](#capabilities)
7. [Proactive Features](#proactive-features)
8. [Integration Services](#integration-services)
9. [Data Storage](#data-storage)

---

## Overview

Brain Agent is an AI-powered Telegram chatbot that combines:
- Multi-turn conversation awareness
- Semantic memory storage and retrieval
- Task and reminder management
- Calendar integration
- Email drafting and sending
- Google Keep note management
- Proactive check-ins and summaries

**Technology Stack:**
- Python 3 with asyncio
- Telegram Bot API (polling)
- Groq LLM (llama-3.3-70b-versatile)
- SentenceTransformers for embeddings
- Google Sheets for persistence
- Google Calendar, Gmail, and Keep APIs

---

## State Machine Diagram

```
                                    BRAIN AGENT STATE MACHINE

    +------------------+
    |   IDLE STATE     |<--------------------------------------------+
    |  (Polling Loop)  |                                             |
    +--------+---------+                                             |
             |                                                       |
             | [Message Received]                                    |
             v                                                       |
    +------------------+                                             |
    |  DEDUPLICATION   |--[Duplicate]--> (Discard)                   |
    |     CHECK        |                                             |
    +--------+---------+                                             |
             |                                                       |
             | [New Message]                                         |
             v                                                       |
    +------------------+     +------------------+                    |
    | COMMAND CHECK    |---->| COMMAND HANDLER  |--------------------+
    | (starts with /)  |     | (Process cmd)    |                    |
    +--------+---------+     +------------------+                    |
             |                                                       |
             | [Not a command]                                       |
             v                                                       |
    +------------------+                                             |
    | TASK DISCUSSION  |--[Active Session]--> Extended context mode  |
    |  SESSION CHECK   |                      (15 memories, 15 tasks)|
    +--------+---------+                                             |
             |                                                       |
             | [No active session or timeout]                        |
             v                                                       |
    +========================================================+       |
    |              4-STAGE PIPELINE                          |       |
    |                                                        |       |
    |  +----------------+     +-------------------+          |       |
    |  | STAGE 1        |     | STAGE 2           |          |       |
    |  | Message Router |     | Context Fetcher   |          |       |
    |  | (Intent Class) |     | (Parallel Fetch)  |          |       |
    |  +-------+--------+     +---------+---------+          |       |
    |          |                        |                    |       |
    |          | [Runs in PARALLEL]     |                    |       |
    |          +------------+-----------+                    |       |
    |                       |                                |       |
    |                       v                                |       |
    |          +------------------------+                    |       |
    |          |    ROUTE DECISION      |                    |       |
    |          +------------------------+                    |       |
    |                  /         \                           |       |
    |        [Chat]   /           \   [Action]               |       |
    |                v             v                         |       |
    |    +--------------+    +----------------+              |       |
    |    | Skip Stage 3 |    | STAGE 3        |              |       |
    |    | Direct Chat  |    | Action Planner |              |       |
    |    +--------------+    | (Entity/Action)|              |       |
    |           |            +-------+--------+              |       |
    |           |                    |                       |       |
    |           |                    v                       |       |
    |           |         +------------------+               |       |
    |           |         | HIGH-STAKES      |               |       |
    |           |         | ACTION CHECK     |               |       |
    |           |         +--------+---------+               |       |
    |           |                  |                         |       |
    |           |        [Requires Confirmation]             |       |
    |           |                  v                         |       |
    |           |         +------------------+               |       |
    |           |         | CONFIRMATION     |               |       |
    |           |         | PENDING STATE    |<---+          |       |
    |           |         +--------+---------+    |          |       |
    |           |                  |              |          |       |
    |           |         [User Response]         |          |       |
    |           |            /        \           |          |       |
    |           |     [Yes] /          \ [No]     |          |       |
    |           |          v            v         |          |       |
    |           |    +---------+   +--------+    |          |       |
    |           |    | EXECUTE |   | CANCEL |----+          |       |
    |           |    | ACTION  |   +--------+               |       |
    |           |    +----+----+                            |       |
    |           |         |                                  |       |
    |           |         v                                  |       |
    |           |    +---------+                             |       |
    |           +--->| STAGE 4 |                             |       |
    |                | Response|                             |       |
    |                |Generator|                             |       |
    |                +----+----+                             |       |
    |                     |                                  |       |
    +=====================|==================================+       |
                          |                                          |
                          v                                          |
                 +------------------+                                |
                 | STORE CONVO      |                                |
                 | (Google Sheets)  |                                |
                 +--------+---------+                                |
                          |                                          |
                          +------------------------------------------+


                        PARALLEL BACKGROUND PROCESSES

    +------------------------------------------------------------------+
    |                    PROACTIVE LOOP (Every 5 min)                  |
    |                                                                  |
    |   +------------------+   +------------------+   +-------------+  |
    |   | Daily Summary    |   | Task Check-ins   |   | Deadline    |  |
    |   | (9 AM default)   |   | (10am,2pm,6pm)   |   | Reminders   |  |
    |   +------------------+   +------------------+   +-------------+  |
    |                                                                  |
    |   +------------------+   +------------------+                    |
    |   | Auto-Archive     |   | Recurring Task   |                    |
    |   | (7 days old)     |   | Generation       |                    |
    |   +------------------+   +------------------+                    |
    +------------------------------------------------------------------+
```

---

## Component Architecture

```
+------------------------------------------------------------------+
|                         SIMPLE_BOT.PY                            |
|                     (Main Entry Point)                           |
|                                                                  |
|  +--------------------+  +--------------------+                  |
|  | Telegram Polling   |  | Proactive Loop     |                  |
|  | (Message Handler)  |  | (Background Thread)|                  |
|  +--------------------+  +--------------------+                  |
+------------------------------------------------------------------+
                |                           |
                v                           v
+------------------------------------------------------------------+
|                           AGENTS                                 |
|                                                                  |
|  +------------------+  +----------------+  +------------------+  |
|  | ConversationAgent|  | MemoryAgent    |  | TaskAgent        |  |
|  | (Multi-turn AI)  |  | (Store/Query)  |  | (CRUD + Recur)   |  |
|  +------------------+  +----------------+  +------------------+  |
+------------------------------------------------------------------+
                |
                v
+------------------------------------------------------------------+
|                     PIPELINE SERVICES                            |
|                                                                  |
|  +----------------+  +------------------+  +------------------+  |
|  | MessageRouter  |  | ContextFetcher   |  | ActionPlanner    |  |
|  | (Stage 1)      |  | (Stage 2)        |  | (Stage 3)        |  |
|  +----------------+  +------------------+  +------------------+  |
|                                                                  |
|  +------------------+  +------------------+                      |
|  | ResponseGenerator|  | Pipeline         |                      |
|  | (Stage 4)        |  | (Orchestrator)   |                      |
|  +------------------+  +------------------+                      |
+------------------------------------------------------------------+
                |
                v
+------------------------------------------------------------------+
|                   INTEGRATION SERVICES                           |
|                                                                  |
|  +----------------+  +----------------+  +------------------+    |
|  | AIService      |  | CalendarService|  | EmailService     |    |
|  | (Groq LLM)     |  | (Google Cal)   |  | (Gmail)          |    |
|  +----------------+  +----------------+  +------------------+    |
|                                                                  |
|  +----------------+  +------------------+                        |
|  | KeepService    |  | SchedulerService |                        |
|  | (Google Keep)  |  | (Reminders)      |                        |
|  +----------------+  +------------------+                        |
+------------------------------------------------------------------+
                |
                v
+------------------------------------------------------------------+
|                      DATA LAYER                                  |
|                                                                  |
|  +------------------+  +------------------+                      |
|  | SheetsClient     |  | VectorProcessor  |                      |
|  | (Google Sheets)  |  | (Embeddings)     |                      |
|  +------------------+  +------------------+                      |
+------------------------------------------------------------------+
```

---

## Message Processing Pipeline

The 4-stage pipeline optimizes message processing for speed and accuracy:

### Stage 1: Message Router

**File:** [message_router.py](app/services/message_router.py)

**Purpose:** Fast intent classification (chat vs action)

**Token Budget:** ~230 tokens

**Output:**
```json
{
  "type": "chat|action|followup",
  "domains": ["task", "calendar", "email", "memory", "keep"],
  "is_followup": true/false
}
```

### Stage 2: Context Fetcher

**File:** [context_fetcher.py](app/services/context_fetcher.py)

**Purpose:** Parallel context retrieval (runs alongside Stage 1)

**Fetches:**
- Conversation history (last 5-8 messages)
- Relevant memories (semantic search)
- Active tasks
- Calendar events (7-day window)
- Contacts

### Stage 3: Action Planner

**File:** [action_planner.py](app/services/action_planner.py)

**Purpose:** Entity extraction and action planning

**Receives:** Full conversation history for pronoun resolution

**High-Stakes Actions (require confirmation):**
- `email.send_email`
- `calendar.delete_event`
- `task.delete_task`
- `memory.delete`

### Stage 4: Response Generator

**File:** [response_generator.py](app/services/response_generator.py)

**Purpose:** Generate natural, honest responses

**Principles:**
- Explicit success/failure reporting
- Match user's conversational energy
- Brief acknowledgments (1-3 sentences)

---

## Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Welcome message with capabilities | `/start` |
| `/help` | Detailed help and examples | `/help` |
| `/status` | System health check | `/status` |
| `/tasks` | View active tasks with priorities | `/tasks` |
| `/memories` | View stored memories | `/memories` |
| `/calendar` | View upcoming events (7 days) | `/calendar` |
| `/dashboard` | Show/update pinned dashboard | `/dashboard` |
| `/settings` | Configure bot settings | `/settings` |
| `/check archives <term>` | Search archived tasks | `/check archives meeting` |
| `/new session` | End active task discussion | `/new session` |

### Settings Commands

| Command | Description |
|---------|-------------|
| `/settings` | Show current settings |
| `/settings checkin 8,12,18` | Set check-in hours |
| `/settings checkin off` | Disable check-ins |
| `/settings skip "Event Name"` | Skip event in summaries |
| `/settings unskip "Event Name"` | Stop skipping event |
| `/settings skip suggest` | Suggest recurring events to skip |

---

## Capabilities

### Task Management

**Natural language examples:**
- "Remind me to call mom tomorrow at 3pm"
- "Add a task to review the quarterly report, high priority"
- "What tasks do I have pending?"
- "Mark the grocery shopping as done"
- "Update the deadline for the project to next Friday"
- "Delete the old meeting task"

**Features:**
- Priority levels (high/medium/low) with auto-assignment
- Deadline parsing with natural language
- Recurring tasks (daily, weekly, monthly, custom)
- Progress tracking and notes
- Task dependencies

### Memory Storage

**Natural language examples:**
- "Remember that my favorite coffee is flat white"
- "My sister's birthday is March 15th"
- "Store that I'm allergic to peanuts"
- "What do you know about my preferences?"
- "Update my phone number to 555-1234"
- "Forget my old address"

**Categories:**
- Personal info
- Preferences
- Work details
- Relationships
- Health info
- Custom categories

### Calendar Integration

**Natural language examples:**
- "What's on my calendar today?"
- "Schedule a meeting with John tomorrow at 2pm"
- "What do I have next week?"
- "Cancel my dentist appointment"
- "Move the team meeting to Thursday"

**Features:**
- 7-day lookahead
- Event creation with location
- Event deletion (with confirmation)
- Event updates
- Brisbane timezone aware

### Email Management

**Natural language examples:**
- "Draft an email to Sarah about the project update"
- "Send a message to Bob saying I'll be late"
- "Reply to John's email about the budget"
- "Email the team about tomorrow's meeting"

**Features:**
- Draft creation for review
- Direct sending (with confirmation)
- Reply to existing emails
- Contact management
- Proper formatting with greeting/sign-off

### Google Keep Notes

**Natural language examples:**
- "Create a note called 'Shopping List' with milk and eggs"
- "Add to my shopping list: bread"
- "What notes do I have?"
- "Delete the old grocery note"

**Features:**
- Note creation and editing
- Label support
- Search functionality
- Archive handling

### Voice Messages

- Send voice messages instead of typing
- Automatic transcription using Groq Whisper
- Transcription shown in response
- Processed as normal text

---

## Proactive Features

### Daily Summary (Default: 9 AM)

Automatically sends each morning:
- Today's calendar events
- High-priority pending tasks
- Upcoming deadlines

### Task Check-ins (Default: 10 AM, 2 PM, 6 PM)

Periodic prompts asking about task progress:
- Quick response buttons: 50%, done, blocked, skip
- Triggers 5-minute discussion session with extended context
- Configurable per user

### Deadline Reminders

- Sent 1 hour before task deadline
- Options to snooze, complete, or skip

### Auto-Archive

- Completed tasks archived after 7 days
- Keeps active task list clean
- Searchable via `/check archives`

### Recurring Task Generation

- Automatically creates next occurrence when task completed
- Supports: daily, weekly, monthly, custom patterns

---

## Integration Services

### AI Service

**File:** [ai_service.py](app/services/ai_service.py)

- Provider: Groq
- Model: llama-3.3-70b-versatile
- Handles all LLM calls
- Automatic retries on failure

### Calendar Service

**File:** [calendar_service.py](app/services/calendar_service.py)

- Google Calendar API
- Service account authentication
- Brisbane timezone
- Event CRUD operations

### Email Service

**File:** [email_service.py](app/services/email_service.py)

- Gmail IMAP/SMTP
- App password authentication
- Draft and send support
- Contact management

### Keep Service

**File:** [keep_service.py](app/services/keep_service.py)

- gkeepapi library
- Note CRUD operations
- Label and color support

---

## Data Storage

All data stored in Google Sheets with the following structure:

### Memories Sheet

| Column | Description |
|--------|-------------|
| user_id | Telegram user ID |
| category | Memory category |
| key | Memory identifier |
| value | Memory content |
| embedding | 384-dim vector |
| timestamp | Creation time |
| confidence | Confidence score |
| tags | JSON array of tags |

### Tasks Sheet

| Column | Description |
|--------|-------------|
| user_id | Telegram user ID |
| task_id | Unique task ID |
| title | Task title |
| description | Task details |
| priority | high/medium/low |
| status | pending/in_progress/completed |
| deadline | Due date/time |
| created_at | Creation timestamp |
| is_recurring | Boolean |
| recurrence_pattern | daily/weekly/monthly/custom |
| recurrence_end_date | End date for recurrence |
| parent_task_id | For subtasks |
| dependencies | JSON array of task IDs |
| notes | Progress notes |

### Conversations Sheet

| Column | Description |
|--------|-------------|
| user_id | Telegram user ID |
| timestamp | Message time |
| message_type | user/assistant |
| content | Message text |

### Archive Sheet

| Column | Description |
|--------|-------------|
| user_id | Telegram user ID |
| original_sheet | Source sheet name |
| content | JSON of archived item |
| archived_at | Archive timestamp |
| reason | Why archived |

### Settings Sheet (Per-User Preferences)

Stores individual user preferences that override global defaults.

| Column | Description |
|--------|-------------|
| user_id | Telegram user ID |
| setting_key | Setting name (e.g., checkin_hours) |
| setting_value | User's preference value |
| updated_at | Last modified timestamp |

**Available User Settings:**

| Setting Key | Example Value | Description |
|-------------|---------------|-------------|
| checkin_hours | 8,12,17 | Custom check-in times (or "off") |
| skipped_events | Panchang\|Gratitude | Events to hide from summaries (pipe-separated) |

### Config Sheet (Global Bot Configuration)

Admin-editable configuration for the entire bot. Edit values directly in Google Sheets.

| Column | Description |
|--------|-------------|
| variable | Configuration variable name |
| value | Current value |
| description | Human-readable explanation |
| type | Data type (string/int/bool) |

**Available Configuration Variables:**

#### Proactive Features
| Variable | Default | Description |
|----------|---------|-------------|
| daily_summary_enabled | true | Enable daily morning summary |
| daily_summary_hour | 9 | Hour to send daily summary (24h format) |
| default_checkin_hours | 10,14,18 | Default check-in hours for all users |
| checkins_enabled | true | Enable periodic task check-ins |
| deadline_reminders_enabled | true | Enable deadline reminder notifications |
| reminder_minutes_before | 60 | Minutes before deadline to send reminder |
| proactive_check_interval | 5 | Minutes between proactive checks |

#### Task Settings
| Variable | Default | Description |
|----------|---------|-------------|
| task_archive_days | 7 | Days after completion to auto-archive |
| default_task_priority | medium | Default priority for new tasks |
| auto_create_calendar_for_tasks | true | Auto-create calendar events for timed tasks |

#### AI Context Limits
| Variable | Default | Description |
|----------|---------|-------------|
| max_memories_context | 5 | Max memories in normal AI context |
| max_tasks_context | 5 | Max tasks in normal AI context |
| max_conversations_context | 5 | Max conversation history to include |
| discussion_mode_memory_limit | 15 | Max memories in task discussion mode |
| discussion_mode_task_limit | 15 | Max tasks in task discussion mode |

#### Session & Interaction
| Variable | Default | Description |
|----------|---------|-------------|
| session_timeout_minutes | 5 | Minutes before task discussion ends |
| typing_indicator_enabled | true | Show typing indicator while processing |
| include_calendar_in_responses | true | Include upcoming events in responses |

#### AI Pipeline
| Variable | Default | Description |
|----------|---------|-------------|
| use_pipeline | true | Enable 4-stage AI pipeline |
| ai_model | llama-3.3-70b-versatile | Groq model for AI responses |

#### Voice & Media
| Variable | Default | Description |
|----------|---------|-------------|
| voice_transcription_enabled | true | Enable voice message transcription |
| show_transcription_in_response | true | Show transcribed text in response |

#### Email Settings
| Variable | Default | Description |
|----------|---------|-------------|
| email_require_confirmation | true | Require confirmation before sending |
| email_default_sign_off | Best regards | Default email sign-off text |
| email_writing_style_professional | (see below) | Writing style for work/formal emails |
| email_writing_style_casual | (see below) | Writing style for friends/informal emails |

**Email Style Selection:**
The AI automatically chooses the appropriate style based on context:
- **Professional**: Used when user says "professional", "formal", "work", "client", "business", or for unknown recipients
- **Casual**: Used when user says "casual", "friendly", "mate", "friend", "informal", or for close colleagues/friends

**Default Professional Style:**
- Proper greeting (Hi [Name],)
- Paragraphs separated by blank lines
- Short paragraphs (2-3 sentences max)
- Clear call-to-action or next step
- Sign-off (Best regards, Kind regards, etc.)
- Professional but warm tone

**Default Casual Style:**
- First-person, informal voice with contractions
- Self-deprecating humor and deadpan delivery
- Parenthetical asides and dashes for interjections
- British-ish expressions when natural
- Light sign-offs (Cheers, Later, Talk soon)
- Honest, direct, genuine tone

#### Calendar Settings
| Variable | Default | Description |
|----------|---------|-------------|
| calendar_lookahead_days | 7 | Days ahead in calendar queries |
| calendar_delete_requires_confirmation | true | Require confirmation to delete |

#### System
| Variable | Default | Description |
|----------|---------|-------------|
| timezone | Australia/Brisbane | Timezone for all calculations |
| bot_name | Brain Agent | Name the bot uses for itself |
| debug_mode | false | Enable verbose debug logging |

---

## File Structure

```
brain_agent/
|-- simple_bot.py              # Main entry point
|-- Howitworks.md              # This documentation
|-- app/
|   |-- __init__.py
|   |-- config.py              # Configuration settings
|   |-- agents/
|   |   |-- conversation_agent.py   # Multi-turn conversations
|   |   |-- memory_agent.py         # Memory CRUD
|   |   |-- task_agent.py           # Task management
|   |-- database/
|   |   |-- sheets_client.py        # Google Sheets API + Settings/Config
|   |-- services/
|   |   |-- ai_service.py           # Groq LLM integration
|   |   |-- pipeline.py             # Pipeline orchestration
|   |   |-- message_router.py       # Stage 1 - Intent routing
|   |   |-- context_fetcher.py      # Stage 2 - Context retrieval
|   |   |-- action_planner.py       # Stage 3 - Action planning
|   |   |-- response_generator.py   # Stage 4 - Response generation
|   |   |-- calendar_service.py     # Google Calendar
|   |   |-- email_service.py        # Gmail integration
|   |   |-- keep_service.py         # Google Keep
|   |   |-- scheduler_service.py    # Reminder scheduling
|   |-- tools/
|   |   |-- web_search.py           # Web search capability
|   |-- utils/
|       |-- vector_processor.py     # Semantic embeddings
|-- docs/
|   |-- AI_ARCHITECTURE.md          # Architecture docs
|-- requirements.txt
|-- .env.example
|-- docker-compose.yml
```

### Google Sheets Structure

The bot uses a single Google Spreadsheet with multiple sheets:

```
Brain Agent Spreadsheet
|-- Memories      # User facts and preferences (with embeddings)
|-- Tasks         # Todo items with deadlines, priorities, recurrence
|-- Conversations # Chat history for context
|-- Archive       # Completed/deleted items for reference
|-- Users         # User metadata and last activity
|-- Settings      # Per-user preferences (check-in times, skipped events)
|-- Config        # Global bot configuration (admin-editable UI)
```

---

## Environment Variables

Required environment variables in `.env`:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Telegram Bot API token |
| `GROQ_API_KEY` | Groq API key |
| `GOOGLE_SHEETS_CREDENTIALS` | Path to service account JSON |
| `SPREADSHEET_ID` | Google Sheets ID |
| `GOOGLE_CALENDAR_ID` | Calendar email/ID |
| `GMAIL_ADDRESS` | Gmail address for drafts |
| `GMAIL_APP_PASSWORD` | App-specific password |
| `GOOGLE_KEEP_TOKEN` | Keep master token (optional) |

**Note:** Most settings that were previously environment variables can now be configured in the **Config sheet** instead, making changes easier without restarting the bot.

---

## Key Design Patterns

### Early Exit for Chat

Simple chat messages skip Stage 3 entirely, going directly to response generation. This reduces latency for conversational messages.

### Parallel Execution

Stage 1 (routing) and Stage 2 (context fetch) run in parallel. Context fetching starts immediately and is cancelled if not needed.

### High-Stakes Confirmation

Destructive actions require explicit user confirmation:
1. Bot detects high-stakes action
2. Returns confirmation request with buttons
3. Waits for user response
4. Executes or cancels based on response

### Pronoun Resolution

Full conversation history passed to Stage 3 allows resolving pronouns like "it", "that", "him" correctly.

### Graceful Degradation

Individual service failures don't crash the bot. If calendar fetch fails, message still processes with available context.
