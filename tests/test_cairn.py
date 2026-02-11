"""Tests for CAIRN module.

Tests the attention minder's core functionality:
- Metadata store (CRUD, kanban states, priorities)
- Activity tracking
- Contact links
- Surfacing algorithms
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from reos.cairn.models import (
    ActivityType,
    CairnMetadata,
    ContactRelationship,
    KanbanState,
    SurfaceContext,
)
from reos.cairn.store import CairnStore
from reos.cairn.surfacing import CairnSurfacer

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
def surfacer(cairn_store: CairnStore) -> CairnSurfacer:
    """Create a surfacer with the test store."""
    return CairnSurfacer(cairn_store)


# =============================================================================
# Store Tests - Metadata CRUD
# =============================================================================


class TestMetadataCRUD:
    """Test metadata create, read, update, delete operations."""

    def test_get_metadata_nonexistent(self, cairn_store: CairnStore) -> None:
        """Getting nonexistent metadata returns None."""
        result = cairn_store.get_metadata("act", "nonexistent")
        assert result is None

    def test_get_or_create_creates_new(self, cairn_store: CairnStore) -> None:
        """get_or_create creates new metadata if not exists."""
        metadata = cairn_store.get_or_create_metadata("act", "test-act-1")

        assert metadata.entity_type == "act"
        assert metadata.entity_id == "test-act-1"
        assert metadata.kanban_state == KanbanState.BACKLOG
        assert metadata.touch_count == 0

    def test_get_or_create_returns_existing(self, cairn_store: CairnStore) -> None:
        """get_or_create returns existing metadata."""
        # Create first
        cairn_store.get_or_create_metadata("act", "test-act-1")

        # Touch it to change touch_count
        cairn_store.touch("act", "test-act-1")

        # Get again
        metadata = cairn_store.get_or_create_metadata("act", "test-act-1")
        assert metadata.touch_count == 1

    def test_save_metadata_updates(self, cairn_store: CairnStore) -> None:
        """save_metadata updates existing metadata."""
        metadata = cairn_store.get_or_create_metadata("act", "test-act-1")
        metadata.priority = 5
        metadata.priority_reason = "Urgent"
        cairn_store.save_metadata(metadata)

        # Retrieve and verify
        retrieved = cairn_store.get_metadata("act", "test-act-1")
        assert retrieved is not None
        assert retrieved.priority == 5
        assert retrieved.priority_reason == "Urgent"

    def test_delete_metadata(self, cairn_store: CairnStore) -> None:
        """delete_metadata removes metadata."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        deleted = cairn_store.delete_metadata("act", "test-act-1")
        assert deleted is True

        # Verify gone
        result = cairn_store.get_metadata("act", "test-act-1")
        assert result is None

    def test_delete_nonexistent_returns_false(self, cairn_store: CairnStore) -> None:
        """delete_metadata returns False for nonexistent."""
        deleted = cairn_store.delete_metadata("act", "nonexistent")
        assert deleted is False


# =============================================================================
# Store Tests - Kanban States
# =============================================================================


