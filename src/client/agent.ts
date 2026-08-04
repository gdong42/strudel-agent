import type {
  AgentActivity,
  AgentActivityTool,
  AgentFinalChange,
  AgentQuestion,
  AgentRunPublic,
  ApplyMode,
  ChangeWarning,
} from './bridge';
import { renderMarkdownInto } from './markdown';

export interface AgentFormValue {
  intent: string;
  applyMode: ApplyMode;
}

export interface AgentQuestionAnswer {
  questionId: string;
  answer: string;
}

export class AgentPanel {
  private submitHandler: ((value: AgentFormValue) => void) | null = null;
  private undoHandler: (() => void) | null = null;
  private cancelHandler: (() => void) | null = null;
  private resetContextHandler: (() => void) | null = null;
  private answerHandler: ((value: AgentQuestionAnswer) => void) | null = null;
  private autoFireAvailable = true;
  private currentQuestion: AgentQuestion | null = null;
  private questionBusy = false;
  private questionOptionInputs: HTMLInputElement[] = [];
  private activityRunId: string | null = null;
  private activityStartedAt = 0;
  private activityCompletedAt: number | null = null;
  private activityTimer: number | null = null;
  private activityStatus: AgentRunPublic['status'] = 'running';
  private activityTurn: number | null = null;

