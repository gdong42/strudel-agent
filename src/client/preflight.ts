export interface PreflightResult {
  errors: string[];
  warnings: string[];
}

const SINGLE_QUOTED_PATTERN_CALL = /\b(?:s|sound|note|n)\(\s*'[^']*(?:[<>\[\]~*]|bd|sd|hh|cp)[^']*'\s*\)/;

export function preflightCode(code: string): PreflightResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!code.trim()) {
    errors.push('Refusing to evaluate empty code.');
  }

  if (SINGLE_QUOTED_PATTERN_CALL.test(code)) {
    warnings.push('Pattern-like mini-notation should use double quotes or backticks, not single quotes.');
  }

  return { errors, warnings };
}
