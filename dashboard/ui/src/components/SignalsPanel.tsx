interface Props {
  data: any;
}

const TIER_COLORS: Record<string, string> = {
  HALT: "bg-red-500/20 text-red-400 border-red-500/30",
  REDUCE: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  CAUTION: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
};

export default function SignalsPanel({ data }: Props) {
  const news = data?.news ?? [];
  const poly = data?.polymarket ?? [];
  const empty = news.length === 0 && poly.length === 0;

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Active Signals</h2>
      {empty && <div className="text-gray-500 text-sm">No active signals</div>}
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {news.map((s: any, i: number) => (
          <div key={i} className={`text-sm p-2 rounded border ${TIER_COLORS[s.tier] ?? "border-gray-700"}`}>
            <div className="font-medium">{s.tier} — {s.source_id}</div>
            <div className="text-gray-300 text-xs mt-1">{s.headline}</div>
            <div className="text-gray-500 text-xs mt-1">{(s.instruments ?? []).join(", ")}</div>
          </div>
        ))}
        {poly.map((s: any, i: number) => (
          <div key={`p${i}`} className="text-sm p-2 rounded border border-blue-500/30 bg-blue-500/10">
            <div className="font-medium text-blue-400">
              {s.type} ({s.strength})
            </div>
            <div className="text-gray-300 text-xs mt-1">{s.market_question}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
