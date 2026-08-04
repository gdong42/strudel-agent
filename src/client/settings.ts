import {
  fetchAgentSettings,
  testAgentProvider,
  type AgentConnection,
  type AgentRuntimeLimits,
  type AgentSettingsPayload,
} from './bridge';

const SETTINGS_KEY = 'strudel-agent.settings.v2';
const API_KEY_PREFIX = 'strudel-agent.api-key.v2.';
const DEFAULT_TOTAL_TOKEN_INPUT = 4_000_000;

export type AgentRuntimeProfiles = Record<string, AgentRuntimeLimits>;
export type AgentApiKeys = Record<string, string>;
export type AgentApiKeyPersistence = Record<string, boolean>;

interface StoredSettings {
  provider: string | null;
  model: string | null;
  rememberApiKeys: AgentApiKeyPersistence;
  runtimeProfiles: AgentRuntimeProfiles;
}

interface ConnectionFormSettings {
  provider: string | null;
  model: string | null;
}

export interface BrowserAgentSettings extends StoredSettings {
  apiKeys: AgentApiKeys;
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
  const apiKeys: AgentApiKeys = {};
  for (const [provider, remembered] of Object.entries(stored.rememberApiKeys)) {
    const value = (remembered ? local : session).getItem(apiKeyStorageKey(provider));
    if (value) apiKeys[provider] = value;
  }
  return { ...stored, apiKeys };
}

export function saveBrowserAgentSettings(
  settings: BrowserAgentSettings,
  local: Storage,
  session: Storage,
): void {
  const previous = loadStoredSettings(local);
  const providers = new Set([
    ...Object.keys(previous.rememberApiKeys),
    ...Object.keys(settings.rememberApiKeys),
    ...Object.keys(settings.apiKeys),
  ]);
  for (const provider of providers) {
    local.removeItem(apiKeyStorageKey(provider));
    session.removeItem(apiKeyStorageKey(provider));
  }
  local.setItem(SETTINGS_KEY, JSON.stringify({
    provider: settings.provider,
    model: settings.model,
    rememberApiKeys: settings.rememberApiKeys,
    runtimeProfiles: settings.runtimeProfiles,
  } satisfies StoredSettings));
  for (const [provider, apiKey] of Object.entries(settings.apiKeys)) {
    if (!apiKey) continue;
    const remembered = settings.rememberApiKeys[provider] === true;
    (remembered ? local : session).setItem(apiKeyStorageKey(provider), apiKey);
  }
}

