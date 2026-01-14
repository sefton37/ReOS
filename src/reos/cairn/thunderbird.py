"""Thunderbird bridge for CAIRN.

Read-only access to Thunderbird's local SQLite databases for contacts and calendar.
Thunderbird remains the source of truth - we just read from it.
"""

from __future__ import annotations

import configparser
import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-Profile Discovery Types
# =============================================================================


@dataclass
class ThunderbirdAccount:
    """An email account within a Thunderbird profile."""

    id: str  # Internal account ID (e.g., "account1")
    name: str  # Display name
    email: str  # Primary email address
    type: str  # "imap", "pop3", "local", "rss"
    server: str | None = None  # Server hostname
    calendars: list[str] = field(default_factory=list)  # Calendar IDs
    address_books: list[str] = field(default_factory=list)  # Address book IDs


@dataclass
class ThunderbirdProfile:
    """A discovered Thunderbird profile."""

    name: str  # Profile name (e.g., "default", "work")
    path: Path  # Full path to profile directory
    is_default: bool  # Is this the default profile?
    accounts: list[ThunderbirdAccount] = field(default_factory=list)


@dataclass
class ThunderbirdIntegration:
    """Full Thunderbird integration state."""

    installed: bool  # Is Thunderbird installed?
    install_suggestion: str | None = None  # Install command if not installed
    profiles: list[ThunderbirdProfile] = field(default_factory=list)
    active_profiles: list[str] = field(default_factory=list)  # Profile names enabled
    declined: bool = False  # User declined integration
    declined_at: datetime | None = None


def check_thunderbird_installation() -> tuple[bool, str | None]:
    """Check if Thunderbird is installed.

    Returns:
        Tuple of (installed, install_suggestion).
    """
    # Check common Thunderbird executable locations
    thunderbird_paths = [
        "/usr/bin/thunderbird",
        "/snap/bin/thunderbird",
        "/usr/bin/thunderbird-esr",
    ]

    # Check if thunderbird is in PATH
    if shutil.which("thunderbird"):
        return True, None

    # Check common paths
    for path in thunderbird_paths:
        if Path(path).exists():
            return True, None

    # Not installed - provide install suggestions based on distro
    # Try to detect package manager
    if shutil.which("apt"):
        return False, "sudo apt install thunderbird"
    elif shutil.which("dnf"):
        return False, "sudo dnf install thunderbird"
    elif shutil.which("pacman"):
        return False, "sudo pacman -S thunderbird"
    elif shutil.which("snap"):
        return False, "sudo snap install thunderbird"
    elif shutil.which("flatpak"):
        return False, "flatpak install flathub org.mozilla.Thunderbird"
    else:
        return False, "Install Thunderbird from your package manager or https://www.thunderbird.net/"


def _get_thunderbird_base_paths() -> list[Path]:
    """Get possible Thunderbird profile base paths.

    Returns:
        List of paths to check for profiles.ini.
    """
    home = Path.home()
    return [
        # Snap installation (Ubuntu/Linux)
        home / "snap" / "thunderbird" / "common" / ".thunderbird",
        # Flatpak installation
        home / ".var" / "app" / "org.mozilla.Thunderbird" / ".thunderbird",
        # Standard Linux
        home / ".thunderbird",
        # macOS
        home / "Library" / "Thunderbird" / "Profiles",
        # Windows
        Path(os.environ.get("APPDATA", "")) / "Thunderbird" / "Profiles",
    ]


