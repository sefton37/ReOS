"""Tests for Thunderbird integration.

Tests the onboarding UX, multi-profile discovery, integration state management,
and conversational awareness features.
"""

from __future__ import annotations

import configparser
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reos.cairn.store import CairnStore
from reos.cairn.surfacing import get_integration_context
from reos.cairn.thunderbird import (
    ThunderbirdAccount,
    ThunderbirdBridge,
    ThunderbirdConfig,
    ThunderbirdIntegration,
    ThunderbirdProfile,
    check_thunderbird_installation,
    discover_all_profiles,
    get_accounts_in_profile,
    get_thunderbird_integration_state,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)


@pytest.fixture
def cairn_store(temp_db: Path) -> CairnStore:
    """Create a CAIRN store with temp database."""
    return CairnStore(temp_db)


@pytest.fixture
def temp_thunderbird_dir() -> Path:
    """Create a temporary Thunderbird profile structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / ".thunderbird"
        base.mkdir(parents=True)
        yield base


@pytest.fixture
def mock_profile(temp_thunderbird_dir: Path) -> Path:
    """Create a mock Thunderbird profile with prefs.js and address book."""
    profile = temp_thunderbird_dir / "abcd1234.default"
    profile.mkdir(parents=True)

    # Create prefs.js with mock account config
    prefs_content = '''
user_pref("mail.accountmanager.accounts", "account1,account2");
user_pref("mail.account.account1.identities", "id1");
user_pref("mail.account.account1.server", "server1");
user_pref("mail.identity.id1.useremail", "user@example.com");
user_pref("mail.identity.id1.fullName", "Test User");
user_pref("mail.server.server1.type", "imap");
user_pref("mail.server.server1.hostname", "mail.example.com");
user_pref("mail.account.account2.identities", "id2");
user_pref("mail.account.account2.server", "server2");
user_pref("mail.identity.id2.useremail", "work@company.com");
user_pref("mail.identity.id2.fullName", "Work Account");
user_pref("mail.server.server2.type", "imap");
user_pref("mail.server.server2.hostname", "mail.company.com");
'''
    (profile / "prefs.js").write_text(prefs_content)

    # Create address book
    (profile / "abook.sqlite").write_bytes(b"")

    # Create calendar data directory
    cal_dir = profile / "calendar-data"
    cal_dir.mkdir()
    (cal_dir / "local.sqlite").write_bytes(b"")

    return profile


@pytest.fixture
def profiles_ini(temp_thunderbird_dir: Path, mock_profile: Path) -> Path:
    """Create a profiles.ini file."""
    ini_path = temp_thunderbird_dir / "profiles.ini"

    config = configparser.ConfigParser()
    config["Profile0"] = {
        "Name": "default",
        "Path": mock_profile.name,
        "IsRelative": "1",
        "Default": "1",
    }
    config["Profile1"] = {
        "Name": "work",
        "Path": "work-profile",
        "IsRelative": "1",
        "Default": "0",
    }

    # Create work profile directory
    work_profile = temp_thunderbird_dir / "work-profile"
    work_profile.mkdir()
    (work_profile / "prefs.js").write_text(
        'user_pref("mail.accountmanager.accounts", "account3");\n'
        'user_pref("mail.account.account3.identities", "id3");\n'
        'user_pref("mail.identity.id3.useremail", "boss@company.com");\n'
        'user_pref("mail.identity.id3.fullName", "Boss Account");\n'
    )

    with open(ini_path, "w") as f:
        config.write(f)

    return ini_path


# =============================================================================
# Multi-Profile Discovery Tests
# =============================================================================


class TestThunderbirdInstallation:
    """Test installation detection."""

    def test_check_installed_when_in_path(self) -> None:
        """Returns True when thunderbird is in PATH."""
        with patch("shutil.which", return_value="/usr/bin/thunderbird"):
            installed, suggestion = check_thunderbird_installation()
            assert installed is True
            assert suggestion is None

    def test_check_not_installed_apt_system(self) -> None:
        """Returns apt install suggestion when not installed and apt available."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: "/usr/bin/apt" if cmd == "apt" else None
            with patch("pathlib.Path.exists", return_value=False):
                installed, suggestion = check_thunderbird_installation()
                assert installed is False
                assert "apt install" in suggestion

    def test_check_not_installed_dnf_system(self) -> None:
        """Returns dnf install suggestion on Fedora-like systems."""
        with patch("shutil.which") as mock_which:
            def which_side_effect(cmd):
                if cmd == "dnf":
                    return "/usr/bin/dnf"
                return None

            mock_which.side_effect = which_side_effect
            with patch("pathlib.Path.exists", return_value=False):
                installed, suggestion = check_thunderbird_installation()
                assert installed is False
                assert "dnf install" in suggestion


