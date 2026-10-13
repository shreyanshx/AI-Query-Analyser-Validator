/** Pure helpers for exporting SQL to a downloadable .sql file. */

/**
 * Build a safe, timestamp-free export filename from a label. Non-alphanumeric
 * characters collapse to a single hyphen; the result always ends in `.sql`.
 */
export function buildExportFilename(label: string): string {
  const base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${base || 'query'}.sql`;
}

/** Trigger a browser download of `sql` as a .sql file. */
export function downloadSql(sql: string, label: string): void {
  const blob = new Blob([sql], { type: 'application/sql' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = buildExportFilename(label);
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
