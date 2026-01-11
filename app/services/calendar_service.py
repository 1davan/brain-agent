#!/usr/bin/env python3
"""
Google Calendar integration for the AI assistant.
Uses the same service account as Google Sheets.
"""

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pytz

# Brisbane timezone
BRISBANE_TZ = pytz.timezone('Australia/Brisbane')


class CalendarService:
    def __init__(self, credentials_path: str, calendar_id: str = 'primary'):
        """
        Initialize Google Calendar client.
        
        Args:
            credentials_path: Path to service account JSON file
            calendar_id: Calendar ID to use. 'primary' uses the calendar owner's primary calendar.
                        For shared calendars, use the calendar's email address.
        
        Setup required:
        1. Enable Google Calendar API in Google Cloud Console
        2. Share your calendar with the service account email (found in the JSON file)
           - Go to Google Calendar settings → Share with specific people
           - Add the service account email with "Make changes to events" permission
        """
        scopes = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events"
        ]
        
        self.creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        self.service = build('calendar', 'v3', credentials=self.creds)
        self.calendar_id = calendar_id
        
        # Get service account email for sharing instructions
        import json
        with open(credentials_path, 'r') as f:
            creds_data = json.load(f)
            self.service_account_email = creds_data.get('client_email', 'unknown')
        
        print(f"Calendar service initialized. Share your calendar with: {self.service_account_email}")

    async def get_upcoming_events(self, max_results: int = 10, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """
        Get upcoming events from the calendar.
        
        Args:
            max_results: Maximum number of events to return
            days_ahead: How many days ahead to look
            
        Returns:
            List of event dictionaries with summary, start, end, location, etc.
        """
        try:
            now = datetime.now(BRISBANE_TZ)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            formatted_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                formatted_events.append({
                    'id': event.get('id'),
                    'summary': event.get('summary', 'No title'),
                    'start': start,
                    'end': end,
                    'location': event.get('location', ''),
                    'description': event.get('description', ''),
                    'link': event.get('htmlLink', '')
                })
            
            return formatted_events
            
        except HttpError as e:
            print(f"Calendar API error: {e}")
            if 'notFound' in str(e):
                print(f"Calendar not found. Make sure to share your calendar with: {self.service_account_email}")
            return []
        except Exception as e:
            print(f"Error getting calendar events: {e}")
            return []

    async def get_events_for_date(self, target_date: datetime) -> List[Dict[str, Any]]:
        """Get all events for a specific date."""
        try:
            # Set time range for the entire day in Brisbane timezone
            if target_date.tzinfo is None:
                target_date = BRISBANE_TZ.localize(target_date)
            
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            formatted_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                formatted_events.append({
                    'id': event.get('id'),
                    'summary': event.get('summary', 'No title'),
                    'start': start,
                    'end': end,
                    'location': event.get('location', ''),
                    'description': event.get('description', '')
                })
            
            return formatted_events
            
        except Exception as e:
            print(f"Error getting events for date: {e}")
            return []

    async def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime = None,
        description: str = None,
        location: str = None,
        reminder_minutes: int = 60
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new calendar event.
        
        Args:
            summary: Event title
            start_time: Event start time (datetime)
            end_time: Event end time (defaults to 1 hour after start)
            description: Optional event description
            location: Optional event location
            reminder_minutes: Minutes before event to send reminder (default 60)
            
        Returns:
            Created event data or None if failed
        """
        try:
            # Ensure timezone
            if start_time.tzinfo is None:
                start_time = BRISBANE_TZ.localize(start_time)
            
            if end_time is None:
                end_time = start_time + timedelta(hours=1)
            elif end_time.tzinfo is None:
                end_time = BRISBANE_TZ.localize(end_time)
            
            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Australia/Brisbane',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Australia/Brisbane',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': reminder_minutes},
                    ],
                },
            }
            
            if description:
                event['description'] = description
            if location:
                event['location'] = location
            
            created_event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event
            ).execute()
            
            return {
                'id': created_event.get('id'),
                'summary': created_event.get('summary'),
                'start': created_event['start'].get('dateTime'),
                'end': created_event['end'].get('dateTime'),
                'link': created_event.get('htmlLink')
            }
            
        except HttpError as e:
            print(f"Calendar API error creating event: {e}")
            return None
        except Exception as e:
            print(f"Error creating calendar event: {e}")
            return None

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event by ID."""
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            return True
        except Exception as e:
            print(f"Error deleting event: {e}")
            return False

    async def update_event(
        self,
        event_id: str,
        summary: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        description: str = None,
        location: str = None
    ) -> Optional[Dict[str, Any]]:
        """Update an existing calendar event."""
        try:
            # Get current event
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            # Update fields if provided
            if summary:
                event['summary'] = summary
            if description:
                event['description'] = description
            if location:
                event['location'] = location
            if start_time:
                if start_time.tzinfo is None:
                    start_time = BRISBANE_TZ.localize(start_time)
                event['start'] = {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Australia/Brisbane'
                }
            if end_time:
                if end_time.tzinfo is None:
                    end_time = BRISBANE_TZ.localize(end_time)
                event['end'] = {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Australia/Brisbane'
                }
            
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            return {
                'id': updated_event.get('id'),
                'summary': updated_event.get('summary'),
                'start': updated_event['start'].get('dateTime'),
                'link': updated_event.get('htmlLink')
            }
            
        except Exception as e:
            print(f"Error updating event: {e}")
            return None

    def format_events_for_display(self, events: List[Dict[str, Any]]) -> str:
        """Format events list for human-readable display."""
        if not events:
            return "No upcoming events found."
        
        lines = []
        for event in events:
            start_str = event.get('start', '')
            
            # Parse and format the datetime
            try:
                if 'T' in start_str:
                    dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    formatted_time = dt.strftime('%a %b %d at %I:%M%p')
                else:
                    # All-day event
                    formatted_time = start_str
            except:
                formatted_time = start_str
            
            line = f"• {event.get('summary', 'Untitled')} - {formatted_time}"
            if event.get('location'):
                line += f" @ {event.get('location')}"
            lines.append(line)
        
        return "\n".join(lines)


# Singleton instance
_calendar_service = None


def get_calendar_service(credentials_path: str = None, calendar_id: str = None) -> Optional[CalendarService]:
    """Get singleton calendar service instance."""
    global _calendar_service
    
    if _calendar_service is None and credentials_path:
        try:
            _calendar_service = CalendarService(
                credentials_path=credentials_path,
                calendar_id=calendar_id or 'primary'
            )
        except Exception as e:
            print(f"Failed to initialize calendar service: {e}")
            return None
    
    return _calendar_service