class TestProfileDiscovery:
    """Test multi-profile discovery."""

    def test_discover_profiles_from_ini(
        self, temp_thunderbird_dir: Path, profiles_ini: Path, mock_profile: Path
    ) -> None:
        """Discovers profiles from profiles.ini."""
        with patch(
            "reos.cairn.thunderbird._get_thunderbird_base_paths",
            return_value=[temp_thunderbird_dir],
        ):
            profiles = discover_all_profiles()

            assert len(profiles) == 2
            profile_names = {p.name for p in profiles}
            assert "default" in profile_names
            assert "work" in profile_names

    def test_discover_profiles_fallback_directory_scan(
        self, temp_thunderbird_dir: Path, mock_profile: Path
    ) -> None:
        """Falls back to directory scanning when no profiles.ini."""
        with patch(
            "reos.cairn.thunderbird._get_thunderbird_base_paths",
            return_value=[temp_thunderbird_dir],
        ):
            profiles = discover_all_profiles()

            # Should find the .default profile via directory scan
            assert len(profiles) >= 1
            assert any(".default" in p.path.name for p in profiles)

    def test_discover_default_profile_flag(
        self, temp_thunderbird_dir: Path, profiles_ini: Path, mock_profile: Path
    ) -> None:
        """Correctly identifies default profile."""
        with patch(
            "reos.cairn.thunderbird._get_thunderbird_base_paths",
            return_value=[temp_thunderbird_dir],
        ):
            profiles = discover_all_profiles()

            default_profiles = [p for p in profiles if p.is_default]
            assert len(default_profiles) == 1
            assert default_profiles[0].name == "default"


class TestAccountExtraction:
    """Test account extraction from profiles."""

    def test_get_accounts_from_prefs(self, mock_profile: Path) -> None:
        """Extracts accounts from prefs.js."""
        accounts = get_accounts_in_profile(mock_profile)

        assert len(accounts) == 2
        emails = {a.email for a in accounts}
        assert "user@example.com" in emails
        assert "work@company.com" in emails

    def test_get_account_details(self, mock_profile: Path) -> None:
        """Extracts full account details."""
        accounts = get_accounts_in_profile(mock_profile)

        user_account = next(a for a in accounts if a.email == "user@example.com")
        assert user_account.name == "Test User"
        assert user_account.type == "imap"
        assert user_account.server == "mail.example.com"

    def test_get_accounts_detects_calendars(self, mock_profile: Path) -> None:
        """Detects calendar data in profile."""
        accounts = get_accounts_in_profile(mock_profile)

        # At least one account should see the calendar
        assert any(len(a.calendars) > 0 for a in accounts)

    def test_get_accounts_detects_address_books(self, mock_profile: Path) -> None:
        """Detects address books in profile."""
        accounts = get_accounts_in_profile(mock_profile)

        # At least one account should see the address book
        assert any(len(a.address_books) > 0 for a in accounts)

    def test_get_accounts_empty_prefs(self, temp_thunderbird_dir: Path) -> None:
        """Returns empty list for profile without prefs.js."""
        empty_profile = temp_thunderbird_dir / "empty.default"
        empty_profile.mkdir()

        accounts = get_accounts_in_profile(empty_profile)
        assert accounts == []


class TestIntegrationState:
    """Test the full integration state function."""

    def test_integration_state_not_installed(self) -> None:
        """Returns not installed state when Thunderbird not found."""
        with patch(
            "reos.cairn.thunderbird.check_thunderbird_installation",
            return_value=(False, "sudo apt install thunderbird"),
        ):
            state = get_thunderbird_integration_state()

            assert state.installed is False
            assert state.install_suggestion == "sudo apt install thunderbird"
            assert len(state.profiles) == 0

    def test_integration_state_with_profiles(
        self, temp_thunderbird_dir: Path, profiles_ini: Path, mock_profile: Path
    ) -> None:
        """Returns profiles when Thunderbird is installed."""
        with patch(
            "reos.cairn.thunderbird.check_thunderbird_installation",
            return_value=(True, None),
        ):
            with patch(
                "reos.cairn.thunderbird._get_thunderbird_base_paths",
                return_value=[temp_thunderbird_dir],
            ):
                state = get_thunderbird_integration_state()

                assert state.installed is True
                assert state.install_suggestion is None
                assert len(state.profiles) >= 1


