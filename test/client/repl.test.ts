import { describe, expect, it } from 'vitest';

import { toJavaScriptStringLiteral } from '../../src/client/repl';

describe('Strudel REPL runtime strings', () => {
  it('uses a JavaScript string that Strudel does not parse as Mini Notation', () => {
    expect(toJavaScriptStringLiteral('/sample-library/strudel.json?v=abc')).toBe(
      "'/sample-library/strudel.json?v=abc'",
    );
  });

  it('escapes quotes and backslashes', () => {
    expect(toJavaScriptStringLiteral("it's\\local")).toBe("'it\\'s\\\\local'");
  });
});
