/** SQL editor backed by Monaco with a debounced change callback. */

import Editor from '@monaco-editor/react';
import { useEffect, useRef } from 'react';

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Called after the debounce window with the latest value. */
  onDebouncedChange?: (value: string) => void;
  debounceMs?: number;
  height?: string;
}

export function SqlEditor({
  value,
  onChange,
  onDebouncedChange,
  debounceMs = 400,
  height = '320px',
}: SqlEditorProps): JSX.Element {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    };
  }, []);

  function handleChange(next: string | undefined) {
    const text = next ?? '';
    onChange(text);
    if (onDebouncedChange) {
      if (timer.current) {
        clearTimeout(timer.current);
      }
      timer.current = setTimeout(() => onDebouncedChange(text), debounceMs);
    }
  }

  return (
    <div className="sql-editor">
      <Editor
        height={height}
        defaultLanguage="sql"
        value={value}
        onChange={handleChange}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          scrollBeyondLastLine: false,
          wordWrap: 'on',
        }}
      />
    </div>
  );
}
