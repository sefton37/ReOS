/* eslint-disable no-undef */
/**
 * Talking Rock Bridge - Calendar Bridge Experiment API
 *
 * Provides CRUD operations for Thunderbird calendar events via the
 * internal calendar manager APIs, plus an HTTP server for ReOS communication.
 */

"use strict";

var { ExtensionCommon } = ChromeUtils.import(
  "resource://gre/modules/ExtensionCommon.jsm"
);

var { cal } = ChromeUtils.import("resource:///modules/calendar/calUtils.jsm");

const PORT = 19192;
const HOST = "127.0.0.1";

let httpServer = null;

/**
 * Get the calendar manager instance.
 */
function getCalendarManager() {
  return cal.manager;
}

/**
 * Find a calendar item (event) by ID across all calendars.
 */
async function findEventById(eventId) {
  const calManager = getCalendarManager();
  const calendars = calManager.getCalendars();

  for (const calendar of calendars) {
    if (calendar.readOnly) continue;

    try {
      const item = await new Promise((resolve) => {
        const listener = {
          QueryInterface: ChromeUtils.generateQI(["calIOperationListener"]),
          onOperationComplete(aCalendar, aStatus, aOperationType, aId, aDetail) {
            if (Components.isSuccessCode(aStatus)) {
              resolve(aDetail);
            } else {
              resolve(null);
            }
          },
          onGetResult() {}
        };
        calendar.getItem(eventId, listener);
      });

      if (item) {
        return { item, calendar };
      }
    } catch (e) {
      // Continue searching other calendars
    }
  }

  return null;
}

/**
 * Create a calendar event item from parameters.
 */
function createEventItem(params) {
  const event = cal.createEvent();

  if (params.title) {
    event.title = params.title;
  }

  if (params.startDate) {
    const startDate = cal.createDateTime();
    const startDateObj = new Date(params.startDate);
    if (params.allDay) {
      // For all-day events, use date only format
      startDate.icalString = startDateObj.toISOString().split("T")[0].replace(/-/g, "");
      startDate.isDate = true;
    } else {
      startDate.icalString = startDateObj.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    }
    event.startDate = startDate;
  }

  if (params.endDate) {
    const endDate = cal.createDateTime();
    const endDateObj = new Date(params.endDate);
    if (params.allDay) {
      endDate.icalString = endDateObj.toISOString().split("T")[0].replace(/-/g, "");
      endDate.isDate = true;
    } else {
      endDate.icalString = endDateObj.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    }
    event.endDate = endDate;
  }

  if (params.description) {
    event.setProperty("DESCRIPTION", params.description);
  }

  if (params.location) {
    event.setProperty("LOCATION", params.location);
  }

  return event;
}

/**
 * Convert a calendar item to a plain object for JSON serialization.
 */
function eventToObject(item) {
  if (!item) return null;

  return {
    id: item.id,
    title: item.title || "",
    startDate: item.startDate ? item.startDate.jsDate.toISOString() : null,
    endDate: item.endDate ? item.endDate.jsDate.toISOString() : null,
    description: item.getProperty("DESCRIPTION") || "",
    location: item.getProperty("LOCATION") || "",
    allDay: item.startDate ? item.startDate.isDate : false,
    calendarId: item.calendar ? item.calendar.id : null
  };
}

/**
 * Calendar operations object (shared between API and HTTP server)
 */
