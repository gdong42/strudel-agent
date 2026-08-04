type StrudelMirror = {
  code: string;
  prebaked?: Promise<unknown>;
  repl?: {
    evaluate(code: string, autostart?: boolean, shouldHush?: boolean): Promise<unknown>;
    state: { evalError?: unknown };
  };
  setCode(code: string): void;
  evaluate(): Promise<void>;
  stop(): Promise<void> | void;
  getCursorLocation?(): number;
  editor?: {
    state: {
      doc: { toString(): string };
      selection: { main: { from: number; to: number } };
      sliceDoc(from: number, to: number): string;
    };
  };
};

let strudelReplLoaded: Promise<void> | null = null;

type StrudelEditorElement = HTMLElement & {
  editor?: StrudelMirror;
};

export interface ReplAdapter {
  getCode(): string;
  setCode(code: string): void;
  evaluate(): Promise<void>;
  registerSamples(mapUrl: string): Promise<void>;
  stop(): Promise<void>;
  getCursor(): { offset: number };
  getSelection(): string;
  isDirty(): boolean;
  markClean(): void;
  onUpdate(callback: (code: string) => void): void;
}

export async function createReplAdapter(element: StrudelEditorElement): Promise<ReplAdapter> {
  await loadStrudelRepl();
  const editor = await waitForEditor(element);
  let cleanCode = editor.code;
  const updateCallbacks = new Set<(code: string) => void>();

  element.addEventListener('update', () => {
    for (const callback of updateCallbacks) {
      callback(editor.code);
    }
  });

  return {
    getCode: () => editor.code,
    setCode(code: string) {
      editor.setCode(code);
    },
    evaluate: () => editor.evaluate(),
    async registerSamples(mapUrl: string) {
      if (import.meta.env.VITE_STRUDEL_REPL_MOCK === '1') {
        const response = await fetch(mapUrl);
        if (!response.ok) throw new Error(`Sample map returned ${response.status}`);
        return;
      }
      if (!editor.repl) {
        throw new Error('Strudel runtime is unavailable');
      }
      await editor.prebaked;
      await editor.repl.evaluate(`samples(${toJavaScriptStringLiteral(mapUrl)})`, false, false);
      if (editor.repl.state.evalError) {
        throw editor.repl.state.evalError;
      }
    },
    async stop() {
      await editor.stop();
    },
    getCursor() {
      return { offset: editor.getCursorLocation?.() ?? 0 };
    },
    getSelection() {
      const state = editor.editor?.state;
      if (!state) {
        return '';
      }
      const selection = state.selection.main;
      return state.sliceDoc(selection.from, selection.to);
    },
    isDirty: () => editor.code !== cleanCode,
    markClean() {
      cleanCode = editor.code;
    },
    onUpdate(callback) {
      updateCallbacks.add(callback);
    },
  };
}

export function toJavaScriptStringLiteral(value: string): string {
  const jsonEscaped = JSON.stringify(value).slice(1, -1).replaceAll("'", "\\'");
  return `'${jsonEscaped}'`;
}

async function loadStrudelRepl(): Promise<void> {
  if (import.meta.env.VITE_STRUDEL_REPL_MOCK === '1') {
    return;
  }
  strudelReplLoaded ??= import('@strudel/repl').then(() => undefined);
  return strudelReplLoaded;
}

function waitForEditor(element: StrudelEditorElement): Promise<StrudelMirror> {
  return new Promise((resolve) => {
    const tick = () => {
      if (element.editor) {
        resolve(element.editor);
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}
