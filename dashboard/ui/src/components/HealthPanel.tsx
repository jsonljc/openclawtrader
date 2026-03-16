interface Props {
  data: Record<string, any>;
}

export default function HealthPanel({ data }: Props) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Strategy Health</h2>
        <div className="text-gray-500 text-sm">No strategy data</div>
      </div>
    );
  }

  const strategies = Object.entries(data).map(([sid, cfg]: [string, any]) => ({
    name: sid.replace(/_/g, " ").replace(/^\w/, (c: string) => c.toUpperCase()),
    sid,
    status: cfg.status ?? "?",
    incubating: cfg.incubation?.is_incubating ?? false,
    incubPct: cfg.incubation?.incubation_size_pct ?? 0,
  }));

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Strategy Health</h2>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {strategies.map((s) => (
          <div key={s.sid} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${
                s.status === "ACTIVE" ? "bg-emerald-400" :
                s.status === "DISABLED" ? "bg-red-400" : "bg-gray-500"
              }`} />
              <span className="text-gray-300 text-xs">{s.sid}</span>
            </div>
            <div className="flex items-center gap-2">
              {s.incubating && (
                <span className="text-xs px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                  INCUB {s.incubPct}%
                </span>
              )}
              <span className={`text-xs ${
                s.status === "ACTIVE" ? "text-emerald-400" : "text-gray-500"
              }`}>
                {s.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