const calendarOps = {
  async listCalendars() {
    const calManager = getCalendarManager();
    const calendars = calManager.getCalendars();

    return calendars
      .filter(c => !c.readOnly)
      .map(c => ({
        id: c.id,
        name: c.name,
        type: c.type,
        color: c.getProperty("color") || "#3366cc"
      }));
  },

  async getDefaultCalendar() {
    const calManager = getCalendarManager();
    const calendars = calManager.getCalendars();

    const writableCalendars = calendars.filter(c => !c.readOnly);

    if (writableCalendars.length === 0) {
      return null;
    }

    const defaultCal = calManager.defaultCalendar;
    if (defaultCal && !defaultCal.readOnly) {
      return {
        id: defaultCal.id,
        name: defaultCal.name,
        type: defaultCal.type
      };
    }

    const c = writableCalendars[0];
    return {
      id: c.id,
      name: c.name,
      type: c.type
    };
  },

  async createEvent(calendarId, title, startDate, endDate, description, location, allDay) {
    const calManager = getCalendarManager();
    let calendar;

    if (calendarId) {
      calendar = calManager.getCalendarById(calendarId);
    } else {
      const defaultCal = await this.getDefaultCalendar();
      if (defaultCal) {
        calendar = calManager.getCalendarById(defaultCal.id);
      }
    }

    if (!calendar) {
      throw new Error("No writable calendar available");
    }

    if (calendar.readOnly) {
      throw new Error("Calendar is read-only");
    }

    const event = createEventItem({
      title,
      startDate,
      endDate,
      description,
      location,
      allDay
    });

    return new Promise((resolve, reject) => {
      const listener = {
        QueryInterface: ChromeUtils.generateQI(["calIOperationListener"]),
        onOperationComplete(aCalendar, aStatus, aOperationType, aId, aDetail) {
          if (Components.isSuccessCode(aStatus)) {
            resolve({
              id: aId || event.id,
              calendarId: calendar.id
            });
          } else {
            reject(new Error(`Failed to create event: ${aStatus}`));
          }
        },
        onGetResult() {}
      };

      calendar.addItem(event, listener);
    });
  },

  async updateEvent(eventId, title, startDate, endDate, description, location, allDay) {
    const found = await findEventById(eventId);

    if (!found) {
      throw new Error(`Event not found: ${eventId}`);
    }

    const { item, calendar } = found;
    const mutableItem = item.clone();

    if (title !== undefined && title !== null) {
      mutableItem.title = title;
    }

    if (startDate !== undefined && startDate !== null) {
      const start = cal.createDateTime();
      const startDateObj = new Date(startDate);
      if (allDay) {
        start.icalString = startDateObj.toISOString().split("T")[0].replace(/-/g, "");
        start.isDate = true;
      } else {
        start.icalString = startDateObj.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
      }
      mutableItem.startDate = start;
    }

    if (endDate !== undefined && endDate !== null) {
      const end = cal.createDateTime();
      const endDateObj = new Date(endDate);
      if (allDay) {
        end.icalString = endDateObj.toISOString().split("T")[0].replace(/-/g, "");
        end.isDate = true;
      } else {
        end.icalString = endDateObj.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
      }
      mutableItem.endDate = end;
    }

    if (description !== undefined) {
      if (description === null || description === "") {
        mutableItem.deleteProperty("DESCRIPTION");
      } else {
        mutableItem.setProperty("DESCRIPTION", description);
      }
    }

    if (location !== undefined) {
      if (location === null || location === "") {
        mutableItem.deleteProperty("LOCATION");
      } else {
        mutableItem.setProperty("LOCATION", location);
      }
    }

    return new Promise((resolve, reject) => {
      const listener = {
        QueryInterface: ChromeUtils.generateQI(["calIOperationListener"]),
        onOperationComplete(aCalendar, aStatus, aOperationType, aId, aDetail) {
          if (Components.isSuccessCode(aStatus)) {
            resolve({
              id: eventId,
              calendarId: calendar.id,
              updated: true
            });
          } else {
            reject(new Error(`Failed to update event: ${aStatus}`));
          }
        },
        onGetResult() {}
      };

      calendar.modifyItem(mutableItem, item, listener);
    });
  },

  async deleteEvent(eventId) {
    const found = await findEventById(eventId);

    if (!found) {
      return { id: eventId, deleted: true, notFound: true };
    }

    const { item, calendar } = found;

    return new Promise((resolve, reject) => {
      const listener = {
        QueryInterface: ChromeUtils.generateQI(["calIOperationListener"]),
        onOperationComplete(aCalendar, aStatus, aOperationType, aId, aDetail) {
          if (Components.isSuccessCode(aStatus)) {
            resolve({ id: eventId, deleted: true });
          } else {
            reject(new Error(`Failed to delete event: ${aStatus}`));
          }
        },
        onGetResult() {}
      };

      calendar.deleteItem(item, listener);
    });
  },

  async getEvent(eventId) {
    const found = await findEventById(eventId);

    if (!found) {
      return null;
    }

    return eventToObject(found.item);
  }
};

