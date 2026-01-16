"""Thunderbird Bridge Client for CAIRN.

HTTP client for the Talking Rock Bridge add-on that enables ReOS
to create/update/delete calendar events in Thunderbird.

The add-on runs an HTTP server on localhost:19192.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default port for the Talking Rock Bridge add-on
BRIDGE_PORT = 19192
BRIDGE_HOST = "127.0.0.1"
BRIDGE_BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"

# Placeholder date for Beats without a specific date (Dec 31, 2099)
PLACEHOLDER_DATE = datetime(2099, 12, 31, 12, 0, 0)


@dataclass
class ThunderbirdCalendar:
    """A calendar from Thunderbird."""

    id: str
    name: str
    type: str
    color: str | None = None


@dataclass
class ThunderbirdEventResult:
    """Result from creating or updating an event."""

    id: str
    calendar_id: str
    updated: bool = False
    deleted: bool = False
    not_found: bool = False


@dataclass
class ThunderbirdEvent:
    """A calendar event from Thunderbird."""

    id: str
    title: str
    start_date: datetime | None
    end_date: datetime | None
    description: str
    location: str
    all_day: bool
    calendar_id: str | None


class ThunderbirdBridgeClient:
    """HTTP client for the Talking Rock Bridge Thunderbird add-on.

    This client communicates with the add-on's HTTP server to
    create, read, update, and delete calendar events.

    The client handles graceful degradation - if the add-on is not
    running, operations return None or False without raising errors
    (unless explicitly requested).
    """

    def __init__(
        self,
        base_url: str = BRIDGE_BASE_URL,
        timeout: float = 5.0,
    ):
        """Initialize the bridge client.

        Args:
            base_url: Base URL for the add-on's HTTP server.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "ThunderbirdBridgeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def is_available(self) -> bool:
        """Check if the Talking Rock Bridge add-on is running.

        Returns:
            True if the add-on is responding to health checks.
        """
        try:
            response = self._get_client().get("/health")
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception as e:
            logger.debug("Bridge health check failed: %s", e)
            return False

    def health_check(self) -> dict[str, Any] | None:
        """Get health status and default calendar info.

        Returns:
            Health info dict, or None if add-on not available.
        """
        try:
            response = self._get_client().get("/health")
            if response.status_code == 200:
                return response.json()
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
        except Exception as e:
            logger.debug("Bridge health check failed: %s", e)
            return None

    def list_calendars(self) -> list[ThunderbirdCalendar]:
        """List all writable calendars.

        Returns:
            List of calendars, or empty list if add-on not available.
        """
        try:
            response = self._get_client().get("/calendars")
            if response.status_code == 200:
                data = response.json()
                return [
                    ThunderbirdCalendar(
                        id=cal["id"],
                        name=cal["name"],
                        type=cal["type"],
                        color=cal.get("color"),
                    )
                    for cal in data.get("calendars", [])
                ]
            return []
        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except Exception as e:
            logger.debug("Failed to list calendars: %s", e)
            return []

    def get_default_calendar(self) -> ThunderbirdCalendar | None:
        """Get the default calendar for creating events.

        Returns:
            Default calendar, or None if not available.
        """
        health = self.health_check()
        if health and health.get("defaultCalendar"):
            cal = health["defaultCalendar"]
            return ThunderbirdCalendar(
                id=cal["id"],
                name=cal["name"],
                type=cal["type"],
            )
        return None

    def create_event(
        self,
        title: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        all_day: bool = False,
        calendar_id: str | None = None,
    ) -> ThunderbirdEventResult | None:
        """Create a calendar event in Thunderbird.

        If no date is specified, uses the placeholder date (Dec 31, 2099).

        Args:
            title: Event title.
            start_date: Start datetime (default: placeholder date).
            end_date: End datetime (default: start_date + 1 hour or all day).
            description: Event description.
            location: Event location.
            all_day: Whether this is an all-day event.
            calendar_id: Calendar ID (uses default if not specified).

        Returns:
            Event result with ID, or None if add-on not available.
        """
        # Use placeholder date if no date specified
        if start_date is None:
            start_date = PLACEHOLDER_DATE
            all_day = True

        if end_date is None:
            if all_day:
                # For all-day events, end is start + 1 day
                end_date = start_date.replace(hour=23, minute=59, second=59)
            else:
                # For timed events, default to 1 hour duration
                from datetime import timedelta
                end_date = start_date + timedelta(hours=1)

        payload: dict[str, Any] = {
            "title": title,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "allDay": all_day,
        }

        if description:
            payload["description"] = description
        if location:
            payload["location"] = location
        if calendar_id:
            payload["calendarId"] = calendar_id

        try:
            response = self._get_client().post("/events", json=payload)
            if response.status_code == 201:
                data = response.json()
                return ThunderbirdEventResult(
                    id=data["id"],
                    calendar_id=data["calendarId"],
                )
            logger.warning("Failed to create event: %s", response.text)
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug("Bridge not available for event creation")
            return None
        except Exception as e:
            logger.warning("Failed to create event: %s", e)
            return None

    def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        all_day: bool | None = None,
    ) -> ThunderbirdEventResult | None:
        """Update an existing calendar event.

        Args:
            event_id: Event ID to update.
            title: New title (optional).
            start_date: New start datetime (optional).
            end_date: New end datetime (optional).
            description: New description (optional).
            location: New location (optional).
            all_day: Whether this is an all-day event (optional).

        Returns:
            Event result, or None if add-on not available or event not found.
        """
        payload: dict[str, Any] = {}

        if title is not None:
            payload["title"] = title
        if start_date is not None:
            payload["startDate"] = start_date.isoformat()
        if end_date is not None:
            payload["endDate"] = end_date.isoformat()
        if description is not None:
            payload["description"] = description
        if location is not None:
            payload["location"] = location
        if all_day is not None:
            payload["allDay"] = all_day

        if not payload:
            logger.debug("No fields to update for event %s", event_id)
            return None

        try:
            response = self._get_client().patch(f"/events/{event_id}", json=payload)
            if response.status_code == 200:
                data = response.json()
                return ThunderbirdEventResult(
                    id=data["id"],
                    calendar_id=data.get("calendarId", ""),
                    updated=True,
                )
            if response.status_code == 404:
                logger.debug("Event not found: %s", event_id)
                return None
            logger.warning("Failed to update event: %s", response.text)
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug("Bridge not available for event update")
            return None
        except Exception as e:
            logger.warning("Failed to update event: %s", e)
            return None

    def delete_event(self, event_id: str) -> ThunderbirdEventResult | None:
        """Delete a calendar event.

        Args:
            event_id: Event ID to delete.

        Returns:
            Event result (deleted=True), or None if add-on not available.
        """
        try:
            response = self._get_client().delete(f"/events/{event_id}")
            if response.status_code == 200:
                data = response.json()
                return ThunderbirdEventResult(
                    id=data.get("id", event_id),
                    calendar_id="",
                    deleted=True,
                    not_found=data.get("notFound", False),
                )
            logger.warning("Failed to delete event: %s", response.text)
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug("Bridge not available for event deletion")
            return None
        except Exception as e:
            logger.warning("Failed to delete event: %s", e)
            return None

    def get_event(self, event_id: str) -> ThunderbirdEvent | None:
        """Get a calendar event by ID.

        Args:
            event_id: Event ID to retrieve.

        Returns:
            Event details, or None if not found or add-on not available.
        """
        try:
            response = self._get_client().get(f"/events/{event_id}")
            if response.status_code == 200:
                data = response.json()
                return ThunderbirdEvent(
                    id=data["id"],
                    title=data.get("title", ""),
                    start_date=datetime.fromisoformat(data["startDate"]) if data.get("startDate") else None,
                    end_date=datetime.fromisoformat(data["endDate"]) if data.get("endDate") else None,
                    description=data.get("description", ""),
                    location=data.get("location", ""),
                    all_day=data.get("allDay", False),
                    calendar_id=data.get("calendarId"),
                )
            return None
        except (httpx.ConnectError, httpx.TimeoutException):
            return None
        except Exception as e:
            logger.debug("Failed to get event: %s", e)
            return None


