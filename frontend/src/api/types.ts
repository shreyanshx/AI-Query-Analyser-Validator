/**
 * TypeScript mirrors of the backend Pydantic API models
 * (backend/app/models/api_models.py and schema_models.py). Field names match
 * the backend exactly. The DB password is sent only in the request body and is
 * never echoed back nor persisted.
 */

export type Dialect = 'postgres' | 'mysql' | 'sqlserver' | 'sqlite' | 'oracle';

export const DIALECTS: Dialect[] = ['postgres', 'mysql', 'sqlserver', 'sqlite', 'oracle'];

export interface ConnectionConfig {
  dialect: Dialect;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl?: boolean;
}

export interface ConnectionInfo {
  connection_id: string;
  dialect: string;
  host: string;
  port: number;
  database: string;
  username: string;
}

export interface TestConnectionResponse {
  connection: ConnectionInfo;
  ok: boolean;
  table_count: number;
}

export interface ValidateRequest {
  sql: string;
  dialect: string;
  connection_id?: string | null;
}

export interface ValidationResult {
  syntax_errors: string[];
  schema_errors: string[];
  warnings: string[];
  parsed_statements: number;
  is_valid: boolean;
}

export interface Optimization {
  rule: string;
  severity: string;
  message: string;
  rewritten_sql?: string | null;
}

export interface OptimizeRequest {
  sql: string;
  dialect: string;
  connection_id?: string | null;
  use_ai: boolean;
}

export interface OptimizeResponse {
  original_sql: string;
  rewritten_sql?: string | null;
  optimizations: Optimization[];
  performance_note: string;
  suggested_sql?: string | null;
  explanation?: string | null;
  provider?: string | null;
  is_suggestion_valid?: boolean | null;
  ai_available: boolean;
  ai_message?: string | null;
}
