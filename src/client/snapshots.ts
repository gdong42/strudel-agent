import type { SnapshotRecord } from './bridge';

export class SnapshotListView {
  constructor(private readonly element: HTMLElement) {}

  render(snapshots: SnapshotRecord[], onRevert: (snapshotId: string) => void): void {
    this.element.replaceChildren();

    if (snapshots.length === 0) {
      this.element.textContent = 'No snapshots yet.';
      return;
    }

    for (const snapshot of snapshots) {
      const item = document.createElement('div');
      item.className = 'snapshot-item';

      const meta = document.createElement('div');
      meta.className = 'snapshot-meta';

      const label = document.createElement('strong');
      label.textContent = snapshot.label;

      const time = document.createElement('span');
      time.textContent = new Date(snapshot.createdAt).toLocaleTimeString();

      const preview = document.createElement('code');
      preview.textContent = snapshot.code.split('\n')[0] ?? '';

      meta.append(label, time, preview);

      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Revert';
      button.addEventListener('click', () => onRevert(snapshot.id));

      item.append(meta, button);
      this.element.append(item);
    }
  }
}
