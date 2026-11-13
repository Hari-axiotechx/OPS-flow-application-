import { useCallback, useMemo } from 'react';

/**
 * Multi-select status filter kept in the URL:  /deployments?status=APPROVED,IN_PROGRESS,COMPLETED_FAILED
 *  - click a chip to add it, click it again to remove it (choose as many as you like)
 *  - "All" clears the selection
 *  - a single value (old links such as ?status=REQUESTED) still works
 */
export function useStatusFilter(params, setParams) {
  const selected = useMemo(
    () => (params.get('status') || '').split(',').map((s) => s.trim()).filter(Boolean),
    [params]
  );

  const write = useCallback(
    (list) => {
      const next = new URLSearchParams(params);
      if (list.length) next.set('status', list.join(','));
      else next.delete('status');
      setParams(next);
    },
    [params, setParams]
  );

  const toggle = useCallback(
    (s) => {
      if (s === 'ALL') return write([]);
      return write(selected.includes(s) ? selected.filter((x) => x !== s) : [...selected, s]);
    },
    [selected, write]
  );

  const isActive = useCallback((s) => (s === 'ALL' ? selected.length === 0 : selected.includes(s)), [selected]);
  const matches = useCallback((status) => selected.length === 0 || selected.includes(status), [selected]);

  return { selected, toggle, isActive, matches };
}
