"""Thunderbird email client integration for ReOS.

This module provides read-only access to Thunderbird's local data:
- Email messages (via global-messages-db.sqlite index)
- Contacts (via abook.sqlite)
- Calendar events (via calendar-data/local.sqlite)

Privacy-first design:
- All access is local-only and read-only
- No modifications to Thunderbird data
- Profile discovery respects standard locations
"""

from __future__ import annotations

import configparser
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Standard Thunderbird profile locations on different platforms
THUNDERBIRD_PROFILE_PATHS = [
    Path.home() / ".thunderbird",  # Linux
    Path.home() / ".mozilla-thunderbird",  # Older Linux
    Path.home() / "snap" / "thunderbird" / "common" / ".thunderbird",  # Snap
    Path.home() / ".var" / "app" / "org.mozilla.Thunderbird" / ".thunderbird",  # Flatpak
]


@dataclass(frozen=True)
class ThunderbirdProfile:
    """A Thunderbird profile with its data paths."""

    name: str
    path: Path
    is_default: bool

    @property
    def global_messages_db(self) -> Path:
        """Path to the global messages database."""
        return self.path / "global-messages-db.sqlite"

    @property
    def contacts_db(self) -> Path:
        """Path to the address book database."""
        return self.path / "abook.sqlite"

    @property
    def calendar_db(self) -> Path:
        """Path to the local calendar database."""
        return self.path / "calendar-data" / "local.sqlite"

    def has_messages_db(self) -> bool:
        """Check if the messages database exists."""
        return self.global_messages_db.exists()

    def has_contacts_db(self) -> bool:
        """Check if the contacts database exists."""
        return self.contacts_db.exists()

    def has_calendar_db(self) -> bool:
        """Check if the calendar database exists."""
        return self.calendar_db.exists()


@dataclass(frozen=True)
class EmailMessage:
    """A summarized email message from Thunderbird."""

    id: int
    folder_id: int
    subject: str
    sender: str
    recipients: str
    date: datetime | None
    snippet: str  # Preview text


@dataclass(frozen=True)
class Contact:
    """A contact from the Thunderbird address book."""

    id: str
    display_name: str
    primary_email: str
    secondary_email: str | None
    phone_work: str | None
    phone_home: str | None
    phone_mobile: str | None
    organization: str | None
    notes: str | None


@dataclass(frozen=True)
class CalendarEvent:
    """A calendar event from Thunderbird."""

    id: str
    title: str
    start_time: datetime | None
    end_time: datetime | None
    location: str | None
    description: str | None
    is_all_day: bool


class ThunderbirdError(RuntimeError):
    """Error accessing Thunderbird data."""

    pass


def find_thunderbird_root() -> Path | None:
    """Find the Thunderbird data root directory.

    Returns the first existing path from standard locations.
    """
    for path in THUNDERBIRD_PROFILE_PATHS:
        if path.exists() and path.is_dir():
            return path
    return None


def list_profiles(thunderbird_root: Path | None = None) -> list[ThunderbirdProfile]:
    """List all Thunderbird profiles.

    Reads profiles.ini to discover configured profiles.
    """
    root = thunderbird_root or find_thunderbird_root()
    if root is None:
        return []

    profiles_ini = root / "profiles.ini"
    if not profiles_ini.exists():
        # Try installs.ini for newer Thunderbird versions
        profiles_ini = root / "installs.ini"
        if not profiles_ini.exists():
            return []

    config = configparser.ConfigParser()
    try:
        config.read(str(profiles_ini))
    except configparser.Error as exc:
        logger.warning("Failed to parse profiles.ini: %s", exc)
        return []

    profiles: list[ThunderbirdProfile] = []

    for section in config.sections():
        if not section.startswith("Profile"):
            continue

        name = config.get(section, "Name", fallback="")
        path_str = config.get(section, "Path", fallback="")
        is_relative = config.getint(section, "IsRelative", fallback=1)
        is_default = config.getint(section, "Default", fallback=0)

        if not path_str:
            continue

        if is_relative:
            profile_path = root / path_str
        else:
            profile_path = Path(path_str)

        if profile_path.exists():
            profiles.append(
                ThunderbirdProfile(
                    name=name,
                    path=profile_path,
                    is_default=bool(is_default),
                )
            )

    return profiles


