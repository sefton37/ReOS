/**
 * Talking Rock Bridge - Background Script
 *
 * This script runs when Thunderbird starts and initializes the HTTP server
 * that allows ReOS to communicate with Thunderbird's calendar.
 *
 * The HTTP server listens on localhost:19192 and provides REST API endpoints
 * for calendar CRUD operations.
 */

"use strict";

const PORT = 19192;
const HOST = "127.0.0.1";

/**
 * Simple HTTP request parser
 */
function parseHttpRequest(data) {
  const text = new TextDecoder().decode(data);
  const lines = text.split("\r\n");
  const [method, path] = lines[0].split(" ");

  // Find body (after empty line)
  const emptyLineIndex = lines.indexOf("");
  let body = null;
  if (emptyLineIndex !== -1 && emptyLineIndex < lines.length - 1) {
    body = lines.slice(emptyLineIndex + 1).join("\r\n");
    if (body) {
      try {
        body = JSON.parse(body);
      } catch (e) {
        // Keep as string if not valid JSON
      }
    }
  }

  // Parse headers
  const headers = {};
  for (let i = 1; i < (emptyLineIndex !== -1 ? emptyLineIndex : lines.length); i++) {
    const colonIndex = lines[i].indexOf(":");
    if (colonIndex !== -1) {
      const key = lines[i].substring(0, colonIndex).trim().toLowerCase();
      const value = lines[i].substring(colonIndex + 1).trim();
      headers[key] = value;
    }
  }

  return { method, path, headers, body };
}

/**
 * Build HTTP response
 */
function buildHttpResponse(status, statusText, body, contentType = "application/json") {
  const bodyStr = typeof body === "string" ? body : JSON.stringify(body);
  const bodyBytes = new TextEncoder().encode(bodyStr);

  const headers = [
    `HTTP/1.1 ${status} ${statusText}`,
    `Content-Type: ${contentType}`,
    `Content-Length: ${bodyBytes.length}`,
    "Access-Control-Allow-Origin: *",
    "Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers: Content-Type",
    "Connection: close",
    "",
    ""
  ].join("\r\n");

  const headerBytes = new TextEncoder().encode(headers);
  const response = new Uint8Array(headerBytes.length + bodyBytes.length);
  response.set(headerBytes);
  response.set(bodyBytes, headerBytes.length);

  return response;
}

/**
 * Extract event ID from path like /events/abc123
 */
function extractEventId(path) {
  const match = path.match(/^\/events\/([^/]+)$/);
  return match ? match[1] : null;
}

/**
 * Handle incoming HTTP request
 */
async function handleRequest(request) {
  const { method, path, body } = request;

  // CORS preflight
  if (method === "OPTIONS") {
    return buildHttpResponse(204, "No Content", "");
  }

  try {
    // GET /health - Health check
    if (method === "GET" && path === "/health") {
      const defaultCal = await browser.calendarBridge.getDefaultCalendar();
      return buildHttpResponse(200, "OK", {
        status: "ok",
        version: "1.0.0",
        defaultCalendar: defaultCal
      });
    }

    // GET /calendars - List calendars
    if (method === "GET" && path === "/calendars") {
      const calendars = await browser.calendarBridge.listCalendars();
      return buildHttpResponse(200, "OK", { calendars });
    }

    // POST /events - Create event
    if (method === "POST" && path === "/events") {
      if (!body || !body.title) {
        return buildHttpResponse(400, "Bad Request", {
          error: "Missing required field: title"
        });
      }

      const result = await browser.calendarBridge.createEvent(
        body.calendarId || null,
        body.title,
        body.startDate,
        body.endDate,
        body.description || null,
        body.location || null,
        body.allDay || false
      );

      return buildHttpResponse(201, "Created", result);
    }

    // GET /events/:id - Get event
    const eventIdForGet = method === "GET" ? extractEventId(path) : null;
    if (method === "GET" && eventIdForGet) {
      const event = await browser.calendarBridge.getEvent(eventIdForGet);
      if (!event) {
        return buildHttpResponse(404, "Not Found", {
          error: `Event not found: ${eventIdForGet}`
        });
      }
      return buildHttpResponse(200, "OK", event);
    }

    // PATCH /events/:id - Update event
    const eventIdForPatch = method === "PATCH" ? extractEventId(path) : null;
    if (method === "PATCH" && eventIdForPatch) {
      const result = await browser.calendarBridge.updateEvent(
        eventIdForPatch,
        body?.title,
        body?.startDate,
        body?.endDate,
        body?.description,
        body?.location,
        body?.allDay
      );
      return buildHttpResponse(200, "OK", result);
    }

    // DELETE /events/:id - Delete event
    const eventIdForDelete = method === "DELETE" ? extractEventId(path) : null;
    if (method === "DELETE" && eventIdForDelete) {
      const result = await browser.calendarBridge.deleteEvent(eventIdForDelete);
      return buildHttpResponse(200, "OK", result);
    }

    // Not found
    return buildHttpResponse(404, "Not Found", {
      error: `Unknown endpoint: ${method} ${path}`
    });

  } catch (error) {
    console.error("Talking Rock Bridge error:", error);
    return buildHttpResponse(500, "Internal Server Error", {
      error: error.message || "Unknown error"
    });
  }
}

/**
 * Start the HTTP server using native messaging or polling
 *
 * Note: WebExtensions don't have direct socket access, so we use a polling
 * mechanism where the Python client makes requests and we respond.
 *
 * For a true HTTP server, we'd need to implement it in the Experiment API.
 * This background script provides the request handling logic.
 */
async function init() {
  console.log("Talking Rock Bridge: Initializing...");

  // Test that the calendar bridge API is available
  try {
    const defaultCal = await browser.calendarBridge.getDefaultCalendar();
    console.log("Talking Rock Bridge: Calendar API available, default calendar:", defaultCal?.name || "none");
  } catch (e) {
    console.error("Talking Rock Bridge: Calendar API not available:", e);
  }

  console.log(`Talking Rock Bridge: Ready on port ${PORT}`);
}

// Export for use by the HTTP server implementation
if (typeof globalThis !== "undefined") {
  globalThis.talkingRockBridge = {
    handleRequest,
    parseHttpRequest,
    buildHttpResponse,
    PORT,
    HOST
  };
}

// Initialize on load
init();
