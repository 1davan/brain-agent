# Brain Agent

An intelligent AI chatbot with human-like memory and task management capabilities, powered by Groq and Google Sheets.

## Quick Start

**Local Development:**
```bash
cd brain_agent
uv run python simple_bot.py
```

**Production (Docker):**
```bash
docker compose up -d --build
```

The bot will start and connect to Telegram.

## Features

**Memory System**
- Semantic search and retrieval
- Memory merging to avoid duplicates
- Persistent storage in Google Sheets

**Task Management**
- Intelligent priority assignment
- Natural language deadline parsing
- Recurring tasks (daily, weekly, monthly)
- Progress tracking with percentage updates
- Proactive check-ins 3x daily (10am, 2pm, 6pm)
- Auto-archive completed tasks after 7 days

**Calendar Integration**
- View upcoming events
- Create calendar events via chat
- Daily morning summary with calendar

**Email Integration**
- Create email drafts via chat
- Reply to existing email threads
- Contact management from Google Sheets

**Smart Conversation**
- Context-aware responses
- Multi-turn dialogue support
- Task discussion sessions with 5-min timeout
- Commands: /start, /help, /status, /tasks, /memories, /calendar, /check archives, /new session

## Setup

### 1. Prerequisites

- Python 3.11+
- uv (Python package manager)
- Google Cloud account (for Sheets API)
- Groq API key
- Telegram Bot Token

### 2. Google Sheets Setup

1. Create a Google Sheet at [sheets.google.com](https://sheets.google.com)
2. Enable Google Sheets API in [Google Cloud Console](https://console.cloud.google.com)
3. Create a Service Account with Editor permissions
4. Download the JSON credentials file
5. Share your spreadsheet with the service account email

### 3. Google Calendar Setup (Optional)

1. Enable Google Calendar API in Google Cloud Console
2. Share your calendar with the service account email (found in credentials JSON)
3. Set `GOOGLE_CALENDAR_ID` in .env (or leave as "primary")

### 4. Get API Keys

**Groq API Key**: Sign up at [groq.com](https://groq.com) and get your API key

**Telegram Bot Token**: Message @BotFather on Telegram, use /newbot

### 5. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit with your keys
```

Fill in your `.env` file:
```bash
TELEGRAM_TOKEN=your_telegram_token
GROQ_API_KEY=your_groq_api_key
GOOGLE_SHEETS_CREDENTIALS=credentials.json
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_CALENDAR_ID=primary

# Optional: Email drafts
GMAIL_ADDRESS=your_email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
```

### 6. Install and Run

**Local Development:**
```bash
# Install dependencies
uv pip install -r requirements.txt

# Run the bot
uv run python simple_bot.py
```

**Docker (Recommended for Production):**
```bash
# Build and run
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

## Usage Examples

### Memory
```
User: I love Italian food and my favorite restaurant is Mario's
Bot: I'll remember that you love Italian food and that Mario's is your favorite restaurant.

User: What's my favorite cuisine?
Bot: Based on what you've told me, you love Italian food.
```

### Tasks
```
User: Remind me to buy groceries tomorrow at 5pm
Bot: I've created a task: "buy groceries" with high priority, due tomorrow at 17:00.

User: Mark groceries as complete
Bot: Task completed: buy groceries
```

### Proactive Check-ins
```
Bot: Hey! Just checking in on 'Project proposal'. Have you had a chance to start on it? (Due tomorrow)
     Reply with your progress (e.g., '50%', 'done', 'blocked') or '/new session' to skip.

User: 70%
Bot: Got it - 'Project proposal' is now at 70%. Keep it up!

User: done
Bot: Excellent! 'Project proposal' marked as complete! Great work!
```

### Archived Tasks
```
User: /check archives meeting
Bot: ARCHIVED TASKS matching 'meeting':
     - Prepare team meeting agenda
       Completed: 2024-01-15
     - Book meeting room
       Completed: 2024-01-10
```

### Calendar
```
User: What's in my calendar tomorrow?
Bot: You have 2 events tomorrow:
  - 09:00AM: Team standup
  - 02:00PM: Client meeting @ Conference Room B
```

## Project Structure

```
brain_agent/
├── simple_bot.py              # Main entry point
├── Dockerfile                 # Multi-stage production build
├── docker-compose.yml         # Container orchestration
├── .gitignore                 # Excludes secrets from git
├── app/
│   ├── config.py              # Configuration (env vars)
│   ├── database/
│   │   ├── sheets_client.py   # Google Sheets integration
│   │   └── local_storage.py   # Fallback storage
│   ├── agents/
│   │   ├── memory_agent.py    # Memory management
│   │   ├── task_agent.py      # Task handling
│   │   └── conversation_agent.py  # Dialogue management
│   ├── services/
│   │   ├── ai_service.py      # Groq LLM integration
│   │   ├── calendar_service.py    # Google Calendar
│   │   ├── email_service.py   # Gmail drafts and contacts
│   │   └── scheduler_service.py   # Task scheduling
│   ├── tools/
│   │   └── web_search.py      # Web search capability
│   └── utils/
│       └── vector_processor.py    # Semantic search
├── requirements.txt
└── .env.example
```

## Deployment

### DigitalOcean Droplet

The bot is designed to run on a minimal $6/month droplet (1GB RAM, 25GB disk).

**Server Setup:**
```bash
# SSH into your droplet
ssh deploy@your-droplet-ip

# Clone the repository
git clone https://github.com/your-username/brain-agent.git
cd brain-agent

# Create .env file with your secrets
nano .env

# Copy credentials.json
# (upload via scp or paste contents)

# Build and run
docker compose up -d --build
```

**Management Commands:**
```bash
# View logs
docker compose logs -f

# Restart the bot
docker compose restart

# Update after pushing changes
git pull && docker compose up -d --build

# Check container status
docker ps
```

**Security Features (Built-in):**
- Container runs as non-root user
- Read-only filesystem with tmpfs for cache
- No exposed ports (uses Telegram polling)
- Resource limits to prevent OOM
- Automatic restarts on failure

### Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 512MB | 1GB |
| Disk | 10GB | 25GB |
| CPU | 1 vCPU | 1 vCPU |

The Docker image uses CPU-only PyTorch (~800MB) instead of CUDA version (~7GB) to fit on small droplets.

## Troubleshooting

**"Google Sheets API error"**
- Ensure credentials.json is in the correct location
- Verify the service account has Editor access to the spreadsheet
- Check that Google Sheets API is enabled

**"Calendar not configured"**
- Enable Google Calendar API in Cloud Console
- Share your calendar with the service account email
- Check GOOGLE_CALENDAR_ID in .env

**Bot not responding**
- Check Telegram token is correct
- Verify the bot is running (check console output)
- Ensure network connectivity

**Docker build fails with "no space left"**
- Run `docker system prune -af` to clear old images
- The CPU-only PyTorch build requires ~8GB free during build

**Container keeps restarting**
- Check logs: `docker compose logs`
- Verify .env file has all required variables
- Ensure credentials.json exists and is valid

## License

MIT License
