import { invoke } from '@tauri-apps/api/core';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import { z } from 'zod';

import './style.css';

const JsonRpcResponseSchema = z.object({
  jsonrpc: z.literal('2.0'),
  id: z.union([z.string(), z.number(), z.null()]).optional(),
  result: z.unknown().optional(),
  error: z
    .object({
      code: z.number(),
      message: z.string(),
      data: z.unknown().optional()
    })
    .optional()
});

type ChatRespondResult = {
  answer: string;
};

// User Presence Types
type UserStatusResult = {
  has_user: boolean;
  current_user_id: string | null;
  has_session: boolean;
  session_user_id: string | null;
};

type UserRegisterResult = {
  user_id: string;
  display_name: string;
  session_id: string;
  recovery_phrase: string;
};

type UserAuthResult = {
  user_id: string;
  display_name: string;
  session_id: string;
};

type UserProfile = {
  user_id: string;
  display_name: string;
  created_at: string;
  updated_at: string;
};

type UserBio = {
  short_bio: string;
  full_bio: string;
  skills: string[];
  interests: string[];
  goals: string;
  context: string;
};

type UserCardResult = {
  profile: UserProfile;
  bio: UserBio;
  has_recovery_phrase: boolean;
  encryption_enabled: boolean;
};

type RecoveryResult = {
  user_id: string;
  display_name: string;
  session_id: string;
  warning?: string;
};

type GenerateRecoveryResult = {
  recovery_phrase: string;
  warning: string;
};

type PlayMeReadResult = {
  markdown: string;
};

type PlayActsListResult = {
  active_act_id: string | null;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

type PlayScenesListResult = {
  scenes: Array<{
    scene_id: string;
    title: string;
    intent: string;
    status: string;
    time_horizon: string;
    notes: string;
  }>;
};

type PlayBeatsListResult = {
  beats: Array<{ beat_id: string; title: string; status: string; notes: string; link: string | null }>;
};

type PlayActsCreateResult = {
  created_act_id: string;
  acts: Array<{ act_id: string; title: string; active: boolean; notes: string }>;
};

type PlayScenesMutationResult = {
  scenes: PlayScenesListResult['scenes'];
};

type PlayBeatsMutationResult = {
  beats: PlayBeatsListResult['beats'];
};

type PlayKbListResult = {
  files: string[];
};

type PlayKbReadResult = {
  path: string;
  text: string;
};

type PlayKbWritePreviewResult = {
  path: string;
  exists: boolean;
  sha256_current: string;
  expected_sha256_current: string;
  sha256_new: string;
  diff: string;
};

type PlayKbWriteApplyResult = {
  ok: boolean;
  sha256_current: string;
};

class KernelError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'KernelError';
    this.code = code;
  }
}


