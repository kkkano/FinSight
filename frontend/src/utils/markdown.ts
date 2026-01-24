export const normalizeMarkdown = (value: string): string => {
  if (!value) return '';
  let output = value;
  // Fix compacted Markdown tables emitted on a single line.
  if (/\|[-:]{3,}\|/.test(output)) {
    output = output.replace(/\|\s+\|/g, '|\n|');
  }
  return output;
};