def discover_all_profiles() -> list[ThunderbirdProfile]:
    """Discover all Thunderbird profiles on the system.

    Parses profiles.ini to find all configured profiles.

    Returns:
        List of discovered profiles with their accounts.
    """
    profiles: list[ThunderbirdProfile] = []

    for base_path in _get_thunderbird_base_paths():
        if not base_path.exists():
            continue

        profiles_ini = base_path / "profiles.ini"
        if not profiles_ini.exists():
            # Fall back to directory-based detection
            for item in base_path.iterdir():
                if item.is_dir() and (
                    item.name.endswith(".default")
                    or item.name.endswith(".default-release")
                ):
                    profile = ThunderbirdProfile(
                        name=item.name.split(".")[0],
                        path=item,
                        is_default=True,
                        accounts=[],
                    )
                    # Get accounts for this profile
                    profile.accounts = get_accounts_in_profile(item)
                    profiles.append(profile)
            continue

        # Parse profiles.ini using configparser
        try:
            config = configparser.ConfigParser()
            config.read(profiles_ini)

            for section in config.sections():
                if not section.startswith("Profile"):
                    continue

                name = config.get(section, "Name", fallback="unknown")
                path_value = config.get(section, "Path", fallback=None)
                is_relative = config.getboolean(section, "IsRelative", fallback=True)
                is_default = config.getboolean(section, "Default", fallback=False)

                if path_value is None:
                    continue

                if is_relative:
                    profile_path = base_path / path_value
                else:
                    profile_path = Path(path_value)

                if not profile_path.exists():
                    logger.debug("Profile path does not exist: %s", profile_path)
                    continue

                profile = ThunderbirdProfile(
                    name=name,
                    path=profile_path,
                    is_default=is_default,
                    accounts=[],
                )
                # Get accounts for this profile
                profile.accounts = get_accounts_in_profile(profile_path)
                profiles.append(profile)

        except Exception as e:
            logger.warning("Failed to parse profiles.ini at %s: %s", profiles_ini, e)

    return profiles


def get_accounts_in_profile(profile_path: Path) -> list[ThunderbirdAccount]:
    """Extract all email accounts from a Thunderbird profile.

    Parses prefs.js to find mail.account.* entries.

    Args:
        profile_path: Path to the profile directory.

    Returns:
        List of accounts in the profile.
    """
    accounts: list[ThunderbirdAccount] = []
    prefs_file = profile_path / "prefs.js"

    if not prefs_file.exists():
        return accounts

    try:
        content = prefs_file.read_text(errors="replace")

        # Extract account IDs from mail.accountmanager.accounts
        # Format: user_pref("mail.accountmanager.accounts", "account1,account2");
        accounts_match = re.search(
            r'user_pref\("mail\.accountmanager\.accounts",\s*"([^"]+)"\);',
            content,
        )

        if not accounts_match:
            return accounts

        account_ids = accounts_match.group(1).split(",")

        for account_id in account_ids:
            account_id = account_id.strip()
            if not account_id:
                continue

            # Get identity for this account
            # Format: user_pref("mail.account.account1.identities", "id1");
            identity_match = re.search(
                rf'user_pref\("mail\.account\.{account_id}\.identities",\s*"([^"]+)"\);',
                content,
            )

            # Get server for this account
            # Format: user_pref("mail.account.account1.server", "server1");
            server_match = re.search(
                rf'user_pref\("mail\.account\.{account_id}\.server",\s*"([^"]+)"\);',
                content,
            )

            email = ""
            name = account_id
            server_type = "unknown"
            server_host = None

            # Get email from identity
            if identity_match:
                identity_id = identity_match.group(1).split(",")[0].strip()
                email_match = re.search(
                    rf'user_pref\("mail\.identity\.{identity_id}\.useremail",\s*"([^"]+)"\);',
                    content,
                )
                if email_match:
                    email = email_match.group(1)

                name_match = re.search(
                    rf'user_pref\("mail\.identity\.{identity_id}\.fullName",\s*"([^"]+)"\);',
                    content,
                )
                if name_match:
                    name = name_match.group(1)

            # Get server type and hostname
            if server_match:
                server_id = server_match.group(1).strip()
                type_match = re.search(
                    rf'user_pref\("mail\.server\.{server_id}\.type",\s*"([^"]+)"\);',
                    content,
                )
                if type_match:
                    server_type = type_match.group(1)

                host_match = re.search(
                    rf'user_pref\("mail\.server\.{server_id}\.hostname",\s*"([^"]+)"\);',
                    content,
                )
                if host_match:
                    server_host = host_match.group(1)

            # Get calendars (from calendar-data directory)
            calendars: list[str] = []
            calendar_data = profile_path / "calendar-data"
            if calendar_data.exists():
                # Each .sqlite file is a calendar
                for cal_file in calendar_data.glob("*.sqlite"):
                    calendars.append(cal_file.stem)

            # Get address books
            address_books: list[str] = []
            abook_path = profile_path / "abook.sqlite"
            if abook_path.exists():
                address_books.append("abook")
            # Check for additional address books
            for abook_file in profile_path.glob("abook-*.sqlite"):
                address_books.append(abook_file.stem)

            account = ThunderbirdAccount(
                id=account_id,
                name=name,
                email=email,
                type=server_type,
                server=server_host,
                calendars=calendars,
                address_books=address_books,
            )
            accounts.append(account)

    except Exception as e:
        logger.warning("Failed to parse prefs.js at %s: %s", prefs_file, e)

    return accounts


