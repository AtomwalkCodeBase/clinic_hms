// Tree-shaken ECharts: only what the health journey uses (~60% smaller than `import 'echarts'`).
import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import React from 'react';

echarts.use([CustomChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export default function EChart(props) {
  return <ReactEChartsCore echarts={echarts} {...props} />;
}