# =============================================================================
# Integration Preferences Store Tests
# =============================================================================


class TestIntegrationPreferencesStore:
    """Test integration preferences in CairnStore."""

    def test_get_nonexistent_integration(self, cairn_store: CairnStore) -> None:
        """Getting nonexistent integration returns None."""
        result = cairn_store.get_integration_state("nonexistent")
        assert result is None

    def test_set_integration_active(self, cairn_store: CairnStore) -> None:
        """set_integration_active stores active configuration."""
        config = {
            "active_profiles": ["default", "work"],
            "active_accounts": ["user@example.com"],
            "all_active": False,
        }

        cairn_store.set_integration_active("thunderbird", config)

        state = cairn_store.get_integration_state("thunderbird")
        assert state is not None
        assert state["state"] == "active"
        assert state["config"]["active_profiles"] == ["default", "work"]
        assert state["declined_at"] is None

    def test_set_integration_declined(self, cairn_store: CairnStore) -> None:
        """set_integration_declined marks as declined with timestamp."""
        cairn_store.set_integration_declined("thunderbird")

        state = cairn_store.get_integration_state("thunderbird")
        assert state is not None
        assert state["state"] == "declined"
        assert state["declined_at"] is not None

    def test_clear_integration_decline(self, cairn_store: CairnStore) -> None:
        """clear_integration_decline resets to not_configured."""
        cairn_store.set_integration_declined("thunderbird")
        cairn_store.clear_integration_decline("thunderbird")

        state = cairn_store.get_integration_state("thunderbird")
        assert state is not None
        assert state["state"] == "not_configured"
        assert state["declined_at"] is None
        assert state["config"] is None

    def test_is_integration_declined(self, cairn_store: CairnStore) -> None:
        """is_integration_declined returns correct boolean."""
        assert cairn_store.is_integration_declined("thunderbird") is False

        cairn_store.set_integration_declined("thunderbird")
        assert cairn_store.is_integration_declined("thunderbird") is True

        cairn_store.clear_integration_decline("thunderbird")
        assert cairn_store.is_integration_declined("thunderbird") is False

    def test_is_integration_active(self, cairn_store: CairnStore) -> None:
        """is_integration_active returns correct boolean."""
        assert cairn_store.is_integration_active("thunderbird") is False

        cairn_store.set_integration_active("thunderbird", {"active_profiles": ["default"]})
        assert cairn_store.is_integration_active("thunderbird") is True

    def test_record_integration_prompt(self, cairn_store: CairnStore) -> None:
        """record_integration_prompt stores last prompt time."""
        cairn_store.record_integration_prompt("thunderbird")

        state = cairn_store.get_integration_state("thunderbird")
        assert state is not None
        assert state["last_prompted"] is not None

    def test_update_existing_integration(self, cairn_store: CairnStore) -> None:
        """Can update an existing integration configuration."""
        # First configuration
        cairn_store.set_integration_active("thunderbird", {"active_profiles": ["default"]})

        # Update configuration
        cairn_store.set_integration_active(
            "thunderbird", {"active_profiles": ["default", "work"]}
        )

        state = cairn_store.get_integration_state("thunderbird")
        assert len(state["config"]["active_profiles"]) == 2

    def test_decline_clears_previous_active(self, cairn_store: CairnStore) -> None:
        """Declining after being active clears config but preserves decline."""
        cairn_store.set_integration_active("thunderbird", {"active_profiles": ["default"]})
        cairn_store.set_integration_declined("thunderbird")

        state = cairn_store.get_integration_state("thunderbird")
        assert state["state"] == "declined"
        # Config is preserved for potential re-enabling


