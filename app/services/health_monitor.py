"""
Health monitoring service for Brain Agent.

Provides:
- Startup validation with clear pass/fail reporting
- Runtime metrics collection (latency, errors, message counts)
- Health status file written every 60 seconds
- Service connectivity tracking
"""

import json
import os
import time
import threading
import platform
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

# Brisbane timezone
try:
    from zoneinfo import ZoneInfo
    BRISBANE_TZ = ZoneInfo("Australia/Brisbane")
except ImportError:
    import pytz
    BRISBANE_TZ = pytz.timezone("Australia/Brisbane")


# Determine health file path based on platform
import platform
if platform.system() == "Windows":
    import tempfile
    HEALTH_FILE_PATH = os.path.join(tempfile.gettempdir(), "brain_agent_health.json")
else:
    HEALTH_FILE_PATH = "/tmp/brain_agent_health.json"


@dataclass
class ErrorRecord:
    """Aggregated error information."""
    error_type: str
    message: str
    first_occurrence: str
    last_occurrence: str
    count_last_hour: int = 1


@dataclass
class PipelineStats:
    """Rolling statistics for pipeline performance."""
    latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    stage1_latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    stage2_latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    stage3_latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    stage4_latencies: deque = field(default_factory=lambda: deque(maxlen=100))

    def record(self, total_ms: int, stage1_ms: int = 0, stage2_ms: int = 0,
               stage3_ms: int = 0, stage4_ms: int = 0):
        """Record pipeline execution timing."""
        self.latencies.append(total_ms)
        if stage1_ms:
            self.stage1_latencies.append(stage1_ms)
        if stage2_ms:
            self.stage2_latencies.append(stage2_ms)
        if stage3_ms:
            self.stage3_latencies.append(stage3_ms)
        if stage4_ms:
            self.stage4_latencies.append(stage4_ms)

    def get_averages(self) -> Dict[str, int]:
        """Get average latencies."""
        def avg(d: deque) -> int:
            return int(sum(d) / len(d)) if d else 0

        return {
            "avg_latency_ms": avg(self.latencies),
            "stage1_avg_ms": avg(self.stage1_latencies),
            "stage2_avg_ms": avg(self.stage2_latencies),
            "stage3_avg_ms": avg(self.stage3_latencies),
            "stage4_avg_ms": avg(self.stage4_latencies),
        }


