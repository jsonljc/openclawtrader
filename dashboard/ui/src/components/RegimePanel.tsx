import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface Props {
  data: Record<string, any>;
}

const REGIME_COLORS: Record<string, string> = {
  TRENDING: "#10b981",
  VOLATILE: "#ef4444",
  NEUTRAL: "#6b7280",
  MEAN_REVERTING: "#3b82f6",
  RANGE_BOUND: "#8b5cf6",
};

export default function RegimePanel({ data }: Props) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Regime State</h2>
        <div className="text-gray-500 text-sm">No regime data</div>
      </div>
    );
  }

  const chartData = Object.entries(data).map(([sym, r]: [string, any]) => ({
    symbol: sym,
    score: r.score ?? 0,
    regime: r.regime_type ?? "?",
    driver: r.vol_driver ?? "?",
    value: r.vol_value ?? 0,
  }));

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Regime State</h2>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData}>
          <XAxis dataKey="symbol" tick={{ fill: "#9ca3af", fontSize: 12 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} domain={[0, 100]} />
          <Tooltip
            contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
            labelStyle={{ color: "#e5e7eb" }}
            formatter={(value, _name, entry) => [
              `${value} (${(entry as any).payload.regime})`,
              "Score",
            ]}
          />
          <Bar dataKey="score" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={REGIME_COLORS[entry.regime] ?? "#6b7280"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3">
        {chartData.map((d) => (
          <div key={d.symbol} className="text-center text-xs">
            <div className="font-medium">{d.symbol}</div>
            <div style={{ color: REGIME_COLORS[d.regime] ?? "#6b7280" }}>{d.regime}</div>
            <div className="text-gray-500">{d.driver}: {d.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
