"""Tests for Thunderbird integration module."""

from __future__ import annotations

import configparser
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from reos.thunderbird import (
    CalendarEvent,
    Contact,
    EmailMessage,
    ThunderbirdClient,
    ThunderbirdError,
    ThunderbirdProfile,
    find_thunderbird_root,
    get_default_profile,
    get_thunderbird_status,
    list_profiles,
)


class TestThunderbirdProfile:
    def test_profile_paths(self, tmp_path: Path) -> None:
        profile = ThunderbirdProfile(
            name="default",
            path=tmp_path,
            is_default=True,
        )
        assert profile.global_messages_db == tmp_path / "global-messages-db.sqlite"
        assert profile.contacts_db == tmp_path / "abook.sqlite"
        assert profile.calendar_db == tmp_path / "calendar-data" / "local.sqlite"

    def test_has_messages_db_false(self, tmp_path: Path) -> None:
        profile = ThunderbirdProfile(name="test", path=tmp_path, is_default=False)
        assert profile.has_messages_db() is False

    def test_has_messages_db_true(self, tmp_path: Path) -> None:
        (tmp_path / "global-messages-db.sqlite").touch()
        profile = ThunderbirdProfile(name="test", path=tmp_path, is_default=False)
        assert profile.has_messages_db() is True

    def test_has_contacts_db(self, tmp_path: Path) -> None:
        profile = ThunderbirdProfile(name="test", path=tmp_path, is_default=False)
        assert profile.has_contacts_db() is False

        (tmp_path / "abook.sqlite").touch()
        assert profile.has_contacts_db() is True

    def test_has_calendar_db(self, tmp_path: Path) -> None:
        profile = ThunderbirdProfile(name="test", path=tmp_path, is_default=False)
        assert profile.has_calendar_db() is False

        (tmp_path / "calendar-data").mkdir()
        (tmp_path / "calendar-data" / "local.sqlite").touch()
        assert profile.has_calendar_db() is True


class TestProfileDiscovery:
    def test_find_thunderbird_root_not_found(self) -> None:
        # On a system without Thunderbird, this should return None
        # (unless Thunderbird is actually installed)
        result = find_thunderbird_root()
        # Can't assert None because it might find real Thunderbird
        assert result is None or result.exists()

    def test_list_profiles_with_mock(self, tmp_path: Path) -> None:
        """Test profile listing with a mock profiles.ini."""
        profiles_ini = tmp_path / "profiles.ini"
        profile_dir = tmp_path / "abcd1234.default"
        profile_dir.mkdir()

        config = configparser.ConfigParser()
        config["Profile0"] = {
            "Name": "default",
            "Path": "abcd1234.default",
            "IsRelative": "1",
            "Default": "1",
        }
        with profiles_ini.open("w") as f:
            config.write(f)

        profiles = list_profiles(tmp_path)
        assert len(profiles) == 1
        assert profiles[0].name == "default"
        assert profiles[0].is_default is True
        assert profiles[0].path == profile_dir

    def test_list_profiles_empty(self, tmp_path: Path) -> None:
        """No profiles.ini means empty list."""
        profiles = list_profiles(tmp_path)
        assert profiles == []

    def test_get_default_profile(self, tmp_path: Path) -> None:
        """Test getting default profile."""
        profiles_ini = tmp_path / "profiles.ini"
        profile_dir = tmp_path / "default-profile"
        profile_dir.mkdir()

        config = configparser.ConfigParser()
        config["Profile0"] = {
            "Name": "test-profile",
            "Path": "default-profile",
            "IsRelative": "1",
            "Default": "1",
        }
        with profiles_ini.open("w") as f:
            config.write(f)

        profile = get_default_profile(tmp_path)
        assert profile is not None
        assert profile.name == "test-profile"


class TestThunderbirdStatus:
    def test_status_when_not_installed(self) -> None:
        """Status should report not installed when no Thunderbird found."""
        # This will use the real system check
        status = get_thunderbird_status()
        assert "installed" in status
        # installed may be True or False depending on system


