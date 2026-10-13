/**
 * Shows the original vs AI-suggested SQL side by side with the explanation,
 * optimization list, serving provider, an is_suggestion_valid badge, the
 * performance-estimate disclaimer, and copy/export actions.
 *
 * When `ai_available` is false, a clear "AI temporarily unavailable" notice is
 * shown while the rule-based optimizations still render.
 */

import { useState } from 'react';

import type { OptimizeResponse } from '../api/types';
import { downloadSql } from './exportSql';

interface ComparisonViewProps {
  result: OptimizeResponse;
}

function CopyExport({ sql, label }: { sql: string; label: string }): JSX.Element {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="copy-export">
      <button type="button" onClick={copy} disabled={!sql}>
        {copied ? 'Copied!' : 'Copy'}
      </button>
      <button type="button" onClick={() => downloadSql(sql, label)} disabled={!sql}>
        Export .sql
      </button>
    </div>
  );
}

export function ComparisonView({ result }: ComparisonViewProps): JSX.Element {
  const suggested = result.suggested_sql ?? result.rewritten_sql ?? '';
  const hasSuggestion = suggested.trim().length > 0;

  return (
    <div className="comparison-view">
      <h3>Analysis &amp; optimization</h3>

      {!result.ai_available && (
        <div className="ai-unavailable">
          AI temporarily unavailable
          {result.ai_message ? ` — ${result.ai_message}` : ''}. Showing rule-based results.
        </div>
      )}

      <div className="comparison-columns">
        <div className="comparison-col">
          <div className="comparison-col-head">
            <h4>Original</h4>
            <CopyExport sql={result.original_sql} label="original-query" />
          </div>
          <pre className="sql-block">{result.original_sql}</pre>
        </div>
        <div className="comparison-col">
          <div className="comparison-col-head">
            <h4>Suggested</h4>
            <CopyExport sql={suggested} label="suggested-query" />
          </div>
          {hasSuggestion ? (
            <pre className="sql-block">{suggested}</pre>
          ) : (
            <p className="muted">No rewrite suggested.</p>
          )}
        </div>
      </div>

      <div className="suggestion-meta">
        {result.provider && (
          <span className="meta-chip">Provider: {result.provider}</span>
        )}
        {result.is_suggestion_valid !== null && result.is_suggestion_valid !== undefined && (
          <span
            className={`validity-badge ${result.is_suggestion_valid ? 'ok' : 'bad'}`}
          >
            Suggestion {result.is_suggestion_valid ? 'validated' : 'not validated'}
          </span>
        )}
      </div>

      {result.explanation && (
        <div className="explanation">
          <h4>Explanation</h4>
          <p>{result.explanation}</p>
        </div>
      )}

      {result.optimizations.length > 0 && (
        <div className="optimizations">
          <h4>Optimizations ({result.optimizations.length})</h4>
          <ul>
            {result.optimizations.map((opt, idx) => (
              <li key={`${opt.rule}-${idx}`} className={`opt-${opt.severity}`}>
                <span className="opt-rule">{opt.rule}</span>
                <span className="opt-severity">{opt.severity}</span>
                <span className="opt-message">{opt.message}</span>
                {opt.rewritten_sql && <pre className="sql-block">{opt.rewritten_sql}</pre>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="perf-disclaimer">{result.performance_note}</p>
    </div>
  );
}
