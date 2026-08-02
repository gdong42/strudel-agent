import {
  fetchAgentSettings,
  testAgentProvider,
  type AgentConnection,
  type AgentRuntimeLimits,
  type AgentSettingsPayload,
} from './bridge';

const SETTINGS_KEY = 'strudel-agent.settings.v1';
const LOCAL_API_KEY = 'strudel-agent.api-key.v1';
const SESSION_API_KEY = 'strudel-agent.session-api-key.v1';
const DEFAULT_TOTAL_TOKEN_INPUT = 4_000_000;

export type AgentRuntimeProfiles = Record<string, AgentRuntimeLimits>;

interface StoredSettings {
  provider: string | null;
  model: string | null;
  rememberApiKey: boolean;
  runtimeProfiles: AgentRuntimeProfiles;
}

interface ConnectionFormSettings {
  provider: string | null;
  model: string | null;
  apiKey: string | null;
  rememberApiKey: boolean;
}

export interface BrowserAgentSettings extends StoredSettings {
  apiKey: string | null;
}

export function resolveAgentModelDefault(backend: AgentSettingsPayload, provider: string): string | null {
  if (provider === backend.defaultProvider && backend.defaultModel) return backend.defaultModel;
  return backend.providers.find((item) => item.id === provider)?.defaultModel ?? null;
}

export function resolveAgentRuntimeDefault(
  backend: AgentSettingsPayload,
  provider: string,
): AgentRuntimeLimits {
  const providerDefault = backend.providers.find((item) => item.id === provider)?.defaultRuntime;
  const limits = provider === backend.defaultProvider
    ? backend.defaultRuntime
    : providerDefault ?? backend.defaultRuntime;
  return { ...limits };
}

export function resolveAgentRuntimeLimits(
  backend: AgentSettingsPayload,
  profiles: AgentRuntimeProfiles,
  provider: string,
  model: string | null,
): AgentRuntimeLimits {
  const effectiveModel = model ?? resolveAgentModelDefault(backend, provider);
  return {
    ...(profiles[runtimeProfileKey(provider, effectiveModel)] ?? resolveAgentRuntimeDefault(backend, provider)),
  };
}

