import { useEffect, useRef } from "react";
import { createChart, type IChartApi, LineSeries } from "lightweight-charts";

interface Props {
  data: any[];
}

export default function EquityCurve({ data }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;

    if (chartInstance.current) {
      chartInstance.current.remove();
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 300,
      layout: { background: { color: "#111827" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
      timeScale: { borderColor: "#374151" },
      rightPriceScale: { borderColor: "#374151" },
    });

    const series = chart.addSeries(LineSeries, {
      color: "#10b981",
      lineWidth: 2,
    });

    const points = data.map((entry: any) => ({
      time: entry.payload?.date || entry.timestamp?.slice(0, 10),
      value: entry.payload?.equity_usd ?? 0,
    }));

    series.setData(points);
    chart.timeScale().fitContent();
    chartInstance.current = chart;

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [data]);

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Equity Curve</h2>
      {(!data || data.length === 0) ? (
        <div className="text-gray-500 text-sm">No equity data yet</div>
      ) : (
        <div ref={chartRef} />
      )}
    </div>
  );
}