  constructor(
    form: HTMLFormElement,
    private readonly intent: HTMLTextAreaElement,
    private readonly autoFire: HTMLInputElement,
    private readonly submit: HTMLButtonElement,
    private readonly cancel: HTMLButtonElement,
    private readonly undo: HTMLButtonElement,
    private readonly resetContext: HTMLButtonElement,
    private readonly transcript: HTMLElement,
    private readonly turnHistory: HTMLElement,
    private readonly currentTurn: HTMLElement,
    private readonly userMessage: HTMLElement,
    private readonly result: HTMLElement,
    private readonly explanation: HTMLElement,
    private readonly warnings: HTMLElement,
    private readonly diff: HTMLElement,
    private readonly activity: HTMLDetailsElement,
    private readonly activitySummary: HTMLElement,
    private readonly activityElapsed: HTMLTimeElement,
    private readonly activityList: HTMLOListElement,
    private readonly question: HTMLElement,
    private readonly questionText: HTMLElement,
    private readonly questionOptions: HTMLElement,
    questionForm: HTMLFormElement,
    private readonly questionAnswer: HTMLTextAreaElement,
    private readonly questionSubmit: HTMLButtonElement,
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
    resetContext.addEventListener('click', () => this.resetContextHandler?.());
    questionForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const question = this.currentQuestion;
      const answer = this.selectedQuestionAnswer();
      if (!question || !answer || !this.answerHandler) return;
      this.answerHandler({ questionId: question.id, answer });
    });
    this.questionAnswer.addEventListener('input', () => {
      if (this.questionAnswer.value.trim()) {
        this.questionOptionInputs.forEach((input) => { input.checked = false; });
      }
      this.updateQuestionControls();
    });
  }

  onSubmit(handler: (value: AgentFormValue) => void): void { this.submitHandler = handler; }
  onUndo(handler: () => void): void { this.undoHandler = handler; }
  onCancel(handler: () => void): void { this.cancelHandler = handler; }
  onResetContext(handler: () => void): void { this.resetContextHandler = handler; }
  onAnswer(handler: (value: AgentQuestionAnswer) => void): void { this.answerHandler = handler; }
  setBusy(busy: boolean): void {
    this.submit.disabled = busy;
    this.cancel.hidden = !busy;
    this.resetContext.disabled = busy;
    this.autoFire.disabled = busy || !this.autoFireAvailable;
  }
  disableAutoFire(): void { this.autoFire.checked = false; }
  setUndoAvailable(available: boolean): void { this.undo.disabled = !available; }
  setAutoFireAvailable(available: boolean): void {
    this.autoFireAvailable = available;
    if (!available) this.autoFire.checked = false;
    this.autoFire.disabled = !available || this.submit.disabled;
  }

  acceptSubmission(submittedIntent: string): void {
    this.showSubmission(submittedIntent);
    if (this.intent.value.trim() === submittedIntent.trim()) {
      this.intent.value = '';
    }
  }

  showSubmission(submittedIntent: string): void {
    this.userMessage.textContent = submittedIntent;
    this.userMessage.hidden = false;
    this.scrollToLatest(true);
  }

  startActivity(): void {
    this.archiveCurrentTurn();
    this.resetCurrentTurn();
    this.activityRunId = null;
    this.activityStartedAt = Math.floor(Date.now() / 1000);
    this.activityCompletedAt = null;
    this.activityStatus = 'running';
    this.activityTurn = null;
    this.activity.hidden = false;
    this.activity.open = true;
    this.activityList.replaceChildren(this.activityItem('Starting Agent Run', 'running'));
    this.startActivityTimer();
    this.renderActivitySummary();
    this.scrollToLatest(true);
  }

  showActivity(run: Pick<AgentRunPublic, 'id' | 'status' | 'activities'>): void {
    const followLatest = this.isNearLatest();
    const activities = [...(run.activities ?? [])].sort((left, right) => left.sequence - right.sequence);
    const firstStartedAt = activities[0]?.startedAt;
    if (this.activityRunId !== run.id) {
      this.activityRunId = run.id;
      this.activityStartedAt = firstStartedAt ?? Math.floor(Date.now() / 1000);
    } else if (firstStartedAt !== undefined) {
      this.activityStartedAt = Math.min(this.activityStartedAt || firstStartedAt, firstStartedAt);
    }

    this.activityStatus = run.status;
    this.activityCompletedAt = run.status === 'running'
      ? null
      : activities.reduce<number | null>((latest, item) => (
          item.completedAt === null ? latest : Math.max(latest ?? item.completedAt, item.completedAt)
        ), null) ?? Math.floor(Date.now() / 1000);
    this.activityTurn = [...activities].reverse().find((item) => item.kind === 'model_turn')?.turn ?? null;
    const visible = activities.slice(-24).map((item) => this.renderActivityItem(item));
    if (visible.length === 0 && run.status === 'running') {
      visible.push(this.activityItem('Starting Agent Run', 'running'));
    }
    this.activityList.replaceChildren(...visible);
    this.activity.hidden = visible.length === 0;
    this.activity.open = run.status === 'running';

    if (run.status === 'running') this.startActivityTimer();
    else this.stopActivityTimer();
    this.renderActivitySummary();
    this.scrollToLatest(followLatest);
  }

  clearActivity(): void {
    this.stopActivityTimer();
    this.activityRunId = null;
    this.activityStartedAt = 0;
    this.activityCompletedAt = null;
    this.activityTurn = null;
    this.activity.hidden = true;
    this.activityList.replaceChildren();
  }

  resetConversationView(): void {
    this.turnHistory.replaceChildren();
    this.resetCurrentTurn();
    this.scrollToLatest(true);
  }

  showChange(change: Pick<AgentFinalChange, 'explanation' | 'warnings'>): void {
    const followLatest = this.isNearLatest();
    renderMarkdownInto(this.explanation, change.explanation);
    this.renderWarnings(change.warnings);
    this.result.hidden = false;
    this.undo.disabled = false;
    this.scrollToLatest(followLatest);
  }

  showNoop(change: Pick<AgentFinalChange, 'explanation' | 'warnings'>): void {
    const followLatest = this.isNearLatest();
    renderMarkdownInto(this.explanation, change.explanation);
    this.renderWarnings(change.warnings);
    this.result.hidden = false;
    this.undo.disabled = true;
    this.scrollToLatest(followLatest);
  }

  showResponse(content: string): void {
    const followLatest = this.isNearLatest();
    renderMarkdownInto(this.explanation, content);
    this.warnings.replaceChildren();
    this.diff.replaceChildren();
    this.result.hidden = false;
    this.undo.disabled = true;
    this.scrollToLatest(followLatest);
  }

  clearChange(): void {
    this.result.hidden = true;
    this.explanation.textContent = '';
    this.warnings.replaceChildren();
    this.diff.replaceChildren();
    this.undo.disabled = true;
  }

  showQuestion(question: AgentQuestion): void {
    if (this.currentQuestion?.id === question.id) {
      this.question.hidden = false;
      return;
    }

    const followLatest = this.isNearLatest();
    this.currentQuestion = question;
    this.questionBusy = false;
    this.questionText.textContent = question.question;
    this.questionAnswer.value = '';
    this.questionOptionInputs = [];
    const options = question.options.map((option) => {
      const item = document.createElement('label');
      item.className = 'agent-question-option';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'agent-question-option';
      input.value = option.label;
      input.addEventListener('change', () => {
        this.questionAnswer.value = '';
        this.updateQuestionControls();
      });
      this.questionOptionInputs.push(input);

      const copy = document.createElement('span');
      copy.className = 'agent-question-option-copy';
      const label = document.createElement('strong');
      label.textContent = option.label;
      copy.append(label);
      if (option.description) {
        const description = document.createElement('span');
        description.className = 'agent-question-option-description';
        description.textContent = option.description;
        copy.append(description);
      }
      item.append(input, copy);
      return item;
    });
    this.questionOptions.replaceChildren(...options);
    this.question.hidden = false;
    this.updateQuestionControls();
    this.scrollToLatest(followLatest);
  }

  clearQuestion(): void {
    this.currentQuestion = null;
    this.questionBusy = false;
    this.questionOptionInputs = [];
    this.question.hidden = true;
    this.questionText.replaceChildren();
    this.questionOptions.replaceChildren();
    this.questionAnswer.value = '';
    this.questionSubmit.disabled = true;
  }

  setQuestionBusy(busy: boolean): void {
    this.questionBusy = busy;
    this.updateQuestionControls();
  }

  private selectedQuestionAnswer(): string | null {
    const typed = this.questionAnswer.value.trim();
    if (typed) return typed;
    return this.questionOptionInputs.find((input) => input.checked)?.value ?? null;
  }

  private updateQuestionControls(): void {
    const disabled = this.questionBusy || !this.currentQuestion;
    this.questionAnswer.disabled = disabled;
    this.questionOptionInputs.forEach((input) => { input.disabled = disabled; });
    this.questionSubmit.disabled = disabled || !this.selectedQuestionAnswer();
  }

  private renderWarnings(warnings: ChangeWarning[]): void {
    this.warnings.replaceChildren(...warnings.map((warning) => {
      const item = document.createElement('div');
      item.className = `agent-warning warning-${warning.level}`;
      item.textContent = warning.message;
      return item;
    }));
  }

  private archiveCurrentTurn(): void {
    if (this.userMessage.hidden) return;

    const archived = this.currentTurn.cloneNode(true) as HTMLElement;
    archived.removeAttribute('id');
    archived.classList.remove('agent-turn-current');
    archived.classList.add('agent-turn-archived');
    archived.querySelectorAll('[hidden]').forEach((element) => element.remove());
    archived.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'));
    archived.querySelectorAll('[aria-live]').forEach((element) => element.removeAttribute('aria-live'));
    archived.querySelectorAll('details').forEach((element) => { element.open = false; });
    this.turnHistory.append(archived);
    while (this.turnHistory.childElementCount > 20) {
      this.turnHistory.firstElementChild?.remove();
    }
  }

  private resetCurrentTurn(): void {
    this.userMessage.hidden = true;
    this.userMessage.textContent = '';
    this.clearActivity();
    this.clearQuestion();
    this.result.hidden = true;
    this.explanation.textContent = '';
    this.warnings.replaceChildren();
    this.diff.replaceChildren();
  }

  private isNearLatest(): boolean {
    return this.transcript.scrollHeight - this.transcript.scrollTop - this.transcript.clientHeight < 48;
  }

  private scrollToLatest(force = false): void {
    if (!force && !this.isNearLatest()) return;
    requestAnimationFrame(() => {
      this.transcript.scrollTop = this.transcript.scrollHeight;
    });
  }

  private renderActivityItem(activity: AgentActivity): HTMLLIElement {
    const item = this.activityItem(
      this.activityLabel(activity),
      activity.status,
      activity.kind === 'commentary',
    );
    item.dataset.kind = activity.kind;
    if (activity.kind === 'tool' && activity.tool) {
      const tool = document.createElement('code');
      tool.textContent = activity.tool;
      item.querySelector('.agent-activity-copy')?.append(tool);
    }
    if (activity.completedAt !== null && activity.completedAt > activity.startedAt) {
      const duration = document.createElement('span');
      duration.className = 'agent-activity-duration';
      duration.textContent = formatDuration(activity.completedAt - activity.startedAt);
      item.append(duration);
    }
    return item;
  }

  private activityItem(label: string, status: AgentActivity['status'], markdown = false): HTMLLIElement {
    const item = document.createElement('li');
    item.className = 'agent-activity-item';
    item.dataset.status = status;
    const marker = document.createElement('span');
    marker.className = 'agent-activity-marker';
    marker.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('div');
    copy.className = 'agent-activity-copy';
    const text = document.createElement('div');
    text.className = markdown ? 'markdown-content markdown-content-compact' : '';
    if (markdown) renderMarkdownInto(text, label);
    else text.textContent = label;
    copy.append(text);
    item.append(marker, copy);
    return item;
  }

  private activityLabel(activity: AgentActivity): string {
    if (activity.kind === 'commentary') return activity.message ?? 'Working on the request';
    if (activity.kind === 'model_turn') {
      return activity.turn === 1 ? 'Working on request' : 'Continuing request';
    }
    if (activity.kind === 'editor_update') return 'Synced editor changes';
    if (activity.kind === 'user_input') return 'Applied your clarification';
    return TOOL_ACTIVITY_LABELS[activity.tool ?? 'agent_tool'];
  }

  private startActivityTimer(): void {
    if (this.activityTimer !== null) return;
    this.activityTimer = window.setInterval(() => this.renderActivitySummary(), 1000);
  }

  private stopActivityTimer(): void {
    if (this.activityTimer === null) return;
    window.clearInterval(this.activityTimer);
    this.activityTimer = null;
  }

  private renderActivitySummary(): void {
    const labels: Record<AgentRunPublic['status'], string> = {
      running: 'Working',
      needs_input: 'Worked for',
      completed: 'Worked for',
      failed: 'Stopped after',
      cancelled: 'Cancelled after',
    };
    const turn = this.activityStatus === 'running' && this.activityTurn ? ` · Turn ${this.activityTurn}` : '';
    this.activitySummary.textContent = `${labels[this.activityStatus]}${turn}`;
    const endedAt = this.activityCompletedAt ?? Math.floor(Date.now() / 1000);
    const elapsed = Math.max(0, endedAt - this.activityStartedAt);
    this.activityElapsed.textContent = this.activityStatus === 'running'
      ? formatDuration(elapsed)
      : formatCompactDuration(elapsed);
    this.activityElapsed.dateTime = `PT${elapsed}S`;
  }
}

const TOOL_ACTIVITY_LABELS: Record<AgentActivityTool, string> = {
  inspect_diff: 'Reviewing code changes',
  validate_candidate: 'Validating Strudel code',
  lookup_strudel_docs: 'Consulting the Strudel manual',
  lookup_samples: 'Looking up declared samples',
  inspect_sample_usage: 'Checking sample usage',
  finalize_change: 'Preparing code change',
  request_user_input: 'Preparing a clarification',
  agent_tool: 'Running an agent tool',
};

function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.max(0, totalSeconds % 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatCompactDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.max(0, totalSeconds % 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