class TestKanbanStates:
    """Test kanban state management."""

    def test_set_kanban_state(self, cairn_store: CairnStore) -> None:
        """set_kanban_state changes state."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        metadata = cairn_store.set_kanban_state("act", "test-act-1", KanbanState.ACTIVE)
        assert metadata.kanban_state == KanbanState.ACTIVE

    def test_set_waiting_state_records_waiting_on(self, cairn_store: CairnStore) -> None:
        """WAITING state records who we're waiting on."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        metadata = cairn_store.set_kanban_state(
            "act", "test-act-1", KanbanState.WAITING, waiting_on="Client feedback"
        )

        assert metadata.kanban_state == KanbanState.WAITING
        assert metadata.waiting_on == "Client feedback"
        assert metadata.waiting_since is not None

    def test_leaving_waiting_clears_waiting_info(self, cairn_store: CairnStore) -> None:
        """Leaving WAITING state clears waiting_on."""
        cairn_store.get_or_create_metadata("act", "test-act-1")
        cairn_store.set_kanban_state("act", "test-act-1", KanbanState.WAITING, waiting_on="Client")

        metadata = cairn_store.set_kanban_state("act", "test-act-1", KanbanState.ACTIVE)

        assert metadata.waiting_on is None
        assert metadata.waiting_since is None

    def test_mark_completed(self, cairn_store: CairnStore) -> None:
        """mark_completed sets state to DONE."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        metadata = cairn_store.mark_completed("act", "test-act-1")
        assert metadata.kanban_state == KanbanState.DONE


# =============================================================================
# Store Tests - Priority
# =============================================================================


class TestPriority:
    """Test priority management."""

    def test_set_priority_valid(self, cairn_store: CairnStore) -> None:
        """set_priority with valid value works."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        metadata = cairn_store.set_priority("act", "test-act-1", 5, reason="Critical deadline")

        assert metadata.priority == 5
        assert metadata.priority_reason == "Critical deadline"
        assert metadata.priority_set_at is not None

    def test_set_priority_invalid_raises(self, cairn_store: CairnStore) -> None:
        """set_priority with invalid value raises."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        with pytest.raises(ValueError, match="Priority must be between 1 and 5"):
            cairn_store.set_priority("act", "test-act-1", 10)

    def test_clear_priority(self, cairn_store: CairnStore) -> None:
        """clear_priority removes priority."""
        cairn_store.get_or_create_metadata("act", "test-act-1")
        cairn_store.set_priority("act", "test-act-1", 5)

        metadata = cairn_store.clear_priority("act", "test-act-1")

        assert metadata.priority is None
        assert metadata.priority_reason is None


# =============================================================================
# Store Tests - Activity Tracking
# =============================================================================


class TestActivityTracking:
    """Test activity/touch tracking."""

    def test_touch_increments_count(self, cairn_store: CairnStore) -> None:
        """touch increments touch_count."""
        cairn_store.get_or_create_metadata("act", "test-act-1")

        cairn_store.touch("act", "test-act-1")
        cairn_store.touch("act", "test-act-1")
        cairn_store.touch("act", "test-act-1")

        metadata = cairn_store.get_metadata("act", "test-act-1")
        assert metadata is not None
        assert metadata.touch_count == 3

    def test_touch_updates_last_touched(self, cairn_store: CairnStore) -> None:
        """touch updates last_touched timestamp."""
        metadata = cairn_store.get_or_create_metadata("act", "test-act-1")
        original_touched = metadata.last_touched

        # Touch again
        updated = cairn_store.touch("act", "test-act-1")

        assert updated.last_touched >= original_touched

    def test_touch_logs_activity(self, cairn_store: CairnStore) -> None:
        """touch creates activity log entry."""
        cairn_store.touch("act", "test-act-1", activity_type=ActivityType.EDITED)

        log = cairn_store.get_activity_log(entity_type="act", entity_id="test-act-1")
        assert len(log) >= 1
        assert log[0].activity_type == ActivityType.EDITED


# =============================================================================
# Store Tests - Contact Links
# =============================================================================


class TestContactLinks:
    """Test contact knowledge graph."""

    def test_link_contact(self, cairn_store: CairnStore) -> None:
        """link_contact creates a link."""
        link = cairn_store.link_contact(
            contact_id="contact-1",
            entity_type="act",
            entity_id="test-act-1",
            relationship=ContactRelationship.COLLABORATOR,
            notes="Working on this together",
        )

        assert link.contact_id == "contact-1"
        assert link.relationship == ContactRelationship.COLLABORATOR

    def test_get_contact_links(self, cairn_store: CairnStore) -> None:
        """get_contact_links returns links."""
        cairn_store.link_contact("c1", "act", "a1", ContactRelationship.OWNER)
        cairn_store.link_contact("c1", "act", "a2", ContactRelationship.COLLABORATOR)

        links = cairn_store.get_contact_links(contact_id="c1")
        assert len(links) == 2

    def test_unlink_contact(self, cairn_store: CairnStore) -> None:
        """unlink_contact removes link."""
        link = cairn_store.link_contact("c1", "act", "a1", ContactRelationship.OWNER)

        removed = cairn_store.unlink_contact(link.link_id)
        assert removed is True

        links = cairn_store.get_contact_links(contact_id="c1")
        assert len(links) == 0


# =============================================================================
# Store Tests - Time Management
# =============================================================================


class TestTimeManagement:
    """Test due dates and deferral."""

    def test_set_due_date(self, cairn_store: CairnStore) -> None:
        """set_due_date works."""
        cairn_store.get_or_create_metadata("act", "test-act-1")
        due = datetime.now() + timedelta(days=7)

        metadata = cairn_store.set_due_date("act", "test-act-1", due)
        assert metadata.due_date is not None

    def test_defer_until(self, cairn_store: CairnStore) -> None:
        """defer_until sets defer date and moves to someday."""
        cairn_store.get_or_create_metadata("act", "test-act-1")
        cairn_store.set_kanban_state("act", "test-act-1", KanbanState.ACTIVE)

        defer_date = datetime.now() + timedelta(days=14)
        metadata = cairn_store.defer_until("act", "test-act-1", defer_date)

        assert metadata.defer_until is not None
        assert metadata.kanban_state == KanbanState.SOMEDAY


# =============================================================================
# Store Tests - Listing and Filtering
# =============================================================================


class TestListingFilters:
    """Test list_metadata with filters."""

    def test_list_by_entity_type(self, cairn_store: CairnStore) -> None:
        """list_metadata filters by entity_type."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.get_or_create_metadata("scene", "s1")
        cairn_store.get_or_create_metadata("scene", "b1")

        acts = cairn_store.list_metadata(entity_type="act")
        assert len(acts) == 1
        assert acts[0].entity_type == "act"

    def test_list_by_kanban_state(self, cairn_store: CairnStore) -> None:
        """list_metadata filters by kanban_state."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.ACTIVE)

        cairn_store.get_or_create_metadata("act", "a2")
        cairn_store.set_kanban_state("act", "a2", KanbanState.BACKLOG)

        active = cairn_store.list_metadata(kanban_state=KanbanState.ACTIVE)
        assert len(active) == 1
        assert active[0].entity_id == "a1"

    def test_list_with_priority(self, cairn_store: CairnStore) -> None:
        """list_metadata filters by has_priority."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_priority("act", "a1", 5)

        cairn_store.get_or_create_metadata("act", "a2")

        with_priority = cairn_store.list_metadata(has_priority=True)
        assert len(with_priority) == 1
        assert with_priority[0].entity_id == "a1"