async function kernelRequest(method: string, params: unknown): Promise<unknown> {
  const raw = await invoke('kernel_request', { method, params });
  const parsed = JsonRpcResponseSchema.parse(raw);
  if (parsed.error) {
    throw new KernelError(parsed.error.message, parsed.error.code);
  }
  return parsed.result;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

// User state
let currentUserCard: UserCardResult | null = null;

async function checkUserStatus(): Promise<UserStatusResult> {
  return (await kernelRequest('user/status', {})) as UserStatusResult;
}

async function registerUser(displayName: string, password: string, shortBio: string): Promise<UserRegisterResult> {
  return (await kernelRequest('user/register', {
    display_name: displayName,
    password,
    short_bio: shortBio
  })) as UserRegisterResult;
}

async function authenticateUser(password: string): Promise<UserAuthResult> {
  return (await kernelRequest('user/authenticate', { password })) as UserAuthResult;
}

async function getUserCard(): Promise<UserCardResult> {
  return (await kernelRequest('user/card', {})) as UserCardResult;
}

async function updateUserProfile(updates: Partial<UserBio & { display_name: string }>): Promise<UserCardResult> {
  return (await kernelRequest('user/update_profile', updates)) as UserCardResult;
}

async function recoverAccount(recoveryPhrase: string, newPassword: string): Promise<RecoveryResult> {
  return (await kernelRequest('user/recover', {
    recovery_phrase: recoveryPhrase,
    new_password: newPassword
  })) as RecoveryResult;
}

async function logoutUser(): Promise<void> {
  await kernelRequest('user/logout', {});
}

function buildRegistrationScreen(root: HTMLElement, onComplete: () => void) {
  root.innerHTML = '';

  const container = el('div');
  container.className = 'auth-container';
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
    font-family: system-ui, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  `;

  const card = el('div');
  card.className = 'auth-card';
  card.style.cssText = `
    background: rgba(255, 255, 255, 0.95);
    border-radius: 16px;
    padding: 32px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  `;

  const title = el('h1');
  title.textContent = 'Welcome to ReOS';
  title.style.cssText = 'margin: 0 0 8px 0; font-size: 28px; color: #1a1a2e;';

  const subtitle = el('p');
  subtitle.textContent = 'Create your presence to get started';
  subtitle.style.cssText = 'margin: 0 0 24px 0; color: #666; font-size: 14px;';

  const form = el('form');
  form.style.cssText = 'display: flex; flex-direction: column; gap: 16px;';

  const nameLabel = el('label');
  nameLabel.textContent = 'Your Name';
  nameLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const nameInput = el('input') as HTMLInputElement;
  nameInput.type = 'text';
  nameInput.placeholder = 'Enter your name';
  nameInput.required = true;
  nameInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 16px;
    transition: border-color 0.2s;
  `;

  const passwordLabel = el('label');
  passwordLabel.textContent = 'Password (min 8 characters)';
  passwordLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.type = 'password';
  passwordInput.placeholder = 'Create a secure password';
  passwordInput.required = true;
  passwordInput.minLength = 8;
  passwordInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 16px;
    transition: border-color 0.2s;
  `;

  const confirmLabel = el('label');
  confirmLabel.textContent = 'Confirm Password';
  confirmLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const confirmInput = el('input') as HTMLInputElement;
  confirmInput.type = 'password';
  confirmInput.placeholder = 'Confirm your password';
  confirmInput.required = true;
  confirmInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 16px;
    transition: border-color 0.2s;
  `;

  const bioLabel = el('label');
  bioLabel.textContent = 'Short Bio (optional)';
  bioLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const bioInput = el('textarea') as HTMLTextAreaElement;
  bioInput.placeholder = 'Tell ReOS a bit about yourself...';
  bioInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 14px;
    min-height: 80px;
    resize: vertical;
  `;

  const errorDiv = el('div');
  errorDiv.style.cssText = 'color: #e53935; font-size: 14px; display: none;';

  const submitBtn = el('button') as HTMLButtonElement;
  submitBtn.type = 'submit';
  submitBtn.textContent = 'Create Account';
  submitBtn.style.cssText = `
    padding: 14px 24px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  `;

  const securityNote = el('div');
  securityNote.style.cssText = `
    margin-top: 16px;
    padding: 12px;
    background: #f5f5f5;
    border-radius: 8px;
    font-size: 12px;
    color: #666;
  `;
  securityNote.innerHTML = `
    <strong>Zero-Trust Security:</strong> Your data is encrypted with your password.
    ReOS never sees or stores your password - only you can decrypt your information.
  `;

  form.appendChild(nameLabel);
  form.appendChild(nameInput);
  form.appendChild(passwordLabel);
  form.appendChild(passwordInput);
  form.appendChild(confirmLabel);
  form.appendChild(confirmInput);
  form.appendChild(bioLabel);
  form.appendChild(bioInput);
  form.appendChild(errorDiv);
  form.appendChild(submitBtn);

  card.appendChild(title);
  card.appendChild(subtitle);
  card.appendChild(form);
  card.appendChild(securityNote);
  container.appendChild(card);
  root.appendChild(container);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorDiv.style.display = 'none';

    if (passwordInput.value !== confirmInput.value) {
      errorDiv.textContent = 'Passwords do not match';
      errorDiv.style.display = 'block';
      return;
    }

    if (passwordInput.value.length < 8) {
      errorDiv.textContent = 'Password must be at least 8 characters';
      errorDiv.style.display = 'block';
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating account...';

    try {
      const result = await registerUser(
        nameInput.value.trim(),
        passwordInput.value,
        bioInput.value.trim()
      );

      // Show recovery phrase
      buildRecoveryPhraseScreen(root, result.recovery_phrase, result.display_name, onComplete);
    } catch (err) {
      errorDiv.textContent = err instanceof Error ? err.message : 'Registration failed';
      errorDiv.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Account';
    }
  });
}

function buildRecoveryPhraseScreen(root: HTMLElement, recoveryPhrase: string, displayName: string, onComplete: () => void) {
  root.innerHTML = '';

  const container = el('div');
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
    font-family: system-ui, sans-serif;
    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  `;

  const card = el('div');
  card.style.cssText = `
    background: rgba(255, 255, 255, 0.95);
    border-radius: 16px;
    padding: 32px;
    width: 100%;
    max-width: 520px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  `;

  const title = el('h1');
  title.textContent = `Welcome, ${displayName}!`;
  title.style.cssText = 'margin: 0 0 8px 0; font-size: 28px; color: #1a1a2e;';

  const subtitle = el('p');
  subtitle.textContent = 'Your account has been created. Save your recovery phrase:';
  subtitle.style.cssText = 'margin: 0 0 24px 0; color: #666; font-size: 14px;';

  const phraseBox = el('div');
  phraseBox.style.cssText = `
    background: #f8f9fa;
    border: 2px dashed #667eea;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    font-family: 'Courier New', monospace;
    font-size: 18px;
    line-height: 1.6;
    text-align: center;
    word-spacing: 8px;
    color: #1a1a2e;
  `;
  phraseBox.textContent = recoveryPhrase;

  const warning = el('div');
  warning.style.cssText = `
    background: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 20px;
    font-size: 14px;
    color: #856404;
  `;
  warning.innerHTML = `
    <strong>Important:</strong> Write down this recovery phrase and store it securely.
    If you forget your password, this is the only way to recover your account.
    <strong>Your encrypted data will be lost during recovery.</strong>
  `;

  const confirmCheck = el('label');
  confirmCheck.style.cssText = 'display: flex; align-items: center; gap: 8px; margin-bottom: 20px; cursor: pointer;';
  const checkbox = el('input') as HTMLInputElement;
  checkbox.type = 'checkbox';
  const checkLabel = el('span');
  checkLabel.textContent = 'I have saved my recovery phrase securely';
  checkLabel.style.cssText = 'font-size: 14px; color: #333;';
  confirmCheck.appendChild(checkbox);
  confirmCheck.appendChild(checkLabel);

  const continueBtn = el('button') as HTMLButtonElement;
  continueBtn.textContent = 'Continue to ReOS';
  continueBtn.disabled = true;
  continueBtn.style.cssText = `
    width: 100%;
    padding: 14px 24px;
    background: #ccc;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: not-allowed;
    transition: all 0.2s;
  `;

  checkbox.addEventListener('change', () => {
    continueBtn.disabled = !checkbox.checked;
    continueBtn.style.background = checkbox.checked
      ? 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)'
      : '#ccc';
    continueBtn.style.cursor = checkbox.checked ? 'pointer' : 'not-allowed';
  });

  continueBtn.addEventListener('click', () => {
    if (checkbox.checked) {
      onComplete();
    }
  });

  card.appendChild(title);
  card.appendChild(subtitle);
  card.appendChild(phraseBox);
  card.appendChild(warning);
  card.appendChild(confirmCheck);
  card.appendChild(continueBtn);
  container.appendChild(card);
  root.appendChild(container);
}

function buildLoginScreen(root: HTMLElement, onComplete: () => void) {
  root.innerHTML = '';

  const container = el('div');
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
    font-family: system-ui, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  `;

  const card = el('div');
  card.style.cssText = `
    background: rgba(255, 255, 255, 0.95);
    border-radius: 16px;
    padding: 32px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  `;

  const title = el('h1');
  title.textContent = 'Welcome Back';
  title.style.cssText = 'margin: 0 0 8px 0; font-size: 28px; color: #1a1a2e;';

  const subtitle = el('p');
  subtitle.textContent = 'Enter your password to unlock ReOS';
  subtitle.style.cssText = 'margin: 0 0 24px 0; color: #666; font-size: 14px;';

  const form = el('form');
  form.style.cssText = 'display: flex; flex-direction: column; gap: 16px;';

  const passwordLabel = el('label');
  passwordLabel.textContent = 'Password';
  passwordLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.type = 'password';
  passwordInput.placeholder = 'Enter your password';
  passwordInput.required = true;
  passwordInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 16px;
  `;

  const errorDiv = el('div');
  errorDiv.style.cssText = 'color: #e53935; font-size: 14px; display: none;';

  const submitBtn = el('button') as HTMLButtonElement;
  submitBtn.type = 'submit';
  submitBtn.textContent = 'Unlock';
  submitBtn.style.cssText = `
    padding: 14px 24px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
  `;

  const forgotLink = el('button') as HTMLButtonElement;
  forgotLink.type = 'button';
  forgotLink.textContent = 'Forgot password? Use recovery phrase';
  forgotLink.style.cssText = `
    background: none;
    border: none;
    color: #667eea;
    font-size: 14px;
    cursor: pointer;
    text-decoration: underline;
    margin-top: 8px;
  `;

  form.appendChild(passwordLabel);
  form.appendChild(passwordInput);
  form.appendChild(errorDiv);
  form.appendChild(submitBtn);
  form.appendChild(forgotLink);

  card.appendChild(title);
  card.appendChild(subtitle);
  card.appendChild(form);
  container.appendChild(card);
  root.appendChild(container);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorDiv.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Unlocking...';

    try {
      await authenticateUser(passwordInput.value);
      onComplete();
    } catch (err) {
      errorDiv.textContent = err instanceof Error ? err.message : 'Authentication failed';
      errorDiv.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Unlock';
    }
  });

  forgotLink.addEventListener('click', () => {
    buildRecoveryScreen(root, onComplete);
  });
}