def get_thunderbird_integration_state() -> ThunderbirdIntegration:
    """Get full Thunderbird integration state.

    Returns:
        ThunderbirdIntegration with installation status and discovered profiles.
    """
    installed, install_suggestion = check_thunderbird_installation()

    if not installed:
        return ThunderbirdIntegration(
            installed=False,
            install_suggestion=install_suggestion,
            profiles=[],
        )

    profiles = discover_all_profiles()

    return ThunderbirdIntegration(
        installed=True,
        install_suggestion=None,
        profiles=profiles,
    )


# =============================================================================
# Original Types (preserved for compatibility)
# =============================================================================


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
            # Check for calendar databases in order of preference:
            # 1. cache.sqlite - synced calendars (CalDAV, Google, etc.) - most common
            # 2. local.sqlite - purely local calendars
            calendar_candidates = [
                self.profile_path / "calendar-data" / "cache.sqlite",
                self.profile_path / "calendar-data" / "local.sqlite",
            ]
            for cal in calendar_candidates:
                if cal.exists():
                    self.calendar_path = cal
                    break


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

    # Recurrence info
    is_recurring: bool = False
    recurrence_rule: str | None = None  # Raw RRULE if present (e.g., "FREQ=WEEKLY;BYDAY=MO,WE,FR")
    recurrence_frequency: str | None = None  # "DAILY", "WEEKLY", "MONTHLY", "YEARLY"

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
                except Exception as e:
                    logger.debug("Failed to parse profiles.ini at %s: %s", profiles_ini, e)

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

        except sqlite3.Error as e:
            logger.warning("Failed to list contacts from Thunderbird: %s", e)
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

        except sqlite3.Error as e:
            logger.warning("Failed to get contact %s from Thunderbird: %s", contact_id, e)
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

    def _open_calendar_db(self) -> sqlite3.Connection | None:
        """Open calendar database with WAL support.

        Returns:
            SQLite connection or None if failed.
        """
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "cairn_calendar"
        temp_dir.mkdir(exist_ok=True)
        temp_db = temp_dir / "cache.sqlite"
        try:
            # Copy main database and WAL files
            shutil.copy(self.config.calendar_path, temp_db)
            for suffix in ["-wal", "-shm"]:
                wal_file = Path(str(self.config.calendar_path) + suffix)
                if wal_file.exists():
                    shutil.copy(wal_file, temp_dir / f"cache.sqlite{suffix}")
            db_path = temp_db
        except (OSError, IOError) as e:
            logger.debug("Could not copy calendar db, using original: %s", e)
            db_path = self.config.calendar_path

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.row_factory = sqlite3.Row
        return conn

    def _expand_recurring_event(
        self,
        event: CalendarEvent,
        rrule_str: str,
        query_start: datetime,
        query_end: datetime,
    ) -> list[CalendarEvent]:
        """Expand a recurring event into occurrences within the time window.

        Args:
            event: The base event with original start/end.
            rrule_str: The RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO").
            query_start: Start of time window.
            query_end: End of time window.

        Returns:
            List of event occurrences within the window.
        """
        try:
            from dateutil.rrule import rrulestr
        except ImportError:
            logger.debug("dateutil not available, skipping recurrence expansion")
            return []

        occurrences = []
        duration = event.end - event.start

        try:
            # Parse the RRULE - strip "RRULE:" prefix if present
            rule_text = rrule_str
            if rule_text.startswith("RRULE:"):
                rule_text = rule_text[6:]

            # Handle timezone issues: UNTIL with Z suffix needs timezone-aware dtstart
            # Convert UNTIL from UTC to naive local time to avoid timezone conflicts
            if "UNTIL=" in rule_text and "Z" in rule_text:
                import re
                # Extract and convert UNTIL to naive local time
                match = re.search(r"UNTIL=(\d{8}T\d{6})Z", rule_text)
                if match:
                    until_str = match.group(1)
                    # Parse as UTC, convert to local, format as naive
                    from datetime import timezone
                    until_utc = datetime.strptime(until_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                    until_local = until_utc.astimezone().replace(tzinfo=None)
                    # Replace in rule text (remove Z suffix)
                    rule_text = rule_text.replace(
                        f"UNTIL={until_str}Z",
                        f"UNTIL={until_local.strftime('%Y%m%dT%H%M%S')}"
                    )

            # Create rrule with the event's original start as dtstart
            rule = rrulestr(rule_text, dtstart=event.start)

            # Get occurrences within the time window
            for dt in rule.between(query_start, query_end, inc=True):
                # Create a new event for this occurrence
                occurrence = CalendarEvent(
                    id=f"{event.id}_{dt.strftime('%Y%m%d%H%M')}",
                    title=event.title,
                    start=dt,
                    end=dt + duration,
                    location=event.location,
                    description=event.description,
                    status=event.status,
                    all_day=event.all_day,
                    is_recurring=True,
                    recurrence_rule=rrule_str,
                    recurrence_frequency=event.recurrence_frequency,
                )
                occurrences.append(occurrence)

        except Exception as e:
            logger.debug("Failed to expand recurrence for %s: %s", event.title, e)

        return occurrences

    def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        include_past: bool = False,
    ) -> list[CalendarEvent]:
        """List calendar events including expanded recurring events.

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
            conn = self._open_calendar_db()
            if conn is None:
                return []

            events = []

            # 1. Query non-recurring events in the time window
            rows = conn.execute(
                """
                SELECT e.id, e.title, e.event_start, e.event_end, e.event_stamp, e.flags
                FROM cal_events e
                LEFT JOIN cal_recurrence r ON e.id = r.item_id AND e.cal_id = r.cal_id
                WHERE e.event_start <= ? AND e.event_end >= ?
                  AND (r.icalString IS NULL OR r.icalString NOT LIKE 'RRULE:%')
                ORDER BY e.event_start
                """,
                (end_us, start_us),
            ).fetchall()

            for row in rows:
                event = self._parse_event(row)
                if event:
                    events.append(event)

            # 2. Query recurring events and expand them
            recurring_rows = conn.execute(
                """
                SELECT DISTINCT e.id, e.title, e.event_start, e.event_end,
                       e.event_stamp, e.flags, r.icalString as rrule
                FROM cal_events e
                JOIN cal_recurrence r ON e.id = r.item_id AND e.cal_id = r.cal_id
                WHERE r.icalString LIKE 'RRULE:%'
                """,
            ).fetchall()

            conn.close()

            # Expand each recurring event
            seen_ids = set()  # Avoid duplicate base events
            for row in recurring_rows:
                base_id = row["id"]
                if base_id in seen_ids:
                    continue
                seen_ids.add(base_id)

                base_event = self._parse_event(row)
                if base_event:
                    rrule_str = row["rrule"]
                    occurrences = self._expand_recurring_event(
                        base_event, rrule_str, start, end
                    )
                    events.extend(occurrences)

            # Sort by start time
            events.sort(key=lambda e: e.start)
            return events

        except sqlite3.Error as e:
            logger.warning("Failed to list calendar events from Thunderbird: %s", e)
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

            # Parse iCal string for additional data (if available)
            location = None
            description = None
            status = None
            ical = None
            is_recurring = False
            recurrence_rule = None
            recurrence_frequency = None
            try:
                ical = row["icalString"]
                if ical:
                    location = self._extract_ical_field(ical, "LOCATION")
                    description = self._extract_ical_field(ical, "DESCRIPTION")
                    status = self._extract_ical_field(ical, "STATUS")
                    # Extract recurrence info
                    recurrence_rule = self._extract_ical_field(ical, "RRULE")
                    if recurrence_rule:
                        is_recurring = True
                        # Extract frequency from RRULE (e.g., "FREQ=WEEKLY;BYDAY=MO" -> "WEEKLY")
                        if "FREQ=" in recurrence_rule:
                            freq_part = recurrence_rule.split("FREQ=")[1].split(";")[0]
                            recurrence_frequency = freq_part
            except (KeyError, IndexError):
                # icalString column may not exist in all Thunderbird versions
                pass

            return CalendarEvent(
                id=row["id"],
                title=row["title"] or "Untitled",
                start=start,
                end=end,
                location=location,
                description=description,
                status=status,
                all_day=all_day,
                is_recurring=is_recurring,
                recurrence_rule=recurrence_rule,
                recurrence_frequency=recurrence_frequency,
                ical_data=ical,
            )
        except Exception as e:
            logger.debug("Failed to parse calendar event row: %s", e)
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

            # First check what columns exist in the table
            try:
                cursor = conn.execute("PRAGMA table_info(cal_todos)")
                columns = {row[1] for row in cursor.fetchall()}
            except sqlite3.Error:
                columns = set()

            # Build query based on available columns
            if "icalString" in columns:
                select_cols = "id, title, todo_entry, todo_due, todo_completed, flags, icalString"
            else:
                select_cols = "id, title, todo_entry, todo_due, todo_completed, flags"

            if include_completed:
                rows = conn.execute(
                    f"""
                    SELECT {select_cols}
                    FROM cal_todos
                    ORDER BY todo_due
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT {select_cols}
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

        except sqlite3.Error as e:
            logger.warning("Failed to list calendar todos from Thunderbird: %s", e)
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

            # Parse iCal string for additional data (if available)
            status = None
            priority = None
            description = None
            try:
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
            except (KeyError, IndexError):
                # icalString column may not exist in all Thunderbird versions
                pass

            return CalendarTodo(
                id=row["id"],
                title=row["title"] or "Untitled",
                due_date=due_date,
                completed_date=completed_date,
                status=status,
                priority=priority,
                description=description,
            )
        except Exception as e:
            logger.debug("Failed to parse calendar todo row: %s", e)
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

    @staticmethod
    def get_next_occurrence(
        rrule_str: str,
        dtstart: datetime,
        after: datetime | None = None,
    ) -> datetime | None:
        """Get the next occurrence of a recurring event.

        Args:
            rrule_str: The RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO").
            dtstart: The original start datetime of the event.
            after: Find next occurrence after this time (default: now).

        Returns:
            The next occurrence datetime, or None if no more occurrences.
        """
        try:
            from dateutil.rrule import rrulestr
        except ImportError:
            logger.debug("dateutil not available, cannot compute next occurrence")
            return None

        if after is None:
            after = datetime.now()

        try:
            # Strip "RRULE:" prefix if present
            rule_text = rrule_str
            if rule_text.startswith("RRULE:"):
                rule_text = rule_text[6:]

            # Handle timezone issues: UNTIL with Z suffix needs conversion
            if "UNTIL=" in rule_text and "Z" in rule_text:
                match = re.search(r"UNTIL=(\d{8}T\d{6})Z", rule_text)
                if match:
                    until_str = match.group(1)
                    from datetime import timezone
                    until_utc = datetime.strptime(until_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                    until_local = until_utc.astimezone().replace(tzinfo=None)
                    rule_text = rule_text.replace(
                        f"UNTIL={until_str}Z",
                        f"UNTIL={until_local.strftime('%Y%m%dT%H%M%S')}"
                    )

            # Create rrule with the event's original start as dtstart
            rule = rrulestr(rule_text, dtstart=dtstart)

            # Get next occurrence after the specified time
            next_dt = rule.after(after, inc=False)
            return next_dt

        except Exception as e:
            logger.debug("Failed to compute next occurrence: %s", e)
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
