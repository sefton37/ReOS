"""Thunderbird bridge for CAIRN.

Read-only access to Thunderbird's local SQLite databases for contacts and calendar.
Thunderbird remains the source of truth - we just read from it.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class ThunderbirdConfig:
    """Configuration for Thunderbird integration."""

    profile_path: Path
    address_book_path: Path | None = None
    calendar_path: Path | None = None

    def __post_init__(self) -> None:
        """Auto-detect database paths if not provided."""
        if self.address_book_path is None:
            abook = self.profile_path / "abook.sqlite"
            if abook.exists():
                self.address_book_path = abook

        if self.calendar_path is None:
            cal = self.profile_path / "calendar-data" / "local.sqlite"
            if cal.exists():
                self.calendar_path = cal


@dataclass
class ThunderbirdContact:
    """Contact from Thunderbird address book."""

    id: str
    display_name: str
    email: str | None = None
    phone: str | None = None
    organization: str | None = None
    notes: str | None = None

    # All properties from Thunderbird
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def first_name(self) -> str | None:
        """Get first name."""
        return self.properties.get("FirstName")

    @property
    def last_name(self) -> str | None:
        """Get last name."""
        return self.properties.get("LastName")

    @property
    def job_title(self) -> str | None:
        """Get job title."""
        return self.properties.get("JobTitle")


@dataclass
class CalendarEvent:
    """Event from Thunderbird calendar."""

    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    status: str | None = None  # "TENTATIVE", "CONFIRMED", "CANCELLED"
    all_day: bool = False

    # Raw icalendar data if needed
    ical_data: str | None = None


@dataclass
class CalendarTodo:
    """Todo from Thunderbird calendar."""

    id: str
    title: str
    due_date: datetime | None = None
    completed_date: datetime | None = None
    status: str | None = None  # "NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"
    priority: int | None = None  # 1-9, lower = higher priority
    description: str | None = None


class ThunderbirdBridge:
    """Read-only bridge to Thunderbird data."""

    def __init__(self, config: ThunderbirdConfig):
        """Initialize the bridge.

        Args:
            config: Thunderbird configuration with paths.
        """
        self.config = config

    @classmethod
    def auto_detect(cls) -> ThunderbirdBridge | None:
        """Auto-detect Thunderbird profile and create bridge.

        Returns:
            ThunderbirdBridge if profile found, None otherwise.
        """
        profile_path = cls._find_profile_path()
        if profile_path is None:
            return None

        config = ThunderbirdConfig(profile_path=profile_path)
        return cls(config)

    @staticmethod
    def _find_profile_path() -> Path | None:
        """Find Thunderbird profile path.

        Checks common locations for Thunderbird profiles.

        Returns:
            Path to profile directory, or None if not found.
        """
        home = Path.home()

        # Possible Thunderbird profile locations
        candidates = [
            # Snap installation (Ubuntu/Linux)
            home / "snap" / "thunderbird" / "common" / ".thunderbird",
            # Flatpak installation
            home / ".var" / "app" / "org.mozilla.Thunderbird" / ".thunderbird",
            # Standard Linux
            home / ".thunderbird",
            # macOS
            home / "Library" / "Thunderbird" / "Profiles",
            # Windows (approximate)
            Path(os.environ.get("APPDATA", "")) / "Thunderbird" / "Profiles",
        ]

        for base_path in candidates:
            if not base_path.exists():
                continue

            # Look for profile directories (ending in .default or .default-release)
            for item in base_path.iterdir():
                if item.is_dir() and (
                    item.name.endswith(".default")
                    or item.name.endswith(".default-release")
                ):
                    return item

            # Also check for profiles.ini and parse it
            profiles_ini = base_path / "profiles.ini"
            if profiles_ini.exists():
                # Simple parsing - look for Path= lines
                try:
                    content = profiles_ini.read_text()
                    for line in content.splitlines():
                        if line.startswith("Path="):
                            profile_name = line.split("=", 1)[1]
                            profile_path = base_path / profile_name
                            if profile_path.exists():
                                return profile_path
                except Exception:
                    pass

        return None

    def has_address_book(self) -> bool:
        """Check if address book is available."""
        return (
            self.config.address_book_path is not None
            and self.config.address_book_path.exists()
        )

    def has_calendar(self) -> bool:
        """Check if calendar is available."""
        return (
            self.config.calendar_path is not None
            and self.config.calendar_path.exists()
        )

    # =========================================================================
    # Contacts
    # =========================================================================

    def list_contacts(self, search: str | None = None) -> list[ThunderbirdContact]:
        """List contacts from address book.

        Args:
            search: Optional search string to filter by name/email.

        Returns:
            List of contacts.
        """
        if not self.has_address_book():
            return []

        contacts: dict[str, ThunderbirdContact] = {}

        try:
            conn = sqlite3.connect(
                f"file:{self.config.address_book_path}?mode=ro",
                uri=True,
            )
            conn.row_factory = sqlite3.Row

            # Thunderbird uses a properties table with key-value pairs
            rows = conn.execute(
                "SELECT card, name, value FROM properties ORDER BY card"
            ).fetchall()
            conn.close()

            # Group properties by card (contact ID)
            for row in rows:
                card_id = row["card"]
                prop_name = row["name"]
                prop_value = row["value"]

                if card_id not in contacts:
                    contacts[card_id] = ThunderbirdContact(
                        id=card_id,
                        display_name="",
                        properties={},
                    )

                contacts[card_id].properties[prop_name] = prop_value

            # Extract common fields
            for contact in contacts.values():
                props = contact.properties
                contact.display_name = props.get(
                    "DisplayName",
                    f"{props.get('FirstName', '')} {props.get('LastName', '')}".strip(),
                )
                contact.email = props.get("PrimaryEmail")
                contact.phone = props.get("WorkPhone") or props.get("HomePhone")
                contact.organization = props.get("Company")
                contact.notes = props.get("Notes")

            result = list(contacts.values())

            # Filter by search string
            if search:
                search_lower = search.lower()
                result = [
                    c
                    for c in result
                    if search_lower in c.display_name.lower()
                    or (c.email and search_lower in c.email.lower())
                    or (c.organization and search_lower in c.organization.lower())
                ]

            return result

        except sqlite3.Error:
            return []

    def get_contact(self, contact_id: str) -> ThunderbirdContact | None:
        """Get a contact by ID.

        Args:
            contact_id: The contact's card ID.

        Returns:
            ThunderbirdContact if found, None otherwise.
        """
        if not self.has_address_book():
            return None

        try:
            conn = sqlite3.connect(
                f"file:{self.config.address_book_path}?mode=ro",
                uri=True,
            )
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT name, value FROM properties WHERE card = ?",
                (contact_id,),
            ).fetchall()
            conn.close()

            if not rows:
                return None

            props = {row["name"]: row["value"] for row in rows}
            contact = ThunderbirdContact(
                id=contact_id,
                display_name=props.get(
                    "DisplayName",
                    f"{props.get('FirstName', '')} {props.get('LastName', '')}".strip(),
                ),
                email=props.get("PrimaryEmail"),
                phone=props.get("WorkPhone") or props.get("HomePhone"),
                organization=props.get("Company"),
                notes=props.get("Notes"),
                properties=props,
            )
            return contact

        except sqlite3.Error:
            return None

    def search_contacts(
        self, query: str, limit: int = 20
    ) -> list[ThunderbirdContact]:
        """Search contacts by name, email, or organization.

        Args:
            query: Search query.
            limit: Maximum results to return.

        Returns:
            List of matching contacts.
        """
        all_contacts = self.list_contacts(search=query)
        return all_contacts[:limit]

    # =========================================================================
    # Calendar Events
    # =========================================================================

    def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        include_past: bool = False,
    ) -> list[CalendarEvent]:
        """List calendar events.

        Args:
            start: Start of date range (default: now).
            end: End of date range (default: 30 days from start).
            include_past: Include past events in results.

        Returns:
            List of calendar events.
        """
        if not self.has_calendar():
            return []

        if start is None:
            start = datetime.now() if not include_past else datetime.min
        if end is None:
            end = start + timedelta(days=30)

        # Convert to microseconds since epoch (Thunderbird's format)
        start_us = int(start.timestamp() * 1_000_000)
        end_us = int(end.timestamp() * 1_000_000)

        try:
            conn = sqlite3.connect(
                f"file:{self.config.calendar_path}?mode=ro",
                uri=True,
            )
            conn.row_factory = sqlite3.Row

            # Query events
            rows = conn.execute(
                """
                SELECT id, title, event_start, event_end, event_stamp,
                       flags, icalString
                FROM cal_events
                WHERE event_start <= ? AND event_end >= ?
                ORDER BY event_start
                """,
                (end_us, start_us),
            ).fetchall()
            conn.close()

            events = []
            for row in rows:
                event = self._parse_event(row)
                if event:
                    events.append(event)

            return events

        except sqlite3.Error:
            return []

    def get_upcoming_events(
        self, hours: int = 24, limit: int = 10
    ) -> list[CalendarEvent]:
        """Get upcoming events.

        Args:
            hours: How many hours ahead to look.
            limit: Maximum events to return.

        Returns:
            List of upcoming events.
        """
        now = datetime.now()
        end = now + timedelta(hours=hours)
        events = self.list_events(start=now, end=end)
        return events[:limit]

    def get_today_events(self) -> list[CalendarEvent]:
        """Get today's events.

        Returns:
            List of today's events.
        """
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.list_events(start=start, end=end)

    def _parse_event(self, row: sqlite3.Row) -> CalendarEvent | None:
        """Parse a database row into CalendarEvent.

        Args:
            row: Database row.

        Returns:
            CalendarEvent or None if invalid.
        """
        try:
            # Thunderbird stores times in microseconds
            start_us = row["event_start"]
            end_us = row["event_end"]

            start = datetime.fromtimestamp(start_us / 1_000_000)
            end = datetime.fromtimestamp(end_us / 1_000_000)

            # Check if all-day (duration is exactly days)
            all_day = (end - start).total_seconds() % 86400 == 0

            # Parse iCal string for additional data
            location = None
            description = None
            status = None
            ical = row["icalString"]
            if ical:
                location = self._extract_ical_field(ical, "LOCATION")
                description = self._extract_ical_field(ical, "DESCRIPTION")
                status = self._extract_ical_field(ical, "STATUS")

            return CalendarEvent(
                id=row["id"],
                title=row["title"] or "Untitled",
                start=start,
                end=end,
                location=location,
                description=description,
                status=status,
                all_day=all_day,
                ical_data=ical,
            )
        except Exception:
            return None

    # =========================================================================
    # Calendar Todos
    # =========================================================================

    def list_todos(
        self,
        include_completed: bool = False,
    ) -> list[CalendarTodo]:
        """List calendar todos.

        Args:
            include_completed: Include completed todos.

        Returns:
            List of calendar todos.
        """
        if not self.has_calendar():
            return []

        try:
            conn = sqlite3.connect(
                f"file:{self.config.calendar_path}?mode=ro",
                uri=True,
            )
            conn.row_factory = sqlite3.Row

            if include_completed:
                rows = conn.execute(
                    """
                    SELECT id, title, todo_entry, todo_due, todo_completed,
                           flags, icalString
                    FROM cal_todos
                    ORDER BY todo_due
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, title, todo_entry, todo_due, todo_completed,
                           flags, icalString
                    FROM cal_todos
                    WHERE todo_completed IS NULL
                    ORDER BY todo_due
                    """
                ).fetchall()
            conn.close()

            todos = []
            for row in rows:
                todo = self._parse_todo(row)
                if todo:
                    todos.append(todo)

            return todos

        except sqlite3.Error:
            return []

    def get_overdue_todos(self) -> list[CalendarTodo]:
        """Get overdue todos.

        Returns:
            List of overdue todos.
        """
        now = datetime.now()
        todos = self.list_todos(include_completed=False)
        return [t for t in todos if t.due_date and t.due_date < now]

    def _parse_todo(self, row: sqlite3.Row) -> CalendarTodo | None:
        """Parse a database row into CalendarTodo.

        Args:
            row: Database row.

        Returns:
            CalendarTodo or None if invalid.
        """
        try:
            due_date = None
            completed_date = None

            if row["todo_due"]:
                due_date = datetime.fromtimestamp(row["todo_due"] / 1_000_000)

            if row["todo_completed"]:
                completed_date = datetime.fromtimestamp(
                    row["todo_completed"] / 1_000_000
                )

            # Parse iCal string for additional data
            status = None
            priority = None
            description = None
            ical = row["icalString"]
            if ical:
                status = self._extract_ical_field(ical, "STATUS")
                priority_str = self._extract_ical_field(ical, "PRIORITY")
                if priority_str:
                    try:
                        priority = int(priority_str)
                    except ValueError:
                        pass
                description = self._extract_ical_field(ical, "DESCRIPTION")

            return CalendarTodo(
                id=row["id"],
                title=row["title"] or "Untitled",
                due_date=due_date,
                completed_date=completed_date,
                status=status,
                priority=priority,
                description=description,
            )
        except Exception:
            return None

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _extract_ical_field(ical_string: str, field: str) -> str | None:
        """Extract a field from iCalendar data.

        Args:
            ical_string: Raw iCalendar string.
            field: Field name to extract (e.g., "LOCATION").

        Returns:
            Field value or None.
        """
        # Simple extraction - looks for FIELD:value or FIELD;params:value
        for line in ical_string.splitlines():
            if line.startswith(f"{field}:"):
                return line.split(":", 1)[1].strip()
            if line.startswith(f"{field};"):
                # Has parameters like LOCATION;ENCODING=UTF-8:value
                parts = line.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
        return None

    def get_status(self) -> dict[str, Any]:
        """Get bridge status information.

        Returns:
            Dict with status information.
        """
        return {
            "profile_path": str(self.config.profile_path),
            "has_address_book": self.has_address_book(),
            "address_book_path": (
                str(self.config.address_book_path)
                if self.config.address_book_path
                else None
            ),
            "has_calendar": self.has_calendar(),
            "calendar_path": (
                str(self.config.calendar_path)
                if self.config.calendar_path
                else None
            ),
        }
