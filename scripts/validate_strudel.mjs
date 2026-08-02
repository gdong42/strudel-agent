import { parse as parseJavaScript } from 'acorn';
import { walk } from 'estree-walker';
import { parse as parseMiniNotation } from '@strudel/mini/krill-parser.js';

const MAX_ISSUES = 20;
const MAX_MESSAGE_CHARS = 500;

let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) input += chunk;

try {
  const payload = JSON.parse(input);
  if (!payload || typeof payload.code !== 'string') throw new Error('invalid validator input');
  process.stdout.write(JSON.stringify({ issues: validate(payload.code) }));
} catch (error) {
  process.stderr.write('Strudel validator protocol failure.\n');
  process.exitCode = 1;
}

function validate(code) {
  const comments = [];
  let ast;
  try {
    ast = parseJavaScript(code, {
      ecmaVersion: 2022,
      allowAwaitOutsideFunction: true,
      locations: true,
      onComment: comments,
    });
  } catch (error) {
    return [javascriptIssue(error)];
  }

  const issues = [];
  const finalStatement = ast.body.at(-1);
  if (finalStatement && !transpilesToFinalExpression(finalStatement)) {
    issues.push({
      code: 'invalid_final_expression',
      message: 'The final top-level statement must be a Strudel pattern expression.',
      line: finalStatement.loc?.start.line ?? 1,
      column: (finalStatement.loc?.start.column ?? 0) + 1,
    });
  }

  const disabledRanges = miniDisableRanges(comments, code.length);
  walk(ast, {
    enter(node, parent) {
      if (issues.length >= MAX_ISSUES) {
        this.skip();
        return;
      }
      if (miniDisabled(node.start, disabledRanges)) return;
      if (isDoubleQuotedLiteral(node)) {
        parseMiniValue(String(node.value), node.start, code, issues);
        return;
      }
      if (node.type === 'TemplateLiteral' && parent?.type !== 'TaggedTemplateExpression') {
        const raw = node.quasis[0]?.value?.raw ?? '';
        parseMiniValue(raw, node.start, code, issues);
        this.skip();
      }
    },
  });
  return issues.slice(0, MAX_ISSUES);
}

function transpilesToFinalExpression(statement) {
  if (statement.type === 'ExpressionStatement') return true;
  return statement.type === 'LabeledStatement' && statement.body?.type === 'ExpressionStatement';
}

function parseMiniValue(value, offset, userCode, issues) {
  try {
    parseMiniNotation(`"${value}"`);
  } catch (error) {
    const relative = error.location?.start?.offset ?? 0;
    const location = offsetLocation(userCode, Math.min(userCode.length, offset + relative));
    issues.push({
      code: 'mini_notation_syntax',
      message: bounded(`[mini] ${error.message || 'Invalid Mini Notation.'}`),
      line: location.line,
      column: location.column,
    });
  }
}

function javascriptIssue(error) {
  return {
    code: 'javascript_syntax',
    message: bounded(error.message || 'Invalid JavaScript syntax.'),
    line: error.loc?.line ?? 1,
    column: (error.loc?.column ?? 0) + 1,
  };
}

function isDoubleQuotedLiteral(node) {
  return node.type === 'Literal' && typeof node.value === 'string' && node.raw?.startsWith('"');
}

function miniDisableRanges(comments, codeEnd) {
  const ranges = [];
  const stack = [];
  for (const comment of comments) {
    const value = comment.value.trim();
    if (value.startsWith('mini-off')) {
      stack.push(comment.start);
    } else if (value.startsWith('mini-on')) {
      const start = stack.pop();
      if (start !== undefined) ranges.push([start, comment.end]);
    }
  }
  while (stack.length) ranges.push([stack.pop(), codeEnd]);
  return ranges;
}

function miniDisabled(offset, ranges) {
  return ranges.some(([start, end]) => offset >= start && offset < end);
}

function offsetLocation(code, offset) {
  const before = code.slice(0, offset);
  const lines = before.split('\n');
  return { line: lines.length, column: lines.at(-1).length + 1 };
}

function bounded(message) {
  const normalized = String(message).replace(/\s+/g, ' ').trim();
  return normalized.length <= MAX_MESSAGE_CHARS
    ? normalized
    : `${normalized.slice(0, MAX_MESSAGE_CHARS - 3)}...`;
}