def get_default_profile(thunderbird_root: Path | None = None) -> ThunderbirdProfile | None:
    """Get the default Thunderbird profile."""
    profiles = list_profiles(thunderbird_root)
    for p in profiles:
        if p.is_default:
            return p
    # Return the first profile if no default is set
    return profiles[0] if profiles else None


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a read-only connection to a SQLite database."""
    if not db_path.exists():
        raise ThunderbirdError(f"Database not found: {db_path}")

    # Open in read-only mode using URI
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise ThunderbirdError(f"Failed to open database: {exc}") from exc


def _parse_timestamp(ts: Any) -> datetime | None:
    """Parse a Thunderbird timestamp (microseconds since epoch)."""
    if ts is None:
        return None
    try:
        # Thunderbird stores timestamps as microseconds since epoch
        seconds = int(ts) / 1_000_000
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _parse_ical_timestamp(ts: str | None) -> datetime | None:
    """Parse an iCal timestamp (YYYYMMDDTHHMMSSZ or YYYYMMDD)."""
    if not ts:
        return None
    try:
        # Try full datetime format
        if "T" in ts:
            ts_clean = ts.rstrip("Z")
            return datetime.strptime(ts_clean, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        # All-day event format
        return datetime.strptime(ts, "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class ThunderbirdClient:
    """Client for accessing Thunderbird data."""

    def __init__(self, profile: ThunderbirdProfile | None = None) -> None:
        """Initialize the client.

        Args:
            profile: The Thunderbird profile to use. If None, uses the default profile.
        """
        self._profile = profile or get_default_profile()
        if self._profile is None:
            raise ThunderbirdError("No Thunderbird profile found")

    @property
    def profile(self) -> ThunderbirdProfile:
        """The active profile."""
        return self._profile

    def search_messages(
        self,
        query: str,
        *,
        limit: int = 50,
        folder_name: str | None = None,
    ) -> list[EmailMessage]:
        """Search email messages.

        Args:
            query: Search term (matches subject, sender, recipients).
            limit: Maximum number of results.
            folder_name: Optional folder name to filter by.

        Returns:
            List of matching messages.
        """
        if not self._profile.has_messages_db():
            raise ThunderbirdError("Messages database not found")

        conn = _connect_readonly(self._profile.global_messages_db)
        try:
            # Build the search query
            sql = """
                SELECT
                    m.id,
                    m.folderID,
                    m.subject,
                    m.sender,
                    m.recipients,
                    m.date,
                    m.body  -- This is often a snippet/preview
                FROM messages m
                WHERE (
                    m.subject LIKE ? OR
                    m.sender LIKE ? OR
                    m.recipients LIKE ?
                )
            """
            params: list[Any] = [f"%{query}%", f"%{query}%", f"%{query}%"]

            if folder_name:
                sql += " AND m.folderID IN (SELECT id FROM folders WHERE name LIKE ?)"
                params.append(f"%{folder_name}%")

            sql += " ORDER BY m.date DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            messages = []
            for row in rows:
                msg = EmailMessage(
                    id=row["id"],
                    folder_id=row["folderID"],
                    subject=row["subject"] or "",
                    sender=row["sender"] or "",
                    recipients=row["recipients"] or "",
                    date=_parse_timestamp(row["date"]),
                    snippet=(row["body"] or "")[:200],
                )
                messages.append(msg)

            return messages
        finally:
            conn.close()

    def list_folders(self) -> list[dict[str, Any]]:
        """List email folders.

        Returns:
            List of folder info dicts with id, name, and message count.
        """
        if not self._profile.has_messages_db():
            raise ThunderbirdError("Messages database not found")

        conn = _connect_readonly(self._profile.global_messages_db)
        try:
            cursor = conn.execute("""
                SELECT
                    f.id,
                    f.name,
                    COUNT(m.id) as message_count
                FROM folders f
                LEFT JOIN messages m ON m.folderID = f.id
                GROUP BY f.id, f.name
                ORDER BY f.name
            """)
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"] or "(unnamed)",
                    "message_count": row["message_count"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def search_contacts(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> list[Contact]:
        """Search contacts in the address book.

        Args:
            query: Search term (matches name, email, organization).
            limit: Maximum number of results.

        Returns:
            List of matching contacts.
        """
        if not self._profile.has_contacts_db():
            raise ThunderbirdError("Contacts database not found")

        conn = _connect_readonly(self._profile.contacts_db)
        try:
            # The abook.sqlite schema uses a properties table with card_id
            # Try the newer schema first
            try:
                cursor = conn.execute("""
                    SELECT
                        c.uid,
                        MAX(CASE WHEN p.name = 'DisplayName' THEN p.value END) as display_name,
                        MAX(CASE WHEN p.name = 'PrimaryEmail' THEN p.value END) as primary_email,
                        MAX(CASE WHEN p.name = 'SecondEmail' THEN p.value END) as secondary_email,
                        MAX(CASE WHEN p.name = 'WorkPhone' THEN p.value END) as phone_work,
                        MAX(CASE WHEN p.name = 'HomePhone' THEN p.value END) as phone_home,
                        MAX(CASE WHEN p.name = 'CellularNumber' THEN p.value END) as phone_mobile,
                        MAX(CASE WHEN p.name = 'Company' THEN p.value END) as organization,
                        MAX(CASE WHEN p.name = 'Notes' THEN p.value END) as notes
                    FROM cards c
                    LEFT JOIN properties p ON p.card = c.uid
                    WHERE EXISTS (
                        SELECT 1 FROM properties p2
                        WHERE p2.card = c.uid
                        AND p2.value LIKE ?
                    )
                    GROUP BY c.uid
                    LIMIT ?
                """, (f"%{query}%", limit))
            except sqlite3.OperationalError:
                # Fall back to older schema
                cursor = conn.execute("""
                    SELECT
                        card as uid,
                        MAX(CASE WHEN name = 'DisplayName' THEN value END) as display_name,
                        MAX(CASE WHEN name = 'PrimaryEmail' THEN value END) as primary_email,
                        MAX(CASE WHEN name = 'SecondEmail' THEN value END) as secondary_email,
                        MAX(CASE WHEN name = 'WorkPhone' THEN value END) as phone_work,
                        MAX(CASE WHEN name = 'HomePhone' THEN value END) as phone_home,
                        MAX(CASE WHEN name = 'CellularNumber' THEN value END) as phone_mobile,
                        MAX(CASE WHEN name = 'Company' THEN value END) as organization,
                        MAX(CASE WHEN name = 'Notes' THEN value END) as notes
                    FROM properties
                    WHERE card IN (
                        SELECT DISTINCT card FROM properties WHERE value LIKE ?
                    )
                    GROUP BY card
                    LIMIT ?
                """, (f"%{query}%", limit))

            rows = cursor.fetchall()
            contacts = []
            for row in rows:
                contact = Contact(
                    id=str(row["uid"] or ""),
                    display_name=row["display_name"] or "",
                    primary_email=row["primary_email"] or "",
                    secondary_email=row["secondary_email"],
                    phone_work=row["phone_work"],
                    phone_home=row["phone_home"],
                    phone_mobile=row["phone_mobile"],
                    organization=row["organization"],
                    notes=row["notes"],
                )
                contacts.append(contact)
            return contacts
        finally:
            conn.close()

    def list_address_books(self) -> list[dict[str, Any]]:
        """List available address books.

        Returns:
            List of address book info.
        """
        # Find all abook*.sqlite files in the profile
        abooks = list(self._profile.path.glob("abook*.sqlite"))
        return [
            {
                "name": ab.stem,
                "path": str(ab),
            }
            for ab in abooks
        ]

    def search_calendar(
        self,
        query: str | None = None,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
    ) -> list[CalendarEvent]:
        """Search calendar events.

        Args:
            query: Optional text search (matches title, description, location).
            start_date: Optional start date filter.
            end_date: Optional end date filter.
            limit: Maximum number of results.

        Returns:
            List of matching calendar events.
        """
        if not self._profile.has_calendar_db():
            raise ThunderbirdError("Calendar database not found")

        conn = _connect_readonly(self._profile.calendar_db)
        try:
            # The calendar database stores events as iCal data
            # We need to parse the cal_properties table
            sql = """
                SELECT
                    i.id,
                    i.ical_component,
                    MAX(CASE WHEN p.key = 'SUMMARY' THEN p.value END) as title,
                    MAX(CASE WHEN p.key = 'DTSTART' THEN p.value END) as start_time,
                    MAX(CASE WHEN p.key = 'DTEND' THEN p.value END) as end_time,
                    MAX(CASE WHEN p.key = 'LOCATION' THEN p.value END) as location,
                    MAX(CASE WHEN p.key = 'DESCRIPTION' THEN p.value END) as description
                FROM cal_events i
                LEFT JOIN cal_properties p ON p.item_id = i.id
                WHERE 1=1
            """
            params: list[Any] = []

            if query:
                sql += """
                    AND i.id IN (
                        SELECT DISTINCT item_id FROM cal_properties
                        WHERE value LIKE ? AND key IN ('SUMMARY', 'DESCRIPTION', 'LOCATION')
                    )
                """
                params.append(f"%{query}%")

            sql += " GROUP BY i.id ORDER BY start_time DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            events = []
            for row in rows:
                start = _parse_ical_timestamp(row["start_time"])
                end = _parse_ical_timestamp(row["end_time"])

                # Check if it's an all-day event (no time component)
                is_all_day = False
                if row["start_time"] and "T" not in str(row["start_time"]):
                    is_all_day = True

                # Apply date filters
                if start_date and start and start < start_date:
                    continue
                if end_date and start and start > end_date:
                    continue

                event = CalendarEvent(
                    id=str(row["id"] or ""),
                    title=row["title"] or "",
                    start_time=start,
                    end_time=end,
                    location=row["location"],
                    description=row["description"],
                    is_all_day=is_all_day,
                )
                events.append(event)

            return events
        except sqlite3.OperationalError as exc:
            # Calendar schema might differ
            logger.warning("Calendar query failed: %s", exc)
            return []
        finally:
            conn.close()

    def list_calendars(self) -> list[dict[str, Any]]:
        """List available calendars.

        Returns:
            List of calendar info.
        """
        if not self._profile.has_calendar_db():
            return []

        conn = _connect_readonly(self._profile.calendar_db)
        try:
            cursor = conn.execute("""
                SELECT id, name FROM cal_calendars
            """)
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"] or "(unnamed)",
                }
                for row in rows
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()


def get_thunderbird_status() -> dict[str, Any]:
    """Get the status of Thunderbird integration.

    Returns a dict with:
    - installed: bool - whether Thunderbird data was found
    - profile: str | None - the default profile name
    - has_messages: bool
    - has_contacts: bool
    - has_calendar: bool
    """
    root = find_thunderbird_root()
    if root is None:
        return {
            "installed": False,
            "profile": None,
            "has_messages": False,
            "has_contacts": False,
            "has_calendar": False,
        }

    profile = get_default_profile(root)
    if profile is None:
        return {
            "installed": True,
            "profile": None,
            "has_messages": False,
            "has_contacts": False,
            "has_calendar": False,
        }

    return {
        "installed": True,
        "profile": profile.name,
        "profile_path": str(profile.path),
        "has_messages": profile.has_messages_db(),
        "has_contacts": profile.has_contacts_db(),
        "has_calendar": profile.has_calendar_db(),
    }
