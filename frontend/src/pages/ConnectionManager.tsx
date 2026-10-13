/**
 * DB connection manager.
 *
 * Lets the user test a database connection (introspecting its schema) and lists
 * previously tested connections. The password field lives only in component
 * state and is sent in the request body; it is NEVER written to localStorage.
 */

import { useEffect, useState, type FormEvent } from 'react';

import { getConnectionSchema, listConnections, testConnection } from '../api/client';
import {
  DIALECTS,
  type ConnectionConfig,
  type ConnectionInfo,
  type Dialect,
  type Schema,
} from '../api/types';

const DEFAULT_PORTS: Record<Dialect, number> = {
  postgres: 5432,
  mysql: 3306,
  sqlserver: 1433,
  sqlite: 0,
  oracle: 1521,
};

export function ConnectionManager(): JSX.Element {
  const [dialect, setDialect] = useState<Dialect>('postgres');
  const [host, setHost] = useState('');
  const [port, setPort] = useState<number>(DEFAULT_PORTS.postgres);
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [enableSampling, setEnableSampling] = useState(false);
  const [sensitiveColumns, setSensitiveColumns] = useState('');

  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [lastTested, setLastTested] = useState<{ info: ConnectionInfo; tableCount: number } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  async function loadSchema(connectionId: string) {
    setSelectedId(connectionId);
    setSchema(null);
    setSchemaError(null);
    setSchemaLoading(true);
    try {
      setSchema(await getConnectionSchema(connectionId));
    } catch (err) {
      const message =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message?: unknown }).message)
          : 'Could not load schema';
      setSchemaError(message);
    } finally {
      setSchemaLoading(false);
    }
  }

  async function refreshConnections() {
    try {
      setConnections(await listConnections());
    } catch {
      // Non-fatal: listing requires auth; leave the list empty on failure.
    }
  }

  useEffect(() => {
    void refreshConnections();
  }, []);

  function onDialectChange(next: Dialect) {
    setDialect(next);
    setPort(DEFAULT_PORTS[next]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const cfg: ConnectionConfig = {
      dialect,
      host,
      port: Number(port),
      database,
      username,
      password,
    };
    try {
      const response = await testConnection(cfg);
      setLastTested({ info: response.connection, tableCount: response.table_count });
      // Clear the password from memory as soon as the request completes.
      setPassword('');
      await refreshConnections();
      // Render the introspected schema tree for the just-tested connection.
      await loadSchema(response.connection.connection_id);
    } catch (err) {
      const message =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message?: unknown }).message)
          : 'Connection test failed';
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  const sensitiveList = sensitiveColumns
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <div className="page connection-manager">
      <h1>Connections</h1>
      <form onSubmit={onSubmit} className="connection-form">
        <label>
          Dialect
          <select value={dialect} onChange={(e) => onDialectChange(e.target.value as Dialect)}>
            {DIALECTS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {dialect !== 'postgres' && (
          <p className="field-note" role="note">
            Live connections (test, schema introspection, schema-aware analysis) currently
            support PostgreSQL only. Other dialects are supported for syntax validation,
            but connecting with them is not yet implemented.
          </p>
        )}
        <label>
          Host
          <input value={host} onChange={(e) => setHost(e.target.value)} required />
        </label>
        <label>
          Port
          <input
            type="number"
            value={port}
            onChange={(e) => setPort(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Database
          <input value={database} onChange={(e) => setDatabase(e.target.value)} required />
        </label>
        <label>
          Username
          <input
            value={username}
            autoComplete="off"
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            autoComplete="new-password"
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={enableSampling}
            onChange={(e) => setEnableSampling(e.target.checked)}
          />
          Enable opt-in data sampling
        </label>
        <label>
          Sensitive columns to exclude (comma-separated)
          <input
            value={sensitiveColumns}
            onChange={(e) => setSensitiveColumns(e.target.value)}
            placeholder="users.email, users.ssn"
          />
        </label>
        {enableSampling && sensitiveList.length > 0 && (
          <p className="muted">Excluding from sampling: {sensitiveList.join(', ')}</p>
        )}
        {error && <p className="form-error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Testing…' : 'Test connection'}
        </button>
        <p className="muted small">The password is never stored in your browser.</p>
      </form>

      {lastTested && (
        <div className="connection-status">
          <h3>Connection OK</h3>
          <p>
            {lastTested.info.dialect} · {lastTested.info.host}:{lastTested.info.port}/
            {lastTested.info.database} · {lastTested.tableCount} table(s) introspected
          </p>
          <p className="muted small">connection id: {lastTested.info.connection_id}</p>
        </div>
      )}

      <div className="connection-list">
        <h3>Stored connections</h3>
        {connections.length === 0 ? (
          <p className="muted">No connections yet.</p>
        ) : (
          <ul className="schema-tree">
            {connections.map((c) => (
              <li key={c.connection_id}>
                <strong>{c.database}</strong> ({c.dialect}) &middot; {c.username}@{c.host}:{c.port}
                <br />
                <span className="muted small">id: {c.connection_id}</span>{' '}
                <button
                  type="button"
                  className="link-button"
                  disabled={schemaLoading && selectedId === c.connection_id}
                  onClick={() => void loadSchema(c.connection_id)}
                >
                  {selectedId === c.connection_id && schemaLoading
                    ? 'Loading schema…'
                    : 'View schema'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedId && (
        <div className="connection-schema">
          <h3>Schema</h3>
          {schemaLoading && <p className="muted">Loading schema…</p>}
          {schemaError && <p className="form-error">{schemaError}</p>}
          {schema && <SchemaTree schema={schema} />}
        </div>
      )}
    </div>
  );
}

function SchemaTree({ schema }: { schema: Schema }): JSX.Element {
  if (schema.tables.length === 0) {
    return <p className="muted">No tables introspected.</p>;
  }
  return (
    <ul className="schema-tree">
      {schema.tables.map((table) => (
        <li key={table.schema_name ? `${table.schema_name}.${table.name}` : table.name}>
          <strong>
            {table.schema_name ? `${table.schema_name}.` : ''}
            {table.name}
          </strong>
          <ul>
            {table.columns.map((col) => (
              <li key={col.name}>
                {col.name} <span className="muted small">{col.data_type}</span>
                {col.is_primary_key && <span className="badge pk"> PK</span>}
                {!col.nullable && <span className="badge not-null"> NOT NULL</span>}
              </li>
            ))}
          </ul>
          {table.indexes.length > 0 && (
            <>
              <span className="muted small">Indexes</span>
              <ul>
                {table.indexes.map((idx) => (
                  <li key={idx.name}>
                    {idx.name}{' '}
                    <span className="muted small">
                      ({idx.columns.join(', ')}){idx.unique ? ' · unique' : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
