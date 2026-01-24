/**
 * Archive Review Overlay - Review and approve conversation archival
 *
 * Shows LLM-generated summary and extracted knowledge before finalizing archive.
 * Allows user feedback (thumbs up/down) and additional notes.
 */

import { el } from './dom';

export interface ArchivePreview {
  title: string;
  summary: string;
  linked_act_id: string | null;
  linking_reason: string | null;
  knowledge_entries: Array<{
    category: string;
    content: string;
  }>;
  topics: string[];
  message_count: number;
}

export interface ArchiveReviewResult {
  approved: boolean;
  rating: number | null; // 1-5 or null if not rated
  additionalNotes: string;
  editedTitle: string;
  editedSummary: string;
  // User can remove entries they don't want saved
  approvedEntries: Array<{
    category: string;
    content: string;
  }>;
}

interface ArchiveReviewOverlayCallbacks {
  onConfirm: (result: ArchiveReviewResult) => void;
  onCancel: () => void;
  getActTitle: (actId: string) => Promise<string | null>;
}

/**
 * Creates the archive review overlay.
 */
export function createArchiveReviewOverlay(
  callbacks: ArchiveReviewOverlayCallbacks
): {
  show: (preview: ArchivePreview) => void;
  hide: () => void;
  container: HTMLElement;
} {
  // Overlay container (full screen backdrop)
  const container = el('div');
  container.className = 'archive-review-overlay';
  container.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.85);
    display: none;
    justify-content: center;
    align-items: center;
    z-index: 10000;
    padding: 20px;
  `;

  // Modal content
  const modal = el('div');
  modal.className = 'archive-review-modal';
  modal.style.cssText = `
    background: #1a1a2e;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    width: 100%;
    max-width: 700px;
    max-height: 90vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  `;

  // Header
  const header = el('div');
  header.style.cssText = `
    padding: 20px 24px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(0, 0, 0, 0.2);
  `;

  const headerTitle = el('h2');
  headerTitle.style.cssText = `
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 10px;
  `;
  headerTitle.innerHTML = `<span>📦</span> Review Archive`;

  const headerSubtitle = el('p');
  headerSubtitle.style.cssText = `
    margin: 6px 0 0 0;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.5);
  `;
  headerSubtitle.textContent = 'Review what will be saved and provide feedback';

  header.appendChild(headerTitle);
  header.appendChild(headerSubtitle);

  // Scrollable content area
  const content = el('div');
  content.className = 'archive-review-content';
  content.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 24px;
  `;

  // Footer with actions
  const footer = el('div');
  footer.style.cssText = `
    padding: 16px 24px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(0, 0, 0, 0.2);
    display: flex;
    justify-content: space-between;
    align-items: center;
  `;

  modal.appendChild(header);
  modal.appendChild(content);
  modal.appendChild(footer);
  container.appendChild(modal);

  // State for the current review
  let currentPreview: ArchivePreview | null = null;
  let currentRating: number | null = null;
  let approvedEntryIndices: Set<number> = new Set();

  // Build the content for a preview
  async function buildContent(preview: ArchivePreview): Promise<void> {
    content.innerHTML = '';
    currentPreview = preview;
    currentRating = null;
    approvedEntryIndices = new Set(preview.knowledge_entries.map((_, i) => i));

    // Title section (editable)
    const titleSection = el('div');
    titleSection.style.cssText = `margin-bottom: 20px;`;

    const titleLabel = el('label');
    titleLabel.style.cssText = `
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.6);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    `;
    titleLabel.textContent = 'Title';

    const titleInput = el('input') as HTMLInputElement;
    titleInput.type = 'text';
    titleInput.value = preview.title;
    titleInput.className = 'archive-title-input';
    titleInput.style.cssText = `
      width: 100%;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      color: #fff;
      font-size: 15px;
      font-weight: 500;
      outline: none;
      box-sizing: border-box;
    `;

    titleSection.appendChild(titleLabel);
    titleSection.appendChild(titleInput);
    content.appendChild(titleSection);

    // Summary section (editable)
    const summarySection = el('div');
    summarySection.style.cssText = `margin-bottom: 20px;`;

    const summaryLabel = el('label');
    summaryLabel.style.cssText = `
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.6);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    `;
    summaryLabel.textContent = 'Summary';

    const summaryTextarea = el('textarea') as HTMLTextAreaElement;
    summaryTextarea.value = preview.summary;
    summaryTextarea.className = 'archive-summary-input';
    summaryTextarea.style.cssText = `
      width: 100%;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      color: #fff;
      font-size: 14px;
      line-height: 1.5;
      min-height: 80px;
      resize: vertical;
      outline: none;
      box-sizing: border-box;
      font-family: inherit;
    `;

    summarySection.appendChild(summaryLabel);
    summarySection.appendChild(summaryTextarea);
    content.appendChild(summarySection);

    // Act linking info
    if (preview.linked_act_id) {
      const actSection = el('div');
      actSection.style.cssText = `
        margin-bottom: 20px;
        padding: 12px 16px;
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.2);
        border-radius: 8px;
      `;

      const actLabel = el('div');
      actLabel.style.cssText = `
        font-size: 12px;
        color: rgba(255, 255, 255, 0.5);
        margin-bottom: 4px;
      `;
      actLabel.textContent = 'Linked to Act';

      const actName = el('div');
      actName.style.cssText = `
        font-size: 14px;
        color: #3b82f6;
        font-weight: 500;
      `;

      // Try to get act title
      const actTitle = await callbacks.getActTitle(preview.linked_act_id);
      actName.textContent = actTitle || preview.linked_act_id;

      if (preview.linking_reason) {
        const reasonText = el('div');
        reasonText.style.cssText = `
          font-size: 12px;
          color: rgba(255, 255, 255, 0.5);
          margin-top: 6px;
          font-style: italic;
        `;
        reasonText.textContent = preview.linking_reason;
        actSection.appendChild(actLabel);
        actSection.appendChild(actName);
        actSection.appendChild(reasonText);
      } else {
        actSection.appendChild(actLabel);
        actSection.appendChild(actName);
      }

      content.appendChild(actSection);
    }

    // Knowledge entries section
    if (preview.knowledge_entries.length > 0) {
      const knowledgeSection = el('div');
      knowledgeSection.style.cssText = `margin-bottom: 20px;`;

      const knowledgeLabel = el('div');
      knowledgeLabel.style.cssText = `
        font-size: 12px;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.6);
        margin-bottom: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      `;
      knowledgeLabel.innerHTML = `
        <span>Extracted Knowledge (${preview.knowledge_entries.length})</span>
        <span style="font-size: 11px; font-weight: 400; text-transform: none; color: rgba(255,255,255,0.4);">Click to toggle</span>
      `;

      const entriesList = el('div');
      entriesList.style.cssText = `
        display: flex;
        flex-direction: column;
        gap: 8px;
      `;

      const categoryColors: Record<string, string> = {
        fact: '#22c55e',
        lesson: '#3b82f6',
        decision: '#f59e0b',
        preference: '#a855f7',
        observation: '#64748b',
      };

      preview.knowledge_entries.forEach((entry, index) => {
        const entryEl = el('div');
        entryEl.className = 'knowledge-entry';
        entryEl.dataset.index = String(index);
        const color = categoryColors[entry.category] || '#64748b';

        const updateEntryStyle = (included: boolean) => {
          entryEl.style.cssText = `
            padding: 10px 14px;
            background: ${included ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.02)'};
            border: 1px solid ${included ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.05)'};
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            opacity: ${included ? '1' : '0.5'};
          `;
        };

        updateEntryStyle(true);

        const categoryBadge = el('span');
        categoryBadge.style.cssText = `
          display: inline-block;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          padding: 2px 8px;
          border-radius: 4px;
          background: ${color}20;
          color: ${color};
          margin-bottom: 6px;
        `;
        categoryBadge.textContent = entry.category;

        const contentText = el('div');
        contentText.style.cssText = `
          font-size: 13px;
          color: rgba(255, 255, 255, 0.9);
          line-height: 1.4;
        `;
        contentText.textContent = entry.content;

        const checkIcon = el('span');
        checkIcon.className = 'entry-check';
        checkIcon.style.cssText = `
          position: absolute;
          right: 12px;
          top: 50%;
          transform: translateY(-50%);
          font-size: 14px;
        `;
        checkIcon.textContent = '✓';

        entryEl.style.position = 'relative';
        entryEl.appendChild(categoryBadge);
        entryEl.appendChild(contentText);
        entryEl.appendChild(checkIcon);

        entryEl.addEventListener('click', () => {
          if (approvedEntryIndices.has(index)) {
            approvedEntryIndices.delete(index);
            updateEntryStyle(false);
            checkIcon.textContent = '';
          } else {
            approvedEntryIndices.add(index);
            updateEntryStyle(true);
            checkIcon.textContent = '✓';
          }
        });

        entriesList.appendChild(entryEl);
      });

      knowledgeSection.appendChild(knowledgeLabel);
      knowledgeSection.appendChild(entriesList);
      content.appendChild(knowledgeSection);
    }

    // Additional notes section
    const notesSection = el('div');
    notesSection.style.cssText = `margin-bottom: 20px;`;

    const notesLabel = el('label');
    notesLabel.style.cssText = `
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.6);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    `;
    notesLabel.textContent = 'Add Additional Notes (Optional)';

    const notesTextarea = el('textarea') as HTMLTextAreaElement;
    notesTextarea.placeholder = 'Add any additional context or memories you want to save...';
    notesTextarea.className = 'archive-notes-input';
    notesTextarea.style.cssText = `
      width: 100%;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      color: #fff;
      font-size: 14px;
      line-height: 1.5;
      min-height: 60px;
      resize: vertical;
      outline: none;
      box-sizing: border-box;
      font-family: inherit;
    `;

    notesSection.appendChild(notesLabel);
    notesSection.appendChild(notesTextarea);
    content.appendChild(notesSection);

    // Rating section
    const ratingSection = el('div');
    ratingSection.style.cssText = `
      padding: 16px;
      background: rgba(147, 51, 234, 0.1);
      border: 1px solid rgba(147, 51, 234, 0.2);
      border-radius: 12px;
    `;

    const ratingLabel = el('div');
    ratingLabel.style.cssText = `
      font-size: 13px;
      color: rgba(255, 255, 255, 0.8);
      margin-bottom: 12px;
      text-align: center;
    `;
    ratingLabel.textContent = 'How well did the AI extract knowledge from this conversation?';

    const ratingButtons = el('div');
    ratingButtons.style.cssText = `
      display: flex;
      justify-content: center;
      gap: 12px;
    `;

    const thumbsDown = el('button');
    thumbsDown.className = 'rating-btn thumbs-down';
    thumbsDown.style.cssText = `
      padding: 10px 20px;
      background: rgba(239, 68, 68, 0.1);
      border: 2px solid rgba(239, 68, 68, 0.3);
      border-radius: 8px;
      color: #ef4444;
      font-size: 20px;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 8px;
    `;
    thumbsDown.innerHTML = `<span>👎</span><span style="font-size: 13px;">Needs Work</span>`;

    const thumbsUp = el('button');
    thumbsUp.className = 'rating-btn thumbs-up';
    thumbsUp.style.cssText = `
      padding: 10px 20px;
      background: rgba(34, 197, 94, 0.1);
      border: 2px solid rgba(34, 197, 94, 0.3);
      border-radius: 8px;
      color: #22c55e;
      font-size: 20px;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 8px;
    `;
    thumbsUp.innerHTML = `<span>👍</span><span style="font-size: 13px;">Good Job</span>`;

    const updateRatingStyles = () => {
      if (currentRating === 2) {
        thumbsDown.style.background = 'rgba(239, 68, 68, 0.3)';
        thumbsDown.style.borderColor = '#ef4444';
        thumbsUp.style.background = 'rgba(34, 197, 94, 0.1)';
        thumbsUp.style.borderColor = 'rgba(34, 197, 94, 0.3)';
      } else if (currentRating === 5) {
        thumbsUp.style.background = 'rgba(34, 197, 94, 0.3)';
        thumbsUp.style.borderColor = '#22c55e';
        thumbsDown.style.background = 'rgba(239, 68, 68, 0.1)';
        thumbsDown.style.borderColor = 'rgba(239, 68, 68, 0.3)';
      } else {
        thumbsDown.style.background = 'rgba(239, 68, 68, 0.1)';
        thumbsDown.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        thumbsUp.style.background = 'rgba(34, 197, 94, 0.1)';
        thumbsUp.style.borderColor = 'rgba(34, 197, 94, 0.3)';
      }
    };

    thumbsDown.addEventListener('click', () => {
      currentRating = currentRating === 2 ? null : 2;
      updateRatingStyles();
    });

    thumbsUp.addEventListener('click', () => {
      currentRating = currentRating === 5 ? null : 5;
      updateRatingStyles();
    });

    ratingButtons.appendChild(thumbsDown);
    ratingButtons.appendChild(thumbsUp);
    ratingSection.appendChild(ratingLabel);
    ratingSection.appendChild(ratingButtons);
    content.appendChild(ratingSection);

    // Build footer buttons
    footer.innerHTML = '';

    const cancelBtn = el('button');
    cancelBtn.style.cssText = `
      padding: 10px 20px;
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 8px;
      color: rgba(255, 255, 255, 0.7);
      font-size: 14px;
      cursor: pointer;
      transition: all 0.2s;
    `;
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => {
      hide();
      callbacks.onCancel();
    });

    const confirmBtn = el('button');
    confirmBtn.style.cssText = `
      padding: 10px 24px;
      background: #22c55e;
      border: none;
      border-radius: 8px;
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 8px;
    `;
    confirmBtn.innerHTML = `<span>📦</span> Save Archive`;
    confirmBtn.addEventListener('click', () => {
      const titleInputEl = content.querySelector('.archive-title-input') as HTMLInputElement;
      const summaryInputEl = content.querySelector('.archive-summary-input') as HTMLTextAreaElement;
      const notesInputEl = content.querySelector('.archive-notes-input') as HTMLTextAreaElement;

      const approvedEntries = preview.knowledge_entries.filter((_, i) =>
        approvedEntryIndices.has(i)
      );

      const result: ArchiveReviewResult = {
        approved: true,
        rating: currentRating,
        additionalNotes: notesInputEl?.value || '',
        editedTitle: titleInputEl?.value || preview.title,
        editedSummary: summaryInputEl?.value || preview.summary,
        approvedEntries,
      };

      hide();
      callbacks.onConfirm(result);
    });

    footer.appendChild(cancelBtn);
    footer.appendChild(confirmBtn);
  }

  function show(preview: ArchivePreview): void {
    container.style.display = 'flex';
    void buildContent(preview);
  }

  function hide(): void {
    container.style.display = 'none';
    currentPreview = null;
    currentRating = null;
  }

  // Close on backdrop click
  container.addEventListener('click', (e) => {
    if (e.target === container) {
      hide();
      callbacks.onCancel();
    }
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && container.style.display === 'flex') {
      hide();
      callbacks.onCancel();
    }
  });

  return {
    show,
    hide,
    container,
  };
}