function buildRecoveryScreen(root: HTMLElement, onComplete: () => void) {
  root.innerHTML = '';

  const container = el('div');
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
    font-family: system-ui, sans-serif;
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  `;

  const card = el('div');
  card.style.cssText = `
    background: rgba(255, 255, 255, 0.95);
    border-radius: 16px;
    padding: 32px;
    width: 100%;
    max-width: 480px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  `;

  const title = el('h1');
  title.textContent = 'Account Recovery';
  title.style.cssText = 'margin: 0 0 8px 0; font-size: 28px; color: #1a1a2e;';

  const subtitle = el('p');
  subtitle.textContent = 'Enter your recovery phrase and a new password';
  subtitle.style.cssText = 'margin: 0 0 24px 0; color: #666; font-size: 14px;';

  const warning = el('div');
  warning.style.cssText = `
    background: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 20px;
    font-size: 13px;
    color: #856404;
  `;
  warning.textContent = 'Warning: Your encrypted bio data will be reset. This cannot be undone.';

  const form = el('form');
  form.style.cssText = 'display: flex; flex-direction: column; gap: 16px;';

  const phraseLabel = el('label');
  phraseLabel.textContent = 'Recovery Phrase (8 words)';
  phraseLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const phraseInput = el('textarea') as HTMLTextAreaElement;
  phraseInput.placeholder = 'Enter your 8-word recovery phrase';
  phraseInput.required = true;
  phraseInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 14px;
    min-height: 80px;
  `;

  const passwordLabel = el('label');
  passwordLabel.textContent = 'New Password';
  passwordLabel.style.cssText = 'font-weight: 500; font-size: 14px; color: #333;';
  const passwordInput = el('input') as HTMLInputElement;
  passwordInput.type = 'password';
  passwordInput.placeholder = 'Create a new password';
  passwordInput.required = true;
  passwordInput.minLength = 8;
  passwordInput.style.cssText = `
    padding: 12px 16px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 16px;
  `;

  const errorDiv = el('div');
  errorDiv.style.cssText = 'color: #e53935; font-size: 14px; display: none;';

  const submitBtn = el('button') as HTMLButtonElement;
  submitBtn.type = 'submit';
  submitBtn.textContent = 'Recover Account';
  submitBtn.style.cssText = `
    padding: 14px 24px;
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
  `;

  const backLink = el('button') as HTMLButtonElement;
  backLink.type = 'button';
  backLink.textContent = 'Back to login';
  backLink.style.cssText = `
    background: none;
    border: none;
    color: #667eea;
    font-size: 14px;
    cursor: pointer;
    text-decoration: underline;
    margin-top: 8px;
  `;

  form.appendChild(phraseLabel);
  form.appendChild(phraseInput);
  form.appendChild(passwordLabel);
  form.appendChild(passwordInput);
  form.appendChild(errorDiv);
  form.appendChild(submitBtn);
  form.appendChild(backLink);

  card.appendChild(title);
  card.appendChild(subtitle);
  card.appendChild(warning);
  card.appendChild(form);
  container.appendChild(card);
  root.appendChild(container);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorDiv.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Recovering...';

    try {
      await recoverAccount(phraseInput.value.trim(), passwordInput.value);
      onComplete();
    } catch (err) {
      errorDiv.textContent = err instanceof Error ? err.message : 'Recovery failed';
      errorDiv.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Recover Account';
    }
  });

  backLink.addEventListener('click', () => {
    buildLoginScreen(root, onComplete);
  });
}

async function buildUi() {
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'me') {
    void buildMeWindow();
    return;
  }
  if (query.get('view') === 'profile') {
    void buildProfileWindow();
    return;
  }

  const root = document.getElementById('app');
  if (!root) return;

  root.innerHTML = '';

  // Check user status
  try {
    const status = await checkUserStatus();

    if (!status.has_user) {
      // First time: show registration
      buildRegistrationScreen(root, () => void buildMainApp(root));
      return;
    }

    if (!status.has_session) {
      // User exists but not logged in: show login
      buildLoginScreen(root, () => void buildMainApp(root));
      return;
    }

    // User is logged in: show main app
    await buildMainApp(root);
  } catch (err) {
    // If kernel not ready, show loading then retry
    root.innerHTML = '<div style="padding: 20px;">Loading ReOS...</div>';
    setTimeout(() => void buildUi(), 1000);
  }
}

