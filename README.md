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
- Two writing styles: Professional (work/formal) and Casual (friends/informal)
- AI auto-selects style based on context or user preference

**Smart Conversation**
- Context-aware responses
- Multi-turn dialogue support
- Task discussion sessions with 5-min timeout
- Commands: /start, /help, /status, /tasks, /memories, /calendar, /dashboard, /settings, /check archives, /new session

**Quick Actions**
- /summary - Get your daily summary with actionable focus items
- /deadlines - View grouped deadline list (overdue/today/tomorrow/week)
- /archive - Archive old completed tasks (7+ days)
- Inline buttons for quick task completion, snoozing, and filtering

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

### Email
```
User: Draft a professional email to Sarah about the project deadline
Bot: I've created a draft email to Sarah:

  Subject: Project Deadline Update

  Hi Sarah,

  I wanted to touch base about the upcoming project deadline...

  Best regards

User: Write a casual email to Mike about Friday drinks
Bot: I've created a draft email to Mike:

  Subject: Friday drinks?

  Hey Mike,

  So, Friday. Drinks. You in? I was thinking we could hit up
  that new place on King Street...

  Cheers
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

### DigitalOcean Droplet (Production)

**Server:** 170.64.142.252 (Sydney)
**SSH:** `ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252`

---

### CRITICAL: DEPLOYMENT RULES

**NEVER do any of these:**
- NEVER use DigitalOcean API actions like `power_cycle`, `rebuild`, `restore`
- NEVER restart the droplet unless absolutely necessary
- NEVER run destructive commands on the server
- NEVER guess at solutions - ask for help instead

**ALWAYS do these for updates:**
```bash
# The ONLY commands needed to deploy updates:
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cd /root/brain_agent && git pull && systemctl restart brain-agent"
```

That's it. Nothing else. No rebuilding, no reinstalling, no Docker.

### Deploy and Verify (Recommended)

Deploy with immediate verification:
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cd /root/brain_agent && git pull && systemctl restart brain-agent && sleep 5 && cat /tmp/brain_agent_health.json | jq -r '.status'"
```

Expected output: `healthy`

If unhealthy, check startup logs:
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "journalctl -u brain-agent -n 30 --no-pager"
```

---

### Current Server Configuration

The bot runs as a **systemd service** (NOT Docker) for simplicity:

```
Service: brain-agent.service
Working Dir: /root/brain_agent
Python: /usr/bin/python3 (system Python 3.10)
Swap: 2GB (required for embedding model)
```

**Service commands:**
```bash
systemctl status brain-agent    # Check status
systemctl restart brain-agent   # Restart bot
systemctl stop brain-agent      # Stop bot
journalctl -u brain-agent -f    # View live logs
journalctl -u brain-agent -n 100  # Last 100 log lines
```

---

### Security Configuration

**Open ports (verified secure):**
- Port 22 (SSH) - key-based auth only, no password
- No other ports exposed
- Bot uses outbound HTTPS polling (no inbound connections needed)

**Firewall (UFW):**
```bash
ufw status                # Check firewall
ufw allow 22/tcp          # Allow SSH only
ufw enable                # Enable firewall
```

---

### Initial Server Setup (ONE TIME ONLY)

This was already done. Only repeat if server is destroyed:

```bash
# 1. Install Python and pip
apt-get update && apt-get install -y python3-pip python3-venv

# 2. Upgrade pip (prevents resolver bugs)
pip3 install --upgrade pip

# 3. Clone repository
git clone https://github.com/1davan/brain-agent.git /root/brain_agent

# 4. Upload .env and credentials
scp .env root@170.64.142.252:/root/brain_agent/
scp n8n-modia-health-11e011607797.json root@170.64.142.252:/root/brain_agent/

# 5. Install dependencies
cd /root/brain_agent && pip3 install -r requirements.txt

# 6. Add swap (prevents OOM when loading embedding model)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

# 7. Create systemd service
cat > /etc/systemd/system/brain-agent.service << 'EOF'
[Unit]
Description=Brain Agent Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/brain_agent
ExecStart=/usr/bin/python3 /root/brain_agent/simple_bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 8. Enable and start
systemctl daemon-reload
systemctl enable brain-agent
systemctl start brain-agent
```

---

### Operations Quick Reference

**Single-command health check:**
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq ."
```

**Check all service connectivity:**
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.service_health'"
```

**View recent errors:**
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.recent_errors'"
```

