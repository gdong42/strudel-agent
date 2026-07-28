import type { ChangeWarning } from './bridge';
import { preflightCode } from './preflight';

export interface AutoFireGate {
  armed: boolean;
  editorMatchesStage: boolean;
  code: string;
  warnings: ChangeWarning[];
}

export function getAutoFireBlockReason(gate: AutoFireGate): string | null {
  if (!gate.armed) return 'Auto Fire was disarmed before the final stage completed.';
  if (!gate.editorMatchesStage) return 'Auto Fire was blocked because the editor changed after staging.';
  if (gate.warnings.some((warning) => warning.level === 'risk')) {
    return 'Auto Fire blocked by risk warnings.';
  }

  const preflight = preflightCode(gate.code);
  if (preflight.errors.length > 0) return preflight.errors.join(' ');
  return null;
}
