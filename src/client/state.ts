import type { ApplyMode, ChangeWarning, RuntimeStatePayload, SnapshotRecord, TrackPayload } from './bridge';

export interface StagedAgentChange {
  id: string | null;
  runId: string | null;
  intent: string;
  applyMode: ApplyMode;
  preAgentCode: string;
  code: string;
  explanation: string;
  action: 'apply' | 'noop';
  warnings: ChangeWarning[];
}

export interface ClientRuntimeState {
  projectId: string;
  sessionId: string;
  activeCode: string;
  editorCode: string;
  lastGoodCode: string;
  lastSnapshotId: string | null;
  preAgentCode: string | null;
  changeSet: StagedAgentChange | null;
}

export type StateListener = (state: ClientRuntimeState) => void;

export class RuntimeStateStore {
  private state: ClientRuntimeState;
  private readonly listeners = new Set<StateListener>();

  constructor(initial: RuntimeStatePayload) {
    this.state = {
      ...initial,
      lastSnapshotId: null,
      preAgentCode: null,
      changeSet: null,
    };
  }

  get(): ClientRuntimeState {
    return this.state;
  }

  subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  setEditorCode(code: string): void {
    this.update({ editorCode: code });
  }

  loadTrack(payload: TrackPayload): void {
    this.update({
      projectId: payload.projectId,
      sessionId: payload.sessionId,
      editorCode: payload.code,
    });
  }

  markEvaluated(code: string, snapshot: SnapshotRecord | null): void {
    this.update({
      activeCode: code,
      editorCode: code,
      lastGoodCode: code,
      lastSnapshotId: snapshot?.id ?? this.state.lastSnapshotId,
      preAgentCode: null,
      changeSet: null,
    });
  }

  setLatestSnapshot(snapshot: SnapshotRecord): void {
    this.update({
      activeCode: snapshot.code,
      lastGoodCode: snapshot.code,
      lastSnapshotId: snapshot.id,
    });
  }

  markReverted(snapshot: SnapshotRecord): void {
    this.update({
      activeCode: snapshot.code,
      editorCode: snapshot.code,
      lastGoodCode: snapshot.code,
      lastSnapshotId: snapshot.id,
      preAgentCode: null,
      changeSet: null,
    });
  }

  stageChange(change: StagedAgentChange): void {
    this.update({ editorCode: change.code, preAgentCode: change.preAgentCode, changeSet: change });
  }

  markStagedChangePersisted(runId: string, changeId: string): void {
    const changeSet = this.state.changeSet;
    if (!changeSet || changeSet.runId !== runId) return;
    this.update({ changeSet: { ...changeSet, id: changeId } });
  }

  undoAgentChange(code: string): void {
    this.update({ editorCode: code, preAgentCode: null, changeSet: null });
  }

  canRevert(): boolean {
    return this.state.editorCode !== this.state.lastGoodCode;
  }

  private update(next: Partial<ClientRuntimeState>): void {
    this.state = { ...this.state, ...next };
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}
