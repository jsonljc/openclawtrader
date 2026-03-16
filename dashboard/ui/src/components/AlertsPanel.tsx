interface Props {
  alerts: any[];
}

const LEVEL_COLORS: Record<string, string> = {
  HALT: "text-red-500",
  DEGRADED: "text-red-400",
  DEFENSIVE: "text-orange-400",
  CAUTION: "text-yellow-400",
  WARNING: "text-yellow-300",
  INFO: "text-blue-400",
  RECOVERY: "text-emerald-400",
};

export default function AlertsPanel({ alerts }: Props) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Alerts</h2>
      {(!alerts || alerts.length === 0) && (
        <div className="text-gray-500 text-sm">No recent alerts</div>
      )}
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {(alerts ?? []).map((a: any, i: number) => (
          <div key={i} className="text-sm flex gap-2">
            <span className="text-gray-600 text-xs whitespace-nowrap">
              {a.ts?.slice(11, 19)}
            </span>
            <span className={`font-medium text-xs ${LEVEL_COLORS[a.level] ?? "text-gray-400"}`}>
              {a.level}
            </span>
            <span className="text-gray-300 text-xs">{a.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
