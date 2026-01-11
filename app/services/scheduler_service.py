from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from typing import Callable, Dict, Any
import logging
import pytz

logger = logging.getLogger(__name__)

# Brisbane timezone
BRISBANE_TZ = pytz.timezone('Australia/Brisbane')

class SchedulerService:
    def __init__(self, timezone: str = 'Australia/Brisbane'):
        self.timezone = pytz.timezone(timezone)
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self.jobs = {}  # Track active jobs

    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    async def schedule_reminder(self, user_id: str, task_id: str, title: str,
                              deadline: datetime, telegram_bot=None):
        """Schedule a reminder for a task deadline"""
        if not deadline:
            return

        # Schedule reminder 1 hour before deadline
        reminder_time = deadline - timedelta(hours=1)

        # Don't schedule if reminder time is in the past
        if reminder_time <= datetime.now():
            return

        job_id = f"reminder_{user_id}_{task_id}"

        # Remove existing job if it exists
        if job_id in self.jobs:
            self.scheduler.remove_job(job_id)

        # Schedule new reminder
        self.scheduler.add_job(
            self._send_reminder,
            trigger=DateTrigger(run_date=reminder_time),
            args=[user_id, task_id, title, telegram_bot],
            id=job_id,
            name=f"Reminder for {title}"
        )

        self.jobs[job_id] = reminder_time
        logger.info(f"Scheduled reminder for task {task_id} at {reminder_time}")

    async def schedule_daily_summary(self, user_id: str, telegram_bot=None):
        """Schedule daily task summary at 9 AM"""
        job_id = f"daily_{user_id}"

        # Remove existing job
        if job_id in self.jobs:
            self.scheduler.remove_job(job_id)

        # Schedule daily at 9 AM
        self.scheduler.add_job(
            self._send_daily_summary,
            trigger=CronTrigger(hour=9, minute=0),
            args=[user_id, telegram_bot],
            id=job_id,
            name=f"Daily summary for {user_id}"
        )

        logger.info(f"Scheduled daily summary for {user_id}")

    async def cancel_reminder(self, user_id: str, task_id: str):
        """Cancel a scheduled reminder"""
        job_id = f"reminder_{user_id}_{task_id}"
        if job_id in self.jobs:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
            logger.info(f"Cancelled reminder for task {task_id}")

    async def _send_reminder(self, user_id: str, task_id: str, title: str, telegram_bot):
        """Send reminder notification"""
        if not telegram_bot:
            return

        try:
            message = f"⏰ Reminder: Your task '{title}' is due in 1 hour!"
            await telegram_bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Sent reminder for task {task_id} to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")

    async def _send_daily_summary(self, user_id: str, telegram_bot):
        """Send daily task summary"""
        if not telegram_bot:
            return

        try:
            # This would need access to the sheets client to get tasks
            # For now, just send a placeholder
            message = "🌅 Good morning! Here's your daily task summary:\n\n📋 Check your pending tasks for today."
            await telegram_bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Sent daily summary to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")

    def get_active_jobs(self) -> Dict[str, Any]:
        """Get information about active scheduled jobs"""
        return {
            job_id: {
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'name': job.name
            }
            for job_id, job in self.scheduler.get_jobs()
        }

    def clear_user_jobs(self, user_id: str):
        """Clear all jobs for a specific user"""
        jobs_to_remove = [job_id for job_id in self.jobs.keys() if str(user_id) in job_id]
        for job_id in jobs_to_remove:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
        logger.info(f"Cleared {len(jobs_to_remove)} jobs for user {user_id}")