import { useCallback, useEffect, useState } from "react";

/** Load data on mount, exposing loading/error/reload without a data library. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const run = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const [nonce, setNonce] = useState(0);
  useEffect(run, [run, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}
