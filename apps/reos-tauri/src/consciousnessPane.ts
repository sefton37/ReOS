/**
 * Consciousness Pane - Real-time visibility into CAIRN's thinking process.
 *
 * Philosophy: Full transparency as our open-source competitive advantage.
 * Users see everything in real-time.
 *
 * This component renders consciousness events as they stream in:
 * - Intent extraction phases
 * - Extended thinking phases
 * - Tool calls
 * - Response generation
 */

import type { ConsciousnessEvent } from "./types";

// Event type to CSS class mapping
const EVENT_TYPE_CLASSES: Record<string, string> = {
  // Phases
  PHASE_START: "event-phase",
  PHASE_COMPLETE: "event-phase",

  // Intent extraction
  INTENT_EXTRACTED: "event-result",
  INTENT_VERIFIED: "event-result",
  PATTERN_MATCHED: "event-result",

  // Extended thinking
  COMPREHENSION_START: "event-phase",
  COMPREHENSION_RESULT: "event-result",
  DECOMPOSITION_START: "event-phase",
  DECOMPOSITION_RESULT: "event-result",
  REASONING_START: "event-phase",
  REASONING_ITERATION: "event-reasoning",
  REASONING_RESULT: "event-result",
  COHERENCE_START: "event-phase",
  COHERENCE_RESULT: "event-result",
  DECISION_START: "event-phase",
  DECISION_RESULT: "event-result",

  // Conversational reasoning
  EXPLORE_PASS: "event-reasoning",
  IDEATE_PASS: "event-reasoning",
  SYNTHESIZE_PASS: "event-reasoning",

  // LLM/Tool interaction
  LLM_CALL_START: "event-llm",
  LLM_CALL_COMPLETE: "event-llm",
  TOOL_CALL_START: "event-llm",
  TOOL_CALL_COMPLETE: "event-llm",

  // Final
  RESPONSE_READY: "event-result",
};

// Event type icons
const EVENT_TYPE_ICONS: Record<string, string> = {
  PHASE_START: "▶",
  PHASE_COMPLETE: "✓",
  INTENT_EXTRACTED: "🎯",
  INTENT_VERIFIED: "✓",
  COMPREHENSION_START: "🔍",
  COMPREHENSION_RESULT: "📋",
  DECOMPOSITION_START: "🔬",
  DECOMPOSITION_RESULT: "📊",
  REASONING_START: "💭",
  REASONING_ITERATION: "🔄",
  REASONING_RESULT: "💡",
  COHERENCE_START: "🪞",
  COHERENCE_RESULT: "✨",
  DECISION_START: "⚖️",
  DECISION_RESULT: "📍",
  EXPLORE_PASS: "🔭",
  IDEATE_PASS: "💡",
  SYNTHESIZE_PASS: "🧩",
  TOOL_CALL_START: "🔧",
  TOOL_CALL_COMPLETE: "✓",
  LLM_CALL_START: "🤖",
  LLM_CALL_COMPLETE: "✓",
  RESPONSE_READY: "✅",
};

export interface ConsciousnessPaneState {
  events: ConsciousnessEvent[];
  expanded: Set<number>;
  isActive: boolean;
  autoScroll: boolean;
}

