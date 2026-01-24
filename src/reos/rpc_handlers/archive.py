"""Archive and conversation RPC handlers.

These handlers manage conversation archiving with LLM-driven
knowledge extraction and archive management.
"""

from __future__ import annotations

from typing import Any

from reos.db import Database

from . import RpcError


# =============================================================================
# Conversation Archive Handlers
# =============================================================================


def handle_conversation_archive_preview(
    db: Database,
    *,
    conversation_id: str,
    auto_link: bool = True,
) -> dict[str, Any]:
    """Preview archive extraction before saving."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    preview = service.preview_archive(
        conversation_id,
        auto_link=auto_link,
    )
    return preview.to_dict()


def handle_conversation_archive_confirm(
    db: Database,
    *,
    conversation_id: str,
    title: str,
    summary: str,
    act_id: str | None = None,
    knowledge_entries: list[dict[str, str]],
    additional_notes: str = "",
    rating: int | None = None,
) -> dict[str, Any]:
    """Archive a conversation with user-reviewed data."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    result = service.archive_with_review(
        conversation_id,
        title=title,
        summary=summary,
        act_id=act_id,
        knowledge_entries=knowledge_entries,
        additional_notes=additional_notes,
        rating=rating,
    )
    return result.to_dict()


def handle_conversation_archive(
    db: Database,
    *,
    conversation_id: str,
    act_id: str | None = None,
    auto_link: bool = True,
    extract_knowledge: bool = True,
) -> dict[str, Any]:
    """Archive a conversation with LLM-driven knowledge extraction."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    result = service.archive_conversation(
        conversation_id,
        act_id=act_id,
        auto_link=auto_link,
        extract_knowledge=extract_knowledge,
    )
    return result.to_dict()


def handle_conversation_delete(
    db: Database,
    *,
    conversation_id: str,
    archive_first: bool = False,
) -> dict[str, Any]:
    """Delete a conversation, optionally archiving first."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    return service.delete_conversation(
        conversation_id,
        archive_first=archive_first,
    )


# =============================================================================
# Archive Management Handlers
# =============================================================================


def handle_archive_list(
    db: Database,
    *,
    act_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List conversation archives."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    archives = service.list_archives(act_id=act_id, limit=limit)
    return {"archives": archives}


def handle_archive_get(
    db: Database,
    *,
    archive_id: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Get a specific archive with full messages."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    archive = service.get_archive(archive_id, act_id=act_id)
    if not archive:
        raise RpcError(code=-32602, message=f"Archive not found: {archive_id}")
    return archive


def handle_archive_assess(
    db: Database,
    *,
    archive_id: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Assess the quality of an archive using LLM."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    assessment = service.assess_archive_quality(archive_id, act_id=act_id)
    return assessment.to_dict()


def handle_archive_feedback(
    db: Database,
    *,
    archive_id: str,
    rating: int,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Submit user feedback on archive quality."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    return service.submit_user_feedback(archive_id, rating, feedback)


def handle_archive_learning_stats(db: Database) -> dict[str, Any]:
    """Get learning statistics for archive quality."""
    from reos.services.archive_service import ArchiveService

    service = ArchiveService(db)
    return service.get_learning_stats()
