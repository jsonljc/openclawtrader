import { useCallback } from "react";
import { useApi } from "../hooks/useApi";
import { fetchEquityCurve, fetchTrades, fetchHealth, fetchRegime } from "../api";
import EquityCurve from "../components/EquityCurve";
import TradesTable from "../components/TradesTable";
import HealthPanel from "../components/HealthPanel";
import RegimePanel from "../components/RegimePanel";

export default function Analytics() {
  const equity = useApi(useCallback(() => fetchEquityCurve(30), []));
  const trades = useApi(useCallback(() => fetchTrades(50), []));
  const health = useApi(useCallback(() => fetchHealth(), []));
  const regime = useApi(useCallback(() => fetchRegime(), []));

  const refreshAll = () => {
    equity.refresh();
    trades.refresh();
    health.refresh();
    regime.refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Analytics</h1>
        <div className="flex items-center gap-3">
          {equity.lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated: {equity.lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={refreshAll}
            disabled={equity.loading}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700
                       text-sm rounded font-medium transition-colors"
          >
            {equity.loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      <EquityCurve data={equity.data ?? []} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TradesTable trades={trades.data ?? []} />
        <HealthPanel data={health.data ?? {}} />
      </div>

      <RegimePanel data={regime.data ?? {}} />
    </div>
  );
}