# Singleton client instance for convenience
_bridge_client: ThunderbirdBridgeClient | None = None


def get_bridge_client() -> ThunderbirdBridgeClient:
    """Get the singleton bridge client instance.

    Returns:
        ThunderbirdBridgeClient instance.
    """
    global _bridge_client
    if _bridge_client is None:
        _bridge_client = ThunderbirdBridgeClient()
    return _bridge_client


def is_bridge_available() -> bool:
    """Check if the Talking Rock Bridge add-on is available.

    Returns:
        True if the add-on is responding.
    """
    return get_bridge_client().is_available()


def create_calendar_event_for_beat(
    title: str,
    start_date: datetime | None = None,
    notes: str | None = None,
) -> str | None:
    """Create a Thunderbird calendar event for a Beat.

    This is a convenience function for the common case of creating
    an event from a Beat. Uses placeholder date if no date specified.

    Args:
        title: Beat title (used as event title).
        start_date: Event date (default: placeholder Dec 31, 2099).
        notes: Beat notes (used as event description).

    Returns:
        Event ID if created, None if add-on not available.
    """
    client = get_bridge_client()

    if not client.is_available():
        logger.debug("Bridge not available, skipping calendar event creation")
        return None

    result = client.create_event(
        title=title,
        start_date=start_date,
        description=notes,
        all_day=start_date is None,
    )

    if result:
        logger.debug("Created calendar event '%s' with ID %s", title, result.id)
        return result.id

    return None


def update_calendar_event_for_beat(
    event_id: str,
    title: str | None = None,
    start_date: datetime | None = None,
    notes: str | None = None,
) -> bool:
    """Update a Thunderbird calendar event for a Beat.

    Args:
        event_id: Event ID to update.
        title: New title (optional).
        start_date: New date (optional).
        notes: New notes/description (optional).

    Returns:
        True if updated, False otherwise.
    """
    client = get_bridge_client()

    if not client.is_available():
        logger.debug("Bridge not available, skipping calendar event update")
        return False

    result = client.update_event(
        event_id=event_id,
        title=title,
        start_date=start_date,
        description=notes,
    )

    return result is not None and result.updated


def delete_calendar_event_for_beat(event_id: str) -> bool:
    """Delete a Thunderbird calendar event for a Beat.

    Args:
        event_id: Event ID to delete.

    Returns:
        True if deleted (or already gone), False if add-on not available.
    """
    client = get_bridge_client()

    if not client.is_available():
        logger.debug("Bridge not available, skipping calendar event deletion")
        return False

    result = client.delete_event(event_id)
    return result is not None and result.deleted