class TestIntegrationPreferencesStateTransitions:
    """Test state transition edge cases."""

    def test_not_configured_to_active(self, cairn_store: CairnStore) -> None:
        """Transition from not_configured to active."""
        cairn_store.set_integration_active("thunderbird", {"active_profiles": []})
        assert cairn_store.is_integration_active("thunderbird") is True

    def test_not_configured_to_declined(self, cairn_store: CairnStore) -> None:
        """Transition from not_configured to declined."""
        cairn_store.set_integration_declined("thunderbird")
        assert cairn_store.is_integration_declined("thunderbird") is True

    def test_active_to_declined(self, cairn_store: CairnStore) -> None:
        """Transition from active to declined."""
        cairn_store.set_integration_active("thunderbird", {"profiles": ["default"]})
        cairn_store.set_integration_declined("thunderbird")

        assert cairn_store.is_integration_declined("thunderbird") is True
        assert cairn_store.is_integration_active("thunderbird") is False

    def test_declined_to_active(self, cairn_store: CairnStore) -> None:
        """Transition from declined back to active (user re-enables)."""
        cairn_store.set_integration_declined("thunderbird")
        cairn_store.set_integration_active("thunderbird", {"profiles": ["default"]})

        assert cairn_store.is_integration_active("thunderbird") is True
        assert cairn_store.is_integration_declined("thunderbird") is False


# =============================================================================
# Integration Context Tests (for LLM awareness)
# =============================================================================


class TestIntegrationContext:
    """Test integration context for LLM system prompts."""

    def test_context_no_store_path(self) -> None:
        """Returns generic message when no store path."""
        context = get_integration_context(store_path=None)
        assert "unknown" in context.lower()

    def test_context_not_configured(self, temp_db: Path) -> None:
        """Returns guidance when not configured."""
        store = CairnStore(temp_db)
        # Don't configure anything

        context = get_integration_context(store_path=temp_db)
        assert "not connected" in context.lower()
        assert "connect" in context.lower()

    def test_context_declined(self, temp_db: Path) -> None:
        """Returns respectful message when declined."""
        store = CairnStore(temp_db)
        store.set_integration_declined("thunderbird")

        context = get_integration_context(store_path=temp_db)
        assert "declined" in context.lower()
        assert "do not suggest" in context.lower()

    def test_context_active(self, temp_db: Path) -> None:
        """Returns connected info when active."""
        store = CairnStore(temp_db)
        store.set_integration_active(
            "thunderbird",
            {"active_profiles": ["default", "work"]},
        )

        context = get_integration_context(store_path=temp_db)
        assert "connected" in context.lower()
        assert "2 profile" in context.lower()


# =============================================================================
# ThunderbirdBridge Tests (existing functionality)
# =============================================================================


class TestThunderbirdBridge:
    """Test the existing ThunderbirdBridge class."""

    def test_config_autodetects_paths(self, mock_profile: Path) -> None:
        """ThunderbirdConfig auto-detects database paths."""
        config = ThunderbirdConfig(profile_path=mock_profile)

        assert config.address_book_path is not None
        assert config.address_book_path.name == "abook.sqlite"
        assert config.calendar_path is not None

    def test_bridge_has_address_book(self, mock_profile: Path) -> None:
        """Bridge correctly reports address book presence."""
        config = ThunderbirdConfig(profile_path=mock_profile)
        bridge = ThunderbirdBridge(config)

        assert bridge.has_address_book() is True

    def test_bridge_has_calendar(self, mock_profile: Path) -> None:
        """Bridge correctly reports calendar presence."""
        config = ThunderbirdConfig(profile_path=mock_profile)
        bridge = ThunderbirdBridge(config)

        assert bridge.has_calendar() is True

    def test_bridge_status(self, mock_profile: Path) -> None:
        """Bridge returns status information."""
        config = ThunderbirdConfig(profile_path=mock_profile)
        bridge = ThunderbirdBridge(config)

        status = bridge.get_status()
        assert "profile_path" in status
        assert "has_address_book" in status
        assert "has_calendar" in status


# =============================================================================
# Data Class Tests
# =============================================================================


