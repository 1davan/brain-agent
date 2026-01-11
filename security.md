# SECURITY AUDIT FRAMEWORK v3.0

**Last Updated: January 2026**

A comprehensive security hardening guide for repositories and DigitalOcean Droplet deployments. This framework is designed to bulletproof your infrastructure against modern attack vectors.

---

## TABLE OF CONTENTS

1. [Pre-Deployment Repository Audit](#layer-1-pre-deployment-repository-audit)
2. [Secrets and Credential Management](#layer-2-secrets-and-credential-management)
3. [Docker and Container Security](#layer-3-docker-and-container-security)
4. [DigitalOcean Droplet Hardening](#layer-4-digitalocean-droplet-hardening)
5. [Network and Firewall Configuration](#layer-5-network-and-firewall-configuration)
6. [Runtime Security Monitoring](#layer-6-runtime-security-monitoring)
7. [Dependency and Supply Chain Security](#layer-7-dependency-and-supply-chain-security)
8. [Backup and Disaster Recovery](#layer-8-backup-and-disaster-recovery)
9. [Automated Security Pipelines](#layer-9-automated-security-pipelines)
10. [Red Team Simulation Checklist](#layer-10-red-team-simulation-checklist)

---

## LAYER 1: PRE-DEPLOYMENT REPOSITORY AUDIT

### 1.1 Git History Secrets Scan

**CRITICAL**: Secrets committed and then deleted are still in git history.

```bash
# Install truffleHog for deep history scanning
pip install truffleHog

# Scan entire git history for secrets
trufflehog git file://. --only-verified

# Alternative: use gitleaks (faster, more patterns)
# Install: https://github.com/gitleaks/gitleaks
gitleaks detect --source . --verbose

# Nuclear option: scan for high-entropy strings
git log -p | grep -E '[A-Za-z0-9+/]{40,}' | head -50
```

**Red Flags to Hunt**:
```bash
# Find hardcoded API keys, tokens, passwords
grep -rE "(api[_-]?key|apikey|secret|password|token|auth|credential)" \
  --include="*.py" --include="*.js" --include="*.ts" --include="*.env*" \
  --include="*.yml" --include="*.yaml" --include="*.json" .

# Find AWS keys specifically
grep -rE "AKIA[0-9A-Z]{16}" .

# Find private keys
grep -rE "BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE KEY" .

# Find JWT tokens
grep -rE "eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*" .
```

### 1.2 Mandatory .gitignore Entries

Create or verify your `.gitignore` contains:

```gitignore
# Environment and secrets
.env
.env.*
!.env.example
*.pem
*.key
*.crt
*.p12
*.pfx
credentials*.json
*-credentials.json
*secret*.json
service-account*.json

# Build artifacts that may contain secrets
*.pyc
__pycache__/
node_modules/
.next/
dist/
build/

# IDE and OS files
.idea/
.vscode/settings.json
.DS_Store
Thumbs.db

# Logs that may contain sensitive data
*.log
logs/

# Database files
*.db
*.sqlite
*.sqlite3

# Backup files
*.bak
*.backup
*.swp
*~

# Docker secrets
docker-compose.override.yml
.docker/
```

### 1.3 Sensitive File Detection Script

```bash
#!/bin/bash
# save as: scripts/security-scan.sh

echo "=== REPOSITORY SECURITY SCAN ==="
echo ""

# Check for credential files that should not be committed
DANGEROUS_FILES=(
    "*.pem"
    "*.key"
    "*.p12"
    "*credentials*.json"
    "*secret*.json"
    "*service-account*.json"
    ".env"
    "*.sqlite"
    "*.db"
)

echo "[1] Checking for dangerous files in git tracking..."
for pattern in "${DANGEROUS_FILES[@]}"; do
    found=$(git ls-files "$pattern" 2>/dev/null)
    if [ -n "$found" ]; then
        echo "  CRITICAL: $found is tracked by git!"
    fi
done

echo ""
echo "[2] Checking for hardcoded secrets in code..."
grep -rn --include="*.py" --include="*.js" --include="*.ts" \
    -E "(password|secret|api_key|apikey|token)\s*=\s*['\"][^'\"]+['\"]" . \
    | grep -v "example" | grep -v "placeholder" | head -20

echo ""
echo "[3] Checking for exposed ports in Docker configs..."
grep -rn "0.0.0.0" docker-compose*.yml Dockerfile* 2>/dev/null

echo ""
echo "[4] Checking for privilege escalation risks..."
grep -rn --include="Dockerfile*" "USER root" .
grep -rn --include="docker-compose*.yml" "privileged:" .

echo ""
echo "=== SCAN COMPLETE ==="
```

---

## LAYER 2: SECRETS AND CREDENTIAL MANAGEMENT

### 2.1 Environment Variable Security

**NEVER** do this:
```yaml
# BAD - secrets in docker-compose.yml
environment:
  - API_KEY=sk-abc123secretkey
```

**ALWAYS** do this:
```yaml
# GOOD - secrets from .env file (not committed)
environment:
  - API_KEY=${API_KEY}
```

### 2.2 Proper .env.example Template

Your `.env.example` should contain placeholders only:

```bash
# API Keys - obtain from respective dashboards
TELEGRAM_TOKEN=your_telegram_bot_token_here
GROQ_API_KEY=your_groq_api_key_here

# Google Cloud - download from GCP Console
GOOGLE_SHEETS_CREDENTIALS=credentials.json
SPREADSHEET_ID=your_spreadsheet_id_here

# Application Settings
CACHE_SIZE=1000
MAX_MEMORY_ITEMS=100

# Production Webhook (HTTPS required)
WEBHOOK_URL=https://your-secure-domain.com
PORT=8443

# Security Settings
ALLOWED_ORIGINS=https://yourdomain.com
RATE_LIMIT_PER_MINUTE=60
```

### 2.3 DigitalOcean Secrets Management

For production, use DigitalOcean's native secrets:

```bash
# Create encrypted environment using doctl
doctl apps create --spec .do/app.yaml

# In app.yaml, reference secrets:
# envs:
#   - key: API_KEY
#     scope: RUN_TIME
#     type: SECRET
#     value: ${API_KEY}
```

### 2.4 Runtime Secrets Injection (Docker)

```yaml
# docker-compose.yml - production pattern
services:
  app:
    build: .
    secrets:
      - telegram_token
      - groq_api_key
    environment:
      - TELEGRAM_TOKEN_FILE=/run/secrets/telegram_token

secrets:
  telegram_token:
    file: ./secrets/telegram_token.txt
  groq_api_key:
    file: ./secrets/groq_api_key.txt
```

Then in your Python code:
```python
import os

def get_secret(name: str) -> str:
    """Read secret from file or environment variable."""
    file_path = os.getenv(f"{name}_FILE")
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return f.read().strip()
    return os.getenv(name, "")
```

---

## LAYER 3: DOCKER AND CONTAINER SECURITY

### 3.1 Hardened Dockerfile Template

```dockerfile
# Use specific version, never :latest
FROM python:3.11-slim-bookworm AS builder

# Security: Don't run apt as interactive
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /build

# Install build dependencies in separate layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy only requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Production Stage ---
FROM python:3.11-slim-bookworm AS production

# Security hardening
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create non-root user BEFORE copying files
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code with correct ownership
COPY --chown=appuser:appgroup . .

# Remove unnecessary files
RUN rm -rf \
    .git \
    .gitignore \
    .env* \
    *.md \
    tests/ \
    __pycache__ \
    *.pyc \
    .pytest_cache

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8443/health')" || exit 1

EXPOSE 8443

# Use exec form to receive signals properly
CMD ["python", "main.py"]
```

### 3.2 Hardened docker-compose.yml

```yaml
version: '3.8'

services:
  brain-agent:
    build:
      context: .
      dockerfile: Dockerfile
      target: production

    # Security constraints
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Only if binding to ports < 1024
    read_only: true

    # Resource limits prevent DoS
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 128M

    # Tmpfs for writable directories
    tmpfs:
      - /tmp:size=64M,mode=1777
      - /app/logs:size=32M,mode=1755

    # Network isolation
    networks:
      - internal

    # Environment from file
    env_file:
      - .env

    # Secrets management
    secrets:
      - telegram_token
      - groq_api_key

    # Minimal volume mounts
    volumes:
      - ./credentials.json:/app/credentials.json:ro

    # Health monitoring
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8443/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

    restart: unless-stopped

    # Logging limits
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  internal:
    driver: bridge
    internal: true  # No external access

  # If you need external access, use a reverse proxy network
  web:
    driver: bridge

secrets:
  telegram_token:
    file: ./secrets/telegram_token.txt
  groq_api_key:
    file: ./secrets/groq_api_key.txt
```

### 3.3 Container Security Scanning

```bash
# Scan image for vulnerabilities using Trivy
trivy image your-image:tag

# Scan with severity filter
trivy image --severity HIGH,CRITICAL your-image:tag

# Scan filesystem (before building)
trivy fs .

# Alternative: use Grype
grype your-image:tag
```

---

## LAYER 4: DIGITALOCEAN DROPLET HARDENING

### 4.1 Initial Server Setup Script

Run this immediately after Droplet creation:

```bash
#!/bin/bash
# save as: scripts/droplet-hardening.sh
set -euo pipefail

echo "=== DIGITALOCEAN DROPLET HARDENING ==="

# 1. Update system
echo "[1/12] Updating system packages..."
apt-get update && apt-get upgrade -y
apt-get install -y \
    ufw \
    fail2ban \
    unattended-upgrades \
    logwatch \
    auditd \
    rkhunter \
    lynis

# 2. Create deploy user
echo "[2/12] Creating deploy user..."
if ! id "deploy" &>/dev/null; then
    useradd --create-home --shell /bin/bash --groups sudo deploy
    mkdir -p /home/deploy/.ssh
    chmod 700 /home/deploy/.ssh
    # Copy your SSH key here
    cp /root/.ssh/authorized_keys /home/deploy/.ssh/
    chown -R deploy:deploy /home/deploy/.ssh
    chmod 600 /home/deploy/.ssh/authorized_keys
fi

# 3. Harden SSH
echo "[3/12] Hardening SSH configuration..."
cat > /etc/ssh/sshd_config.d/hardening.conf << 'EOF'
# Disable root login
PermitRootLogin no

# Only allow specific user
AllowUsers deploy

# Disable password authentication
PasswordAuthentication no
ChallengeResponseAuthentication no
UsePAM yes

# Use strong ciphers only
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org

# Session hardening
ClientAliveInterval 300
ClientAliveCountMax 2
MaxAuthTries 3
MaxSessions 2

# Disable unnecessary features
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
EOF

# 4. Configure firewall
echo "[4/12] Configuring UFW firewall..."
ufw default deny incoming
ufw default deny outgoing  # Strict: deny outgoing by default
ufw allow out 53/udp       # DNS
ufw allow out 80/tcp       # HTTP (for updates)
ufw allow out 443/tcp      # HTTPS
ufw allow out 123/udp      # NTP

# Allow incoming SSH and app ports
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8443/tcp

# Rate limit SSH
ufw limit 22/tcp

ufw --force enable

# 5. Configure Fail2Ban
echo "[5/12] Configuring Fail2Ban..."
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = ufw

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400

[sshd-ddos]
enabled = true
port = ssh
filter = sshd-ddos
logpath = /var/log/auth.log
maxretry = 6
bantime = 172800
EOF

systemctl enable fail2ban
systemctl restart fail2ban

# 6. Enable automatic security updates
echo "[6/12] Enabling automatic security updates..."
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

# 7. Kernel hardening
echo "[7/12] Applying kernel hardening..."
cat > /etc/sysctl.d/99-security.conf << 'EOF'
# IP Spoofing protection
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Disable source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0

# Disable ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0

# Disable IP forwarding
net.ipv4.ip_forward = 0
net.ipv6.conf.all.forwarding = 0

# Enable SYN flood protection
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2

# Ignore ICMP broadcasts
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Log martian packets
net.ipv4.conf.all.log_martians = 1

# ASLR protection
kernel.randomize_va_space = 2

# Restrict dmesg
kernel.dmesg_restrict = 1

# Restrict kernel pointers
kernel.kptr_restrict = 2

# Disable core dumps
fs.suid_dumpable = 0
EOF

sysctl -p /etc/sysctl.d/99-security.conf

# 8. Configure auditd
echo "[8/12] Configuring audit logging..."
cat > /etc/audit/rules.d/security.rules << 'EOF'
# Delete all existing rules
-D

# Buffer size
-b 8192

# Failure mode (1=print warning, 2=panic)
-f 1

# Monitor authentication
-w /etc/passwd -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers

# Monitor SSH
-w /etc/ssh/sshd_config -p wa -k sshd
-w /root/.ssh -p wa -k rootssh

# Monitor cron
-w /etc/cron.d -p wa -k cron
-w /etc/crontab -p wa -k cron
-w /var/spool/cron -p wa -k cron

# Monitor Docker
-w /var/run/docker.sock -p wa -k docker
-w /etc/docker -p wa -k docker

# Monitor executable locations
-w /tmp -p x -k tmp_exec
-w /dev/shm -p x -k shm_exec

# Monitor system calls for privilege escalation
-a always,exit -F arch=b64 -S execve -k exec
-a always,exit -F arch=b64 -S setuid -S setgid -k priv_esc
EOF

systemctl enable auditd
systemctl restart auditd

# 9. Secure shared memory
echo "[9/12] Securing shared memory..."
if ! grep -q "/run/shm" /etc/fstab; then
    echo "tmpfs /run/shm tmpfs defaults,noexec,nosuid,nodev 0 0" >> /etc/fstab
fi

# 10. Disable unnecessary services
echo "[10/12] Disabling unnecessary services..."
DISABLE_SERVICES="cups avahi-daemon bluetooth"
for svc in $DISABLE_SERVICES; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl disable "$svc"
        systemctl stop "$svc"
    fi
done

# 11. Set file permissions
echo "[11/12] Setting secure file permissions..."
chmod 600 /etc/ssh/sshd_config
chmod 644 /etc/passwd
chmod 600 /etc/shadow
chmod 644 /etc/group
chmod 600 /etc/gshadow
chmod 700 /root
chmod 600 /boot/grub/grub.cfg 2>/dev/null || true

# 12. Create security check script
echo "[12/12] Creating daily security check script..."
cat > /etc/cron.daily/security-check << 'EOF'
#!/bin/bash
LOG="/var/log/security-check.log"
echo "=== Security Check $(date) ===" >> $LOG

# Check for unauthorized SUID/SGID binaries
echo "SUID/SGID changes:" >> $LOG
find / -type f \( -perm -4000 -o -perm -2000 \) -ls 2>/dev/null | \
    md5sum >> $LOG

# Check for world-writable files
echo "World-writable files:" >> $LOG
find / -xdev -type f -perm -0002 -ls 2>/dev/null >> $LOG

# Check listening ports
echo "Listening ports:" >> $LOG
ss -tulpn | grep LISTEN >> $LOG

# Check failed SSH attempts
echo "Failed SSH attempts (last 24h):" >> $LOG
grep "Failed password" /var/log/auth.log | tail -20 >> $LOG

# Check for rootkits
rkhunter --check --skip-keypress --quiet >> $LOG 2>&1
EOF

chmod 700 /etc/cron.daily/security-check

# Restart services
echo "[*] Restarting SSH (connection may drop)..."
systemctl restart sshd

echo ""
echo "=== HARDENING COMPLETE ==="
echo "IMPORTANT: Test SSH access with 'deploy' user before logging out!"
echo "Run 'lynis audit system' for a full security audit."
```

### 4.2 SSH Key-Only Access Setup

On your local machine:

```bash
# Generate strong SSH key (Ed25519 recommended)
ssh-keygen -t ed25519 -a 100 -C "deploy@your-project"

# Copy to server
ssh-copy-id -i ~/.ssh/id_ed25519.pub deploy@your-droplet-ip

# Test before disabling password auth
ssh -i ~/.ssh/id_ed25519 deploy@your-droplet-ip
```

### 4.3 DigitalOcean Cloud Firewall Rules

Configure via DigitalOcean Console or doctl:

```bash
# Create cloud firewall
doctl compute firewall create \
  --name "production-firewall" \
  --inbound-rules "protocol:tcp,ports:22,address:YOUR_IP/32" \
  --inbound-rules "protocol:tcp,ports:80,address:0.0.0.0/0" \
  --inbound-rules "protocol:tcp,ports:443,address:0.0.0.0/0" \
  --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0" \
  --outbound-rules "protocol:udp,ports:53,address:0.0.0.0/0" \
  --droplet-ids YOUR_DROPLET_ID
```

---

## LAYER 5: NETWORK AND FIREWALL CONFIGURATION

### 5.1 Nginx Reverse Proxy with Security Headers

```nginx
# /etc/nginx/sites-available/app
upstream app_backend {
    server 127.0.0.1:8443;
    keepalive 32;
}

# Rate limiting zone
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

server {
    listen 80;
    server_name your-domain.com;

    # Redirect all HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Configuration (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets off;

    # Modern TLS only
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # Hide server version
    server_tokens off;

    # Request limits
    client_max_body_size 10M;
    client_body_timeout 10s;
    client_header_timeout 10s;

    # Connection limits
    limit_conn conn_limit 10;

    location / {
        # Rate limiting
        limit_req zone=api_limit burst=20 nodelay;

        proxy_pass http://app_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Block common attack patterns
    location ~* (\.php|\.asp|\.aspx|\.jsp|\.cgi)$ {
        return 404;
    }

    # Block hidden files
    location ~ /\. {
        deny all;
        return 404;
    }

    # Health check endpoint (no rate limit)
    location /health {
        proxy_pass http://app_backend;
        access_log off;
    }
}
```

### 5.2 Egress Filtering (Outbound Traffic Control)

```bash
# Block reverse shells and unauthorized outbound connections
# Only allow specific outbound ports

# Reset to defaults
iptables -P OUTPUT ACCEPT
iptables -F OUTPUT

# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Allow HTTP/HTTPS (for updates and API calls)
iptables -A OUTPUT -p tcp --dport 80 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT

# Allow NTP
iptables -A OUTPUT -p udp --dport 123 -j ACCEPT

# Allow localhost
iptables -A OUTPUT -o lo -j ACCEPT

# Log and drop everything else
iptables -A OUTPUT -j LOG --log-prefix "BLOCKED_OUTBOUND: "
iptables -A OUTPUT -j DROP

# Save rules
iptables-save > /etc/iptables/rules.v4
```

### 5.3 VPC and Private Networking

```bash
# Verify your Droplet is in a VPC
doctl compute droplet get YOUR_DROPLET_ID --format ID,Name,VPCNetworks

# Bind services to private IP only
# In your app config or docker-compose:
# DATABASE_HOST=10.xxx.xxx.xxx (private VPC IP)
# REDIS_HOST=10.xxx.xxx.xxx

# Verify no services listen on public interface except nginx
ss -tulpn | grep -v "127.0.0.1" | grep -v "10\."
```

---

## LAYER 6: RUNTIME SECURITY MONITORING

### 6.1 Audit Log Monitoring

```bash
# Real-time audit log monitoring
ausearch -k identity --start today

# Check for privilege escalation attempts
ausearch -k priv_esc --start today

# Check for suspicious executions in /tmp
ausearch -k tmp_exec --start today

# Generate audit report
aureport --summary
aureport --auth
aureport --failed
```

### 6.2 Container Runtime Monitoring

```bash
# Monitor Docker events in real-time
docker events --filter 'type=container' &

# Check container resource usage
docker stats --no-stream

# Scan running container for vulnerabilities
docker exec CONTAINER_NAME cat /etc/os-release
trivy image $(docker inspect CONTAINER_NAME --format='{{.Image}}')

# Check for containers running as root
docker ps -q | xargs -I{} docker inspect {} --format '{{.Name}}: User={{.Config.User}}'
```

### 6.3 Log Analysis Script

```bash
#!/bin/bash
# save as: scripts/analyze-logs.sh

echo "=== SECURITY LOG ANALYSIS ==="
echo "Time: $(date)"
echo ""

echo "[1] Failed SSH attempts (last 24h):"
grep "Failed password" /var/log/auth.log | awk '{print $11}' | sort | uniq -c | sort -rn | head -10
echo ""

echo "[2] Successful logins (last 24h):"
grep "Accepted" /var/log/auth.log | tail -10
echo ""

echo "[3] Sudo usage:"
grep "sudo:" /var/log/auth.log | tail -10
echo ""

echo "[4] Blocked outbound connections:"
grep "BLOCKED_OUTBOUND" /var/log/syslog | tail -10
echo ""

echo "[5] Failed2Ban status:"
fail2ban-client status sshd 2>/dev/null || echo "Fail2Ban not running"
echo ""

echo "[6] Docker container status:"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

echo "[7] Unusual processes:"
ps aux | awk '$3 > 50 || $4 > 50 {print $0}'
echo ""

echo "[8] Listening ports check:"
ss -tulpn | grep LISTEN | grep -v "127.0.0.1"
```

### 6.4 Intrusion Detection with OSSEC/Wazuh

```bash
# Install Wazuh agent
curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --dearmor -o /usr/share/keyrings/wazuh.gpg
echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" > /etc/apt/sources.list.d/wazuh.list
apt-get update
apt-get install wazuh-agent

# Configure to monitor critical paths
cat >> /var/ossec/etc/ossec.conf << 'EOF'
<syscheck>
  <directories check_all="yes" realtime="yes">/etc,/usr/bin,/usr/sbin</directories>
  <directories check_all="yes" realtime="yes">/root/.ssh</directories>
</syscheck>
EOF
```

---

## LAYER 7: DEPENDENCY AND SUPPLY CHAIN SECURITY

### 7.1 Python Dependency Auditing

```bash
# Install safety and pip-audit
pip install safety pip-audit

# Scan for known vulnerabilities
pip-audit

# Alternative with safety
safety check --full-report

# Pin all dependencies with hashes
pip-compile --generate-hashes requirements.in -o requirements.txt

# Verify installed packages match requirements
pip install --require-hashes -r requirements.txt
```

### 7.2 Secure requirements.txt Template

```txt
# requirements.txt - with version pinning and hashes
# Generated by pip-compile with --generate-hashes

# Core dependencies
aiohttp==3.9.1 \
    --hash=sha256:...
python-telegram-bot==21.0 \
    --hash=sha256:...

# Security: No wildcards, no >= without upper bounds
# BAD:  requests>=2.0
# GOOD: requests>=2.31.0,<3.0.0
```

### 7.3 Pre-Commit Security Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: detect-private-key
      - id: detect-aws-credentials
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: check-merge-conflict
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.6
    hooks:
      - id: bandit
        args: ['-r', '.', '-ll']

  - repo: https://github.com/pyupio/safety
    rev: 2.3.5
    hooks:
      - id: safety
        args: ['check', '--full-report']
```

Install hooks:
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### 7.4 Docker Image Supply Chain

```bash
# Always use official images
# BAD:  FROM node
# GOOD: FROM node:20-slim@sha256:abc123...

# Get image digest
docker pull python:3.11-slim
docker images --digests python:3.11-slim

# In Dockerfile, pin to digest:
# FROM python:3.11-slim@sha256:your-specific-digest

# Scan base image
trivy image python:3.11-slim
```

---

## LAYER 8: BACKUP AND DISASTER RECOVERY

### 8.1 Secure Backup Strategy

```bash
#!/bin/bash
# save as: scripts/backup.sh

set -euo pipefail

BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create encrypted backup
backup_app() {
    mkdir -p "$BACKUP_DIR"

    # Stop containers gracefully
    docker-compose down

    # Create tarball (excluding secrets)
    tar --exclude='.env' \
        --exclude='secrets/' \
        --exclude='*.log' \
        --exclude='__pycache__' \
        -czvf "$BACKUP_DIR/app_$DATE.tar.gz" /opt/app

    # Encrypt backup
    gpg --symmetric --cipher-algo AES256 \
        --output "$BACKUP_DIR/app_$DATE.tar.gz.gpg" \
        "$BACKUP_DIR/app_$DATE.tar.gz"

    # Remove unencrypted backup
    rm "$BACKUP_DIR/app_$DATE.tar.gz"

    # Upload to DigitalOcean Spaces (or S3)
    s3cmd put "$BACKUP_DIR/app_$DATE.tar.gz.gpg" \
        s3://your-backup-bucket/droplet-backups/

    # Restart containers
    docker-compose up -d
}

# Clean old backups
cleanup_old_backups() {
    find "$BACKUP_DIR" -name "*.gpg" -mtime +$RETENTION_DAYS -delete

    # Also clean remote backups
    s3cmd ls s3://your-backup-bucket/droplet-backups/ | \
        awk '{print $4}' | while read backup; do
            backup_date=$(echo "$backup" | grep -oP '\d{8}')
            if [[ $(date -d "$backup_date" +%s) -lt $(date -d "-$RETENTION_DAYS days" +%s) ]]; then
                s3cmd del "$backup"
            fi
        done
}

backup_app
cleanup_old_backups
```

### 8.2 DigitalOcean Snapshot Policy

```bash
# Create snapshot via API
doctl compute droplet-action snapshot YOUR_DROPLET_ID --snapshot-name "pre-deploy-$(date +%Y%m%d)"

# Automate weekly snapshots (add to cron)
# 0 2 * * 0 doctl compute droplet-action snapshot DROPLET_ID --snapshot-name "weekly-$(date +\%Y\%m\%d)"

# List snapshots
doctl compute snapshot list --resource droplet

# Clean snapshots older than 30 days
doctl compute snapshot list --resource droplet --format ID,Name,Created | \
    awk -v date="$(date -d '-30 days' +%Y-%m-%d)" '$3 < date {print $1}' | \
    xargs -I{} doctl compute snapshot delete {}
```

### 8.3 Disaster Recovery Runbook

```markdown
## DISASTER RECOVERY RUNBOOK

### Scenario 1: Compromised Droplet
1. IMMEDIATELY: Create a forensic snapshot (do NOT destroy yet)
   doctl compute droplet-action snapshot DROPLET_ID --snapshot-name "forensic-$(date +%s)"

2. Block all inbound traffic except your IP
   doctl compute firewall update FIREWALL_ID --inbound-rules "protocol:tcp,ports:22,address:YOUR_IP/32"

3. Rotate ALL secrets:
   - Telegram bot token
   - Groq API key
   - Google credentials
   - SSH keys

4. Create NEW Droplet from CLEAN image (not snapshot)
5. Run hardening script
6. Deploy from clean git (verify commit signatures)
7. Restore data from KNOWN-GOOD encrypted backup
8. Investigate forensic snapshot offline

### Scenario 2: Secrets Exposed
1. IMMEDIATELY rotate exposed credentials
2. Check git history: git log --all --full-history -- "*secret*" "*.env"
3. If in git history: use BFG Repo Cleaner or git filter-branch
4. Force push cleaned history
5. Notify affected services (Telegram, Groq, Google)
6. Monitor for unauthorized usage

### Scenario 3: Container Breakout
1. Stop all containers: docker stop $(docker ps -q)
2. Check host for modifications:
   - ls -la /root/.ssh/
   - cat /etc/passwd | diff - /etc/passwd.bak
   - ausearch -k docker
3. If host compromised: follow Scenario 1
4. Rebuild container images from scratch
5. Implement additional isolation (gVisor, Kata Containers)
```

---

## LAYER 9: AUTOMATED SECURITY PIPELINES

### 9.1 GitHub Actions Security Workflow

```yaml
# .github/workflows/security.yml
name: Security Checks

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 6 * * *'  # Daily at 6 AM

jobs:
  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Gitleaks Scan
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install pip-audit safety bandit

      - name: Pip Audit
        run: pip-audit -r requirements.txt

      - name: Safety Check
        run: safety check -r requirements.txt

      - name: Bandit Security Scan
        run: bandit -r . -ll -f json -o bandit-report.json

      - name: Upload Bandit Report
        uses: actions/upload-artifact@v4
        with:
          name: bandit-report
          path: bandit-report.json

  container-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build Image
        run: docker build -t app:scan .

      - name: Trivy Scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'app:scan'
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'

      - name: Upload Trivy Results
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'

  sast-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Semgrep Scan
        uses: returntocorp/semgrep-action@v1
        with:
          config: >-
            p/python
            p/security-audit
            p/secrets
```

### 9.2 Pre-Deploy Security Gate

```bash
#!/bin/bash
# scripts/pre-deploy-check.sh
# Run before every deployment

set -e

echo "=== PRE-DEPLOYMENT SECURITY GATE ==="

# 1. Check for secrets in code
echo "[1/6] Scanning for secrets..."
if gitleaks detect --source . --no-git; then
    echo "PASS: No secrets detected"
else
    echo "FAIL: Secrets detected in codebase"
    exit 1
fi

# 2. Dependency vulnerabilities
echo "[2/6] Checking dependencies..."
if pip-audit -r requirements.txt; then
    echo "PASS: No vulnerable dependencies"
else
    echo "FAIL: Vulnerable dependencies found"
    exit 1
fi

# 3. Static analysis
echo "[3/6] Running static analysis..."
if bandit -r . -ll -q; then
    echo "PASS: No high-severity issues"
else
    echo "FAIL: Security issues found"
    exit 1
fi

# 4. Dockerfile security
echo "[4/6] Checking Dockerfile..."
if docker run --rm -i hadolint/hadolint < Dockerfile; then
    echo "PASS: Dockerfile follows best practices"
else
    echo "WARN: Dockerfile improvements recommended"
fi

# 5. Container image scan
echo "[5/6] Scanning container image..."
docker build -t app:check .
if trivy image --severity HIGH,CRITICAL --exit-code 1 app:check; then
    echo "PASS: No critical vulnerabilities in image"
else
    echo "FAIL: Critical vulnerabilities in container"
    exit 1
fi

# 6. Verify no sensitive files staged
echo "[6/6] Checking for sensitive files..."
SENSITIVE_PATTERNS=".env credentials.json *.pem *.key"
for pattern in $SENSITIVE_PATTERNS; do
    if git diff --cached --name-only | grep -q "$pattern"; then
        echo "FAIL: Sensitive file staged: $pattern"
        exit 1
    fi
done
echo "PASS: No sensitive files staged"

echo ""
echo "=== ALL SECURITY CHECKS PASSED ==="
echo "Safe to deploy."
```

---

## LAYER 10: RED TEAM SIMULATION CHECKLIST

### 10.1 Attack Surface Analysis

| Vector | Check Command | Expected Result | Severity |
|--------|---------------|-----------------|----------|
| Open Ports | `ss -tulpn \| grep LISTEN` | Only 22, 80, 443, 8443 | CRITICAL |
| Docker Socket | `ls -la /var/run/docker.sock` | 660, root:docker | CRITICAL |
| SUID Binaries | `find / -perm -4000 2>/dev/null` | Standard system only | HIGH |
| World-Writable | `find / -perm -0002 -type f 2>/dev/null` | /tmp only | HIGH |
| Sudo Config | `cat /etc/sudoers` | No NOPASSWD for scripts | CRITICAL |
| SSH Config | `grep PermitRootLogin /etc/ssh/sshd_config` | no | CRITICAL |
| Container User | `docker exec app whoami` | appuser (not root) | HIGH |
| Secrets in Env | `docker exec app env \| grep -i key` | None visible | CRITICAL |

### 10.2 Privilege Escalation Paths (Check and Block)

```bash
# 1. SUID exploitation - find unusual SUID binaries
find / -perm -4000 -type f 2>/dev/null | while read bin; do
    if ! dpkg -S "$bin" 2>/dev/null | grep -q .; then
        echo "SUSPICIOUS SUID: $bin"
    fi
done

# 2. Writable /etc/passwd (should fail)
echo "test" >> /etc/passwd 2>&1 && echo "CRITICAL: /etc/passwd writable!"

# 3. Docker group membership
getent group docker

# 4. Sudo misconfigurations
sudo -l

# 5. Kernel exploits - check kernel version
uname -r
# Compare against known vulnerable versions

# 6. Cron jobs with weak permissions
ls -la /etc/cron.d/
ls -la /var/spool/cron/crontabs/

# 7. Writable systemd services
find /etc/systemd -writable 2>/dev/null

# 8. LD_PRELOAD exploitation
cat /etc/ld.so.preload
```

### 10.3 Container Escape Paths (Verify Blocked)

```bash
# 1. Privileged container check
docker inspect CONTAINER --format='{{.HostConfig.Privileged}}'
# Should be: false

# 2. Dangerous capabilities
docker inspect CONTAINER --format='{{.HostConfig.CapAdd}}'
# Should be: [] or minimal

# 3. Host mounts
docker inspect CONTAINER --format='{{.Mounts}}'
# Should NOT include /, /etc, /var/run/docker.sock

# 4. Host network
docker inspect CONTAINER --format='{{.HostConfig.NetworkMode}}'
# Should NOT be: host

# 5. PID namespace
docker inspect CONTAINER --format='{{.HostConfig.PidMode}}'
# Should be empty or "private"
```

### 10.4 Post-Breach Indicators (Detection)

```bash
# Monitor for these indicators of compromise:

# 1. Unusual outbound connections
ss -tun state established | grep -v ":22\|:80\|:443"

# 2. Processes running from /tmp or /dev/shm
ps aux | grep -E "/tmp|/dev/shm"

# 3. Hidden processes (compare ps vs /proc)
ps aux | wc -l
ls -d /proc/[0-9]* | wc -l

# 4. Unexpected cron jobs
crontab -l
ls -la /etc/cron.*

# 5. Modified system binaries
debsums -c 2>/dev/null | head -20

# 6. Unusual authorized_keys entries
cat /home/*/.ssh/authorized_keys /root/.ssh/authorized_keys 2>/dev/null

# 7. Processes with deleted executables
ls -l /proc/*/exe 2>/dev/null | grep deleted

# 8. Unusual listening services
ss -tulpn | grep -v "127.0.0.1" | grep -v ":22\|:80\|:443"
```

---

## QUICK REFERENCE COMMANDS

### Daily Security Check
```bash
# Run this daily
lynis audit system --quick
rkhunter --check --skip-keypress
aureport --summary
fail2ban-client status
docker ps -a
ss -tulpn | grep LISTEN
```

### Before Deployment
```bash
# Run before every deployment
./scripts/pre-deploy-check.sh
```

### After Incident
```bash
# Forensic snapshot first
doctl compute droplet-action snapshot DROPLET_ID

# Then investigate
ausearch -i --start today
last -100
grep -i "fail\|error\|denied" /var/log/auth.log
docker logs --since 24h CONTAINER
```

---

## COMPLIANCE CHECKLIST

| Control | Implementation | Verified |
|---------|---------------|----------|
| Encryption at rest | LUKS or DO encrypted volumes | [ ] |
| Encryption in transit | TLS 1.2+ only | [ ] |
| Access control | SSH key-only, no root | [ ] |
| Audit logging | auditd enabled | [ ] |
| Vulnerability scanning | Trivy in CI/CD | [ ] |
| Secret management | No secrets in code/git | [ ] |
| Network segmentation | VPC, egress filtering | [ ] |
| Backup encryption | GPG encrypted backups | [ ] |
| Incident response | Runbook documented | [ ] |
| Container hardening | Non-root, read-only, caps dropped | [ ] |

---

## VERSION HISTORY

- **v3.0** (January 2026): Complete rewrite with DigitalOcean focus, container security, supply chain protection, automated pipelines
- **v2.0** (January 2026): Added Sadhuastro-specific auditing
- **v1.0** (2025): Initial DigitalOcean audit framework