export function createConsciousnessPane(
  container: HTMLElement
): {
  update: (events: ConsciousnessEvent[], isActive: boolean) => void;
  clear: () => void;
  getState: () => ConsciousnessPaneState;
} {
  const state: ConsciousnessPaneState = {
    events: [],
    expanded: new Set<number>(),
    isActive: false,
    autoScroll: true,
  };

  // Render the pane structure
  container.innerHTML = `
    <div class="consciousness-pane">
      <div class="consciousness-header">
        <span class="consciousness-title">Consciousness Stream</span>
        <div class="consciousness-header-actions">
          <button class="consciousness-scroll-btn" title="Toggle auto-scroll">⬇</button>
          <button class="consciousness-clear-btn" title="Clear">×</button>
        </div>
      </div>
      <div class="consciousness-events"></div>
      <div class="consciousness-footer">
        <span class="consciousness-status">Idle</span>
      </div>
    </div>
  `;

  const eventsContainer = container.querySelector(
    ".consciousness-events"
  ) as HTMLElement;
  const statusEl = container.querySelector(
    ".consciousness-status"
  ) as HTMLElement;
  const clearBtn = container.querySelector(
    ".consciousness-clear-btn"
  ) as HTMLButtonElement;
  const scrollBtn = container.querySelector(
    ".consciousness-scroll-btn"
  ) as HTMLButtonElement;

  // Update scroll button appearance
  function updateScrollBtn() {
    if (state.autoScroll) {
      scrollBtn.textContent = "⬇";
      scrollBtn.title = "Auto-scroll ON (click to stop)";
      scrollBtn.style.opacity = "1";
    } else {
      scrollBtn.textContent = "⏸";
      scrollBtn.title = "Auto-scroll OFF (click to resume)";
      scrollBtn.style.opacity = "0.5";
    }
  }
  updateScrollBtn();

  // Clear button handler
  clearBtn.addEventListener("click", () => {
    state.events = [];
    state.expanded.clear();
    renderEvents();
  });

  // Scroll toggle button handler
  scrollBtn.addEventListener("click", () => {
    state.autoScroll = !state.autoScroll;
    updateScrollBtn();
    // If re-enabling auto-scroll, scroll to bottom immediately
    if (state.autoScroll) {
      eventsContainer.scrollTop = eventsContainer.scrollHeight;
    }
  });

  function formatTimestamp(isoString: string): string {
    const date = new Date(isoString);
    return date.toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function renderEvent(event: ConsciousnessEvent, index: number): string {
    const typeClass = EVENT_TYPE_CLASSES[event.type] || "event-phase";
    const icon = EVENT_TYPE_ICONS[event.type] || "•";
    const isExpanded = state.expanded.has(index);
    const hasContent = event.content && event.content.length > 0;

    // Render content as markdown if it looks like it needs formatting
    let contentHtml = "";
    if (hasContent) {
      try {
        // Simple content - just escape and wrap
        const escapedContent = event.content
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/\n/g, "<br>");
        contentHtml = `<div class="consciousness-content">${escapedContent}</div>`;
      } catch {
        contentHtml = `<div class="consciousness-content">${event.content}</div>`;
      }
    }

    return `
      <div class="consciousness-event ${typeClass}" data-index="${index}">
        <div class="consciousness-event-header">
          <span class="consciousness-icon">${icon}</span>
          <span class="consciousness-title">${event.title}</span>
          <span class="consciousness-timestamp">${formatTimestamp(event.timestamp)}</span>
          ${hasContent ? `<button class="consciousness-expand-btn">${isExpanded ? "−" : "+"}</button>` : ""}
        </div>
        ${isExpanded ? contentHtml : ""}
      </div>
    `;
  }

  function renderEvents() {
    const html = state.events.map(renderEvent).join("");
    console.log('[CONSCIOUSNESS PANE] renderEvents:', state.events.length, 'events, html length:', html.length);
    eventsContainer.innerHTML = html;

    // Attach expand/collapse handlers
    eventsContainer.querySelectorAll(".consciousness-expand-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const eventEl = (e.target as HTMLElement).closest(".consciousness-event");
        if (!eventEl) return;
        const index = parseInt(eventEl.getAttribute("data-index") || "0", 10);

        if (state.expanded.has(index)) {
          state.expanded.delete(index);
        } else {
          state.expanded.add(index);
        }
        renderEvents();
      });
    });

    // Auto-scroll to bottom only when enabled
    if (state.autoScroll) {
      eventsContainer.scrollTop = eventsContainer.scrollHeight;
    }
  }

  function update(events: ConsciousnessEvent[], isActive: boolean) {
    console.log('[CONSCIOUSNESS PANE] update called with', events.length, 'events, container:', eventsContainer?.tagName);
    state.events = events;
    state.isActive = isActive;

    // Auto-expand new events
    const prevCount = eventsContainer.children.length;
    if (events.length > prevCount) {
      // Expand the latest event if it has content
      const latestIdx = events.length - 1;
      if (events[latestIdx]?.content) {
        state.expanded.add(latestIdx);
      }
    }

    renderEvents();

    // Update status
    if (isActive) {
      statusEl.textContent = "Processing...";
      statusEl.classList.add("active");
    } else if (events.length > 0) {
      statusEl.textContent = `${events.length} events`;
      statusEl.classList.remove("active");
    } else {
      statusEl.textContent = "Idle";
      statusEl.classList.remove("active");
    }
  }

  function clear() {
    state.events = [];
    state.expanded.clear();
    state.isActive = false;
    renderEvents();
    statusEl.textContent = "Idle";
    statusEl.classList.remove("active");
  }

  function getState() {
    return { ...state };
  }

  return { update, clear, getState };
}
