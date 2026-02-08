import { useEffect, useState } from 'react';
import { BREAKPOINTS, type BreakpointKey } from '../config/breakpoints';

/**
 * 响应式断点 hook — 使用统一断点常量
 * 默认使用 lg (1024px) 作为移动端判定阈值
 */
export function useIsMobileLayout(key: BreakpointKey = 'lg') {
  const bp = BREAKPOINTS[key];
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < bp : false,
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < bp);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [bp]);

  return isMobile;
}

// 保留旧导出以保持向后兼容
export const MOBILE_LAYOUT_BREAKPOINT = BREAKPOINTS.lg;
