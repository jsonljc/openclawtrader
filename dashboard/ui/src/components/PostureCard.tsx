interface Props {
  data: any;
}

const POSTURE_COLORS: Record<string, string> = {
  NORMAL: "text-emerald-400",
  CAUTION: "text-yellow-400",
  DEFENSIVE: "text-orange-400",
  HALT: "text-red-500",
};

export default function PostureCard({ data }: Props) {
  if (!data) return null;
  const posture = data.sentinel_posture ?? "?";
  const since = data.sentinel_posture_since ?? "";
  const details = data.posture_details ?? {};
  const streak = details.consecutive_positive_days ?? 0;
  const dd = data.pnl?.portfolio_dd_pct ?? 0;

  const thresholds = [
    { label: "CAUTION", pct: 4 },
    { label: "DEFENSIVE", pct: 10 },
    { label: "HALT", pct: 15 },
  ];

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Sentinel Posture</h2>
      <div className={`text-2xl font-bold mb-2 ${POSTURE_COLORS[posture] ?? "text-gray-300"}`}>
        {posture}
      </div>
      <div className="text-sm space-y-1">
        <div><span className="text-gray-500">Since </span>{since.slice(0, 10)}</div>
        <div><span className="text-gray-500">Streak </span>{streak} positive days</div>
        <div className="mt-2">
          <div className="text-gray-500 text-xs mb-1">DD vs thresholds</div>
          <div className="w-full bg-gray-800 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${dd > 10 ? "bg-red-500" : dd > 4 ? "bg-yellow-400" : "bg-emerald-400"}`}
              style={{ width: `${Math.min(dd / 15 * 100, 100)}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-600 mt-1">
            {thresholds.map((t) => (
              <span key={t.label}>{t.label} {t.pct}%</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
