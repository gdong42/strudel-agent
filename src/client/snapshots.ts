import type { SnapshotRecord } from './bridge';
import { computeLineDiff, type DiffLine } from './diff';
import type { StagedAgentChange } from './state';

const SNAPSHOT_DIFF_LINE_LIMIT = 24;

export interface SnapshotChangeSummary {
  baseline: boolean;
  additions: number;
  removals: number;
  lineCount: number;
  changedLines: DiffLine[];
  preview: DiffLine | null;
}

export function summarizeSnapshotChange(code: string, previousCode?: string): SnapshotChangeSummary {
  const lineCount = code.split('\n').length;
  if (previousCode === undefined) {
    return {
      baseline: true,
      additions: 0,
      removals: 0,
      lineCount,
      changedLines: [],
      preview: null,
    };
  }

  const changedLines = computeLineDiff(previousCode, code).filter((line) => line.kind !== 'same');
  const additions = changedLines.filter((line) => line.kind === 'add').length;
  const removals = changedLines.length - additions;
  const preview = changedLines.find((line) => line.kind === 'add' && line.text.trim())
    ?? changedLines.find((line) => line.text.trim())
    ?? changedLines[0]
    ?? null;
  return { baseline: false, additions, removals, lineCount, changedLines, preview };
}

export function getSnapshotLabel(code: string, stagedChange: StagedAgentChange | null): string {
  if (!stagedChange) return 'Manual evaluate';
  const prefix = stagedChange.code === code ? 'Agent' : 'Edited after agent';
  return `${prefix}: ${stagedChange.intent.trim()}`;
}

export class SnapshotListView {
  constructor(private readonly element: HTMLElement) {}

  render(snapshots: SnapshotRecord[], onRevert: (snapshotId: string) => void | Promise<void>): void {
    this.element.replaceChildren();

    if (snapshots.length === 0) {
      this.element.textContent = 'No snapshots yet.';
      return;
    }

    snapshots.forEach((snapshot, index) => {
      const olderSnapshot = snapshots[index + 1];
      const summary = summarizeSnapshotChange(snapshot.code, olderSnapshot?.code);
      this.element.append(this.renderSnapshot(snapshot, summary, index === 0, onRevert));
    });
  }

  private renderSnapshot(
    snapshot: SnapshotRecord,
    summary: SnapshotChangeSummary,
    latest: boolean,
    onRevert: (snapshotId: string) => void,
  ): HTMLElement {
    const item = document.createElement('article');
    item.className = 'snapshot-item';

    const meta = document.createElement('div');
    meta.className = 'snapshot-meta';

    const heading = document.createElement('div');
    heading.className = 'snapshot-heading';
    const label = document.createElement('strong');
    label.textContent = snapshot.label;
    label.title = snapshot.label;
    const time = document.createElement('time');
    const createdAt = new Date(snapshot.createdAt);
    time.dateTime = createdAt.toISOString();
    time.textContent = formatSnapshotTime(createdAt);
    time.title = createdAt.toLocaleString();
    heading.append(label, time);

    const change = document.createElement('div');
    change.className = 'snapshot-change';
    if (latest) {
      const latestLabel = document.createElement('span');
      latestLabel.className = 'snapshot-latest';
      latestLabel.textContent = 'Latest';
      change.append(latestLabel);
    }
    if (summary.baseline) {
      change.append(statusText(`Baseline · ${summary.lineCount} lines`, 'snapshot-baseline'));
    } else if (summary.changedLines.length === 0) {
      change.append(statusText('No code changes', 'snapshot-unchanged'));
    } else {
      change.append(
        statusText(`+${summary.additions}`, 'snapshot-additions'),
        statusText(`-${summary.removals}`, 'snapshot-removals'),
      );
    }
    meta.append(heading, change);

    if (summary.baseline) {
      const preview = firstMeaningfulLine(snapshot.code);
      if (preview) meta.append(codePreview(preview, 'baseline'));
    } else if (summary.preview) {
      meta.append(codePreview(summary.preview.text, summary.preview.kind));
      meta.append(changedLineDetails(summary.changedLines));
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Revert';
    button.title = `Revert to ${createdAt.toLocaleString()}`;
    button.addEventListener('click', () => { void onRevert(snapshot.id); });

    item.append(meta, button);
    return item;
  }
}

function statusText(text: string, className: string): HTMLSpanElement {
  const element = document.createElement('span');
  element.className = className;
  element.textContent = text;
  return element;
}

function codePreview(text: string, kind: DiffLine['kind'] | 'baseline'): HTMLElement {
  const preview = document.createElement('code');
  preview.className = `snapshot-preview snapshot-preview-${kind}`;
  preview.textContent = `${kind === 'add' ? '+' : kind === 'remove' ? '-' : ''} ${text.trim() || '(blank line)'}`.trim();
  preview.title = text;
  return preview;
}

function changedLineDetails(lines: DiffLine[]): HTMLDetailsElement {
  const details = document.createElement('details');
  details.className = 'snapshot-diff-details';
  const control = document.createElement('summary');
  control.textContent = 'Changed lines';
  const content = document.createElement('div');
  content.className = 'snapshot-diff-lines';

  for (const line of lines.slice(0, SNAPSHOT_DIFF_LINE_LIMIT)) {
    const row = document.createElement('code');
    row.className = `snapshot-diff-line snapshot-diff-${line.kind}`;
    row.textContent = `${line.kind === 'add' ? '+' : '-'} ${line.text}`;
    content.append(row);
  }
  if (lines.length > SNAPSHOT_DIFF_LINE_LIMIT) {
    const remaining = document.createElement('span');
    remaining.className = 'snapshot-diff-more';
    remaining.textContent = `${lines.length - SNAPSHOT_DIFF_LINE_LIMIT} more changed lines`;
    content.append(remaining);
  }
  details.append(control, content);
  return details;
}

function firstMeaningfulLine(code: string): string {
  return code.split('\n').find((line) => line.trim()) ?? '';
}

function formatSnapshotTime(date: Date): string {
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