@pytest.fixture
def mock_messages_db(tmp_path: Path) -> Path:
    """Create a mock Thunderbird messages database."""
    db_path = tmp_path / "global-messages-db.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE folders (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            folderID INTEGER,
            subject TEXT,
            sender TEXT,
            recipients TEXT,
            date INTEGER,
            body TEXT
        )
    """)
    # Insert test data
    conn.execute("INSERT INTO folders (id, name) VALUES (1, 'Inbox')")
    conn.execute("INSERT INTO folders (id, name) VALUES (2, 'Sent')")

    # Date as microseconds since epoch
    test_date = int(datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)
    conn.execute(
        "INSERT INTO messages (id, folderID, subject, sender, recipients, date, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "Test Subject", "sender@example.com", "recipient@example.com", test_date, "This is a test email body"),
    )
    conn.execute(
        "INSERT INTO messages (id, folderID, subject, sender, recipients, date, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, 1, "Meeting Tomorrow", "boss@example.com", "me@example.com", test_date, "Don't forget the meeting"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mock_contacts_db(tmp_path: Path) -> Path:
    """Create a mock Thunderbird contacts database."""
    db_path = tmp_path / "abook.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE properties (
            card TEXT,
            name TEXT,
            value TEXT
        )
    """)
    # Insert test contact
    conn.execute("INSERT INTO properties VALUES ('card1', 'DisplayName', 'John Doe')")
    conn.execute("INSERT INTO properties VALUES ('card1', 'PrimaryEmail', 'john@example.com')")
    conn.execute("INSERT INTO properties VALUES ('card1', 'Company', 'Acme Corp')")
    conn.execute("INSERT INTO properties VALUES ('card1', 'CellularNumber', '555-1234')")

    conn.execute("INSERT INTO properties VALUES ('card2', 'DisplayName', 'Jane Smith')")
    conn.execute("INSERT INTO properties VALUES ('card2', 'PrimaryEmail', 'jane@example.com')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mock_calendar_db(tmp_path: Path) -> Path:
    """Create a mock Thunderbird calendar database."""
    cal_dir = tmp_path / "calendar-data"
    cal_dir.mkdir()
    db_path = cal_dir / "local.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE cal_calendars (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE cal_events (
            id TEXT PRIMARY KEY,
            ical_component TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE cal_properties (
            item_id TEXT,
            key TEXT,
            value TEXT
        )
    """)
    # Insert test calendar
    conn.execute("INSERT INTO cal_calendars VALUES ('cal1', 'Personal')")
    conn.execute("INSERT INTO cal_calendars VALUES ('cal2', 'Work')")

    # Insert test event
    conn.execute("INSERT INTO cal_events VALUES ('event1', 'VEVENT')")
    conn.execute("INSERT INTO cal_properties VALUES ('event1', 'SUMMARY', 'Team Meeting')")
    conn.execute("INSERT INTO cal_properties VALUES ('event1', 'DTSTART', '20250120T100000Z')")
    conn.execute("INSERT INTO cal_properties VALUES ('event1', 'DTEND', '20250120T110000Z')")
    conn.execute("INSERT INTO cal_properties VALUES ('event1', 'LOCATION', 'Conference Room A')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mock_profile(tmp_path: Path, mock_messages_db: Path, mock_contacts_db: Path, mock_calendar_db: Path) -> ThunderbirdProfile:
    """Create a complete mock profile with all databases."""
    return ThunderbirdProfile(
        name="test",
        path=tmp_path,
        is_default=True,
    )


class TestThunderbirdClient:
    def test_client_no_profile_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client should raise if no profile is found."""
        monkeypatch.setattr("reos.thunderbird.get_default_profile", lambda: None)
        with pytest.raises(ThunderbirdError, match="No Thunderbird profile found"):
            ThunderbirdClient()

    def test_search_messages(self, mock_profile: ThunderbirdProfile) -> None:
        """Test message search."""
        client = ThunderbirdClient(profile=mock_profile)
        messages = client.search_messages("Test")

        assert len(messages) == 1
        assert messages[0].subject == "Test Subject"
        assert messages[0].sender == "sender@example.com"

    def test_search_messages_multiple_results(self, mock_profile: ThunderbirdProfile) -> None:
        """Test message search with broader query."""
        client = ThunderbirdClient(profile=mock_profile)
        messages = client.search_messages("example.com")

        assert len(messages) == 2

    def test_search_messages_no_results(self, mock_profile: ThunderbirdProfile) -> None:
        """Test message search with no matches."""
        client = ThunderbirdClient(profile=mock_profile)
        messages = client.search_messages("nonexistent")

        assert len(messages) == 0

    def test_list_folders(self, mock_profile: ThunderbirdProfile) -> None:
        """Test folder listing."""
        client = ThunderbirdClient(profile=mock_profile)
        folders = client.list_folders()

        assert len(folders) == 2
        folder_names = {f["name"] for f in folders}
        assert "Inbox" in folder_names
        assert "Sent" in folder_names

    def test_search_contacts(self, mock_profile: ThunderbirdProfile) -> None:
        """Test contact search."""
        client = ThunderbirdClient(profile=mock_profile)
        contacts = client.search_contacts("John")

        assert len(contacts) == 1
        assert contacts[0].display_name == "John Doe"
        assert contacts[0].primary_email == "john@example.com"
        assert contacts[0].organization == "Acme Corp"

    def test_search_contacts_by_email(self, mock_profile: ThunderbirdProfile) -> None:
        """Test contact search by email."""
        client = ThunderbirdClient(profile=mock_profile)
        contacts = client.search_contacts("jane@example")

        assert len(contacts) == 1
        assert contacts[0].display_name == "Jane Smith"

    def test_list_calendars(self, mock_profile: ThunderbirdProfile) -> None:
        """Test calendar listing."""
        client = ThunderbirdClient(profile=mock_profile)
        calendars = client.list_calendars()

        assert len(calendars) == 2
        names = {c["name"] for c in calendars}
        assert "Personal" in names
        assert "Work" in names

    def test_search_calendar(self, mock_profile: ThunderbirdProfile) -> None:
        """Test calendar event search."""
        client = ThunderbirdClient(profile=mock_profile)
        events = client.search_calendar("Meeting")

        assert len(events) == 1
        assert events[0].title == "Team Meeting"
        assert events[0].location == "Conference Room A"

    def test_search_calendar_no_query(self, mock_profile: ThunderbirdProfile) -> None:
        """Test calendar search without query returns all events."""
        client = ThunderbirdClient(profile=mock_profile)
        events = client.search_calendar(None)

        assert len(events) >= 1


class TestDataClasses:
    def test_email_message_frozen(self) -> None:
        msg = EmailMessage(
            id=1,
            folder_id=1,
            subject="Test",
            sender="a@b.com",
            recipients="c@d.com",
            date=None,
            snippet="preview",
        )
        with pytest.raises(AttributeError):
            msg.subject = "New Subject"  # type: ignore

    def test_contact_frozen(self) -> None:
        contact = Contact(
            id="1",
            display_name="Test",
            primary_email="test@example.com",
            secondary_email=None,
            phone_work=None,
            phone_home=None,
            phone_mobile=None,
            organization=None,
            notes=None,
        )
        with pytest.raises(AttributeError):
            contact.display_name = "New Name"  # type: ignore

    def test_calendar_event_frozen(self) -> None:
        event = CalendarEvent(
            id="1",
            title="Test",
            start_time=None,
            end_time=None,
            location=None,
            description=None,
            is_all_day=False,
        )
        with pytest.raises(AttributeError):
            event.title = "New Title"  # type: ignore
