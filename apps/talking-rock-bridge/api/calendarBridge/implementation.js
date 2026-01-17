/* eslint-disable no-undef */
/**
 * Talking Rock Bridge - Calendar Bridge Experiment API
 *
 * Provides CRUD operations for Thunderbird calendar events via the
 * internal calendar manager APIs, plus an HTTP server for ReOS communication.
 */

"use strict";

// Use ChromeUtils.importESModule for TB 115+ or fall back to ChromeUtils.import
var { ExtensionCommon } = ChromeUtils.importESModule
  ? ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs")
  : ChromeUtils.import("resource://gre/modules/ExtensionCommon.jsm");

var { cal } = ChromeUtils.importESModule
  ? ChromeUtils.importESModule("resource:///modules/calendar/calUtils.sys.mjs")
  : ChromeUtils.import("resource:///modules/calendar/calUtils.jsm");

// TB 140+ uses separate classes for events and datetimes
var CalEvent, CalDateTime;
try {
  ({ CalEvent } = ChromeUtils.importESModule("resource:///modules/calendar/CalEvent.sys.mjs"));
  ({ CalDateTime } = ChromeUtils.importESModule("resource:///modules/calendar/CalDateTime.sys.mjs"));
} catch (e) {
  // Try alternate paths (TB 140+ uses different location)
  try {
    ({ CalEvent } = ChromeUtils.importESModule("resource:///modules/CalEvent.sys.mjs"));
    ({ CalDateTime } = ChromeUtils.importESModule("resource:///modules/CalDateTime.sys.mjs"));
  } catch (e2) {
    // Older TB versions - will use cal.createEvent/createDateTime
    CalEvent = null;
    CalDateTime = null;
  }
}

/**
 * Create a new calendar event instance.
 */
function createNewEvent() {
  if (CalEvent) {
    try {
      return new CalEvent();
    } catch (e) {
      // Fall through to cal.createEvent
    }
  }
  if (cal.createEvent) {
    return cal.createEvent();
  }
  throw new Error("No method available to create calendar event");
}

/**
 * Create a new DateTime instance.
 */
