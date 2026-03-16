interface Props {
  positions: any[];
}

export default function PositionsTable({ positions }: Props) {
  if (!positions || positions.length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Open Positions</h2>
        <div className="text-gray-500 text-sm">No open positions</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">
        Open Positions ({positions.length})
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-left border-b border-gray-800">
              <th className="pb-2">Symbol</th>
              <th className="pb-2">Side</th>
              <th className="pb-2">Qty</th>
              <th className="pb-2">Entry</th>
              <th className="pb-2">Current</th>
              <th className="pb-2">P&L</th>
              <th className="pb-2">Stop</th>
              <th className="pb-2">Target</th>
              <th className="pb-2">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos: any) => {
              const pnl = pos.unrealized_pnl_usd ?? 0;
              const positive = pnl >= 0;
              return (
                <tr key={pos.position_id} className="border-b border-gray-800/50">
                  <td className="py-2 font-medium">{pos.symbol}</td>
                  <td className={pos.side === "LONG" ? "text-emerald-400" : "text-red-400"}>
                    {pos.side}
                  </td>
                  <td>{pos.contracts}</td>
                  <td>{pos.entry_price?.toLocaleString()}</td>
                  <td>{pos.current_price?.toLocaleString()}</td>
                  <td className={positive ? "text-emerald-400" : "text-red-400"}>
                    {positive ? "+" : ""}${pnl.toLocaleString()}
                  </td>
                  <td className="text-gray-500">{pos.stop_price?.toLocaleString()}</td>
                  <td className="text-gray-500">{pos.target_price?.toLocaleString()}</td>
                  <td className="text-gray-500 text-xs">{pos.strategy_id}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