class HealthMonitor:
    """
    Central health monitoring for Brain Agent.

    Usage:
        monitor = HealthMonitor()

        # During startup
        monitor.validate_service("telegram", check_telegram_api())
        monitor.validate_service("google_sheets", check_sheets())

        # During runtime
        monitor.record_message_processed(user_id, latency_ms)
        monitor.record_error("groq_api_timeout", "Request timed out")
        monitor.record_pipeline_timing(total, s1, s2, s3, s4)

        # Background - called by proactive loop
        monitor.write_health_file()
    """

    def __init__(self):
        self.start_time = datetime.now(BRISBANE_TZ)
        self.lock = threading.Lock()

        # Service health tracking
        self.service_health: Dict[str, str] = {
            "telegram_polling": "unknown",
            "google_sheets": "unknown",
            "groq_api": "unknown",
            "calendar_service": "unknown",
            "email_service": "unknown",
        }

        # Message metrics
        self.messages_processed_total = 0
        self.messages_by_hour: Dict[int, int] = {}  # hour -> count
        self.active_users_today: set = set()
        self.last_message_time: Optional[datetime] = None

        # Pipeline performance
        self.pipeline_stats = PipelineStats()

        # Error tracking - keyed by error_type
        self.errors: Dict[str, ErrorRecord] = {}
        self.error_timestamps: deque = deque(maxlen=1000)  # For hourly counts

        # Proactive loop tracking
        self.proactive_last_run: Optional[datetime] = None
        self.proactive_next_scheduled: Optional[datetime] = None
        self.check_ins_sent_today = 0
        self.summaries_sent_today = 0
        self.last_reset_date: Optional[str] = None

        # Startup validation results
        self.startup_validations: Dict[str, Dict[str, Any]] = {}
        self.startup_complete = False
        self.startup_time_ms: Optional[int] = None

    def _now(self) -> datetime:
        """Get current time in Brisbane timezone."""
        return datetime.now(BRISBANE_TZ)

    def _reset_daily_counters(self):
        """Reset daily counters if date changed."""
        today = self._now().strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.active_users_today = set()
            self.check_ins_sent_today = 0
            self.summaries_sent_today = 0
            self.last_reset_date = today

    # -------------------------------------------------------------------------
    # Startup Validation
    # -------------------------------------------------------------------------

    def validate_service(self, service_name: str, success: bool,
                        details: str = "", critical: bool = True) -> bool:
        """
        Record service validation result during startup.

        Args:
            service_name: Name of the service (telegram, google_sheets, etc.)
            success: Whether validation passed
            details: Additional info (bot name, spreadsheet ID, etc.)
            critical: If True and failed, startup should abort

        Returns:
            The success value (for chaining)
        """
        status = "ok" if success else "failed"

        with self.lock:
            self.startup_validations[service_name] = {
                "success": success,
                "details": details,
                "critical": critical,
                "timestamp": self._now().isoformat(),
            }

            # Update service health
            if service_name in self.service_health:
                self.service_health[service_name] = status

            # Log startup message
            if success:
                detail_str = f" ({details})" if details else ""
                print(f"[STARTUP] Checking {service_name}... OK{detail_str}")
            else:
                print(f"[STARTUP] Checking {service_name}... FAILED ({details})")
                if critical:
                    print(f"[STARTUP] CRITICAL: Cannot start - {service_name} validation failed")

        return success

    def mark_startup_complete(self, startup_time_ms: int):
        """Mark startup as complete and record timing."""
        with self.lock:
            self.startup_complete = True
            self.startup_time_ms = startup_time_ms

            services = [name for name, v in self.startup_validations.items() if v["success"]]
            print(f"[STARTUP] All systems operational. Ready to receive messages.")

            # Log structured startup completion
            self._log_json({
                "level": "INFO",
                "component": "startup",
                "event": "deployment_complete",
                "startup_time_ms": startup_time_ms,
                "services_validated": services,
                "ready": True,
            })

    def startup_failed(self, reason: str):
        """Mark startup as failed with reason."""
        print(f"[STARTUP] CRITICAL: {reason}")
        print(f"[STARTUP] Check configuration and restart.")

    # -------------------------------------------------------------------------
    # Runtime Metrics
    # -------------------------------------------------------------------------

    def record_message_processed(self, user_id: int, latency_ms: int,
                                  route_type: str = "unknown",
                                  domains: List[str] = None):
        """Record a successfully processed message."""
        with self.lock:
            self._reset_daily_counters()

            self.messages_processed_total += 1
            self.last_message_time = self._now()
            self.active_users_today.add(user_id)

            # Track by hour
            hour = self._now().hour
            self.messages_by_hour[hour] = self.messages_by_hour.get(hour, 0) + 1

            # Log structured message
            self._log_json({
                "level": "INFO",
                "component": "pipeline",
                "event": "message_processed",
                "user_id": user_id,
                "route_type": route_type,
                "domains": domains or [],
                "latency_ms": latency_ms,
                "success": True,
            })

    def record_pipeline_timing(self, total_ms: int, stage1_ms: int = 0,
                               stage2_ms: int = 0, stage3_ms: int = 0,
                               stage4_ms: int = 0):
        """Record pipeline stage timings."""
        with self.lock:
            self.pipeline_stats.record(total_ms, stage1_ms, stage2_ms,
                                       stage3_ms, stage4_ms)

    def record_error(self, error_type: str, message: str,
                     component: str = "unknown"):
        """Record an error occurrence."""
        now = self._now()
        now_iso = now.isoformat()

        with self.lock:
            self.error_timestamps.append((now, error_type))

            if error_type in self.errors:
                self.errors[error_type].last_occurrence = now_iso
                self.errors[error_type].message = message
                # Count will be recalculated when writing health file
            else:
                self.errors[error_type] = ErrorRecord(
                    error_type=error_type,
                    message=message,
                    first_occurrence=now_iso,
                    last_occurrence=now_iso,
                    count_last_hour=1,
                )

            # Log structured error
            self._log_json({
                "level": "ERROR",
                "component": component,
                "event": "error",
                "error_type": error_type,
                "message": message,
            })

    def record_service_call(self, service_name: str, success: bool,
                           latency_ms: int = 0, error: str = None):
        """Record a service call result."""
        with self.lock:
            if service_name in self.service_health:
                # Update health based on recent success
                if success:
                    self.service_health[service_name] = "ok"
                else:
                    # Don't immediately mark as failed - track pattern
                    self.service_health[service_name] = "degraded"
                    if error:
                        self.record_error(f"{service_name}_error", error, service_name)

    def update_service_health(self, service_name: str, status: str):
        """Directly update service health status."""
        with self.lock:
            if service_name in self.service_health:
                self.service_health[service_name] = status

    # -------------------------------------------------------------------------
    # Proactive Loop Tracking
    # -------------------------------------------------------------------------

    def record_proactive_run(self):
        """Record that proactive loop executed."""
        with self.lock:
            self._reset_daily_counters()
            self.proactive_last_run = self._now()
            self.proactive_next_scheduled = self._now() + timedelta(seconds=60)

    def record_checkin_sent(self):
        """Record a check-in was sent."""
        with self.lock:
            self._reset_daily_counters()
            self.check_ins_sent_today += 1

    def record_summary_sent(self):
        """Record a daily summary was sent."""
        with self.lock:
            self._reset_daily_counters()
            self.summaries_sent_today += 1

    # -------------------------------------------------------------------------
    # Health Status Calculation
    # -------------------------------------------------------------------------

    def _calculate_status(self) -> str:
        """Determine overall health status."""
        # Check for critical service failures
        critical_services = ["telegram_polling", "google_sheets", "groq_api"]
        for svc in critical_services:
            if self.service_health.get(svc) == "failed":
                return "unhealthy"

        # Check for recent errors
        now = self._now()
        hour_ago = now - timedelta(hours=1)
        recent_errors = sum(1 for ts, _ in self.error_timestamps if ts > hour_ago)

        if recent_errors > 10:
            return "unhealthy"
        elif recent_errors > 3:
            return "degraded"

        # Check for degraded services
        degraded_count = sum(1 for s in self.service_health.values() if s == "degraded")
        if degraded_count > 0:
            return "degraded"

        return "healthy"

    def _get_error_counts(self) -> Dict[str, int]:
        """Get error counts for the last hour."""
        now = self._now()
        hour_ago = now - timedelta(hours=1)

        counts: Dict[str, int] = {}
        for ts, error_type in self.error_timestamps:
            if ts > hour_ago:
                counts[error_type] = counts.get(error_type, 0) + 1

        return counts

    def _get_messages_last_hour(self) -> int:
        """Get message count for current and previous hour."""
        current_hour = self._now().hour
        prev_hour = (current_hour - 1) % 24
        return (self.messages_by_hour.get(current_hour, 0) +
                self.messages_by_hour.get(prev_hour, 0))

    # -------------------------------------------------------------------------
    # Health File Output
    # -------------------------------------------------------------------------

    def get_health_status(self) -> Dict[str, Any]:
        """Generate complete health status dictionary."""
        with self.lock:
            self._reset_daily_counters()
            now = self._now()

            # Calculate error counts
            error_counts = self._get_error_counts()

            # Build recent errors list
            recent_errors = []
            for error_type, record in self.errors.items():
                count = error_counts.get(error_type, 0)
                if count > 0:
                    recent_errors.append({
                        "timestamp": record.last_occurrence,
                        "type": error_type,
                        "message": record.message,
                        "count_last_hour": count,
                        "first_occurrence": record.first_occurrence,
                    })

            # Sort by most recent
            recent_errors.sort(key=lambda x: x["timestamp"], reverse=True)

            return {
                "timestamp": now.isoformat(),
                "uptime_seconds": int((now - self.start_time).total_seconds()),
                "status": self._calculate_status(),
                "last_message_processed": (self.last_message_time.isoformat()
                                           if self.last_message_time else None),
                "messages_last_hour": self._get_messages_last_hour(),
                "active_users_today": len(self.active_users_today),
                "pipeline_stats": self.pipeline_stats.get_averages(),
                "service_health": dict(self.service_health),
                "recent_errors": recent_errors[:10],  # Top 10 most recent
                "proactive_loop": {
                    "last_run": (self.proactive_last_run.isoformat()
                                if self.proactive_last_run else None),
                    "next_scheduled": (self.proactive_next_scheduled.isoformat()
                                      if self.proactive_next_scheduled else None),
                    "check_ins_sent_today": self.check_ins_sent_today,
                    "summaries_sent_today": self.summaries_sent_today,
                },
            }

    def write_health_file(self, path: str = HEALTH_FILE_PATH):
        """Write health status to file."""
        try:
            health_status = self.get_health_status()

            # Write atomically using temp file
            temp_path = f"{path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(health_status, f, indent=2)

            # Atomic rename
            Path(temp_path).rename(path)

        except Exception as e:
            print(f"[HEALTH] Failed to write health file: {e}")

    # -------------------------------------------------------------------------
    # Structured Logging
    # -------------------------------------------------------------------------

    def _log_json(self, data: Dict[str, Any]):
        """Output structured JSON log entry."""
        data["timestamp"] = self._now().isoformat()
        print(json.dumps(data))


# Global singleton instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get or create the global health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


def reset_health_monitor():
    """Reset the global health monitor (for testing)."""
    global _health_monitor
    _health_monitor = None
