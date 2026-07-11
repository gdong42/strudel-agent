export interface DiffLine {
  kind: 'same' | 'add' | 'remove';
  text: string;
}

export function computeLineDiff(before: string, after: string): DiffLine[] {
  const left = before.split('\n');
  const right = after.split('\n');
  const table = Array.from({ length: left.length + 1 }, () => Array<number>(right.length + 1).fill(0));
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      table[i][j] = left[i] === right[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      result.push({ kind: 'same', text: left[i++] });
      j += 1;
    } else if (j < right.length && (i === left.length || table[i][j + 1] >= table[i + 1][j])) {
      result.push({ kind: 'add', text: right[j++] });
    } else {
      result.push({ kind: 'remove', text: left[i++] });
    }
  }
  return result;
}

export class DiffView {
  constructor(private readonly element: HTMLElement) {}

  render(before: string, after: string): void {
    this.element.replaceChildren(
      ...computeLineDiff(before, after).map((line) => {
        const row = document.createElement('div');
        row.className = `diff-line diff-${line.kind}`;
        row.textContent = `${line.kind === 'add' ? '+' : line.kind === 'remove' ? '-' : ' '} ${line.text}`;
        return row;
      }),
    );
  }

  clear(): void {
    this.element.replaceChildren();
  }
}
