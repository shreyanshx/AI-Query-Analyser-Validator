/** Renders deterministic validation results with severity styling. */

import type { ValidationResult } from '../api/types';

interface ResultsPanelProps {
  result: ValidationResult | null;
  loading: boolean;
}

function Section({
  title,
  items,
  severity,
}: {
  title: string;
  items: string[];
  severity: 'error' | 'warning';
}): JSX.Element | null {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className={`result-section result-${severity}`}>
      <h4>
        {title} ({items.length})
      </h4>
      <ul>
        {items.map((item, idx) => (
          <li key={`${title}-${idx}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function ResultsPanel({ result, loading }: ResultsPanelProps): JSX.Element {
  if (loading && !result) {
    return <div className="results-panel">Validating…</div>;
  }
  if (!result) {
    return <div className="results-panel muted">Start typing SQL to see live validation.</div>;
  }

  const hasIssues =
    result.syntax_errors.length > 0 ||
    result.schema_errors.length > 0 ||
    result.warnings.length > 0;

  return (
    <div className="results-panel">
      <div className={`validity-badge ${result.is_valid ? 'ok' : 'bad'}`}>
        {result.is_valid ? 'Valid' : 'Invalid'} · {result.parsed_statements} statement(s)
        {loading && <span className="inline-spinner"> · updating…</span>}
      </div>
      <Section title="Syntax errors" items={result.syntax_errors} severity="error" />
      <Section title="Schema errors" items={result.schema_errors} severity="error" />
      <Section title="Warnings" items={result.warnings} severity="warning" />
      {!hasIssues && <p className="result-ok">No issues found.</p>}
    </div>
  );
}
