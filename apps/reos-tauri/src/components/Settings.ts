/**
 * Settings component for configuring ReOS
 */

import {
  Component,
  KernelRequestFn,
  el,
  rowHeader,
  label,
  textInput,
  smallButton
} from './types';

interface SettingsData {
  ollama_url: string;
  ollama_model: string;
  repo_path: string;
  poll_interval_seconds: number;
  commit_review_enabled: boolean;
  default_persona_id: string | null;
}

interface PersonaData {
  id: string;
  name: string;
  system_prompt: string;
}

export class Settings implements Component {
  private container: HTMLDivElement;
  private settingsData: SettingsData | null = null;
  private personas: PersonaData[] = [];

  constructor(private kernelRequest: KernelRequestFn) {
    this.container = el('div');
    this.container.className = 'settings-component';
    this.container.style.padding = '12px';
    this.container.style.overflow = 'auto';
  }

  async init(): Promise<void> {
    await this.loadSettings();
    await this.loadPersonas();
    this.renderContent();
  }

  private async loadSettings(): Promise<void> {
    try {
      const result = await this.kernelRequest('settings_get', {});
      this.settingsData = result as SettingsData;
    } catch (error) {
      console.error('Failed to load settings:', error);
      // Use defaults
      this.settingsData = {
        ollama_url: 'http://127.0.0.1:11434',
        ollama_model: '',
        repo_path: '',
        poll_interval_seconds: 30,
        commit_review_enabled: false,
        default_persona_id: null
      };
    }
  }

  private async loadPersonas(): Promise<void> {
    try {
      const result = await this.kernelRequest('personas_list', {});
      this.personas = (result as { personas: PersonaData[] }).personas || [];
    } catch (error) {
      console.error('Failed to load personas:', error);
      this.personas = [];
    }
  }

