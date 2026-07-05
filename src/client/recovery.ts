export class RecoveryView {
  constructor(private readonly revertButton: HTMLButtonElement) {}

  setCanRevert(canRevert: boolean): void {
    this.revertButton.disabled = !canRevert;
    this.revertButton.title = canRevert ? 'Revert editor to the last successful evaluation' : 'No changes to revert';
  }

  onRevert(callback: () => void): void {
    this.revertButton.addEventListener('click', callback);
  }
}
