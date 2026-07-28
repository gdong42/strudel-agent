import type { AgentFinalChange, AgentQuestion, ApplyMode, ChangeWarning } from './bridge';

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
  private answerHandler: ((value: AgentQuestionAnswer) => void) | null = null;
  private autoFireAvailable = true;
  private currentQuestion: AgentQuestion | null = null;
  private questionBusy = false;
  private questionOptionInputs: HTMLInputElement[] = [];

  constructor(
    form: HTMLFormElement,
    private readonly intent: HTMLTextAreaElement,
    private readonly autoFire: HTMLInputElement,
    private readonly submit: HTMLButtonElement,
    private readonly cancel: HTMLButtonElement,
    private readonly undo: HTMLButtonElement,
    private readonly explanation: HTMLElement,
    private readonly warnings: HTMLElement,
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
  onAnswer(handler: (value: AgentQuestionAnswer) => void): void { this.answerHandler = handler; }
  setBusy(busy: boolean): void {
    this.submit.disabled = busy;
    this.cancel.hidden = !busy;
    this.autoFire.disabled = busy || !this.autoFireAvailable;
  }
  disableAutoFire(): void { this.autoFire.checked = false; }
  setUndoAvailable(available: boolean): void { this.undo.disabled = !available; }
  setAutoFireAvailable(available: boolean): void {
    this.autoFireAvailable = available;
    if (!available) this.autoFire.checked = false;
    this.autoFire.disabled = !available || this.submit.disabled;
  }

  showChange(change: Pick<AgentFinalChange, 'explanation' | 'warnings'>): void {
    this.explanation.textContent = change.explanation;
    this.renderWarnings(change.warnings);
    this.undo.disabled = false;
  }

  showNoop(change: Pick<AgentFinalChange, 'explanation' | 'warnings'>): void {
    this.explanation.textContent = change.explanation;
    this.renderWarnings(change.warnings);
    this.undo.disabled = true;
  }

  clearChange(): void {
    this.explanation.textContent = 'No staged agent change.';
    this.warnings.replaceChildren();
    this.undo.disabled = true;
  }

  showQuestion(question: AgentQuestion): void {
    if (this.currentQuestion?.id === question.id) {
      this.question.hidden = false;
      return;
    }

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
}
