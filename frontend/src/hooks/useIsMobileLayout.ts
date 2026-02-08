import { useEffect, useState } from 'react';

export const MOBILE_LAYOUT_BREAKPOINT = 1024;

export function useIsMobileLayout(breakpoint: number = MOBILE_LAYOUT_BREAKPOINT) {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false,
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < breakpoint);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpoint]);

  return isMobile;
}

