import type { ApplyMode, ChangeRecord, ChangeWarning } from './bridge';

export interface AgentFormValue {
  intent: string;
  applyMode: ApplyMode;
}

export class AgentPanel {
  private submitHandler: ((value: AgentFormValue) => void) | null = null;
  private undoHandler: (() => void) | null = null;
  private cancelHandler: (() => void) | null = null;

  constructor(
    form: HTMLFormElement,
    private readonly intent: HTMLTextAreaElement,
    private readonly autoFire: HTMLInputElement,
    private readonly submit: HTMLButtonElement,
    private readonly cancel: HTMLButtonElement,
    private readonly undo: HTMLButtonElement,
    private readonly explanation: HTMLElement,
    private readonly warnings: HTMLElement,
  ) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const intent = this.intent.value.trim();
      if (!intent || !this.submitHandler) return;
      this.submitHandler({
        intent,
        applyMode: this.autoFire.checked ? 'auto' : 'manual',
      });
    });
    undo.addEventListener('click', () => this.undoHandler?.());
    cancel.addEventListener('click', () => this.cancelHandler?.());
  }

  onSubmit(handler: (value: AgentFormValue) => void): void { this.submitHandler = handler; }
  onUndo(handler: () => void): void { this.undoHandler = handler; }
  onCancel(handler: () => void): void { this.cancelHandler = handler; }
  setBusy(busy: boolean): void {
    this.submit.disabled = busy;
    this.cancel.hidden = !busy;
  }
  disableAutoFire(): void { this.autoFire.checked = false; }

  showChange(change: ChangeRecord): void {
    this.explanation.textContent = change.explanation;
    this.renderWarnings(change.warnings);
    this.undo.disabled = false;
  }

  showNoop(change: ChangeRecord): void {
    this.explanation.textContent = change.explanation;
    this.renderWarnings(change.warnings);
    this.undo.disabled = true;
  }

  clearChange(): void {
    this.explanation.textContent = 'No staged agent change.';
    this.warnings.replaceChildren();
    this.undo.disabled = true;
  }

  private renderWarnings(warnings: ChangeWarning[]): void {
    this.warnings.replaceChildren(...warnings.map((warning) => {
      const item = document.createElement('div');
      item.className = `agent-warning warning-${warning.level}`;
      item.textContent = warning.message;
      return item;
    }));
  }
}
