import { describe, expect, it } from 'vitest';

import { buildExportFilename } from './exportSql';

describe('buildExportFilename', () => {
  it('slugifies a label and appends .sql', () => {
    expect(buildExportFilename('Suggested Query')).toBe('suggested-query.sql');
  });

  it('collapses runs of non-alphanumerics', () => {
    expect(buildExportFilename('my__weird  name!!')).toBe('my-weird-name.sql');
  });

  it('falls back to query for empty input', () => {
    expect(buildExportFilename('')).toBe('query.sql');
    expect(buildExportFilename('   ')).toBe('query.sql');
  });
});