function createNewDateTime() {
  if (CalDateTime) {
    try {
      return new CalDateTime();
    } catch (e) {
      // Fall through to cal.createDateTime
    }
  }
  if (cal.createDateTime) {
    return cal.createDateTime();
  }
  throw new Error("No method available to create datetime");
}

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
      // TB 140+ uses Promise-based API
      const result = calendar.getItem(eventId);

      let item = null;
      if (result && typeof result.then === "function") {
        item = await result;
      } else {
        // Fallback to listener-based API
        item = await new Promise((resolve) => {
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
      }

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
  const event = createNewEvent();

  if (params.title) {
    event.title = params.title;
  }

  if (params.startDate) {
    const startDate = createNewDateTime();
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
    const endDate = createNewDateTime();
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
 * Convert a calendar datetime to ISO string.
 */
function dateTimeToISO(dt) {
  if (!dt) return null;

  // Try jsDate property first (older TB), then try native date conversion
  if (dt.jsDate && typeof dt.jsDate.toISOString === "function") {
    return dt.jsDate.toISOString();
  }
  // TB 140+ might use different property or method
  if (dt.nativeTime) {
    // nativeTime is microseconds since epoch
    return new Date(dt.nativeTime / 1000).toISOString();
  }
  if (typeof dt.toICALString === "function") {
    // Parse from iCal string
    const icalStr = dt.toICALString();
    // Format: YYYYMMDDTHHMMSSZ or YYYYMMDD
    if (icalStr.length >= 8) {
      const year = icalStr.substring(0, 4);
      const month = icalStr.substring(4, 6);
      const day = icalStr.substring(6, 8);
      if (icalStr.length >= 15) {
        const hour = icalStr.substring(9, 11);
        const min = icalStr.substring(11, 13);
        const sec = icalStr.substring(13, 15);
        return `${year}-${month}-${day}T${hour}:${min}:${sec}Z`;
      }
      return `${year}-${month}-${day}T00:00:00Z`;
    }
  }
  return null;
}

/**
 * Convert a calendar item to a plain object for JSON serialization.
 */
function eventToObject(item) {
  if (!item) return null;

  return {
    id: item.id,
    title: item.title || "",
    startDate: dateTimeToISO(item.startDate),
    endDate: dateTimeToISO(item.endDate),
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

    // TB 140+ uses Promise-based API instead of listener-based
    try {
      const result = calendar.addItem(event);

      // Check if it's a Promise
      if (result && typeof result.then === "function") {
        const addedItem = await result;
        return {
          id: addedItem?.id || event.id,
          calendarId: calendar.id
        };
      }

      // If not a Promise, might be the item directly or need listener
      if (result && result.id) {
        return {
          id: result.id,
          calendarId: calendar.id
        };
      }

      // Fall back to listener-based approach (older TB versions)
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
    } catch (e) {
      throw e;
    }
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
      const start = createNewDateTime();
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
      const end = createNewDateTime();
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

    // TB 140+ uses Promise-based API
    try {
      const result = calendar.modifyItem(mutableItem, item);

      if (result && typeof result.then === "function") {
        await result;
        return {
          id: eventId,
          calendarId: calendar.id,
          updated: true
        };
      }

      // Fallback to listener-based API
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
    } catch (e) {
      throw new Error(`Failed to update event: ${e.message}`);
    }
  },

  async deleteEvent(eventId) {
    const found = await findEventById(eventId);

    if (!found) {
      return { id: eventId, deleted: true, notFound: true };
    }

    const { item, calendar } = found;

    // TB 140+ uses Promise-based API
    try {
      const result = calendar.deleteItem(item);

      if (result && typeof result.then === "function") {
        await result;
        return { id: eventId, deleted: true };
      }

      // Fallback to listener-based API
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
    } catch (e) {
      throw new Error(`Failed to delete event: ${e.message}`);
    }
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
    this.listener = null; // Keep strong reference to prevent GC
  }

  start() {
    if (this.socket) {
      return;
    }

    try {
      this.socket = Cc["@mozilla.org/network/server-socket;1"]
        .createInstance(Ci.nsIServerSocket);

      this.socket.init(PORT, true, -1); // loopback only

      const self = this;
      // Store listener as property to prevent garbage collection
      this.listener = {
        QueryInterface: ChromeUtils.generateQI(["nsIServerSocketListener"]),
        onSocketAccepted: function(serverSocket, transport) {
          console.log("Talking Rock Bridge: New connection");
          self.handleConnection(transport);
        },
        onStopListening: function(serverSocket, status) {
          console.log("Talking Rock Bridge: Server stopped", status);
        }
      };
      this.socket.asyncListen(this.listener);

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
    const self = this;

    // Use ThreadManager to handle async operations properly
    const tm = Cc["@mozilla.org/thread-manager;1"].getService(Ci.nsIThreadManager);

    let inputStream, outputStream, bis, bos;

    try {
      inputStream = transport.openInputStream(0, 0, 0);
      outputStream = transport.openOutputStream(Ci.nsITransport.OPEN_BLOCKING, 0, 0);

      bis = Cc["@mozilla.org/binaryinputstream;1"]
        .createInstance(Ci.nsIBinaryInputStream);
      bis.setInputStream(inputStream);

      bos = Cc["@mozilla.org/binaryoutputstream;1"]
        .createInstance(Ci.nsIBinaryOutputStream);
      bos.setOutputStream(outputStream);

      // Use async wait for data
      const asyncInput = inputStream.QueryInterface(Ci.nsIAsyncInputStream);

      // Store callback to prevent GC
      const callback = {
        QueryInterface: ChromeUtils.generateQI(["nsIInputStreamCallback"]),
        onInputStreamReady: function(stream) {
          (async () => {
            try {
              // Read available data
              let requestData = "";
              try {
                const available = bis.available();
                if (available > 0) {
                  requestData = String.fromCharCode.apply(null, bis.readByteArray(available));
                }
              } catch (e) {
                // Stream closed or error - ignore
              }

              // Process and respond
              if (requestData.length > 0) {
                const response = await self.processRequest(requestData);
                self.writeResponse(bos, outputStream, response);
              }
            } catch (e) {
              console.error("Talking Rock Bridge: Request handler error:", e);
              try {
                self.writeResponse(bos, outputStream, self.buildErrorResponse(500, e.message));
              } catch (e2) {
                // Ignore send errors
              }
            } finally {
              try {
                inputStream.close();
                outputStream.close();
                transport.close(0);
              } catch (e) {
                // Ignore
              }
              self.connections.delete(transport);
            }
          })().catch(e => {
            console.error("Talking Rock Bridge: Async handler error:", e);
          });
        }
      };

      asyncInput.asyncWait(callback, 0, 0, tm.mainThread);

    } catch (e) {
      console.error("Talking Rock Bridge: Connection setup error:", e);
      try {
        if (inputStream) inputStream.close();
        if (outputStream) outputStream.close();
        transport.close(0);
      } catch (e2) {
        // Ignore
      }
      this.connections.delete(transport);
    }
  }

  writeResponse(bos, outputStream, response) {
    try {
      // Write as bytes
      const bytes = [];
      for (let i = 0; i < response.length; i++) {
        bytes.push(response.charCodeAt(i));
      }
      bos.writeByteArray(bytes);
      outputStream.flush();
    } catch (e) {
      console.error("Talking Rock Bridge: Failed to write response:", e);
    }
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
    // Use string length - for ASCII/UTF-8 JSON this equals byte length
    const headers = [
      `HTTP/1.1 ${status} ${statusText}`,
      "Content-Type: application/json; charset=utf-8",
      `Content-Length: ${bodyStr.length}`,
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