async function buildMainApp(root: HTMLElement) {
  root.innerHTML = '';

  // Load user card
  try {
    currentUserCard = await getUserCard();
  } catch {
    currentUserCard = null;
  }

  const shell = el('div');
  shell.className = 'shell';
  shell.style.display = 'flex';
  shell.style.height = '100vh';
  shell.style.fontFamily = 'system-ui, sans-serif';

  const nav = el('div');
  nav.className = 'nav';
  nav.style.width = '240px';
  nav.style.borderRight = '1px solid #ddd';
  nav.style.padding = '12px';
  nav.style.overflow = 'auto';

  const navTitle = el('div');
  navTitle.textContent = 'ReOS';
  navTitle.style.fontWeight = '600';
  navTitle.style.marginBottom = '10px';

  // User Profile Card in Nav
  const userCard = el('div');
  userCard.className = 'user-card';
  userCard.style.cssText = `
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 16px;
    color: white;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  `;
  userCard.addEventListener('mouseenter', () => {
    userCard.style.transform = 'scale(1.02)';
    userCard.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)';
  });
  userCard.addEventListener('mouseleave', () => {
    userCard.style.transform = 'scale(1)';
    userCard.style.boxShadow = 'none';
  });

  const userName = el('div');
  userName.style.cssText = 'font-weight: 600; font-size: 16px; margin-bottom: 4px;';
  userName.textContent = currentUserCard?.profile.display_name ?? 'User';

  const userBio = el('div');
  userBio.style.cssText = 'font-size: 12px; opacity: 0.9; line-height: 1.4;';
  userBio.textContent = currentUserCard?.bio.short_bio
    ? (currentUserCard.bio.short_bio.length > 60
        ? currentUserCard.bio.short_bio.substring(0, 60) + '...'
        : currentUserCard.bio.short_bio)
    : 'Click to edit your profile';

  const encryptionBadge = el('div');
  encryptionBadge.style.cssText = `
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    font-size: 10px;
    opacity: 0.8;
    background: rgba(255,255,255,0.2);
    padding: 2px 6px;
    border-radius: 4px;
  `;
  encryptionBadge.textContent = currentUserCard?.encryption_enabled ? '🔒 Encrypted' : '🔓 Not encrypted';

  userCard.appendChild(userName);
  userCard.appendChild(userBio);
  userCard.appendChild(encryptionBadge);

  userCard.addEventListener('click', () => void openProfileWindow());

  // Logout button
  const logoutBtn = el('button');
  logoutBtn.textContent = 'Lock ReOS';
  logoutBtn.style.cssText = `
    width: 100%;
    padding: 8px;
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 12px;
    cursor: pointer;
    margin-bottom: 16px;
  `;
  logoutBtn.addEventListener('click', async () => {
    await logoutUser();
    void buildUi();
  });

  const meHeader = el('div');
  meHeader.textContent = 'Me (The Play)';
  meHeader.style.marginTop = '12px';
  meHeader.style.fontWeight = '600';

  const meBtn = el('button');
  meBtn.textContent = 'Me';

  const actsHeader = el('div');
  actsHeader.textContent = 'Acts';
  actsHeader.style.marginTop = '12px';
  actsHeader.style.fontWeight = '600';

  const actsList = el('div');
  actsList.style.display = 'flex';
  actsList.style.flexDirection = 'column';
  actsList.style.gap = '6px';

  nav.appendChild(navTitle);
  nav.appendChild(userCard);
  nav.appendChild(logoutBtn);
  nav.appendChild(meHeader);
  nav.appendChild(meBtn);
  nav.appendChild(actsHeader);
  nav.appendChild(actsList);

  const center = el('div');
  center.className = 'center';
  center.style.flex = '1';
  center.style.display = 'flex';
  center.style.flexDirection = 'column';

  const chatLog = el('div');
  chatLog.className = 'chat-log';
  chatLog.style.flex = '1';
  chatLog.style.padding = '12px';
  chatLog.style.overflow = 'auto';

  const inputRow = el('div');
  inputRow.className = 'input-row';
  inputRow.style.display = 'flex';
  inputRow.style.gap = '8px';
  inputRow.style.padding = '12px';
  inputRow.style.borderTop = '1px solid #ddd';

  const input = el('input');
  input.className = 'chat-input';
  input.type = 'text';
  input.placeholder = 'Type a message…';
  input.style.flex = '1';

  const send = el('button');
  send.className = 'send-btn';
  send.textContent = 'Send';

  inputRow.appendChild(input);
  inputRow.appendChild(send);

  const inspection = el('div');
  inspection.className = 'inspection';
  inspection.style.width = '420px';
  inspection.style.borderLeft = '1px solid #ddd';
  inspection.style.margin = '0';
  inspection.style.padding = '12px';
  inspection.style.overflow = 'auto';

  const inspectionTitle = el('div');
  inspectionTitle.style.fontWeight = '600';
  inspectionTitle.style.marginBottom = '8px';
  inspectionTitle.textContent = 'Inspection';

  const inspectionBody = el('div');

  inspection.appendChild(inspectionTitle);
  inspection.appendChild(inspectionBody);

  center.appendChild(chatLog);
  center.appendChild(inputRow);

  shell.appendChild(nav);
  shell.appendChild(center);
  shell.appendChild(inspection);

  root.appendChild(shell);

  function append(role: 'user' | 'reos', text: string) {
    const row = el('div');
    row.className = `chat-row ${role}`;

    const bubble = el('div');
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function appendThinking(): { row: HTMLDivElement; bubble: HTMLDivElement } {
    const row = el('div') as HTMLDivElement;
    row.className = 'chat-row reos';

    const bubble = el('div') as HTMLDivElement;
    bubble.className = 'chat-bubble reos thinking';

    const dots = el('span') as HTMLSpanElement;
    dots.className = 'typing-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    bubble.appendChild(dots);

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
    return { row, bubble };
  }

  let activeActId: string | null = null;
  let actsCache: PlayActsListResult['acts'] = [];
  let selectedSceneId: string | null = null;
  let selectedBeatId: string | null = null;

  let scenesCache: PlayScenesListResult['scenes'] = [];
  let beatsCache: PlayBeatsListResult['beats'] = [];

  let kbSelectedPath = 'kb.md';
  let kbTextDraft = '';
  let kbPreview: PlayKbWritePreviewResult | null = null;

  function showJsonInInspector(title: string, obj: unknown) {
    inspectionTitle.textContent = title;
    inspectionBody.innerHTML = '';
    const pre = el('pre');
    pre.style.margin = '0';
    pre.textContent = JSON.stringify(obj ?? null, null, 2);
    inspectionBody.appendChild(pre);
  }

  async function openMeWindow() {
    try {
      const existing = await WebviewWindow.getByLabel('me');
      if (existing) {
        await existing.setFocus();
        return;
      }
    } catch {
      // Best effort: if getByLabel fails, fall through and create a new window.
    }

    const w = new WebviewWindow('me', {
      title: 'Me — ReOS',
      url: '/?view=me',
      width: 900,
      height: 700
    });
    void w;
  }

  meBtn.addEventListener('click', () => void openMeWindow());

  function rowHeader(title: string) {
    const h = el('div');
    h.textContent = title;
    h.style.fontWeight = '600';
    h.style.margin = '10px 0 6px';
    return h;
  }

  function label(text: string) {
    const l = el('div');
    l.textContent = text;
    l.style.fontSize = '12px';
    l.style.opacity = '0.8';
    l.style.marginBottom = '4px';
    return l;
  }

  function textInput(value: string) {
    const i = el('input') as HTMLInputElement;
    i.type = 'text';
    i.value = value;
    i.style.width = '100%';
    i.style.boxSizing = 'border-box';
    i.style.padding = '8px 10px';
    i.style.border = '1px solid rgba(209, 213, 219, 0.7)';
    i.style.borderRadius = '10px';
    i.style.background = 'rgba(255, 255, 255, 0.55)';
    return i;
  }

  function textArea(value: string, heightPx = 90) {
    const t = el('textarea') as HTMLTextAreaElement;
    t.value = value;
    t.style.width = '100%';
    t.style.boxSizing = 'border-box';
    t.style.padding = '8px 10px';
    t.style.border = '1px solid rgba(209, 213, 219, 0.7)';
    t.style.borderRadius = '10px';
    t.style.background = 'rgba(255, 255, 255, 0.55)';
    t.style.minHeight = `${heightPx}px`;
    t.style.resize = 'vertical';
    return t;
  }

  function smallButton(text: string) {
    const b = el('button') as HTMLButtonElement;
    b.textContent = text;
    b.style.padding = '8px 10px';
    b.style.border = '1px solid rgba(209, 213, 219, 0.65)';
    b.style.borderRadius = '10px';
    b.style.background = 'rgba(255, 255, 255, 0.35)';
    return b;
  }

  async function refreshBeats(actId: string, sceneId: string) {
    const res = (await kernelRequest('play/beats/list', { act_id: actId, scene_id: sceneId })) as PlayBeatsListResult;
    beatsCache = res.beats ?? [];
  }

  async function refreshKbForSelection() {
    if (!activeActId) return;
    const sceneId = selectedSceneId ?? undefined;
    const beatId = selectedBeatId ?? undefined;

    const filesRes = (await kernelRequest('play/kb/list', {
      act_id: activeActId,
      scene_id: sceneId,
      beat_id: beatId
    })) as PlayKbListResult;

    const files = filesRes.files ?? [];
    if (files.length > 0 && !files.includes(kbSelectedPath)) {
      kbSelectedPath = files[0];
    }

    try {
      const readRes = (await kernelRequest('play/kb/read', {
        act_id: activeActId,
        scene_id: sceneId,
        beat_id: beatId,
        path: kbSelectedPath
      })) as PlayKbReadResult;
      kbTextDraft = readRes.text ?? '';
    } catch {
      // If missing, keep draft as-is (acts as a create).
    }
    kbPreview = null;
  }

  function renderPlayInspector() {
    inspectionTitle.textContent = 'The Play';
    inspectionBody.innerHTML = '';

    if (!activeActId) {
      const empty = el('div');
      empty.textContent = 'Create an Act to begin.';
      empty.style.opacity = '0.8';
      inspectionBody.appendChild(empty);

      inspectionBody.appendChild(rowHeader('Act'));
      const actCreateRow = el('div');
      actCreateRow.style.display = 'flex';
      actCreateRow.style.gap = '8px';
      const actNewTitle = textInput('');
      actNewTitle.placeholder = 'New act title';
      const actCreate = smallButton('Create');
      actCreateRow.appendChild(actNewTitle);
      actCreateRow.appendChild(actCreate);
      inspectionBody.appendChild(actCreateRow);

      actCreate.addEventListener('click', () => {
        void (async () => {
          const title = actNewTitle.value.trim();
          if (!title) return;
          const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
          activeActId = res.created_act_id;
          selectedSceneId = null;
          selectedBeatId = null;
          await refreshActs();
          if (activeActId) await refreshScenes(activeActId);
        })();
      });
      return;
    }

    const activeAct = actsCache.find((a) => a.act_id === activeActId) ?? null;

    const status = el('div');
    status.style.fontSize = '12px';
    status.style.opacity = '0.85';
    status.style.marginBottom = '8px';
    status.textContent = selectedBeatId
      ? `Act → Scene → Beat`
      : selectedSceneId
        ? `Act → Scene`
        : `Act`;
    inspectionBody.appendChild(status);

    // Act editor + create
    inspectionBody.appendChild(rowHeader('Act'));

    const actTitle = textInput('');
    const actNotes = textArea('', 70);
    const actSave = smallButton('Save Act');
    const actCreateRow = el('div');
    actCreateRow.style.display = 'flex';
    actCreateRow.style.gap = '8px';
    const actNewTitle = textInput('');
    actNewTitle.placeholder = 'New act title';
    const actCreate = smallButton('Create');
    actCreateRow.appendChild(actNewTitle);
    actCreateRow.appendChild(actCreate);

    inspectionBody.appendChild(label('Title'));
    inspectionBody.appendChild(actTitle);
    inspectionBody.appendChild(label('Notes'));
    inspectionBody.appendChild(actNotes);
    inspectionBody.appendChild(actSave);
    inspectionBody.appendChild(label('Create new act'));
    inspectionBody.appendChild(actCreateRow);

    void (async () => {
      if (!activeAct) return;
      actTitle.value = activeAct.title ?? '';
      actNotes.value = activeAct.notes ?? '';
    })();

    actSave.addEventListener('click', () => {
      void (async () => {
        if (!activeActId) return;
        await kernelRequest('play/acts/update', {
          act_id: activeActId,
          title: actTitle.value,
          notes: actNotes.value
        });
        await refreshActs();
      })();
    });

    actCreate.addEventListener('click', () => {
      void (async () => {
        const title = actNewTitle.value.trim();
        if (!title) return;
        const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
        activeActId = res.created_act_id;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      })();
    });

    // Scenes section
    inspectionBody.appendChild(rowHeader('Scenes'));

    const sceneCreateTitle = textInput('');
    sceneCreateTitle.placeholder = 'New scene title';
    const sceneCreateBtn = smallButton('Create');
    const sceneCreateRow = el('div');
    sceneCreateRow.style.display = 'flex';
    sceneCreateRow.style.gap = '8px';
    sceneCreateRow.appendChild(sceneCreateTitle);
    sceneCreateRow.appendChild(sceneCreateBtn);
    inspectionBody.appendChild(sceneCreateRow);

    const scenesList = el('div');
    scenesList.style.display = 'flex';
    scenesList.style.flexDirection = 'column';
    scenesList.style.gap = '6px';
    scenesList.style.marginTop = '8px';
    inspectionBody.appendChild(scenesList);

    const sceneDetails = el('div');
    inspectionBody.appendChild(sceneDetails);

    const beatsDetails = el('div');
    inspectionBody.appendChild(beatsDetails);

    const kbSection = el('div');
    inspectionBody.appendChild(kbSection);

    const renderScenesList = () => {
      scenesList.innerHTML = '';
      if (scenesCache.length === 0) {
        const empty = el('div');
        empty.textContent = '(no scenes yet)';
        empty.style.opacity = '0.7';
        scenesList.appendChild(empty);
        return;
      }
      for (const s of scenesCache) {
        const btn = smallButton(selectedSceneId === s.scene_id ? `• ${s.title}` : s.title);
        btn.style.textAlign = 'left';
        btn.addEventListener('click', () => {
          selectedSceneId = s.scene_id;
          selectedBeatId = null;
          void (async () => {
            if (activeActId) {
              await refreshBeats(activeActId, s.scene_id);
              await refreshKbForSelection();
            }
            renderPlayInspector();
          })();
        });
        scenesList.appendChild(btn);
      }
    };

    const renderSceneDetails = () => {
      sceneDetails.innerHTML = '';
      if (!selectedSceneId) return;
      const s = scenesCache.find((x) => x.scene_id === selectedSceneId);
      if (!s) return;

      sceneDetails.appendChild(rowHeader('Scene Details'));
      const tTitle = textInput(s.title ?? '');
      const tIntent = textInput(s.intent ?? '');
      const tStatus = textInput(s.status ?? '');
      const tH = textInput(s.time_horizon ?? '');
      const tNotes = textArea(s.notes ?? '', 80);
      const save = smallButton('Save Scene');

      sceneDetails.appendChild(label('Title'));
      sceneDetails.appendChild(tTitle);
      sceneDetails.appendChild(label('Intent'));
      sceneDetails.appendChild(tIntent);
      sceneDetails.appendChild(label('Status'));
      sceneDetails.appendChild(tStatus);
      sceneDetails.appendChild(label('Time horizon'));
      sceneDetails.appendChild(tH);
      sceneDetails.appendChild(label('Notes'));
      sceneDetails.appendChild(tNotes);
      sceneDetails.appendChild(save);

      save.addEventListener('click', () => {
        void (async () => {
          if (!activeActId || !selectedSceneId) return;
          await kernelRequest('play/scenes/update', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title: tTitle.value,
            intent: tIntent.value,
            status: tStatus.value,
            time_horizon: tH.value,
            notes: tNotes.value
          });
          await refreshScenes(activeActId);
          renderPlayInspector();
        })();
      });
    };

    const renderBeats = () => {
      beatsDetails.innerHTML = '';
      if (!activeActId || !selectedSceneId) return;

      beatsDetails.appendChild(rowHeader('Beats'));

      const createRow = el('div');
      createRow.style.display = 'flex';
      createRow.style.gap = '8px';
      const newTitle = textInput('');
      newTitle.placeholder = 'New beat title';
      const newStatus = textInput('');
      newStatus.placeholder = 'status';
      const createBtn = smallButton('Create');
      createRow.appendChild(newTitle);
      createRow.appendChild(newStatus);
      createRow.appendChild(createBtn);
      beatsDetails.appendChild(createRow);

      const list = el('div');
      list.style.display = 'flex';
      list.style.flexDirection = 'column';
      list.style.gap = '6px';
      list.style.marginTop = '8px';
      beatsDetails.appendChild(list);

      const detail = el('div');
      beatsDetails.appendChild(detail);

      const renderList = () => {
        list.innerHTML = '';
        if (beatsCache.length === 0) {
          const empty = el('div');
          empty.textContent = '(no beats yet)';
          empty.style.opacity = '0.7';
          list.appendChild(empty);
          return;
        }
        for (const b of beatsCache) {
          const btn = smallButton(selectedBeatId === b.beat_id ? `• ${b.title}` : b.title);
          btn.style.textAlign = 'left';
          btn.addEventListener('click', () => {
            selectedBeatId = b.beat_id;
            void (async () => {
              await refreshKbForSelection();
              renderPlayInspector();
            })();
          });
          list.appendChild(btn);
        }
      };

      const renderDetail = () => {
        detail.innerHTML = '';
        if (!selectedBeatId) return;
        const b = beatsCache.find((x) => x.beat_id === selectedBeatId);
        if (!b) return;

        detail.appendChild(rowHeader('Beat Details'));
        const tTitle = textInput(b.title ?? '');
        const tStatus = textInput(b.status ?? '');
        const tLink = textInput(b.link ?? '');
        const tNotes = textArea(b.notes ?? '', 80);
        const save = smallButton('Save Beat');

        detail.appendChild(label('Title'));
        detail.appendChild(tTitle);
        detail.appendChild(label('Status'));
        detail.appendChild(tStatus);
        detail.appendChild(label('Link'));
        detail.appendChild(tLink);
        detail.appendChild(label('Notes'));
        detail.appendChild(tNotes);
        detail.appendChild(save);

        save.addEventListener('click', () => {
          void (async () => {
            if (!activeActId || !selectedSceneId || !selectedBeatId) return;
            await kernelRequest('play/beats/update', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              title: tTitle.value,
              status: tStatus.value,
              link: tLink.value || null,
              notes: tNotes.value
            });
            await refreshBeats(activeActId, selectedSceneId);
            renderPlayInspector();
          })();
        });
      };

      createBtn.addEventListener('click', () => {
        void (async () => {
          const title = newTitle.value.trim();
          if (!title) return;
          await kernelRequest('play/beats/create', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title,
            status: newStatus.value
          });
          await refreshBeats(activeActId, selectedSceneId);
          renderPlayInspector();
        })();
      });

      renderList();
      renderDetail();
    };

    const renderKb = () => {
      kbSection.innerHTML = '';
      kbSection.appendChild(rowHeader('Mini Knowledgebase'));

      const who = el('div');
      who.style.fontSize = '12px';
      who.style.opacity = '0.8';
      who.style.marginBottom = '6px';
      who.textContent = selectedBeatId
        ? `Beat KB`
        : selectedSceneId
          ? `Scene KB`
          : `Act KB`;
      kbSection.appendChild(who);

      const fileRow = el('div');
      fileRow.style.display = 'flex';
      fileRow.style.gap = '8px';
      const pathInput = textInput(kbSelectedPath);
      const loadBtn = smallButton('Load');
      fileRow.appendChild(pathInput);
      fileRow.appendChild(loadBtn);
      kbSection.appendChild(fileRow);

      const listWrap = el('div');
      listWrap.style.display = 'flex';
      listWrap.style.flexWrap = 'wrap';
      listWrap.style.gap = '6px';
      listWrap.style.margin = '8px 0';
      kbSection.appendChild(listWrap);

      const editor = textArea(kbTextDraft, 180);
      kbSection.appendChild(editor);

      const btnRow = el('div');
      btnRow.style.display = 'flex';
      btnRow.style.gap = '8px';
      btnRow.style.marginTop = '8px';
      const previewBtn = smallButton('Preview');
      const applyBtn = smallButton('Apply');
      btnRow.appendChild(previewBtn);
      btnRow.appendChild(applyBtn);
      kbSection.appendChild(btnRow);

      const diffPre = el('pre');
      diffPre.style.whiteSpace = 'pre-wrap';
      diffPre.style.fontSize = '12px';
      diffPre.style.marginTop = '8px';
      diffPre.style.padding = '8px 10px';
      diffPre.style.borderRadius = '10px';
      diffPre.style.border = '1px solid rgba(209, 213, 219, 0.65)';
      diffPre.style.background = 'rgba(255, 255, 255, 0.35)';
      diffPre.textContent = kbPreview ? kbPreview.diff : '';
      kbSection.appendChild(diffPre);

      const errorLine = el('div');
      errorLine.style.fontSize = '12px';
      errorLine.style.marginTop = '6px';
      errorLine.style.opacity = '0.85';
      kbSection.appendChild(errorLine);

      editor.addEventListener('input', () => {
        kbTextDraft = editor.value;
      });

      pathInput.addEventListener('input', () => {
        kbSelectedPath = pathInput.value;
      });

      loadBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          kbSelectedPath = pathInput.value || 'kb.md';
          await refreshKbForSelection();
          renderPlayInspector();
        })();
      });

      previewBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          try {
            const res = (await kernelRequest('play/kb/write_preview', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value
            })) as PlayKbWritePreviewResult;
            kbPreview = res;
            diffPre.textContent = res.diff ?? '';
          } catch (e) {
            errorLine.textContent = `Preview error: ${String(e)}`;
          }
        })();
      });

      applyBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          if (!kbPreview) {
            errorLine.textContent = 'Preview first.';
            return;
          }
          try {
            const res = (await kernelRequest('play/kb/write_apply', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value,
              expected_sha256_current: kbPreview.expected_sha256_current
            })) as PlayKbWriteApplyResult;
            void res;
            await refreshKbForSelection();
            renderPlayInspector();
          } catch (e) {
            if (e instanceof KernelError && e.code === -32009) {
              errorLine.textContent = 'Conflict: file changed since preview. Re-preview to continue.';
            } else {
              errorLine.textContent = `Apply error: ${String(e)}`;
            }
          }
        })();
      });

      // Render file pills if we already have them cached.
      void (async () => {
        try {
          if (!activeActId) return;
          const filesRes = (await kernelRequest('play/kb/list', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            beat_id: selectedBeatId
          })) as PlayKbListResult;
          const files = filesRes.files ?? [];
          listWrap.innerHTML = '';
          for (const f of files) {
            const pill = smallButton(f);
            pill.addEventListener('click', () => {
              kbSelectedPath = f;
              void (async () => {
                await refreshKbForSelection();
                renderPlayInspector();
              })();
            });
            listWrap.appendChild(pill);
          }
        } catch {
          // ignore
        }
      })();
    };

    sceneCreateBtn.addEventListener('click', () => {
      void (async () => {
        const title = sceneCreateTitle.value.trim();
        if (!title) return;
        await kernelRequest('play/scenes/create', { act_id: activeActId, title });
        await refreshScenes(activeActId);
        renderPlayInspector();
      })();
    });

    renderScenesList();
    renderSceneDetails();
    renderBeats();
    void (async () => {
      await refreshKbForSelection();
      renderKb();
    })();
  }

  async function refreshActs() {
    const res = (await kernelRequest('play/acts/list', {})) as PlayActsListResult;
    activeActId = res.active_act_id ?? null;
    actsCache = res.acts ?? [];

    actsList.innerHTML = '';
    for (const a of actsCache) {
      const btn = el('button');
      btn.textContent = a.act_id === activeActId ? `• ${a.title}` : a.title;
      btn.addEventListener('click', async () => {
        const setRes = (await kernelRequest('play/acts/set_active', { act_id: a.act_id })) as PlayActsListResult;
        activeActId = setRes.active_act_id ?? null;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      });
      actsList.appendChild(btn);
    }

    if (actsCache.length === 0) {
      const empty = el('div');
      empty.textContent = '(no acts yet)';
      empty.style.opacity = '0.7';
      actsList.appendChild(empty);
    }

    renderPlayInspector();
  }

  async function refreshScenes(actId: string) {
    const res = (await kernelRequest('play/scenes/list', { act_id: actId })) as PlayScenesListResult;
    scenesCache = res.scenes ?? [];
    if (selectedSceneId && !scenesCache.some((s) => s.scene_id === selectedSceneId)) {
      selectedSceneId = null;
      selectedBeatId = null;
    }
    if (activeActId) {
      if (selectedSceneId) {
        await refreshBeats(activeActId, selectedSceneId);
      } else {
        beatsCache = [];
      }
    }
    renderPlayInspector();
  }


  async function onSend() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    append('user', text);

    // Immediately show an empty ReOS bubble with a thinking animation.
    const pending = appendThinking();

    // Ensure the browser paints the new bubbles before we start the kernel RPC.
    // Note: `requestAnimationFrame` alone can resume into a microtask that still
    // runs before paint, so we also yield a macrotask.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    try {
      const res = (await kernelRequest('chat/respond', { text })) as ChatRespondResult;
      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = res.answer ?? '(no answer)';
    } catch (e) {
      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = `Error: ${String(e)}`;
    }
  }

  send.addEventListener('click', () => void onSend());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void onSend();
  });

  // Initial load
  void (async () => {
    try {
      await refreshActs();
      if (activeActId) await refreshScenes(activeActId);
    } catch (e) {
      showJsonInInspector('Startup error', { error: String(e) });
    }
  })();
}

