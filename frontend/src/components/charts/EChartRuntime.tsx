import { useLayoutEffect, useRef, type ComponentProps } from 'react';
import * as echarts from 'echarts';
import type ReactECharts from 'echarts-for-react';

type Props = ComponentProps<typeof ReactECharts>;

/** 同步管理实例和 ResizeObserver，避免切页时异步初始化在卸载后重新绑定传感器。 */
export default function EChart({ option, style, className, opts, theme, notMerge, lazyUpdate,
  replaceMerge, showLoading, loadingOption, onChartReady, onEvents, autoResize = true }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  const readyCallback = useRef(onChartReady);
  const { renderer = 'canvas', devicePixelRatio, width, height, locale } = opts ?? {};
  useLayoutEffect(() => { readyCallback.current = onChartReady; }, [onChartReady]);

  useLayoutEffect(() => {
    const chart = echarts.init(element.current!, theme, { renderer, devicePixelRatio, width: width ?? undefined, height: height ?? undefined, locale });
    instance.current = chart;
    const observer = autoResize ? new ResizeObserver(() => chart.resize()) : null;
    observer?.observe(element.current!);
    readyCallback.current?.(chart);
    return () => {
      observer?.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, [theme, renderer, devicePixelRatio, width, height, locale, autoResize]);

  useLayoutEffect(() => {
    const chart = instance.current!;
    chart.setOption(option, { notMerge, lazyUpdate, replaceMerge });
    if (showLoading) chart.showLoading(loadingOption);
    else chart.hideLoading();
  }, [option, notMerge, lazyUpdate, replaceMerge, showLoading, loadingOption, theme,
    renderer, devicePixelRatio, width, height, locale, autoResize]);

  useLayoutEffect(() => {
    const chart = instance.current!;
    const handlers = Object.entries(onEvents ?? {}).map(([event, handler]) =>
      [event, (...args: unknown[]) => { handler(...args, chart); }] as const);
    handlers.forEach(([event, handler]) => chart.on(event, handler));
    return () => handlers.forEach(([event, handler]) => chart.off(event, handler));
  }, [onEvents, theme, renderer, devicePixelRatio, width, height, locale, autoResize]);

  return <div ref={element} className={`echarts-for-react ${className ?? ''}`} style={{ height: 300, ...style }} />;
}
