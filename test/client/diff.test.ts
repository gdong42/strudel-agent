import { describe, expect, it } from 'vitest';
import { computeLineDiff } from '../../src/client/diff';

describe('computeLineDiff', () => {
  it('marks inserted and removed lines', () => {
    expect(computeLineDiff('a\nb', 'a\nc')).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'add', text: 'c' },
      { kind: 'remove', text: 'b' },
    ]);
  });
});