async function buildMeWindow() {
  const root = document.getElementById('app');
  if (!root) return;
  root.innerHTML = '';

  const wrap = el('div');
  wrap.style.padding = '12px';
  wrap.style.height = '100vh';
  wrap.style.boxSizing = 'border-box';
  wrap.style.overflow = 'auto';

  const title = el('div');
  title.textContent = 'Me (The Play)';
  title.style.fontWeight = '600';
  title.style.marginBottom = '10px';

  const body = el('pre');
  body.style.margin = '0';
  body.style.whiteSpace = 'pre-wrap';

  wrap.appendChild(title);
  wrap.appendChild(body);
  root.appendChild(wrap);

  try {
    const res = (await kernelRequest('play/me/read', {})) as PlayMeReadResult;
    body.textContent = res.markdown ?? '';
  } catch (e) {
    body.textContent = `Error: ${String(e)}`;
  }
}

async function openProfileWindow() {
  try {
    const existing = await WebviewWindow.getByLabel('profile');
    if (existing) {
      await existing.setFocus();
      return;
    }
  } catch {
    // Fall through
  }

  const w = new WebviewWindow('profile', {
    title: 'My Profile — ReOS',
    url: '/?view=profile',
    width: 700,
    height: 800
  });
  void w;
}

async function buildProfileWindow() {
  const root = document.getElementById('app');
  if (!root) return;
  root.innerHTML = '';

  const container = el('div');
  container.style.cssText = `
    padding: 24px;
    height: 100vh;
    box-sizing: border-box;
    overflow: auto;
    font-family: system-ui, sans-serif;
    background: #f8f9fa;
  `;

  const header = el('div');
  header.style.cssText = `
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  `;

  const avatar = el('div');
  avatar.style.cssText = `
    width: 80px;
    height: 80px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 32px;
    color: white;
    font-weight: 600;
  `;

  const headerInfo = el('div');
  const headerTitle = el('h1');
  headerTitle.style.cssText = 'margin: 0 0 4px 0; font-size: 24px; color: #1a1a2e;';
  const headerSub = el('div');
  headerSub.style.cssText = 'font-size: 14px; color: #666;';

  headerInfo.appendChild(headerTitle);
  headerInfo.appendChild(headerSub);
  header.appendChild(avatar);
  header.appendChild(headerInfo);

  const formCard = el('div');
  formCard.style.cssText = `
    background: white;
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  `;

  const formTitle = el('h2');
  formTitle.textContent = 'Edit Profile';
  formTitle.style.cssText = 'margin: 0 0 20px 0; font-size: 18px; color: #1a1a2e;';

  const form = el('form');
  form.style.cssText = 'display: flex; flex-direction: column; gap: 16px;';

  const createField = (labelText: string, inputEl: HTMLInputElement | HTMLTextAreaElement) => {
    const wrapper = el('div');
    const label = el('label');
    label.textContent = labelText;
    label.style.cssText = 'display: block; font-weight: 500; font-size: 14px; color: #333; margin-bottom: 6px;';
    wrapper.appendChild(label);
    wrapper.appendChild(inputEl);
    return wrapper;
  };

  const inputStyle = `
    width: 100%;
    box-sizing: border-box;
    padding: 10px 14px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 14px;
  `;

  const displayNameInput = el('input') as HTMLInputElement;
  displayNameInput.type = 'text';
  displayNameInput.style.cssText = inputStyle;

  const shortBioInput = el('textarea') as HTMLTextAreaElement;
  shortBioInput.style.cssText = inputStyle + 'min-height: 60px; resize: vertical;';

  const fullBioInput = el('textarea') as HTMLTextAreaElement;
  fullBioInput.style.cssText = inputStyle + 'min-height: 120px; resize: vertical;';

  const skillsInput = el('input') as HTMLInputElement;
  skillsInput.type = 'text';
  skillsInput.placeholder = 'Comma-separated skills';
  skillsInput.style.cssText = inputStyle;

  const interestsInput = el('input') as HTMLInputElement;
  interestsInput.type = 'text';
  interestsInput.placeholder = 'Comma-separated interests';
  interestsInput.style.cssText = inputStyle;

  const goalsInput = el('textarea') as HTMLTextAreaElement;
  goalsInput.style.cssText = inputStyle + 'min-height: 80px; resize: vertical;';

  const contextInput = el('textarea') as HTMLTextAreaElement;
  contextInput.style.cssText = inputStyle + 'min-height: 80px; resize: vertical;';
  contextInput.placeholder = 'Additional context for ReOS to understand you better...';

  form.appendChild(createField('Display Name', displayNameInput));
  form.appendChild(createField('Short Bio', shortBioInput));
  form.appendChild(createField('Full Bio', fullBioInput));
  form.appendChild(createField('Skills', skillsInput));
  form.appendChild(createField('Interests', interestsInput));
  form.appendChild(createField('Goals', goalsInput));
  form.appendChild(createField('Context for ReOS', contextInput));

  const statusDiv = el('div');
  statusDiv.style.cssText = 'font-size: 14px; min-height: 20px;';

  const saveBtn = el('button') as HTMLButtonElement;
  saveBtn.type = 'submit';
  saveBtn.textContent = 'Save Changes';
  saveBtn.style.cssText = `
    padding: 12px 24px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    align-self: flex-start;
  `;

  form.appendChild(statusDiv);
  form.appendChild(saveBtn);

  formCard.appendChild(formTitle);
  formCard.appendChild(form);

  // Security section
  const securityCard = el('div');
  securityCard.style.cssText = `
    background: white;
    border-radius: 12px;
    padding: 24px;
    margin-top: 20px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  `;

  const securityTitle = el('h2');
  securityTitle.textContent = 'Security';
  securityTitle.style.cssText = 'margin: 0 0 16px 0; font-size: 18px; color: #1a1a2e;';

  const securityNote = el('div');
  securityNote.style.cssText = `
    background: #e8f5e9;
    border: 1px solid #4caf50;
    border-radius: 8px;
    padding: 12px;
    font-size: 13px;
    color: #2e7d32;
    margin-bottom: 16px;
  `;
  securityNote.innerHTML = `
    <strong>🔒 Zero-Trust Encryption Active</strong><br>
    Your bio and personal data are encrypted with keys derived from your password.
    ReOS cannot access your data without your password.
  `;

  securityCard.appendChild(securityTitle);
  securityCard.appendChild(securityNote);

  container.appendChild(header);
  container.appendChild(formCard);
  container.appendChild(securityCard);
  root.appendChild(container);

  // Load current data
  try {
    const card = await getUserCard();

    avatar.textContent = card.profile.display_name.charAt(0).toUpperCase();
    headerTitle.textContent = card.profile.display_name;
    headerSub.textContent = `Member since ${new Date(card.profile.created_at).toLocaleDateString()}`;

    displayNameInput.value = card.profile.display_name;
    shortBioInput.value = card.bio.short_bio;
    fullBioInput.value = card.bio.full_bio;
    skillsInput.value = card.bio.skills.join(', ');
    interestsInput.value = card.bio.interests.join(', ');
    goalsInput.value = card.bio.goals;
    contextInput.value = card.bio.context;
  } catch (e) {
    statusDiv.textContent = `Error loading profile: ${String(e)}`;
    statusDiv.style.color = '#e53935';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    statusDiv.textContent = '';
    statusDiv.style.color = '';

    try {
      const skills = skillsInput.value
        .split(',')
        .map(s => s.trim())
        .filter(s => s.length > 0);
      const interests = interestsInput.value
        .split(',')
        .map(s => s.trim())
        .filter(s => s.length > 0);

      await updateUserProfile({
        display_name: displayNameInput.value.trim(),
        short_bio: shortBioInput.value,
        full_bio: fullBioInput.value,
        skills,
        interests,
        goals: goalsInput.value,
        context: contextInput.value,
      });

      statusDiv.textContent = '✓ Profile saved successfully';
      statusDiv.style.color = '#4caf50';

      // Update header
      headerTitle.textContent = displayNameInput.value.trim();
      avatar.textContent = displayNameInput.value.trim().charAt(0).toUpperCase();
    } catch (err) {
      statusDiv.textContent = `Error: ${err instanceof Error ? err.message : 'Failed to save'}`;
      statusDiv.style.color = '#e53935';
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
    }
  });
}

void buildUi();
