# Talking Rock Bridge

A Thunderbird WebExtension that enables ReOS to create, update, and delete calendar events in Thunderbird via a local HTTP API.

## Overview

Talking Rock Bridge runs a lightweight HTTP server on `localhost:19192` that exposes Thunderbird's calendar functionality through a REST API. This allows ReOS to sync beats with Thunderbird calendar events bidirectionally.

## Requirements

- Thunderbird 115.0 or later (tested up to 140+)
- ReOS with the Thunderbird bridge client (`src/reos/cairn/thunderbird_bridge.py`)

## Installation

1. Build the extension package:
   ```bash
   cd apps/talking-rock-bridge
   zip -r ../talking-rock-bridge.xpi . -x "*.md"
   ```

2. In Thunderbird:
   - Go to **Add-ons and Themes** (Ctrl+Shift+A)
   - Click the gear icon → **Install Add-on From File**
   - Select `talking-rock-bridge.xpi`

## API Reference

The server listens on `http://127.0.0.1:19192`. All responses are JSON.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check, returns default calendar info |
| `GET` | `/calendars` | List all writable calendars |
| `POST` | `/events` | Create a new event |
| `GET` | `/events/:id` | Get an event by ID |
| `PATCH` | `/events/:id` | Update an event |
| `DELETE` | `/events/:id` | Delete an event |

### Event Payload

```json
{
  "title": "Meeting",
  "startDate": "2026-01-20T10:00:00Z",
  "endDate": "2026-01-20T11:00:00Z",
  "description": "Optional description",
  "location": "Optional location",
  "allDay": false,
  "calendarId": "optional-calendar-id"
}
```

### Example Usage

```bash
# Health check
curl http://127.0.0.1:19192/health

# Create an event
curl -X POST http://127.0.0.1:19192/events \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Event", "startDate": "2026-01-20T10:00:00Z", "endDate": "2026-01-20T11:00:00Z"}'

# Get an event
curl http://127.0.0.1:19192/events/EVENT_ID

# Update an event
curl -X PATCH http://127.0.0.1:19192/events/EVENT_ID \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Title"}'

# Delete an event
curl -X DELETE http://127.0.0.1:19192/events/EVENT_ID
```

## Architecture

```
┌─────────────────┐         HTTP          ┌─────────────────────────┐
│     ReOS        │ ◄──────────────────► │  Talking Rock Bridge     │
│                 │    localhost:19192    │  (Thunderbird Add-on)    │
│ thunderbird_    │                       │                          │
│ bridge.py       │                       │  ┌───────────────────┐   │
│                 │                       │  │ Experiment API    │   │
└─────────────────┘                       │  │ (calendarBridge)  │   │
                                          │  └─────────┬─────────┘   │
                                          │            │             │
                                          │  ┌─────────▼─────────┐   │
                                          │  │ Thunderbird       │   │
                                          │  │ Calendar API      │   │
                                          │  └───────────────────┘   │
                                          └─────────────────────────┘
```

## Compatibility

The extension handles multiple Thunderbird versions:

- **TB 115-139**: Uses `ChromeUtils.import()` and listener-based calendar APIs
- **TB 140+**: Uses `ChromeUtils.importESModule()` and Promise-based calendar APIs

DateTime conversion supports multiple internal formats (jsDate, nativeTime, iCalString) for cross-version compatibility.

## Security

- Server binds to `127.0.0.1` only (localhost)
- No authentication required (trusted local environment)
- CORS enabled for local web clients

## Development

The extension uses Mozilla's Experiment API to access Thunderbird's internal calendar APIs:

- `api/calendarBridge/schema.json` - API definition
- `api/calendarBridge/implementation.js` - Core implementation
- `background.js` - Extension entry point

## Related Files

- `src/reos/cairn/thunderbird_bridge.py` - Python HTTP client
- `src/reos/cairn/beat_calendar_sync.py` - Beat sync logic
- `tests/test_thunderbird_integration.py` - Integration tests