class TestDataClasses:
    """Test the new data classes."""

    def test_thunderbird_account_creation(self) -> None:
        """ThunderbirdAccount can be created with all fields."""
        account = ThunderbirdAccount(
            id="account1",
            name="Test User",
            email="user@example.com",
            type="imap",
            server="mail.example.com",
            calendars=["local"],
            address_books=["abook"],
        )

        assert account.id == "account1"
        assert account.email == "user@example.com"
        assert len(account.calendars) == 1

    def test_thunderbird_account_defaults(self) -> None:
        """ThunderbirdAccount has sensible defaults."""
        account = ThunderbirdAccount(
            id="account1",
            name="Test",
            email="test@example.com",
            type="imap",
        )

        assert account.server is None
        assert account.calendars == []
        assert account.address_books == []

    def test_thunderbird_profile_creation(self, mock_profile: Path) -> None:
        """ThunderbirdProfile can be created."""
        profile = ThunderbirdProfile(
            name="default",
            path=mock_profile,
            is_default=True,
            accounts=[],
        )

        assert profile.name == "default"
        assert profile.is_default is True

    def test_thunderbird_integration_not_installed(self) -> None:
        """ThunderbirdIntegration represents not-installed state."""
        integration = ThunderbirdIntegration(
            installed=False,
            install_suggestion="sudo apt install thunderbird",
        )

        assert integration.installed is False
        assert integration.profiles == []
        assert integration.active_profiles == []
        assert integration.declined is False

    def test_thunderbird_integration_with_profiles(self, mock_profile: Path) -> None:
        """ThunderbirdIntegration represents installed state."""
        profile = ThunderbirdProfile(
            name="default",
            path=mock_profile,
            is_default=True,
        )

        integration = ThunderbirdIntegration(
            installed=True,
            profiles=[profile],
            active_profiles=["default"],
        )

        assert integration.installed is True
        assert len(integration.profiles) == 1


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_malformed_prefs_js(self, temp_thunderbird_dir: Path) -> None:
        """Handles malformed prefs.js gracefully."""
        profile = temp_thunderbird_dir / "malformed.default"
        profile.mkdir()
        (profile / "prefs.js").write_text("this is not valid prefs.js content!!!")

        accounts = get_accounts_in_profile(profile)
        assert accounts == []

    def test_missing_identity(self, temp_thunderbird_dir: Path) -> None:
        """Handles account without identity."""
        profile = temp_thunderbird_dir / "noidentity.default"
        profile.mkdir()
        (profile / "prefs.js").write_text(
            'user_pref("mail.accountmanager.accounts", "account1");\n'
            'user_pref("mail.account.account1.server", "server1");\n'
        )

        accounts = get_accounts_in_profile(profile)
        # Should still extract the account, just without email
        assert len(accounts) == 1
        assert accounts[0].email == ""

    def test_unicode_in_prefs(self, temp_thunderbird_dir: Path) -> None:
        """Handles unicode characters in prefs.js."""
        profile = temp_thunderbird_dir / "unicode.default"
        profile.mkdir()
        (profile / "prefs.js").write_text(
            'user_pref("mail.accountmanager.accounts", "account1");\n'
            'user_pref("mail.account.account1.identities", "id1");\n'
            'user_pref("mail.identity.id1.useremail", "usuario@ejemplo.com");\n'
            'user_pref("mail.identity.id1.fullName", "Usuário Español 日本語");\n',
            encoding="utf-8",
        )

        accounts = get_accounts_in_profile(profile)
        assert len(accounts) == 1
        assert "日本語" in accounts[0].name

    def test_empty_accounts_string(self, temp_thunderbird_dir: Path) -> None:
        """Handles empty accounts string."""
        profile = temp_thunderbird_dir / "empty.default"
        profile.mkdir()
        (profile / "prefs.js").write_text(
            'user_pref("mail.accountmanager.accounts", "");\n'
        )

        accounts = get_accounts_in_profile(profile)
        assert accounts == []

    def test_multiple_base_paths(self) -> None:
        """Discovers profiles across multiple base paths."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                # Create profile in first base
                base1 = Path(tmpdir1)
                profile1 = base1 / "abc.default"
                profile1.mkdir()
                (profile1 / "prefs.js").write_text("")

                # Create profile in second base
                base2 = Path(tmpdir2)
                profile2 = base2 / "xyz.default-release"
                profile2.mkdir()
                (profile2 / "prefs.js").write_text("")

                with patch(
                    "reos.cairn.thunderbird._get_thunderbird_base_paths",
                    return_value=[base1, base2],
                ):
                    profiles = discover_all_profiles()
                    assert len(profiles) == 2
