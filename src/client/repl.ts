import '@strudel/repl';

type StrudelMirror = {
  code: string;
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

type StrudelEditorElement = HTMLElement & {
  editor?: StrudelMirror;
};

export interface ReplAdapter {
  getCode(): string;
  setCode(code: string): void;
  evaluate(): Promise<void>;
  stop(): Promise<void>;
  getCursor(): { offset: number };
  getSelection(): string;
  isDirty(): boolean;
  markClean(): void;
  onUpdate(callback: (code: string) => void): void;
}

export async function createReplAdapter(element: StrudelEditorElement): Promise<ReplAdapter> {
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