**Check pipeline performance:**
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.pipeline_stats'"
```

**Live log streaming:**
```bash
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "journalctl -u brain-agent -f"
```

---

### Troubleshooting

**Bot not responding after deploy:**
```bash
# Step 1: Check health file
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.status, .recent_errors'"

# Step 2: If health file missing or stale, check systemd
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "systemctl status brain-agent"

# Step 3: Check startup logs for validation failures
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "journalctl -u brain-agent -n 50 | grep -i 'startup\|error\|failed'"
```

**OOM killed (out of memory):**
```bash
free -h                          # Check swap is enabled
swapon --show                    # Verify swap active
```

**SSH permission denied:**
- Use the correct key: `-i ~/.ssh/sadhuastro_key`
- Do NOT use id_ed25519 (not authorized on this server)

**Need to add new SSH key:**
```bash
# From existing SSH session:
echo "ssh-ed25519 AAAA... user@host" >> /root/.ssh/authorized_keys
```

**Groq API timeouts:**
```bash
# Check if it's a pattern or one-off
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.recent_errors[] | select(.type | contains(\"groq\"))'"
```

**Google Sheets rate limiting:**
```bash
# Check error frequency
ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
  "cat /tmp/brain_agent_health.json | jq '.recent_errors[] | select(.type | contains(\"sheets\"))'"
```

---

### Resource Requirements

| Resource | Current | Notes |
|----------|---------|-------|
| RAM | 1GB + 2GB swap | Swap required for embedding model |
| Disk | 25GB | ~8GB used |
| CPU | 1 vCPU | Sufficient |
| Cost | $6/month | s-1vcpu-1gb droplet |

---

### Health Monitoring System

The bot maintains a health status file at `/tmp/brain_agent_health.json` that provides:

- **Current status**: `healthy`, `degraded`, or `unhealthy`
- **Service connectivity**: Status of Telegram, Google Sheets, Groq, Calendar, Email
- **Pipeline performance**: Average latency for each processing stage
- **Error aggregation**: Recent errors grouped by type with occurrence counts
- **Proactive loop status**: Last run time and next scheduled check

This file updates every 60 seconds and is the fastest way to diagnose issues.

**Status interpretation:**

| Status | Meaning | Action |
|--------|---------|--------|
| `healthy` | All systems operational | None required |
| `degraded` | Some services slow or erroring | Check `recent_errors` and `service_health` |
| `unhealthy` | Critical service failure | Check logs, may need restart |

**Health file missing or stale (>2 min old):**
- Bot process likely crashed
- Check `systemctl status brain-agent`
- Check `journalctl -u brain-agent -n 50` for crash reason

## Troubleshooting

### Startup Validation

On startup, the bot validates all external dependencies before accepting messages. Check startup logs for validation status:

```bash
journalctl -u brain-agent -n 30 | grep "STARTUP"
```

**Successful startup shows:**
```
[STARTUP] Brain Agent starting...
[STARTUP] Checking Telegram API... OK
[STARTUP] Checking Google Sheets... OK
[STARTUP] Checking Groq API... OK
[STARTUP] Checking Google Calendar... OK
[STARTUP] Checking Gmail... OK
[STARTUP] All systems operational. Ready to receive messages.
```

**Failed startup identifies the problem:**
```
[STARTUP] Checking Google Sheets... FAILED (Permission denied)
[STARTUP] CRITICAL: Cannot start - fix configuration and restart
```

### Common Issues

**"Google Sheets API error"**
- Ensure credentials.json is in the correct location
- Verify the service account has Editor access to the spreadsheet
- Check that Google Sheets API is enabled
- Check startup logs: `journalctl -u brain-agent | grep "Google Sheets"`

**"Calendar not configured"**
- Enable Google Calendar API in Cloud Console
- Share your calendar with the service account email
- Check GOOGLE_CALENDAR_ID in .env

**Bot not responding**
- First: `cat /tmp/brain_agent_health.json | jq '.status'`
- If `healthy`: Check Telegram token, network connectivity
- If `degraded`: Check `.service_health` for failing service
- If file missing: `systemctl status brain-agent`

**Docker build fails with "no space left"**
- Run `docker system prune -af` to clear old images
- The CPU-only PyTorch build requires ~8GB free during build

**Container keeps restarting**
- Check logs: `docker compose logs`
- Verify .env file has all required variables
- Ensure credentials.json exists and is valid

## License

MIT License
