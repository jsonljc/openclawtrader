interface Props {
  trades: any[];
}

export default function TradesTable({ trades }: Props) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">
        Recent Trades ({trades?.length ?? 0})
      </h2>
      {(!trades || trades.length === 0) ? (
        <div className="text-gray-500 text-sm">No closed trades yet</div>
      ) : (
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-left border-b border-gray-800 sticky top-0 bg-gray-900">
                <th className="pb-2">Date</th>
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Side</th>
                <th className="pb-2">Entry</th>
                <th className="pb-2">Exit</th>
                <th className="pb-2">P&L</th>
                <th className="pb-2">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t: any, i: number) => {
                const p = t.payload ?? {};
                const pnl = p.realized_pnl_usd ?? 0;
                const positive = pnl >= 0;
                return (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="py-2 text-gray-500 text-xs">{t.timestamp?.slice(0, 10)}</td>
                    <td className="font-medium">{p.symbol}</td>
                    <td className={p.side === "LONG" ? "text-emerald-400" : "text-red-400"}>
                      {p.side}
                    </td>
                    <td>{p.entry_price?.toLocaleString()}</td>
                    <td>{p.exit_price?.toLocaleString()}</td>
                    <td className={positive ? "text-emerald-400" : "text-red-400"}>
                      {positive ? "+" : ""}${pnl.toLocaleString()}
                    </td>
                    <td className="text-gray-500 text-xs">{p.strategy_id}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
