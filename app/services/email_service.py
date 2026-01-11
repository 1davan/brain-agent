#!/usr/bin/env python3
"""
Gmail email service for creating drafts and sending emails.
Uses IMAP for draft creation (works with app password).
"""

import os
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any, List
from datetime import datetime


class EmailService:
    def __init__(self, gmail_address: str = None, app_password: str = None, sheets_client=None):
        """
        Initialize Gmail service using IMAP/SMTP with app password.

        Args:
            gmail_address: Gmail address
            app_password: Gmail app password (16 chars, no spaces)
            sheets_client: Optional SheetsClient for persistent contact storage
        """
        self.gmail_address = gmail_address or os.getenv('GMAIL_ADDRESS', '')
        self.app_password = app_password or os.getenv('GMAIL_APP_PASSWORD', '')
        self.sheets_client = sheets_client

        # Remove any spaces from app password
        self.app_password = self.app_password.replace(' ', '')

        # Known contacts - name -> email mapping
        self.contacts: Dict[str, str] = {}

        # IMAP/SMTP settings for Gmail
        self.imap_server = 'imap.gmail.com'
        self.imap_port = 993
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 587

        if self.gmail_address and self.app_password:
            print(f"Email service initialized for: {self.gmail_address}")
            # Load contacts from sheets if available
            self._load_contacts_sync()
        else:
            print("Email service: Missing GMAIL_ADDRESS or GMAIL_APP_PASSWORD in .env")

    def _load_contacts_sync(self):
        """Load contacts from Google Sheets synchronously"""
        if not self.sheets_client:
            return

        import asyncio
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def load():
                try:
                    contacts_df = await self.sheets_client.get_sheet_data("Contacts")
                    if contacts_df.empty:
                        return
                    # Make column names lowercase for case-insensitive lookup
                    contacts_df.columns = contacts_df.columns.str.lower()
                    for _, row in contacts_df.iterrows():
                        name = str(row.get('name', '')).strip().lower()
                        email_addr = str(row.get('email', '')).strip()
                        if name and email_addr and '@' in email_addr:
                            self.contacts[name] = email_addr
                    print(f"Loaded {len(self.contacts)} contacts from storage")
                except Exception as e:
                    # Contacts sheet might not exist yet
                    print(f"Note: No contacts sheet yet (will be created on first add)")
            loop.run_until_complete(load())
        except Exception as e:
            print(f"Error loading contacts: {e}")
        finally:
            loop.close()

    async def _save_contact_to_sheets(self, name: str, email: str):
        """Save a contact to Google Sheets"""
        if not self.sheets_client:
            return

        try:
            await self.sheets_client.append_row("Contacts", {
                "name": name,
                "email": email,
                "added_at": datetime.now().isoformat()
            })
        except Exception as e:
            print(f"Error saving contact to sheets: {e}")

    def add_contact(self, name: str, email_addr: str):
        """Add a contact to the address book."""
        self.contacts[name.lower()] = email_addr
        print(f"Added contact: {name} -> {email_addr}")

        # Save to sheets in background
        if self.sheets_client:
            import asyncio
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._save_contact_to_sheets(name.lower(), email_addr))
            except Exception as e:
                print(f"Error saving contact: {e}")
            finally:
                loop.close()

    def remove_contact(self, name: str) -> bool:
        """Remove a contact from the address book."""
        if name.lower() in self.contacts:
            del self.contacts[name.lower()]
            return True
        return False

    def get_contact_email(self, name: str) -> Optional[str]:
        """Look up email address by contact name."""
        return self.contacts.get(name.lower())

    def list_contacts(self) -> Dict[str, str]:
        """Return all known contacts."""
        return self.contacts.copy()

    def _resolve_recipient(self, to: str) -> Optional[str]:
        """Resolve contact name to email, or validate email format."""
        if '@' in to:
            return to

        resolved = self.get_contact_email(to)
        if resolved:
            print(f"Resolved contact '{to}' -> {resolved}")
            return resolved

        # Debug: show what contacts we have
        print(f"Unknown contact: '{to}' (lowercase: '{to.lower()}')")
        print(f"Available contacts: {list(self.contacts.keys())}")
        return None

    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a draft email in Gmail using IMAP.

        Args:
            to: Recipient email address or contact name
            subject: Email subject
            body: Email body (plain text or HTML)
            is_html: Whether body is HTML

        Returns:
            Draft info dict or None if failed
        """
        if not self.gmail_address or not self.app_password:
            print("Email service not configured")
            return None

        # Resolve recipient
        recipient = self._resolve_recipient(to)
        if not recipient:
            return None

        try:
            # Create the email message
            if is_html:
                msg = MIMEMultipart('alternative')
                msg.attach(MIMEText(body, 'html'))
            else:
                msg = MIMEText(body, 'plain')

            msg['From'] = self.gmail_address
            msg['To'] = recipient
            msg['Subject'] = subject
            msg['Date'] = email.utils.formatdate(localtime=True)

            # Connect to IMAP and save to Drafts folder
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.gmail_address, self.app_password)

            # Gmail's Drafts folder
            imap.select('[Gmail]/Drafts')

            # Append message to Drafts
            result = imap.append(
                '[Gmail]/Drafts',
                '\\Draft',
                None,
                msg.as_bytes()
            )

            imap.logout()

            if result[0] == 'OK':
                print(f"Draft created: '{subject}' to {recipient}")
                return {
                    'status': 'created',
                    'to': recipient,
                    'subject': subject,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                print(f"Failed to create draft: {result}")
                return None

        except imaplib.IMAP4.error as e:
            print(f"IMAP error creating draft: {e}")
            return None
        except Exception as e:
            print(f"Error creating draft: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Send an email directly using SMTP.

        Args:
            to: Recipient email address or contact name
            subject: Email subject
            body: Email body
            is_html: Whether body is HTML

        Returns:
            Sent message info or None if failed
        """
        if not self.gmail_address or not self.app_password:
            print("Email service not configured")
            return None

        # Resolve recipient
        recipient = self._resolve_recipient(to)
        if not recipient:
            return None

        try:
            # Create the email message
            if is_html:
                msg = MIMEMultipart('alternative')
                msg.attach(MIMEText(body, 'html'))
            else:
                msg = MIMEText(body, 'plain')

            msg['From'] = self.gmail_address
            msg['To'] = recipient
            msg['Subject'] = subject

            # Send via SMTP
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.gmail_address, self.app_password)
                server.send_message(msg)

            print(f"Email sent: '{subject}' to {recipient}")
            return {
                'status': 'sent',
                'to': recipient,
                'subject': subject,
                'timestamp': datetime.now().isoformat()
            }

        except smtplib.SMTPAuthenticationError as e:
            print(f"SMTP auth error: {e}")
            print("Check your Gmail app password is correct")
            return None
        except Exception as e:
            print(f"Error sending email: {e}")
            return None

    async def list_drafts(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        List existing drafts from Gmail.

        Returns:
            List of draft summaries
        """
        if not self.gmail_address or not self.app_password:
            return []

        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.gmail_address, self.app_password)

            imap.select('[Gmail]/Drafts')

            # Search for all messages in Drafts
            result, data = imap.search(None, 'ALL')
            if result != 'OK':
                imap.logout()
                return []

            message_ids = data[0].split()
            drafts = []

            # Get the most recent drafts
            for msg_id in message_ids[-max_results:]:
                result, msg_data = imap.fetch(msg_id, '(RFC822.HEADER)')
                if result == 'OK':
                    msg = email.message_from_bytes(msg_data[0][1])
                    drafts.append({
                        'id': msg_id.decode(),
                        'subject': msg.get('Subject', 'No subject'),
                        'to': msg.get('To', 'Unknown'),
                        'date': msg.get('Date', '')
                    })

            imap.logout()
            return drafts

        except Exception as e:
            print(f"Error listing drafts: {e}")
            return []

    async def get_recent_emails(self, max_results: int = 10, folder: str = 'INBOX') -> List[Dict[str, Any]]:
        """
        Get recent emails from inbox.

        Args:
            max_results: Maximum emails to fetch
            folder: Folder to read from (INBOX, [Gmail]/Sent Mail, etc.)

        Returns:
            List of email summaries with sender, subject, date, snippet
        """
        if not self.gmail_address or not self.app_password:
            return []

        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.gmail_address, self.app_password)
            imap.select(folder)

            # Search for all messages, get most recent
            result, data = imap.search(None, 'ALL')
            if result != 'OK':
                imap.logout()
                return []

            message_ids = data[0].split()
            emails = []

            # Get the most recent emails (from newest to oldest)
            for msg_id in reversed(message_ids[-max_results:]):
                result, msg_data = imap.fetch(msg_id, '(RFC822)')
                if result == 'OK':
                    msg = email.message_from_bytes(msg_data[0][1])

                    # Extract sender info
                    from_header = msg.get('From', '')
                    sender_name = ''
                    sender_email = from_header

                    # Parse "Name <email>" format
                    if '<' in from_header:
                        parts = from_header.split('<')
                        sender_name = parts[0].strip().strip('"')
                        sender_email = parts[1].rstrip('>')
                    elif from_header:
                        sender_email = from_header
                        sender_name = from_header.split('@')[0]

                    # Get message body snippet
                    body_snippet = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == 'text/plain':
                                try:
                                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                    body_snippet = body[:200].replace('\n', ' ').strip()
                                except:
                                    pass
                                break
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                            body_snippet = body[:200].replace('\n', ' ').strip()
                        except:
                            pass

                    emails.append({
                        'id': msg_id.decode(),
                        'message_id': msg.get('Message-ID', ''),
                        'subject': msg.get('Subject', 'No subject'),
                        'from_name': sender_name,
                        'from_email': sender_email,
                        'date': msg.get('Date', ''),
                        'snippet': body_snippet,
                        'references': msg.get('References', ''),
                        'in_reply_to': msg.get('In-Reply-To', '')
                    })

            imap.logout()
            return emails

        except Exception as e:
            print(f"Error getting recent emails: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def find_email_from_sender(self, sender_name: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
        """
        Find the most recent email from a specific sender by name.

        Args:
            sender_name: Name to search for (partial match)

        Returns:
            Most recent matching email or None
        """
        emails = await self.get_recent_emails(max_results=max_results)
        sender_lower = sender_name.lower()

        for email_msg in emails:
            if sender_lower in email_msg.get('from_name', '').lower():
                return email_msg
            if sender_lower in email_msg.get('from_email', '').lower():
                return email_msg

        return None

    async def create_reply_draft(
        self,
        original_email: Dict[str, Any],
        body: str
    ) -> Optional[Dict[str, Any]]:
        """
        Create a reply draft to an existing email thread.

        Args:
            original_email: Email dict from get_recent_emails or find_email_from_sender
            body: Reply body text

        Returns:
            Draft info or None if failed
        """
        if not self.gmail_address or not self.app_password:
            return None

        try:
            # Build reply subject
            original_subject = original_email.get('subject', '')
            if not original_subject.lower().startswith('re:'):
                subject = f"Re: {original_subject}"
            else:
                subject = original_subject

            # Get recipient (original sender)
            recipient = original_email.get('from_email', '')
            if not recipient:
                print("Cannot reply: no sender email found")
                return None

            # Create the reply message
            msg = MIMEText(body, 'plain')
            msg['From'] = self.gmail_address
            msg['To'] = recipient
            msg['Subject'] = subject
            msg['Date'] = email.utils.formatdate(localtime=True)

            # Set threading headers for proper thread grouping
            original_message_id = original_email.get('message_id', '')
            if original_message_id:
                msg['In-Reply-To'] = original_message_id
                # Build References header
                original_refs = original_email.get('references', '')
                if original_refs:
                    msg['References'] = f"{original_refs} {original_message_id}"
                else:
                    msg['References'] = original_message_id

            # Save to Drafts via IMAP
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.gmail_address, self.app_password)
            imap.select('[Gmail]/Drafts')

            result = imap.append(
                '[Gmail]/Drafts',
                '\\Draft',
                None,
                msg.as_bytes()
            )

            imap.logout()

            if result[0] == 'OK':
                print(f"Reply draft created: '{subject}' to {recipient}")
                return {
                    'status': 'created',
                    'type': 'reply',
                    'to': recipient,
                    'subject': subject,
                    'in_reply_to': original_subject,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                print(f"Failed to create reply draft: {result}")
                return None

        except Exception as e:
            print(f"Error creating reply draft: {e}")
            import traceback
            traceback.print_exc()
            return None


# Singleton instance
_email_service = None


def get_email_service() -> Optional[EmailService]:
    """Get singleton email service instance."""
    global _email_service

    if _email_service is None:
        _email_service = EmailService()

    return _email_service
