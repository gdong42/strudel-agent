import { describe, expect, it } from 'vitest';
import { getAutoFireBlockReason } from '../../src/client/auto-fire';

describe('Auto Fire gate', () => {
  it('permits a validated, armed staged change', () => {
    expect(getAutoFireBlockReason({
      armed: true,
      editorMatchesStage: true,
      code: 's("bd*4")',
      warnings: [],
    })).toBeNull();
  });

  it('blocks disarmed, stale, risk, and invalid stages', () => {
    expect(getAutoFireBlockReason({
      armed: false,
      editorMatchesStage: true,
      code: 's("bd*4")',
      warnings: [],
    })).toContain('disarmed');
    expect(getAutoFireBlockReason({
      armed: true,
      editorMatchesStage: false,
      code: 's("bd*4")',
      warnings: [],
    })).toContain('editor changed');
    expect(getAutoFireBlockReason({
      armed: true,
      editorMatchesStage: true,
      code: 's("bd*4")',
      warnings: [{ level: 'risk', message: 'Unverified sample.', category: 'sample' }],
    })).toContain('risk warnings');
    expect(getAutoFireBlockReason({
      armed: true,
      editorMatchesStage: true,
      code: '',
      warnings: [],
    })).toContain('empty');
  });
});