// =============================================================================
// HTTP Server Implementation
// =============================================================================

/**
 * Simple HTTP server using nsIServerSocket
 */
class TalkingRockHttpServer {
  constructor() {
    this.socket = null;
    this.connections = new Set();
  }

  start() {
    if (this.socket) {
      return;
    }

    try {
      this.socket = Cc["@mozilla.org/network/server-socket;1"]
        .createInstance(Ci.nsIServerSocket);

      this.socket.init(PORT, true, -1); // loopback only

      this.socket.asyncListen({
        onSocketAccepted: (serverSocket, transport) => {
          this.handleConnection(transport);
        },
        onStopListening: (serverSocket, status) => {
          console.log("Talking Rock Bridge: Server stopped", status);
        }
      });

      console.log(`Talking Rock Bridge: HTTP server listening on ${HOST}:${PORT}`);
    } catch (e) {
      console.error("Talking Rock Bridge: Failed to start HTTP server:", e);
    }
  }

  stop() {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    for (const conn of this.connections) {
      try {
        conn.close(0);
      } catch (e) {
        // Ignore
      }
    }
    this.connections.clear();
  }

  handleConnection(transport) {
    this.connections.add(transport);

    const inputStream = transport.openInputStream(0, 0, 0);
    const outputStream = transport.openOutputStream(0, 0, 0);

    const scriptableInput = Cc["@mozilla.org/scriptableinputstream;1"]
      .createInstance(Ci.nsIScriptableInputStream);
    scriptableInput.init(inputStream);

    // Read request data
    let requestData = "";
    const pump = Cc["@mozilla.org/network/input-stream-pump;1"]
      .createInstance(Ci.nsIInputStreamPump);

    pump.init(inputStream, 0, 0, true);
    pump.asyncRead({
      onStartRequest: () => {},
      onStopRequest: async () => {
        try {
          const response = await this.processRequest(requestData);
          this.sendResponse(outputStream, response);
        } catch (e) {
          console.error("Talking Rock Bridge: Request error:", e);
          this.sendResponse(outputStream, this.buildErrorResponse(500, e.message));
        } finally {
          try {
            inputStream.close();
            outputStream.close();
            transport.close(0);
          } catch (e) {
            // Ignore close errors
          }
          this.connections.delete(transport);
        }
      },
      onDataAvailable: (request, inputStream, offset, count) => {
        requestData += scriptableInput.read(count);
      }
    });
  }

  async processRequest(rawRequest) {
    const { method, path, body } = this.parseRequest(rawRequest);

    // CORS preflight
    if (method === "OPTIONS") {
      return this.buildResponse(204, "No Content", "");
    }

    try {
      // GET /health
      if (method === "GET" && path === "/health") {
        const defaultCal = await calendarOps.getDefaultCalendar();
        return this.buildResponse(200, "OK", {
          status: "ok",
          version: "1.0.0",
          defaultCalendar: defaultCal
        });
      }

      // GET /calendars
      if (method === "GET" && path === "/calendars") {
        const calendars = await calendarOps.listCalendars();
        return this.buildResponse(200, "OK", { calendars });
      }

      // POST /events
      if (method === "POST" && path === "/events") {
        if (!body || !body.title) {
          return this.buildResponse(400, "Bad Request", {
            error: "Missing required field: title"
          });
        }

        const result = await calendarOps.createEvent(
          body.calendarId || null,
          body.title,
          body.startDate,
          body.endDate,
          body.description || null,
          body.location || null,
          body.allDay || false
        );

        return this.buildResponse(201, "Created", result);
      }

      // GET /events/:id
      const eventIdForGet = method === "GET" ? this.extractEventId(path) : null;
      if (method === "GET" && eventIdForGet) {
        const event = await calendarOps.getEvent(eventIdForGet);
        if (!event) {
          return this.buildResponse(404, "Not Found", {
            error: `Event not found: ${eventIdForGet}`
          });
        }
        return this.buildResponse(200, "OK", event);
      }

      // PATCH /events/:id
      const eventIdForPatch = method === "PATCH" ? this.extractEventId(path) : null;
      if (method === "PATCH" && eventIdForPatch) {
        const result = await calendarOps.updateEvent(
          eventIdForPatch,
          body?.title,
          body?.startDate,
          body?.endDate,
          body?.description,
          body?.location,
          body?.allDay
        );
        return this.buildResponse(200, "OK", result);
      }

      // DELETE /events/:id
      const eventIdForDelete = method === "DELETE" ? this.extractEventId(path) : null;
      if (method === "DELETE" && eventIdForDelete) {
        const result = await calendarOps.deleteEvent(eventIdForDelete);
        return this.buildResponse(200, "OK", result);
      }

      return this.buildResponse(404, "Not Found", {
        error: `Unknown endpoint: ${method} ${path}`
      });

    } catch (error) {
      console.error("Talking Rock Bridge: Handler error:", error);
      return this.buildResponse(500, "Internal Server Error", {
        error: error.message || "Unknown error"
      });
    }
  }