# =============================================================================
# Surfacing Tests
# =============================================================================


class TestSurfacing:
    """Test surfacing algorithms."""

    def test_surface_next_returns_list(
        self, surfacer: CairnSurfacer, cairn_store: CairnStore
    ) -> None:
        """surface_next returns a list of surfaced items."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.ACTIVE)
        cairn_store.set_priority("act", "a1", 5)

        result = surfacer.surface_next()

        assert isinstance(result, list)
        # May or may not contain items depending on context
        if result:
            assert hasattr(result[0], "entity_id")

    def test_surface_today_returns_list(
        self, surfacer: CairnSurfacer, cairn_store: CairnStore
    ) -> None:
        """surface_today returns a list."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.ACTIVE)

        results = surfacer.surface_today()

        assert isinstance(results, list)

    def test_surface_stale_returns_old_items(
        self, surfacer: CairnSurfacer, cairn_store: CairnStore
    ) -> None:
        """surface_stale returns items not touched recently."""
        # Create an item and set to ACTIVE state
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.ACTIVE)

        # Re-fetch after state change (set_kanban_state saves a fresh copy)
        metadata = cairn_store.get_metadata("act", "a1")
        assert metadata is not None

        # Manually set last_touched to 8 days ago (active items stale after 3 days)
        metadata.last_touched = datetime.now() - timedelta(days=8)
        cairn_store.save_metadata(metadata)

        # surface_stale uses days parameter, not stale_days
        results = surfacer.surface_stale(days=3)

        assert len(results) >= 1
        assert any(r.entity_id == "a1" for r in results)

    def test_surface_waiting_returns_waiting_items(
        self, surfacer: CairnSurfacer, cairn_store: CairnStore
    ) -> None:
        """surface_waiting returns items in WAITING state."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.WAITING, waiting_on="Client")

        results = surfacer.surface_waiting()

        assert len(results) >= 1
        assert any(r.entity_id == "a1" for r in results)

    def test_surface_needs_priority(self, surfacer: CairnSurfacer, cairn_store: CairnStore) -> None:
        """surface_needs_priority returns active items without priority."""
        cairn_store.get_or_create_metadata("act", "a1")
        cairn_store.set_kanban_state("act", "a1", KanbanState.ACTIVE)
        # No priority set

        results = surfacer.surface_needs_priority()

        assert len(results) >= 1
        assert any(r.entity_id == "a1" for r in results)


# =============================================================================
# Model Tests
# =============================================================================


class TestModels:
    """Test CAIRN model classes."""

    def test_cairn_metadata_is_stale_active(self) -> None:
        """is_stale for ACTIVE items (stale after 3 days)."""
        metadata = CairnMetadata(
            entity_type="act",
            entity_id="a1",
            kanban_state=KanbanState.ACTIVE,
            last_touched=datetime.now() - timedelta(days=5),
        )
        assert metadata.is_stale is True

        metadata.last_touched = datetime.now()
        assert metadata.is_stale is False

    def test_cairn_metadata_is_stale_backlog(self) -> None:
        """is_stale for BACKLOG items (stale after 14 days)."""
        metadata = CairnMetadata(
            entity_type="act",
            entity_id="a1",
            kanban_state=KanbanState.BACKLOG,
            last_touched=datetime.now() - timedelta(days=8),
        )
        # Backlog items are not stale until 14 days
        assert metadata.is_stale is False

        metadata.last_touched = datetime.now() - timedelta(days=15)
        assert metadata.is_stale is True

    def test_cairn_metadata_needs_priority(self) -> None:
        """needs_priority property works correctly."""
        metadata = CairnMetadata(
            entity_type="act",
            entity_id="a1",
            kanban_state=KanbanState.ACTIVE,
            priority=None,
        )
        assert metadata.needs_priority is True

        metadata.priority = 3
        assert metadata.needs_priority is False

    def test_kanban_state_values(self) -> None:
        """KanbanState enum has expected values."""
        assert KanbanState.ACTIVE.value == "active"
        assert KanbanState.BACKLOG.value == "backlog"
        assert KanbanState.WAITING.value == "waiting"
        assert KanbanState.SOMEDAY.value == "someday"
        assert KanbanState.DONE.value == "done"

    def test_surface_context_has_max_items(self) -> None:
        """SurfaceContext has max_items attribute."""
        context = SurfaceContext()
        # Check max_items exists (default should be 5)
        assert hasattr(context, "max_items")
        assert context.max_items == 5

    def test_activity_type_values(self) -> None:
        """ActivityType enum has expected values."""
        assert ActivityType.VIEWED.value == "viewed"
        assert ActivityType.EDITED.value == "edited"
        assert ActivityType.COMPLETED.value == "completed"
        assert ActivityType.CREATED.value == "created"
        assert ActivityType.TOOL_EXECUTED.value == "tool_executed"

    def test_contact_relationship_values(self) -> None:
        """ContactRelationship enum has expected values."""
        assert ContactRelationship.OWNER.value == "owner"
        assert ContactRelationship.COLLABORATOR.value == "collaborator"
        assert ContactRelationship.STAKEHOLDER.value == "stakeholder"
        assert ContactRelationship.WAITING_ON.value == "waiting_on"

    def test_cairn_metadata_to_dict(self) -> None:
        """CairnMetadata serializes to dict correctly."""
        meta = CairnMetadata(
            entity_type="act",
            entity_id="a1",
            kanban_state=KanbanState.ACTIVE,
            priority=3,
            priority_reason="Important",
        )
        d = meta.to_dict()
        assert d["entity_type"] == "act"
        assert d["entity_id"] == "a1"
        assert d["kanban_state"] == "active"
        assert d["priority"] == 3

    def test_cairn_metadata_from_dict(self) -> None:
        """CairnMetadata deserializes from dict correctly."""
        data = {
            "entity_type": "scene",
            "entity_id": "s1",
            "kanban_state": "waiting",
            "touch_count": 5,
            "last_touched": "2024-01-15T10:00:00",
        }
        meta = CairnMetadata.from_dict(data)
        assert meta.entity_type == "scene"
        assert meta.kanban_state == KanbanState.WAITING
        assert meta.touch_count == 5

    def test_activity_log_entry_to_dict(self) -> None:
        """ActivityLogEntry serializes correctly."""
        from reos.cairn.models import ActivityLogEntry

        entry = ActivityLogEntry(
            log_id="log1",
            entity_type="act",
            entity_id="a1",
            activity_type=ActivityType.EDITED,
            timestamp=datetime.now(),
            details={"field": "title"},
        )
        d = entry.to_dict()
        assert d["log_id"] == "log1"
        assert d["activity_type"] == "edited"
        assert d["details"]["field"] == "title"

    def test_contact_link_to_dict_and_from_dict(self) -> None:
        """ContactLink round-trips through dict."""
        from reos.cairn.models import ContactLink

        link = ContactLink(
            link_id="link1",
            contact_id="contact1",
            entity_type="act",
            entity_id="a1",
            relationship=ContactRelationship.COLLABORATOR,
            created_at=datetime.now(),
            notes="Working together",
        )
        d = link.to_dict()
        restored = ContactLink.from_dict(d)
        assert restored.link_id == link.link_id
        assert restored.relationship == ContactRelationship.COLLABORATOR

    def test_undo_context_to_dict_and_from_dict(self) -> None:
        """UndoContext round-trips through dict."""
        from reos.cairn.models import UndoContext

        ctx = UndoContext(
            tool_name="cairn_set_priority",
            reverse_tool="cairn_clear_priority",
            reverse_args={"entity_type": "act", "entity_id": "a1"},
            before_state={"priority": None},
            after_state={"priority": 5},
            description="Set priority to 5",
            reversible=True,
        )
        d = ctx.to_dict()
        restored = UndoContext.from_dict(d)
        assert restored.tool_name == "cairn_set_priority"
        assert restored.reversible is True

    def test_pending_confirmation_properties(self) -> None:
        """PendingConfirmation properties work correctly."""
        from reos.cairn.models import PendingConfirmation

        conf = PendingConfirmation(
            confirmation_id="conf1",
            tool_name="cairn_delete_act",
            tool_args={"act_id": "a1"},
            description="Delete Act 'Test'",
            warning="This cannot be undone",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=5),
        )
        assert conf.is_expired is False
        assert conf.is_actionable is True

        # After expiry
        conf.expires_at = datetime.now() - timedelta(minutes=1)
        assert conf.is_expired is True
        assert conf.is_actionable is False

    def test_pending_confirmation_to_dict_from_dict(self) -> None:
        """PendingConfirmation round-trips through dict."""
        from reos.cairn.models import PendingConfirmation

        conf = PendingConfirmation(
            confirmation_id="conf1",
            tool_name="cairn_delete_act",
            tool_args={"act_id": "a1"},
            description="Delete Act",
            warning="Cannot undo",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=5),
            confirmed=True,
        )
        d = conf.to_dict()
        restored = PendingConfirmation.from_dict(d)
        assert restored.confirmation_id == "conf1"
        assert restored.confirmed is True

    def test_surfaced_item_fields(self) -> None:
        """SurfacedItem has expected fields."""
        from reos.cairn.models import SurfacedItem

        item = SurfacedItem(
            entity_type="act",
            entity_id="a1",
            title="Test Act",
            reason="Due soon",
            urgency="high",
            due_in_days=2,
            act_id="a1",
            act_title="Test Act",
        )
        assert item.entity_type == "act"
        assert item.urgency == "high"
        assert item.due_in_days == 2

    def test_tools_requiring_confirmation(self) -> None:
        """TOOLS_REQUIRING_CONFIRMATION has expected tools."""
        from reos.cairn.models import TOOLS_REQUIRING_CONFIRMATION

        assert "cairn_delete_act" in TOOLS_REQUIRING_CONFIRMATION
        assert "cairn_delete_scene" in TOOLS_REQUIRING_CONFIRMATION


# =============================================================================
# Store Edge Cases Tests
# =============================================================================


class TestStoreEdgeCases:
    """Test edge cases and error handling in CairnStore."""

    def test_concurrent_metadata_updates_last_wins(self, cairn_store: CairnStore) -> None:
        """Concurrent metadata updates - last save wins."""
        # Create metadata
        meta1 = cairn_store.get_or_create_metadata("act", "concurrent-test")
        meta2 = cairn_store.get_metadata("act", "concurrent-test")

        assert meta1 is not None
        assert meta2 is not None

        # Both modify the same entity
        meta1.priority = 5
        meta2.priority = 3

        # Save in sequence
        cairn_store.save_metadata(meta1)
        cairn_store.save_metadata(meta2)

        # Last save wins
        result = cairn_store.get_metadata("act", "concurrent-test")
        assert result is not None
        assert result.priority == 3

    def test_orphaned_activity_log_cleanup(self, cairn_store: CairnStore) -> None:
        """Activity logs for deleted metadata are orphaned (soft reference)."""
        # Create metadata and touch it
        cairn_store.get_or_create_metadata("item", "orphan-test")
        cairn_store.touch("item", "orphan-test", ActivityType.EDITED)
        cairn_store.touch("item", "orphan-test", ActivityType.VIEWED)

        # Verify activity log exists
        log = cairn_store.get_activity_log("item", "orphan-test")
        assert len(log) >= 2

        # Delete metadata
        cairn_store.delete_metadata("item", "orphan-test")

        # Metadata gone
        assert cairn_store.get_metadata("item", "orphan-test") is None

        # Activity log may still exist (depends on CASCADE policy)
        # This is expected behavior - logs are historical record

    def test_large_batch_operations(self, cairn_store: CairnStore) -> None:
        """Test handling many metadata records."""
        # Create many items
        for i in range(100):
            cairn_store.get_or_create_metadata("item", f"batch-{i}")
            cairn_store.set_kanban_state("item", f"batch-{i}", KanbanState.ACTIVE)
            cairn_store.set_priority("item", f"batch-{i}", i % 5 + 1)

        # Query all active items
        active = cairn_store.list_metadata(entity_type="item", kanban_state=KanbanState.ACTIVE)
        assert len(active) == 100

    def test_metadata_with_null_optional_fields(self, cairn_store: CairnStore) -> None:
        """Metadata with all optional fields as None works correctly."""
        meta = cairn_store.get_or_create_metadata("act", "minimal")

        # All optional fields should be None/default
        assert meta.priority is None
        assert meta.priority_reason is None
        assert meta.due_date is None
        assert meta.defer_until is None
        assert meta.waiting_on is None

        # Save and retrieve should work
        cairn_store.save_metadata(meta)
        retrieved = cairn_store.get_metadata("act", "minimal")
        assert retrieved is not None

    def test_special_characters_in_entity_id(self, cairn_store: CairnStore) -> None:
        """Entity IDs with special characters work."""
        special_ids = [
            "test-with-dashes",
            "test_with_underscores",
            "test.with.dots",
            "test:with:colons",
            "test/with/slashes",  # URL-like
            "test123numbers",
        ]

        for entity_id in special_ids:
            meta = cairn_store.get_or_create_metadata("item", entity_id)
            assert meta.entity_id == entity_id

            cairn_store.touch("item", entity_id)
            retrieved = cairn_store.get_metadata("item", entity_id)
            assert retrieved is not None
            assert retrieved.touch_count >= 1

    def test_unicode_in_reason_field(self, cairn_store: CairnStore) -> None:
        """Unicode characters in priority_reason field work."""
        meta = cairn_store.get_or_create_metadata("act", "unicode-test")
        meta.priority_reason = "Important for \u65e5\u672c\u8a9e project \U0001f680"

        cairn_store.save_metadata(meta)

        retrieved = cairn_store.get_metadata("act", "unicode-test")
        assert retrieved is not None
        assert "\u65e5\u672c\u8a9e" in retrieved.priority_reason

    def test_very_long_reason_field(self, cairn_store: CairnStore) -> None:
        """Very long priority_reason field is handled."""
        meta = cairn_store.get_or_create_metadata("item", "long-reason")
        meta.priority_reason = "x" * 5000  # 5K characters

        cairn_store.save_metadata(meta)

        retrieved = cairn_store.get_metadata("item", "long-reason")
        assert retrieved is not None
        assert len(retrieved.priority_reason) == 5000

    def test_priority_boundary_values(self, cairn_store: CairnStore) -> None:
        """Priority boundary values (1-5) are handled."""
        # Valid priorities
        for priority in [1, 2, 3, 4, 5]:
            cairn_store.get_or_create_metadata("item", f"priority-{priority}")
            cairn_store.set_priority("item", f"priority-{priority}", priority)

            meta = cairn_store.get_metadata("item", f"priority-{priority}")
            assert meta is not None
            assert meta.priority == priority

    def test_kanban_state_transitions(self, cairn_store: CairnStore) -> None:
        """All kanban state transitions work."""
        states = [
            KanbanState.BACKLOG,
            KanbanState.ACTIVE,
            KanbanState.WAITING,
            KanbanState.SOMEDAY,
            KanbanState.DONE,
        ]

        cairn_store.get_or_create_metadata("act", "state-test")

        # Transition through all states
        for state in states:
            cairn_store.set_kanban_state("act", "state-test", state)
            meta = cairn_store.get_metadata("act", "state-test")
            assert meta is not None
            assert meta.kanban_state == state

    def test_delete_nonexistent_metadata(self, cairn_store: CairnStore) -> None:
        """Deleting nonexistent metadata doesn't raise."""
        # Should not raise
        result = cairn_store.delete_metadata("act", "does-not-exist")
        # Returns False or handles gracefully
        assert result is False or result is None