  private renderContent(): void {
    if (!this.settingsData) return;

    this.container.innerHTML = '';

    const title = el('h2');
    title.textContent = 'Settings';
    title.style.marginTop = '0';
    this.container.appendChild(title);

    // Ollama Configuration Section
    const ollamaSection = el('div');
    ollamaSection.style.marginBottom = '24px';

    ollamaSection.appendChild(rowHeader('Ollama Configuration'));

    ollamaSection.appendChild(label('Ollama URL'));
    const ollamaUrlInput = textInput(this.settingsData.ollama_url);
    ollamaSection.appendChild(ollamaUrlInput);

    ollamaSection.appendChild(label('Ollama Model'));
    const ollamaModelInput = textInput(this.settingsData.ollama_model);
    const modelHint = el('div');
    modelHint.style.fontSize = '11px';
    modelHint.style.color = '#666';
    modelHint.style.marginTop = '2px';
    modelHint.textContent = 'e.g., llama3.2:3b, qwen2.5:7b, mistral:7b';
    ollamaSection.appendChild(ollamaModelInput);
    ollamaSection.appendChild(modelHint);

    const testOllamaBtn = smallButton('Test Connection');
    testOllamaBtn.style.marginTop = '8px';
    const testResult = el('div');
    testResult.style.fontSize = '12px';
    testResult.style.marginTop = '4px';

    testOllamaBtn.addEventListener('click', async () => {
      testResult.textContent = 'Testing...';
      testResult.style.color = '#666';
      try {
        await this.kernelRequest('ollama_health', {});
        testResult.textContent = '✓ Connection successful';
        testResult.style.color = 'green';
      } catch (error) {
        testResult.textContent = `✗ Connection failed: ${error}`;
        testResult.style.color = 'red';
      }
    });

    ollamaSection.appendChild(testOllamaBtn);
    ollamaSection.appendChild(testResult);

    this.container.appendChild(ollamaSection);

    // Repository Configuration Section
    const repoSection = el('div');
    repoSection.style.marginBottom = '24px';

    repoSection.appendChild(rowHeader('Repository Configuration'));

    repoSection.appendChild(label('Repository Path'));
    const repoPathInput = textInput(this.settingsData.repo_path);
    repoSection.appendChild(repoPathInput);

    repoSection.appendChild(label('Poll Interval (seconds)'));
    const pollIntervalInput = textInput(this.settingsData.poll_interval_seconds.toString());
    pollIntervalInput.type = 'number';
    repoSection.appendChild(pollIntervalInput);

    this.container.appendChild(repoSection);

    // Agent Configuration Section
    const agentSection = el('div');
    agentSection.style.marginBottom = '24px';

    agentSection.appendChild(rowHeader('Agent Configuration'));

    agentSection.appendChild(label('Default Persona'));
    const personaSelect = el('select');
    personaSelect.style.width = '100%';
    personaSelect.style.padding = '4px';
    personaSelect.style.fontSize = '13px';

    const defaultOption = el('option');
    defaultOption.value = '';
    defaultOption.textContent = '(Default)';
    personaSelect.appendChild(defaultOption);

    for (const persona of this.personas) {
      const option = el('option');
      option.value = persona.id;
      option.textContent = persona.name;
      if (persona.id === this.settingsData.default_persona_id) {
        option.selected = true;
      }
      personaSelect.appendChild(option);
    }

    agentSection.appendChild(personaSelect);

    const commitReviewLabel = el('label');
    commitReviewLabel.style.display = 'flex';
    commitReviewLabel.style.alignItems = 'center';
    commitReviewLabel.style.marginTop = '12px';
    commitReviewLabel.style.cursor = 'pointer';

    const commitReviewCheckbox = el('input');
    commitReviewCheckbox.type = 'checkbox';
    commitReviewCheckbox.checked = this.settingsData.commit_review_enabled;
    commitReviewCheckbox.style.marginRight = '8px';

    const commitReviewText = el('span');
    commitReviewText.textContent = 'Enable commit review (background analysis)';
    commitReviewText.style.fontSize = '13px';

    commitReviewLabel.appendChild(commitReviewCheckbox);
    commitReviewLabel.appendChild(commitReviewText);
    agentSection.appendChild(commitReviewLabel);

    this.container.appendChild(agentSection);

    // Action Buttons
    const actions = el('div');
    actions.style.display = 'flex';
    actions.style.gap = '8px';
    actions.style.marginTop = '24px';

    const saveBtn = el('button');
    saveBtn.textContent = 'Save Settings';
    saveBtn.style.padding = '8px 16px';

    const cancelBtn = el('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.padding = '8px 16px';

    const saveStatus = el('div');
    saveStatus.style.fontSize = '13px';
    saveStatus.style.marginTop = '8px';

    saveBtn.addEventListener('click', async () => {
      const newSettings: SettingsData = {
        ollama_url: ollamaUrlInput.value,
        ollama_model: ollamaModelInput.value,
        repo_path: repoPathInput.value,
        poll_interval_seconds: parseInt(pollIntervalInput.value, 10),
        commit_review_enabled: commitReviewCheckbox.checked,
        default_persona_id: personaSelect.value || null
      };

      saveStatus.textContent = 'Saving...';
      saveStatus.style.color = '#666';

      try {
        await this.kernelRequest('settings_update', newSettings);
        this.settingsData = newSettings;
        saveStatus.textContent = '✓ Settings saved successfully';
        saveStatus.style.color = 'green';

        setTimeout(() => {
          saveStatus.textContent = '';
        }, 3000);
      } catch (error) {
        saveStatus.textContent = `✗ Failed to save: ${error}`;
        saveStatus.style.color = 'red';
      }
    });

    cancelBtn.addEventListener('click', () => {
      this.renderContent(); // Re-render with original data
    });

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);

    this.container.appendChild(actions);
    this.container.appendChild(saveStatus);
  }

  render(): HTMLElement {
    return this.container;
  }

  destroy(): void {
    // Cleanup if needed
  }
}
