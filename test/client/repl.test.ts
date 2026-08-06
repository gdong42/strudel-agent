import { describe, expect, it, vi } from 'vitest';

import {
  configureEditorAppearance,
  DEFAULT_EDITOR_THEME,
  toJavaScriptStringLiteral,
} from '../../src/client/repl';

describe('Strudel REPL runtime strings', () => {
  it('uses a JavaScript string that Strudel does not parse as Mini Notation', () => {
    expect(toJavaScriptStringLiteral('/sample-library/strudel.json?v=abc')).toBe(
      "'/sample-library/strudel.json?v=abc'",
    );
  });

  it('escapes quotes and backslashes', () => {
    expect(toJavaScriptStringLiteral("it's\\local")).toBe("'it\\'s\\\\local'");
  });

  it('applies the product theme and editor navigation aids', () => {
    const editor = {
      setTheme: vi.fn(),
      setBracketMatchingEnabled: vi.fn(),
      reconfigureExtension: vi.fn(),
    };

    configureEditorAppearance(editor);

    expect(editor.setTheme).toHaveBeenCalledWith(DEFAULT_EDITOR_THEME);
    expect(editor.setBracketMatchingEnabled).toHaveBeenCalledWith(true);
    expect(editor.reconfigureExtension).toHaveBeenCalledWith('isActiveLineHighlighted', true);
  });
});
