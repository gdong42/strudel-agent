export type StatusKind = 'idle' | 'ok' | 'warn' | 'error';

export class StatusView {
  constructor(private readonly element: HTMLElement) {}

  set(message: string, kind: StatusKind = 'idle'): void {
    this.element.textContent = message;
    this.element.dataset.status = kind;
  }
}