  parseRequest(rawRequest) {
    const lines = rawRequest.split("\r\n");
    const [method, path] = (lines[0] || "").split(" ");

    // Find body (after empty line)
    const emptyLineIndex = lines.indexOf("");
    let body = null;
    if (emptyLineIndex !== -1 && emptyLineIndex < lines.length - 1) {
      const bodyStr = lines.slice(emptyLineIndex + 1).join("\r\n").trim();
      if (bodyStr) {
        try {
          body = JSON.parse(bodyStr);
        } catch (e) {
          // Keep as null if not valid JSON
        }
      }
    }

    return { method: method || "GET", path: path || "/", body };
  }

  extractEventId(path) {
    const match = (path || "").match(/^\/events\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  buildResponse(status, statusText, body) {
    const bodyStr = typeof body === "string" ? body : JSON.stringify(body);
    const headers = [
      `HTTP/1.1 ${status} ${statusText}`,
      "Content-Type: application/json",
      `Content-Length: ${new TextEncoder().encode(bodyStr).length}`,
      "Access-Control-Allow-Origin: *",
      "Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS",
      "Access-Control-Allow-Headers: Content-Type",
      "Connection: close",
      "",
      ""
    ].join("\r\n");

    return headers + bodyStr;
  }

  buildErrorResponse(status, message) {
    return this.buildResponse(status, "Error", { error: message });
  }

  sendResponse(outputStream, response) {
    try {
      const bytes = new TextEncoder().encode(response);
      outputStream.write(response, bytes.length);
      outputStream.flush();
    } catch (e) {
      console.error("Talking Rock Bridge: Failed to send response:", e);
    }
  }
}

// =============================================================================
// Extension API
// =============================================================================

var calendarBridge = class extends ExtensionCommon.ExtensionAPI {
  onStartup() {
    // Start HTTP server when extension loads
    if (!httpServer) {
      httpServer = new TalkingRockHttpServer();
      httpServer.start();
    }
  }

  onShutdown() {
    // Stop HTTP server when extension unloads
    if (httpServer) {
      httpServer.stop();
      httpServer = null;
    }
  }

  getAPI(context) {
    // Start server if not already running
    if (!httpServer) {
      httpServer = new TalkingRockHttpServer();
      httpServer.start();
    }

    return {
      calendarBridge: {
        listCalendars: () => calendarOps.listCalendars(),
        getDefaultCalendar: () => calendarOps.getDefaultCalendar(),
        createEvent: (calendarId, title, startDate, endDate, description, location, allDay) =>
          calendarOps.createEvent(calendarId, title, startDate, endDate, description, location, allDay),
        updateEvent: (eventId, title, startDate, endDate, description, location, allDay) =>
          calendarOps.updateEvent(eventId, title, startDate, endDate, description, location, allDay),
        deleteEvent: (eventId) => calendarOps.deleteEvent(eventId),
        getEvent: (eventId) => calendarOps.getEvent(eventId)
      }
    };
  }
};
