import { lazy, Suspense, type ComponentProps } from 'react';
import type ReactECharts from 'echarts-for-react';

type Props = ComponentProps<typeof ReactECharts>;
const ChartRuntime = lazy(() => import('./EChartRuntime'));

/** 引擎仅在真实图表挂载时加载，首屏不预载图表供应商包。 */
export default function EChart(props: Props) {
  return (
    <Suspense fallback={
      <div role="status" aria-busy="true"
        className={`echarts-for-react animate-pulse bg-t-elevated ${props.className ?? ''}`}
        style={{ height: 300, ...props.style }} />
    }>
      <ChartRuntime {...props} />
    </Suspense>
  );
}
