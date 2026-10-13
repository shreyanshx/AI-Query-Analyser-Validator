/**
 * Analyzer workspace: SQL editor with debounced live validation, a results
 * panel, and an "Analyze & Optimize" action producing the comparison view.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { listConnections, optimizeSql, validateSql } from '../api/client';
import {
  DIALECTS,
  type ConnectionInfo,
  type Dialect,
  type OptimizeResponse,
  type ValidationResult,
} from '../api/types';
import { ComparisonView } from '../components/ComparisonView';
import { ResultsPanel } from '../components/ResultsPanel';
import { SqlEditor } from '../components/SqlEditor';

export function Analyzer(): JSX.Element {
  const [sql, setSql] = useState('SELECT 1;');
  const [dialect, setDialect] = useState<Dialect>('postgres');
  const [connectionId, setConnectionId] = useState<string>('');
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);

  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [validating, setValidating] = useState(false);

  const [optimizeResult, setOptimizeResult] = useState<OptimizeResponse | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Guards against out-of-order validation responses.
  const validateSeq = useRef(0);

  useEffect(() => {
    void listConnections()
      .then(setConnections)
      .catch(() => undefined);
  }, []);

  const runValidate = useCallback(
    async (text: string) => {
      if (!text.trim()) {
        setValidation(null);
        return;
      }
      const seq = ++validateSeq.current;
      setValidating(true);
      try {
        const result = await validateSql({
          sql: text,
          dialect,
          connection_id: connectionId || null,
        });
        if (seq === validateSeq.current) {
          setValidation(result);
        }
      } catch {
        // Live validation errors are non-fatal; keep the previous result.
      } finally {
        if (seq === validateSeq.current) {
          setValidating(false);
        }
      }
    },
    [dialect, connectionId],
  );

  // Re-validate when dialect/connection change (editor onChange covers typing).
  useEffect(() => {
    void runValidate(sql);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialect, connectionId]);

  async function onAnalyze() {
    setError(null);
    setOptimizing(true);
    try {
      const result = await optimizeSql({
        sql,
        dialect,
        connection_id: connectionId || null,
        use_ai: useAi,
      });
      setOptimizeResult(result);
    } catch (err) {
      const message =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message?: unknown }).message)
          : 'Analysis failed';
      setError(message);
    } finally {
      setOptimizing(false);
    }
  }

  return (
    <div className="page analyzer">
      <h1>Analyzer</h1>
      <div className="analyzer-toolbar">
        <label>
          Dialect
          <select value={dialect} onChange={(e) => setDialect(e.target.value as Dialect)}>
            {DIALECTS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label>
          Connection
          <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
            <option value="">(none — syntax only)</option>
            {connections.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>
                {c.database} ({c.dialect})
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
          Use AI
        </label>
        <button type="button" onClick={onAnalyze} disabled={optimizing || !sql.trim()}>
          {optimizing ? 'Analyzing…' : 'Analyze & Optimize'}
        </button>
      </div>

      <div className="analyzer-body">
        <div className="analyzer-editor">
          <SqlEditor value={sql} onChange={setSql} onDebouncedChange={runValidate} />
        </div>
        <div className="analyzer-results">
          <ResultsPanel result={validation} loading={validating} />
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}
      {optimizeResult && <ComparisonView result={optimizeResult} />}
    </div>
  );
}