export function loadBrowserAgentSettings(local: Storage, session: Storage): BrowserAgentSettings {
  let stored: StoredSettings = defaultStoredSettings();
  try {
    const raw = local.getItem(SETTINGS_KEY);
    if (raw) stored = normalizeStoredSettings(JSON.parse(raw));
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
    runtimeProfiles: settings.runtimeProfiles,
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
  private runtimeDrafts: AgentRuntimeProfiles = {};
  private activeRuntimeKey: string | null = null;
  private runtimeUsesDefault = true;

  constructor(
    private readonly dialog: HTMLDialogElement,
    openButton: HTMLButtonElement,
    closeButton: HTMLButtonElement,
    form: HTMLFormElement,
    private readonly provider: HTMLSelectElement,
    private readonly model: HTMLInputElement,
    private readonly apiKey: HTMLInputElement,
    private readonly remember: HTMLInputElement,
    private readonly maxTurns: HTMLInputElement,
    private readonly maxElapsedSeconds: HTMLInputElement,
    private readonly maxTotalTokens: HTMLInputElement,
    private readonly maxOutputTokensPerTurn: HTMLInputElement,
    private readonly unlimitedTotalTokens: HTMLInputElement,
    resetRuntimeButton: HTMLButtonElement,
    private readonly testButton: HTMLButtonElement,
    private readonly clearKeyButton: HTMLButtonElement,
    private readonly message: HTMLElement,
    private readonly summary: HTMLElement,
  ) {
    openButton.addEventListener('click', () => this.open());
    closeButton.addEventListener('click', () => dialog.close());
    provider.addEventListener('change', () => this.changeRuntimeSelection());
    model.addEventListener('change', () => this.changeRuntimeSelection());
    apiKey.addEventListener('input', () => this.syncKeyState());
    for (const input of [maxTurns, maxElapsedSeconds, maxTotalTokens, maxOutputTokensPerTurn]) {
      input.addEventListener('input', () => { this.runtimeUsesDefault = false; });
    }
    unlimitedTotalTokens.addEventListener('change', () => {
      this.runtimeUsesDefault = false;
      this.syncTotalTokenState();
    });
    resetRuntimeButton.addEventListener('click', () => this.resetRuntimeLimits());
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

  getRuntimeLimits(): AgentRuntimeLimits | null {
    if (!this.backend) return null;
    const provider = this.settings.provider ?? this.backend.defaultProvider;
    return resolveAgentRuntimeLimits(
      this.backend,
      this.settings.runtimeProfiles,
      provider,
      this.settings.model,
    );
  }

  private open(): void {
    this.provider.value = this.settings.provider ?? '';
    this.model.value = this.settings.model ?? '';
    this.apiKey.value = this.settings.apiKey ?? '';
    this.remember.checked = this.settings.rememberApiKey;
    this.runtimeDrafts = cloneRuntimeProfiles(this.settings.runtimeProfiles);
    this.activeRuntimeKey = null;
    this.message.textContent = '';
    this.syncKeyState();
    this.loadRuntimeFields();
    this.dialog.showModal();
  }

  private save(): void {
    this.stashRuntimeDraft();
    this.settings = {
      ...this.readConnectionForm(),
      runtimeProfiles: cloneRuntimeProfiles(this.runtimeDrafts),
    };
    saveBrowserAgentSettings(this.settings, localStorage, sessionStorage);
    this.renderSummary();
  }

  private async test(): Promise<void> {
    this.testButton.disabled = true;
    this.message.textContent = 'Testing connection...';
    try {
      const formSettings = this.readConnectionForm();
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

  private readConnectionForm(): ConnectionFormSettings {
    return {
      provider: this.provider.value || null,
      model: this.model.value.trim() || null,
      apiKey: this.apiKey.value.trim() || null,
      rememberApiKey: this.remember.checked,
    };
  }

  private readRuntimeFields(): AgentRuntimeLimits {
    return {
      maxTurns: positiveInteger(this.maxTurns),
      maxElapsedSeconds: positiveInteger(this.maxElapsedSeconds),
      maxTotalTokens: this.unlimitedTotalTokens.checked ? null : positiveInteger(this.maxTotalTokens),
      maxOutputTokensPerTurn: positiveInteger(this.maxOutputTokensPerTurn),
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

  private changeRuntimeSelection(): void {
    this.stashRuntimeDraft();
    this.syncKeyState();
    this.loadRuntimeFields();
  }

  private loadRuntimeFields(): void {
    if (!this.backend) return;
    const { provider, model } = this.currentFormSelection();
    const key = runtimeProfileKey(provider, model);
    const profile = this.runtimeDrafts[key];
    const limits = profile ?? resolveAgentRuntimeDefault(this.backend, provider);
    this.activeRuntimeKey = key;
    this.runtimeUsesDefault = profile === undefined;
    this.maxTurns.value = String(limits.maxTurns);
    this.maxElapsedSeconds.value = String(limits.maxElapsedSeconds);
    this.maxTotalTokens.value = String(limits.maxTotalTokens ?? DEFAULT_TOTAL_TOKEN_INPUT);
    this.maxOutputTokensPerTurn.value = String(limits.maxOutputTokensPerTurn);
    this.unlimitedTotalTokens.checked = limits.maxTotalTokens === null;
    this.syncTotalTokenState();
  }

  private stashRuntimeDraft(): void {
    if (!this.activeRuntimeKey) return;
    if (this.runtimeUsesDefault) {
      delete this.runtimeDrafts[this.activeRuntimeKey];
      return;
    }
    this.runtimeDrafts[this.activeRuntimeKey] = this.readRuntimeFields();
  }

  private resetRuntimeLimits(): void {
    if (!this.backend) return;
    if (this.activeRuntimeKey) delete this.runtimeDrafts[this.activeRuntimeKey];
    this.runtimeUsesDefault = true;
    const { provider } = this.currentFormSelection();
    const limits = resolveAgentRuntimeDefault(this.backend, provider);
    this.maxTurns.value = String(limits.maxTurns);
    this.maxElapsedSeconds.value = String(limits.maxElapsedSeconds);
    this.maxTotalTokens.value = String(limits.maxTotalTokens ?? DEFAULT_TOTAL_TOKEN_INPUT);
    this.maxOutputTokensPerTurn.value = String(limits.maxOutputTokensPerTurn);
    this.unlimitedTotalTokens.checked = limits.maxTotalTokens === null;
    this.syncTotalTokenState();
  }

  private currentFormSelection(): { provider: string; model: string | null } {
    if (!this.backend) throw new Error('Agent settings are not loaded');
    const provider = this.provider.value || this.backend.defaultProvider;
    const model = this.model.value.trim() || resolveAgentModelDefault(this.backend, provider);
    return { provider, model };
  }

  private syncTotalTokenState(): void {
    this.maxTotalTokens.disabled = this.unlimitedTotalTokens.checked;
  }

  private syncKeyState(): void {
    if (!this.backend) return;
    const selected = this.provider.value || this.backend.defaultProvider;
    const requiresKey = this.providerRequiresKey(selected);
    const defaultModel = this.providerDefaultModel(selected);
    this.apiKey.disabled = !requiresKey;
    this.remember.disabled = !requiresKey;
    this.clearKeyButton.disabled = !this.settings.apiKey && !this.apiKey.value;
    this.model.placeholder = defaultModel ? `Default: ${defaultModel}` : 'Use provider default';
  }

  private renderSummary(): void {
    if (!this.backend) return;
    const provider = this.settings.provider || this.backend.defaultProvider;
    const defaultModel = this.providerDefaultModel(provider);
    const model = this.settings.model || defaultModel;
    this.summary.textContent = model ? `${provider} / ${model}` : provider;
  }

  private providerRequiresKey(provider: string | null): boolean {
    return this.backend?.providers.find((item) => item.id === provider)?.requiresApiKey ?? false;
  }

  private providerDefaultModel(provider: string | null): string | null {
    if (!this.backend || !provider) return null;
    return resolveAgentModelDefault(this.backend, provider);
  }
}

function defaultStoredSettings(): StoredSettings {
  return { provider: null, model: null, rememberApiKey: false, runtimeProfiles: {} };
}

function normalizeStoredSettings(value: unknown): StoredSettings {
  if (!value || typeof value !== 'object') return defaultStoredSettings();
  const candidate = value as Record<string, unknown>;
  return {
    provider: typeof candidate.provider === 'string' ? candidate.provider : null,
    model: typeof candidate.model === 'string' ? candidate.model : null,
    rememberApiKey: candidate.rememberApiKey === true,
    runtimeProfiles: normalizeRuntimeProfiles(candidate.runtimeProfiles),
  };
}

function normalizeRuntimeProfiles(value: unknown): AgentRuntimeProfiles {
  if (!value || typeof value !== 'object') return {};
  const profiles: AgentRuntimeProfiles = {};
  for (const [key, candidate] of Object.entries(value)) {
    const limits = normalizeRuntimeLimits(candidate);
    if (limits) profiles[key] = limits;
  }
  return profiles;
}

function normalizeRuntimeLimits(value: unknown): AgentRuntimeLimits | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Record<string, unknown>;
  const maxTurns = positiveStoredInteger(candidate.maxTurns);
  const maxElapsedSeconds = positiveStoredInteger(candidate.maxElapsedSeconds);
  const maxOutputTokensPerTurn = positiveStoredInteger(candidate.maxOutputTokensPerTurn);
  const maxTotalTokens = candidate.maxTotalTokens === null
    ? null
    : positiveStoredInteger(candidate.maxTotalTokens);
  if (maxTurns === null || maxElapsedSeconds === null || maxOutputTokensPerTurn === null) return null;
  if (candidate.maxTotalTokens !== null && maxTotalTokens === null) return null;
  return { maxTurns, maxElapsedSeconds, maxTotalTokens, maxOutputTokensPerTurn };
}

function positiveStoredInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 ? value : null;
}

function positiveInteger(input: HTMLInputElement): number {
  const value = input.valueAsNumber;
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${input.id} requires a positive integer`);
  }
  return value;
}

function runtimeProfileKey(provider: string, model: string | null): string {
  return JSON.stringify([provider, model ?? '']);
}

function cloneRuntimeProfiles(profiles: AgentRuntimeProfiles): AgentRuntimeProfiles {
  return Object.fromEntries(Object.entries(profiles).map(([key, limits]) => [key, { ...limits }]));
}
