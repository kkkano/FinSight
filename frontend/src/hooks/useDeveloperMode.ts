import { useCallback, useEffect, useState } from 'react';

const DEVELOPER_MODE_KEY = 'finsight_dev';
const DEVELOPER_MODE_EVENT = 'finsight-dev-mode-change';

export function isDeveloperModeEnabled(): boolean {
  return typeof window !== 'undefined' && window.localStorage.getItem(DEVELOPER_MODE_KEY) === '1';
}

export function setDeveloperModeEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  if (enabled) window.localStorage.setItem(DEVELOPER_MODE_KEY, '1');
  else window.localStorage.removeItem(DEVELOPER_MODE_KEY);
  window.dispatchEvent(new Event(DEVELOPER_MODE_EVENT));
}

export function useDeveloperMode(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = useState(isDeveloperModeEnabled);

  useEffect(() => {
    const sync = () => setEnabled(isDeveloperModeEnabled());
    window.addEventListener('storage', sync);
    window.addEventListener(DEVELOPER_MODE_EVENT, sync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener(DEVELOPER_MODE_EVENT, sync);
    };
  }, []);

  const update = useCallback((nextEnabled: boolean) => {
    setDeveloperModeEnabled(nextEnabled);
    setEnabled(nextEnabled);
  }, []);

  return [enabled, update];
}
