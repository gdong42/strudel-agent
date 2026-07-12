import {
  fetchAgentSettings,
  testAgentProvider,
  type AgentConnection,
  type AgentSettingsPayload,
} from './bridge';

const SETTINGS_KEY = 'strudel-agent.settings.v1';
const LOCAL_API_KEY = 'strudel-agent.api-key.v1';
const SESSION_API_KEY = 'strudel-agent.session-api-key.v1';

interface StoredSettings {
  provider: string | null;
  model: string | null;
  rememberApiKey: boolean;
}

export interface BrowserAgentSettings extends StoredSettings {
  apiKey: string | null;
}

export function loadBrowserAgentSettings(local: Storage, session: Storage): BrowserAgentSettings {
  let stored: StoredSettings = { provider: null, model: null, rememberApiKey: false };
  try {
    const raw = local.getItem(SETTINGS_KEY);
    if (raw) stored = { ...stored, ...JSON.parse(raw) as StoredSettings };
  } catch {
    // Corrupt browser settings fall back to backend defaults.
  }
  const apiKey = stored.rememberApiKey ? local.getItem(LOCAL_API_KEY) : session.getItem(SESSION_API_KEY);
  return { ...stored, apiKey };
}

export function saveBrowserAgentSettings(
  settings: BrowserAgentSettings,
  local: Storage,
  session: Storage,
): void {
  local.setItem(SETTINGS_KEY, JSON.stringify({
    provider: settings.provider,
    model: settings.model,
    rememberApiKey: settings.rememberApiKey,
  } satisfies StoredSettings));
  local.removeItem(LOCAL_API_KEY);
  session.removeItem(SESSION_API_KEY);
  if (!settings.apiKey) return;
  (settings.rememberApiKey ? local : session).setItem(
    settings.rememberApiKey ? LOCAL_API_KEY : SESSION_API_KEY,
    settings.apiKey,
  );
}

export class SettingsPanel {
  private backend: AgentSettingsPayload | null = null;
  private settings = loadBrowserAgentSettings(localStorage, sessionStorage);

  constructor(
    private readonly dialog: HTMLDialogElement,
    openButton: HTMLButtonElement,
    closeButton: HTMLButtonElement,
    form: HTMLFormElement,
    private readonly provider: HTMLSelectElement,
    private readonly model: HTMLInputElement,
    private readonly apiKey: HTMLInputElement,
    private readonly remember: HTMLInputElement,
    private readonly testButton: HTMLButtonElement,
    private readonly clearKeyButton: HTMLButtonElement,
    private readonly message: HTMLElement,
    private readonly summary: HTMLElement,
  ) {
    openButton.addEventListener('click', () => this.open());
    closeButton.addEventListener('click', () => dialog.close());
    provider.addEventListener('change', () => this.syncKeyState());
    apiKey.addEventListener('input', () => this.syncKeyState());
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.save();
      dialog.close();
    });
    testButton.addEventListener('click', () => { this.test(); });
    clearKeyButton.addEventListener('click', () => this.clearKey());
  }

  async initialize(): Promise<void> {
    this.backend = await fetchAgentSettings();
    this.renderProviderOptions();
    this.renderSummary();
  }

  getConnection(): AgentConnection {
    const provider = this.settings.provider ?? this.backend?.defaultProvider ?? null;
    return {
      provider: this.settings.provider,
      model: this.settings.model,
      apiKey: this.providerRequiresKey(provider) ? this.settings.apiKey : null,
    };
  }

  private open(): void {
    this.provider.value = this.settings.provider ?? '';
    this.model.value = this.settings.model ?? '';
    this.apiKey.value = this.settings.apiKey ?? '';
    this.remember.checked = this.settings.rememberApiKey;
    this.message.textContent = '';
    this.syncKeyState();
    this.dialog.showModal();
  }

  private save(): void {
    this.settings = this.readForm();
    saveBrowserAgentSettings(this.settings, localStorage, sessionStorage);
    this.renderSummary();
  }

  private async test(): Promise<void> {
    this.testButton.disabled = true;
    this.message.textContent = 'Testing connection...';
    try {
      const formSettings = this.readForm();
      const provider = formSettings.provider ?? this.backend?.defaultProvider ?? null;
      const result = await testAgentProvider({
        provider: formSettings.provider,
        model: formSettings.model,
        apiKey: this.providerRequiresKey(provider) ? formSettings.apiKey : null,
      });
      this.message.textContent = result.message;
    } catch (error) {
      this.message.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      this.testButton.disabled = false;
    }
  }

  private clearKey(): void {
    this.apiKey.value = '';
    this.settings = { ...this.settings, apiKey: null };
    saveBrowserAgentSettings(this.settings, localStorage, sessionStorage);
    this.message.textContent = 'API key cleared from this browser.';
  }

  private readForm(): BrowserAgentSettings {
    return {
      provider: this.provider.value || null,
      model: this.model.value.trim() || null,
      apiKey: this.apiKey.value.trim() || null,
      rememberApiKey: this.remember.checked,
    };
  }

  private renderProviderOptions(): void {
    if (!this.backend) return;
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = `Backend default (${this.backend.defaultProvider})`;
    const options = this.backend.providers.map((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.label;
      return option;
    });
    this.provider.replaceChildren(defaultOption, ...options);
  }

  private syncKeyState(): void {
    if (!this.backend) return;
    const selected = this.provider.value || this.backend.defaultProvider;
    const requiresKey = this.providerRequiresKey(selected);
    this.apiKey.disabled = !requiresKey;
    this.remember.disabled = !requiresKey;
    this.clearKeyButton.disabled = !this.settings.apiKey && !this.apiKey.value;
  }

  private renderSummary(): void {
    if (!this.backend) return;
    const provider = this.settings.provider || this.backend.defaultProvider;
    const model = this.settings.model || this.backend.defaultModel;
    this.summary.textContent = model ? `${provider} / ${model}` : provider;
  }

  private providerRequiresKey(provider: string | null): boolean {
    return this.backend?.providers.find((item) => item.id === provider)?.requiresApiKey ?? false;
  }
}