export class SettingsPanel {
  private backend: AgentSettingsPayload | null = null;
  private settings = loadBrowserAgentSettings(localStorage, sessionStorage);
  private runtimeDrafts: AgentRuntimeProfiles = {};
  private apiKeyDrafts: AgentApiKeys = {};
  private rememberApiKeyDrafts: AgentApiKeyPersistence = {};
  private modelDrafts: Record<string, string> = {};
  private activeRuntimeKey: string | null = null;
  private activeProvider: string | null = null;
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
    provider.addEventListener('change', () => this.changeProviderSelection());
    model.addEventListener('change', () => this.changeModelSelection());
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
      apiKey: provider && this.providerRequiresKey(provider) ? this.settings.apiKeys[provider] ?? null : null,
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
    this.runtimeDrafts = cloneRuntimeProfiles(this.settings.runtimeProfiles);
    this.apiKeyDrafts = { ...this.settings.apiKeys };
    this.rememberApiKeyDrafts = { ...this.settings.rememberApiKeys };
    this.modelDrafts = {};
    const provider = this.currentProvider();
    if (this.settings.model) this.modelDrafts[provider] = this.settings.model;
    this.activeProvider = provider;
    this.model.value = this.modelDrafts[provider] ?? '';
    this.activeRuntimeKey = null;
    this.message.textContent = '';
    this.loadCredentialFields();
    this.syncKeyState();
    this.loadRuntimeFields();
    this.dialog.showModal();
  }

  private save(): void {
    this.stashRuntimeDraft();
    this.stashProviderDrafts();
    this.settings = {
      ...this.readConnectionForm(),
      apiKeys: { ...this.apiKeyDrafts },
      rememberApiKeys: { ...this.rememberApiKeyDrafts },
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
        apiKey: this.providerRequiresKey(provider) ? this.apiKey.value.trim() || null : null,
      });
      this.message.textContent = result.message;
    } catch (error) {
      this.message.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      this.testButton.disabled = false;
    }
  }

  private clearKey(): void {
    const provider = this.currentProvider();
    this.apiKey.value = '';
    delete this.apiKeyDrafts[provider];
    delete this.rememberApiKeyDrafts[provider];
    const apiKeys = { ...this.settings.apiKeys };
    const rememberApiKeys = { ...this.settings.rememberApiKeys };
    delete apiKeys[provider];
    delete rememberApiKeys[provider];
    this.settings = { ...this.settings, apiKeys, rememberApiKeys };
    saveBrowserAgentSettings(this.settings, localStorage, sessionStorage);
    this.message.textContent = 'API key cleared from this browser.';
    this.syncKeyState();
  }

  private readConnectionForm(): ConnectionFormSettings {
    return {
      provider: this.provider.value || null,
      model: this.model.value.trim() || null,
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

  private changeProviderSelection(): void {
    this.stashRuntimeDraft();
    this.stashProviderDrafts();
    this.activeProvider = this.currentProvider();
    this.model.value = this.modelDrafts[this.activeProvider] ?? '';
    this.loadCredentialFields();
    this.syncKeyState();
    this.loadRuntimeFields();
  }

  private changeModelSelection(): void {
    this.stashRuntimeDraft();
    if (this.activeProvider) this.modelDrafts[this.activeProvider] = this.model.value.trim();
    this.loadRuntimeFields();
  }

  private stashProviderDrafts(): void {
    if (!this.activeProvider) return;
    const apiKey = this.apiKey.value.trim();
    if (apiKey) this.apiKeyDrafts[this.activeProvider] = apiKey;
    else delete this.apiKeyDrafts[this.activeProvider];
    this.rememberApiKeyDrafts[this.activeProvider] = this.remember.checked;
    this.modelDrafts[this.activeProvider] = this.model.value.trim();
  }

  private loadCredentialFields(): void {
    if (!this.activeProvider) return;
    this.apiKey.value = this.apiKeyDrafts[this.activeProvider] ?? '';
    this.remember.checked = this.rememberApiKeyDrafts[this.activeProvider] === true;
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

  private currentProvider(): string {
    if (!this.backend) throw new Error('Agent settings are not loaded');
    return this.provider.value || this.backend.defaultProvider;
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
    this.clearKeyButton.disabled = !this.apiKey.value;
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
  return { provider: null, model: null, rememberApiKeys: {}, runtimeProfiles: {} };
}

function normalizeStoredSettings(value: unknown): StoredSettings {
  if (!value || typeof value !== 'object') return defaultStoredSettings();
  const candidate = value as Record<string, unknown>;
  return {
    provider: typeof candidate.provider === 'string' ? candidate.provider : null,
    model: typeof candidate.model === 'string' ? candidate.model : null,
    rememberApiKeys: normalizeApiKeyPersistence(candidate.rememberApiKeys),
    runtimeProfiles: normalizeRuntimeProfiles(candidate.runtimeProfiles),
  };
}

function loadStoredSettings(local: Storage): StoredSettings {
  try {
    const raw = local.getItem(SETTINGS_KEY);
    return raw ? normalizeStoredSettings(JSON.parse(raw)) : defaultStoredSettings();
  } catch {
    return defaultStoredSettings();
  }
}

function normalizeApiKeyPersistence(value: unknown): AgentApiKeyPersistence {
  if (!value || typeof value !== 'object') return {};
  return Object.fromEntries(
    Object.entries(value).filter(([provider, remembered]) => provider.length > 0 && typeof remembered === 'boolean'),
  );
}

function apiKeyStorageKey(provider: string): string {
  return `${API_KEY_PREFIX}${encodeURIComponent(provider)}`;
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
