import { describe, expect, it } from 'vitest';
import { getSnapshotLabel, summarizeSnapshotChange } from '../../src/client/snapshots';
import type { StagedAgentChange } from '../../src/client/state';

describe('snapshot presentation', () => {
  it('summarizes how a snapshot changed from the previous version', () => {
    const summary = summarizeSnapshotChange('a\nnew line\nc', 'a\nold line\nc');

    expect(summary.baseline).toBe(false);
    expect(summary.additions).toBe(1);
    expect(summary.removals).toBe(1);
    expect(summary.preview).toEqual({ kind: 'add', text: 'new line' });
  });

  it('distinguishes identical snapshots and the oldest baseline', () => {
    expect(summarizeSnapshotChange('a\nb', 'a\nb').changedLines).toEqual([]);
    expect(summarizeSnapshotChange('a\nb')).toMatchObject({ baseline: true, lineCount: 2 });
  });

  it('labels evaluated agent code with its originating intent', () => {
    const change: StagedAgentChange = {
      id: 'change-1',
      runId: 'run-1',
      intent: 'Make the hats brighter',
      applyMode: 'manual',
      preAgentCode: 's("bd")',
      code: 's("bd hh")',
      explanation: 'Added a hi-hat.',
      action: 'apply',
      warnings: [],
    };

    expect(getSnapshotLabel(change.code, change)).toBe('Agent: Make the hats brighter');
    expect(getSnapshotLabel('s("bd hh").gain(.8)', change)).toBe(
      'Edited after agent: Make the hats brighter',
    );
    expect(getSnapshotLabel('s("bd")', null)).toBe('Manual evaluate');
  });
});
