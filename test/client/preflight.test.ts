import { describe, expect, it } from 'vitest';
import { preflightCode } from '../../src/client/preflight';

describe('preflightCode', () => {
  it('rejects empty code', () => {
    const result = preflightCode('   ');

    expect(result.errors.join(' ')).toContain('empty');
  });

  it('accepts normal double-quoted mini-notation', () => {
    const result = preflightCode('s("bd hh").note("<c4 eb4>")');

    expect(result.errors).toEqual([]);
    expect(result.warnings).toEqual([]);
  });

  it('warns for single-quoted pattern strings', () => {
    const result = preflightCode("s('bd hh')");

    expect(result.errors).toEqual([]);
    expect(result.warnings.join(' ')).toContain('double quotes or backticks');
  });

  it('accepts backtick mini-notation', () => {
    const result = preflightCode('s(`bd [hh cp]`)');

    expect(result.errors).toEqual([]);
    expect(result.warnings).toEqual([]);
  });

  it('does not warn for single-quoted color strings', () => {
    const result = preflightCode("s(\"bd\").color('cyan')");

    expect(result.warnings).toEqual([]);
  });
});
