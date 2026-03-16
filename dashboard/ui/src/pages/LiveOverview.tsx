import { useCallback } from "react";
import { useApi } from "../hooks/useApi";
import { fetchPortfolio, fetchSignals, fetchAlerts } from "../api";
import PortfolioSummary from "../components/PortfolioSummary";
import PostureCard from "../components/PostureCard";
import PositionsTable from "../components/PositionsTable";
import SignalsPanel from "../components/SignalsPanel";
import AlertsPanel from "../components/AlertsPanel";

export default function LiveOverview() {
  const portfolio = useApi(useCallback(() => fetchPortfolio(), []));
  const signals = useApi(useCallback(() => fetchSignals(), []));
  const alerts = useApi(useCallback(() => fetchAlerts(20), []));

  const refreshAll = () => {
    portfolio.refresh();
    signals.refresh();
    alerts.refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Live Overview</h1>
        <div className="flex items-center gap-3">
          {portfolio.lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated: {portfolio.lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={refreshAll}
            disabled={portfolio.loading}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700
                       text-sm rounded font-medium transition-colors"
          >
            {portfolio.loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <PortfolioSummary data={portfolio.data} />
        </div>
        <PostureCard data={portfolio.data} />
      </div>

      <PositionsTable positions={portfolio.data?.positions ?? []} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SignalsPanel data={signals.data} />
        <AlertsPanel alerts={alerts.data ?? []} />
      </div>

      {portfolio.error && (
        <div className="text-red-400 text-sm">Error: {portfolio.error}</div>
      )}
    </div>
  );
}
