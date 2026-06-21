import { connectTrackEvents, fetchTrack, saveTrack } from './bridge';
import { createReplAdapter, type ReplAdapter } from './repl';
import { StatusView } from './status';
import './styles.css';

let repl: ReplAdapter | null = null;
let applyingRemoteCode = false;

const replElement = requireElement<HTMLElement>('#repl');
const evaluateButton = requireElement<HTMLButtonElement>('#evaluate');
const stopButton = requireElement<HTMLButtonElement>('#stop');
const panicButton = requireElement<HTMLButtonElement>('#panic');
const statusElement = requireElement<HTMLElement>('#status');

function requireElement<TElement extends HTMLElement>(selector: string): TElement {
  const element = document.querySelector<TElement>(selector);
  if (!element) {
    throw new Error(`Missing required element: ${selector}`);
  }
  return element;
}

const status = new StatusView(statusElement);

async function applyTrack(code: string, autoEvaluate = false): Promise<void> {
  if (!repl) {
    status.set('Loaded. Waiting for REPL.', 'warn');
    return;
  }

  try {
    applyingRemoteCode = true;
    repl.setCode(code);
    repl.markClean();
    if (autoEvaluate) {
      await repl.evaluate();
    }
    status.set(autoEvaluate ? 'Applied and playing.' : 'Loaded. Ready to evaluate.', 'ok');
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    applyingRemoteCode = false;
  }
}

async function evaluate(): Promise<void> {
  if (!repl) {
    return;
  }

  try {
    const code = repl.getCode();
    await saveTrack(code);
    repl.markClean();
    await repl.evaluate();
    status.set(`Playing ${new Date().toLocaleTimeString()}`, 'ok');
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function stop(): Promise<void> {
  await repl?.stop();
  status.set('Stopped', 'warn');
}

async function panic(): Promise<void> {
  await stop();
  status.set('Panic stop complete. Reload the page if visuals are stuck.', 'error');
}

async function boot(): Promise<void> {
  status.set('Waiting for REPL...', 'warn');
  repl = await createReplAdapter(replElement);
  repl.onUpdate(() => {
    if (!applyingRemoteCode && repl?.isDirty()) {
      status.set('Editor changed. Evaluate to save and play.', 'warn');
    }
  });

  const track = await fetchTrack();
  await applyTrack(track.code);

  connectTrackEvents(
    (payload) => {
      applyTrack(payload.code);
    },
    () => {
      status.set('Event stream disconnected.', 'error');
    },
  );
}

evaluateButton.addEventListener('click', () => {
  evaluate();
});

stopButton.addEventListener('click', () => {
  stop();
});

panicButton.addEventListener('click', () => {
  panic();
});

boot().catch((error) => {
  status.set(error instanceof Error ? error.message : String(error), 'error');
});
