import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Load data once per `key`. Guards against React StrictMode's double effect run in dev,
 * which would otherwise trigger agent calls (and audit entries) twice.
 */
export function useLoad<T>(load: () => Promise<T>, key: string | number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lastKey = useRef<string | number | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    return loadRef
      .current()
      .then((d) => {
        setData(d);
        return d;
      })
      .catch((e: Error) => {
        setError(e.message);
        return null;
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (lastKey.current === key) return;
    lastKey.current = key;
    void reload();
  }, [key, reload]);

  return { data, error, loading, reload };
}
