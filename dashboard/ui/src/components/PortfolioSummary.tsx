interface Props {
  data: any;
}

export default function PortfolioSummary({ data }: Props) {
  if (!data) return null;
  const { account, pnl, heat } = data;
  const equity = account?.equity_usd ?? 0;
  const opening = account?.opening_equity_usd ?? 0;
  const peak = account?.peak_equity_usd ?? 0;
  const todayPnl = pnl?.total_today_usd ?? 0;
  const todayPct = pnl?.total_today_pct ?? 0;
  const dd = pnl?.portfolio_dd_pct ?? 0;
  const heatPct = heat?.total_open_risk_pct ?? 0;
  const positive = todayPnl >= 0;

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Portfolio</h2>
      <div className="text-3xl font-bold mb-2">${equity.toLocaleString()}</div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-gray-500">Today </span>
          <span className={positive ? "text-emerald-400" : "text-red-400"}>
            {positive ? "+" : ""}${todayPnl.toLocaleString()} ({positive ? "+" : ""}{todayPct.toFixed(2)}%)
          </span>
        </div>
        <div>
          <span className="text-gray-500">Opening </span>
          <span>${opening.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-500">Peak </span>
          <span>${peak.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-500">DD </span>
          <span className={dd > 4 ? "text-red-400" : "text-gray-300"}>{dd.toFixed(2)}%</span>
        </div>
        <div>
          <span className="text-gray-500">Heat </span>
          <span>{heatPct.toFixed(2)}%</span>
        </div>
      </div>
    </div>
  );
}
