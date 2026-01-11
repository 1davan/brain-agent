from datetime import datetime, timedelta
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Optional
import uuid
import json
import re
import pytz
from app.database.sheets_client import SheetsClient
from app.services.ai_service import AIService
from app.services.scheduler_service import SchedulerService

# Brisbane timezone
BRISBANE_TZ = pytz.timezone('Australia/Brisbane')

class TaskAgent:
    def __init__(self, sheets_client: SheetsClient, scheduler: SchedulerService, ai_service: AIService):
        self.sheets = sheets_client
        self.scheduler = scheduler
        self.ai = ai_service

    async def create_task(self, user_id: str, title: str, description: str = None,
                         priority: str = "auto", deadline: str = None,
                         is_recurring: bool = False, recurrence_pattern: str = None,
                         recurrence_end_date: str = None, parent_task_id: str = None) -> str:
        """Create new task with intelligent processing and recurring support"""
        try:
            # Parse deadline if provided
            parsed_deadline = None
            if deadline:
                try:
                    parsed_deadline = date_parser.parse(deadline)
                except:
                    # Use AI to parse natural language dates
                    parsed_deadline = await self._parse_deadline_with_ai(deadline)

            # For recurring tasks, calculate first occurrence if no deadline given
            if is_recurring and recurrence_pattern and not parsed_deadline:
                parsed_deadline = self._get_next_occurrence(recurrence_pattern)

            # Intelligent priority assignment
            if not priority or priority == "auto":
                priority = await self.ai.determine_task_priority(title, description or "", deadline)

            # Generate unique task ID
            task_id = f"task_{user_id}_{uuid.uuid4().hex[:8]}"

            # Parse recurrence end date if provided
            parsed_recurrence_end = None
            if recurrence_end_date:
                try:
                    parsed_recurrence_end = date_parser.parse(recurrence_end_date)
                except:
                    parsed_recurrence_end = await self._parse_deadline_with_ai(recurrence_end_date)

            task_data = {
                "user_id": user_id,
                "task_id": task_id,
                "title": title,
                "description": description or "",
                "priority": priority,
                "status": "pending",
                "deadline": parsed_deadline.isoformat() if parsed_deadline else None,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "dependencies": "[]",
                "notes": "",
                "is_recurring": str(is_recurring).lower(),
                "recurrence_pattern": recurrence_pattern or "",
                "recurrence_end_date": parsed_recurrence_end.isoformat() if parsed_recurrence_end else "",
                "parent_task_id": parent_task_id or ""
            }

            await self.sheets.append_row("Tasks", task_data)

            # Schedule reminder if deadline exists and scheduler is available
            if parsed_deadline and self.scheduler:
                await self.scheduler.schedule_reminder(
                    user_id, task_id, title, parsed_deadline
                )

            # Build response message
            msg = f"Task created: {title} (Priority: {priority}"
            if parsed_deadline:
                msg += f", Next: {parsed_deadline.strftime('%a %b %d %I:%M%p')}"
            if is_recurring and recurrence_pattern:
                msg += f", Recurring: {recurrence_pattern}"
                if parsed_recurrence_end:
                    msg += f" until {parsed_recurrence_end.strftime('%b %d, %Y')}"
            msg += ")"
            return msg

        except Exception as e:
            print(f"Error creating task: {e}")
            return f"Error creating task: {str(e)}"

    def _get_next_occurrence(self, recurrence_pattern: str) -> Optional[datetime]:
        """Calculate next occurrence based on recurrence pattern"""
        now = datetime.now(BRISBANE_TZ)
        
        try:
            if recurrence_pattern.startswith("weekly_"):
                # Format: weekly_thursday_1630
                parts = recurrence_pattern.split("_")
                if len(parts) >= 3:
                    day_name = parts[1].lower()
                    time_str = parts[2]
                    
                    # Map day names to weekday numbers (Monday=0)
                    days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
                            "friday": 4, "saturday": 5, "sunday": 6}
                    target_day = days.get(day_name, 0)
                    
                    # Parse time
                    hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                    minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                    
                    # Find next occurrence
                    days_ahead = target_day - now.weekday()
                    if days_ahead <= 0:  # Target day already happened this week
                        days_ahead += 7
                    
                    next_date = now + timedelta(days=days_ahead)
                    return next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            elif recurrence_pattern.startswith("daily_"):
                # Format: daily_0900
                time_str = recurrence_pattern.split("_")[1] if "_" in recurrence_pattern else "0900"
                hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                
                next_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_date <= now:
                    next_date += timedelta(days=1)
                return next_date
            
            elif recurrence_pattern.startswith("monthly_"):
                # Format: monthly_15_0900
                parts = recurrence_pattern.split("_")
                day = int(parts[1]) if len(parts) >= 2 else 1
                time_str = parts[2] if len(parts) >= 3 else "0900"
                hour = int(time_str[:2]) if len(time_str) >= 2 else 9
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                
                next_date = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                if next_date <= now:
                    next_date = next_date + relativedelta(months=1)
                return next_date
        
        except Exception as e:
            print(f"Error parsing recurrence pattern: {e}")
        
        return None

    async def update_task_priority(self, user_id: str, task_id: str, new_priority: str) -> str:
        """Update task priority and rearrange task list"""
        try:
            row_index = await self.sheets.find_row_by_id("Tasks", user_id, task_id)
            if not row_index:
                return f"Task not found: {task_id}"

            await self.sheets.update_row("Tasks", row_index, {
                "priority": new_priority,
                "updated_at": datetime.now().isoformat()
            })

            return f"Task priority updated: {task_id} → {new_priority}"

        except Exception as e:
            print(f"Error updating task priority: {e}")
            return f"Error updating task priority: {str(e)}"

    async def complete_task(self, user_id: str, task_id: str) -> str:
        """Mark task complete - will be auto-archived after 7 days"""
        try:
            # Get task data
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return f"Task not found: {task_id}"

            task = tasks_df[tasks_df['task_id'] == task_id]
            if task.empty:
                return f"Task not found: {task_id}"

            task_data = task.iloc[0].to_dict()

            # Update status and set completed_at timestamp
            row_index = await self.sheets.find_row_by_id("Tasks", user_id, task_id)
            if row_index:
                await self.sheets.update_row("Tasks", row_index, {
                    "status": "complete",
                    "progress_percent": "100",
                    "completed_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                })

            # Cancel reminder if scheduler is available
            if self.scheduler:
                await self.scheduler.cancel_reminder(user_id, task_id)

            return f"Task completed: {task_data['title']} (will be archived in 7 days)"

        except Exception as e:
            print(f"Error completing task: {e}")
            return f"Error completing task: {str(e)}"

    async def update_task_progress(self, user_id: str, task_id: str, progress: int, notes: str = None) -> str:
        """Update task progress percentage and optional notes"""
        try:
            row_index = await self.sheets.find_row_by_id("Tasks", user_id, task_id)
            if not row_index:
                return f"Task not found: {task_id}"

            update_data = {
                "progress_percent": str(min(100, max(0, progress))),
                "last_discussed": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            if notes:
                # Append to existing notes
                tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
                task = tasks_df[tasks_df['task_id'] == task_id]
                if not task.empty:
                    existing_notes = task.iloc[0].get('notes', '')
                    timestamp = datetime.now(BRISBANE_TZ).strftime('%m/%d %H:%M')
                    new_note = f"[{timestamp}] {notes}"
                    if existing_notes:
                        update_data["notes"] = f"{existing_notes}\n{new_note}"
                    else:
                        update_data["notes"] = new_note

            await self.sheets.update_row("Tasks", row_index, update_data)

            # If progress is 100%, also mark as complete
            if progress >= 100:
                return await self.complete_task(user_id, task_id)

            return f"Task progress updated to {progress}%"

        except Exception as e:
            print(f"Error updating task progress: {e}")
            return f"Error updating task progress: {str(e)}"

    async def get_tasks_for_checkin(self, user_id: str, limit: int = 3) -> List[Dict]:
        """Get tasks suitable for proactive check-in with intelligent weighting"""
        try:
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return []

            # Filter: pending tasks only, not archived
            pending_mask = tasks_df['status'] == 'pending'
            if 'archived' in tasks_df.columns:
                pending_mask &= tasks_df['archived'].astype(str) != 'true'
            tasks = tasks_df[pending_mask].to_dict('records')

            if not tasks:
                return []

            now = datetime.now(BRISBANE_TZ)

            # Score each task for check-in priority
            scored_tasks = []
            for task in tasks:
                score = 0

                # Priority weighting: high=30, medium=20, low=10
                priority = task.get('priority', 'medium')
                if priority == 'high':
                    score += 30
                elif priority == 'medium':
                    score += 20
                else:
                    score += 10

                # Deadline proximity: closer deadline = higher score
                deadline_str = task.get('deadline')
                if deadline_str:
                    try:
                        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                        if deadline.tzinfo is None:
                            deadline = BRISBANE_TZ.localize(deadline)
                        days_until = (deadline - now).days
                        if days_until < 0:
                            score += 50  # Overdue
                        elif days_until <= 1:
                            score += 40  # Due within 24h
                        elif days_until <= 3:
                            score += 25  # Due within 3 days
                        elif days_until <= 7:
                            score += 15  # Due within a week
                    except:
                        pass

                # Progress: lower progress = higher need for check-in
                progress = int(task.get('progress_percent', '0') or '0')
                if progress == 0:
                    score += 20  # Not started
                elif progress < 50:
                    score += 15  # Less than halfway
                elif progress < 80:
                    score += 10  # Making progress

                # Time since last discussed: longer = higher priority
                last_discussed = task.get('last_discussed')
                if last_discussed:
                    try:
                        last_dt = datetime.fromisoformat(last_discussed.replace('Z', '+00:00'))
                        if last_dt.tzinfo is None:
                            last_dt = BRISBANE_TZ.localize(last_dt)
                        days_since = (now - last_dt).days
                        if days_since >= 3:
                            score += 25
                        elif days_since >= 1:
                            score += 15
                    except:
                        score += 20  # Never discussed, give it a boost
                else:
                    score += 20  # Never discussed

                # Add some randomness to prevent always picking the same tasks
                import random
                score += random.randint(0, 10)

                scored_tasks.append((score, task))

            # Sort by score descending and pick top tasks
            scored_tasks.sort(key=lambda x: x[0], reverse=True)
            return [task for _, task in scored_tasks[:limit]]

        except Exception as e:
            print(f"Error getting tasks for check-in: {e}")
            return []

    async def archive_old_completed_tasks(self, user_id: str, days_threshold: int = 7) -> int:
        """Archive tasks completed more than X days ago"""
        try:
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return 0

            now = datetime.now(BRISBANE_TZ)
            archived_count = 0

            for _, task in tasks_df.iterrows():
                if task.get('status') != 'complete':
                    continue
                if str(task.get('archived', '')).lower() == 'true':
                    continue

                completed_at = task.get('completed_at')
                if not completed_at:
                    continue

                try:
                    completed_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    if completed_dt.tzinfo is None:
                        completed_dt = BRISBANE_TZ.localize(completed_dt)

                    days_since = (now - completed_dt).days
                    if days_since >= days_threshold:
                        # Mark as archived
                        row_index = await self.sheets.find_row_by_id("Tasks", user_id, task.get('task_id'))
                        if row_index:
                            await self.sheets.update_row("Tasks", row_index, {
                                "archived": "true",
                                "updated_at": now.isoformat()
                            })
                            archived_count += 1
                            print(f"Auto-archived task: {task.get('title')}")
                except:
                    continue

            return archived_count

        except Exception as e:
            print(f"Error archiving old tasks: {e}")
            return 0

    async def search_archived_tasks(self, user_id: str, search_term: str, limit: int = 10) -> List[Dict]:
        """Search through archived tasks"""
        try:
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return []

            # Filter to archived tasks
            if 'archived' in tasks_df.columns:
                archived = tasks_df[tasks_df['archived'].astype(str) == 'true'].to_dict('records')
            else:
                archived = []

            # Also check the Archive sheet for older tasks
            archive_df = await self.sheets.get_sheet_data("Archive", user_id)
            if not archive_df.empty:
                for _, row in archive_df.iterrows():
                    if row.get('original_sheet') == 'Tasks':
                        try:
                            task_data = json.loads(row.get('content', '{}'))
                            task_data['archived_at'] = row.get('archived_at')
                            archived.append(task_data)
                        except:
                            continue

            # Search
            search_lower = search_term.lower()
            matching = []
            for task in archived:
                title = task.get('title', '').lower()
                description = task.get('description', '').lower()
                notes = task.get('notes', '').lower()

                if search_lower in title or search_lower in description or search_lower in notes:
                    matching.append(task)

            # Sort by archived_at or completed_at descending
            matching.sort(
                key=lambda t: t.get('completed_at') or t.get('archived_at') or '',
                reverse=True
            )

            return matching[:limit]

        except Exception as e:
            print(f"Error searching archived tasks: {e}")
            return []

    async def get_prioritized_tasks(self, user_id: str, limit: int = 10, status: str = "pending") -> List[Dict]:
        """Get tasks sorted by priority and deadline"""
        try:
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return []

            # Filter by status
            if status != "all":
                tasks_df = tasks_df[tasks_df['status'] == status]

            # Convert to list of dicts
            tasks = tasks_df.to_dict('records')

            # Sort by priority (high > medium > low) then by deadline
            priority_order = {'high': 0, 'medium': 1, 'low': 2}

            def sort_key(task):
                priority_val = priority_order.get(task.get('priority', 'medium'), 1)
                deadline_str = task.get('deadline')
                deadline_val = float('inf')
                if deadline_str:
                    try:
                        deadline_val = datetime.fromisoformat(deadline_str).timestamp()
                    except:
                        pass
                return (priority_val, deadline_val)

            tasks.sort(key=sort_key)
            return tasks[:limit]

        except Exception as e:
            print(f"Error getting prioritized tasks: {e}")
            return []

    async def get_overdue_tasks(self, user_id: str) -> List[Dict]:
        """Get tasks that are past their deadline"""
        try:
            tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
            if tasks_df.empty:
                return []

            now = datetime.now()
            overdue_tasks = []

            for _, task in tasks_df.iterrows():
                if task['status'] != 'pending':
                    continue

                deadline_str = task.get('deadline')
                if deadline_str:
                    try:
                        deadline = datetime.fromisoformat(deadline_str)
                        if deadline < now:
                            overdue_tasks.append(task.to_dict())
                    except:
                        continue

            return overdue_tasks

        except Exception as e:
            print(f"Error getting overdue tasks: {e}")
            return []

    async def update_task_deadline(self, user_id: str, task_id: str, new_deadline: str) -> str:
        """Update task deadline and reschedule reminder"""
        try:
            # Parse new deadline
            parsed_deadline = None
            try:
                parsed_deadline = date_parser.parse(new_deadline)
            except:
                parsed_deadline = await self._parse_deadline_with_ai(new_deadline)

            if not parsed_deadline:
                return "Could not parse deadline"

            row_index = await self.sheets.find_row_by_id("Tasks", user_id, task_id)
            if not row_index:
                return f"Task not found: {task_id}"

            await self.sheets.update_row("Tasks", row_index, {
                "deadline": parsed_deadline.isoformat(),
                "updated_at": datetime.now().isoformat()
            })

            # Reschedule reminder if scheduler is available
            if self.scheduler:
                tasks_df = await self.sheets.get_sheet_data("Tasks", user_id)
                task = tasks_df[tasks_df['task_id'] == task_id]
                if not task.empty:
                    title = task.iloc[0]['title']
                    await self.scheduler.schedule_reminder(user_id, task_id, title, parsed_deadline)

            return f"Task deadline updated: {task_id} → {new_deadline}"

        except Exception as e:
            print(f"Error updating task deadline: {e}")
            return f"Error updating task deadline: {str(e)}"

    async def update_task_field(self, user_id: str, task_id: str, field_name: str, field_value: str) -> str:
        """Update a specific field on a task (generic update method)"""
        try:
            row_index = await self.sheets.find_row_by_id("Tasks", user_id, task_id)
            if not row_index:
                return f"Task not found: {task_id}"

            # Parse date fields if needed
            if field_name in ['recurrence_end_date', 'deadline'] and field_value:
                try:
                    parsed_date = date_parser.parse(field_value)
                    if parsed_date.tzinfo is None:
                        parsed_date = BRISBANE_TZ.localize(parsed_date)
                    field_value = parsed_date.isoformat()
                except:
                    # Try AI parsing for natural language dates
                    parsed_date = await self._parse_deadline_with_ai(field_value)
                    if parsed_date:
                        field_value = parsed_date.isoformat()

            await self.sheets.update_row("Tasks", row_index, {
                field_name: field_value,
                "updated_at": datetime.now().isoformat()
            })

            return f"Task updated: {field_name} → {field_value}"

        except Exception as e:
            print(f"Error updating task field: {e}")
            return f"Error updating task field: {str(e)}"

    async def _parse_deadline_with_ai(self, deadline_text: str) -> Optional[datetime]:
        """Parse natural language deadlines using pattern matching and AI fallback"""
        now = datetime.now(BRISBANE_TZ)
        deadline_text = deadline_text.lower().strip()

        try:
            # Common patterns for natural language dates
            # "tomorrow", "today", "next week", etc.
            if 'tomorrow' in deadline_text:
                base_date = now + timedelta(days=1)
            elif 'today' in deadline_text:
                base_date = now
            elif 'next week' in deadline_text:
                base_date = now + timedelta(weeks=1)
            elif 'next month' in deadline_text:
                base_date = now + relativedelta(months=1)
            else:
                base_date = None

            # Extract time if specified (e.g., "9pm", "9:00 AM", "21:00")
            time_pattern = r'(\d{1,2}):?(\d{2})?\s*(am|pm)?'
            time_match = re.search(time_pattern, deadline_text, re.IGNORECASE)

            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                am_pm = time_match.group(3)

                if am_pm:
                    if am_pm.lower() == 'pm' and hour != 12:
                        hour += 12
                    elif am_pm.lower() == 'am' and hour == 12:
                        hour = 0

                if base_date:
                    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Try standard date parsing
            try:
                parsed = date_parser.parse(deadline_text, fuzzy=True, dayfirst=True)
                # Make timezone aware
                if parsed.tzinfo is None:
                    parsed = BRISBANE_TZ.localize(parsed)
                return parsed
            except:
                pass

            # If we have a base date but no time, default to 9 AM
            if base_date:
                return base_date.replace(hour=9, minute=0, second=0, microsecond=0)

            return None

        except Exception as e:
            print(f"Error parsing deadline: {e}")
            return None