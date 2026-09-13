/**
 * BatchHistory.tsx — Phase 4 page: history sidebar + batch detail view.
 *
 * Layout:
 *   [HistorySidebar | PersonalBaselineCard + batch transaction table]
 *
 * Reuses the existing TransactionModal for per-row audit details.
 * Does NOT build a new transaction display component — the table here
 * mirrors the LiveFeed table layout.
 *
 * Auth: requires a bearer token from AuthContext. Shows a sign-in form
 * if no token is present (token is in-memory, never localStorage).
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { fetchBatchDetail } from '../services/api';
import type { BatchDetailResponse, ScoredTransaction, UserBaseline } from '../types';
import { HistorySidebar } from '../components/HistorySidebar';
import { PersonalBaselineCard } from '../components/PersonalBaselineCard';
import { RiskBandBadge } from '../components/RiskBandBadge';
import { TransactionModal } from '../components/TransactionModal';
import { Eye, KeyRound, Loader2, FolderOpen } from 'lucide-react';

// ── Utility: derive a rough UserBaseline from the batch transactions ──────────
// The baseline is stored per-transaction as personal_context on each row.
// We reconstruct avg_amount and top_categories from the batch's actual data
// so we don't need a separate /user-baseline endpoint.
function deriveBaselineFromBatch(txns: ScoredTransaction[]): UserBaseline | null {
  if (!txns || txns.length === 0) return null;

  const amounts = txns.map((t) => t.amount).filter((a) => typeof a === 'number');
  if (amounts.length === 0) return null;

  const avg_amount = amounts.reduce((s, a) => s + a, 0) / amounts.length;

  // Category frequency
  const catFreq: Record<string, number> = {};
  for (const t of txns) {
    const c = t.merchant_category;
    if (c) catFreq[c] = (catFreq[c] || 0) + 1;
  }
  const top_categories = Object.entries(catFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([c]) => c);

  // Typical hours from personal_context.time_match hints — we reconstruct from
  // the transactions' own timestamps instead since we don't store typical_hours
  // in each row's personal_context.
  const hourFreq: Record<number, number> = {};
  for (const t of txns) {
    try {
      const h = new Date(t.timestamp).getHours();
      hourFreq[h] = (hourFreq[h] || 0) + 1;
    } catch {
      // ignore unparseable timestamps
    }
  }
  const typical_hours = Object.entries(hourFreq)
    .filter(([, cnt]) => cnt >= 2)
    .map(([h]) => parseInt(h))
    .sort((a, b) => a - b);

  return {
    avg_amount,
    top_categories,
    typical_hours,
    transaction_count: txns.length,
  };
}

// ── Sign-in form ──────────────────────────────────────────────────────────────

const TokenForm: React.FC<{ onSubmit: (token: string) => void }> = ({ onSubmit }) => {
  const [value, setValue] = useState('');
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-6">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg">
        <KeyRound className="w-7 h-7 text-white" />
      </div>
      <div className="text-center">
        <h2 className="text-lg font-bold text-white">Sign in to view batch history</h2>
        <p className="text-sm text-slate-400 mt-1">Paste your JWT bearer token to continue.</p>
      </div>
      <div className="w-full max-w-md flex gap-2">
        <input
          type="password"
          placeholder="Bearer token…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && value.trim() && onSubmit(value.trim())}
          className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition"
        />
        <button
          disabled={!value.trim()}
          onClick={() => onSubmit(value.trim())}
          className="px-5 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-semibold disabled:opacity-40 hover:bg-blue-500 transition"
        >
          Sign in
        </button>
      </div>
    </div>
  );
};

// ── Main page ─────────────────────────────────────────────────────────────────

export const BatchHistory: React.FC = () => {
  const { token, setToken } = useAuth();
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [batchDetail, setBatchDetail] = useState<BatchDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedTx, setSelectedTx] = useState<ScoredTransaction | null>(null);

  // Load batch detail when selection changes
  useEffect(() => {
    if (!selectedBatchId || !token) return;

    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setBatchDetail(null);

    fetchBatchDetail(token, selectedBatchId)
      .then((res) => {
        if (!cancelled) setBatchDetail(res);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err?.response?.data?.detail || err.message || 'Failed to load batch';
          setDetailError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => { cancelled = true; };
  }, [selectedBatchId, token]);

  // Require token
  if (!token) {
    return <TokenForm onSubmit={(t) => setToken(t)} />;
  }

  const txns = batchDetail?.transactions ?? [];
  const derivedBaseline = deriveBaselineFromBatch(txns);

  return (
    <div className="flex gap-4 h-[calc(100vh-120px)]">
      {/* Left: history sidebar */}
      <HistorySidebar
        token={token}
        selectedBatchId={selectedBatchId}
        onSelectBatch={(id) => {
          setSelectedBatchId(id);
          setSelectedTx(null);
        }}
      />

      {/* Right: detail panel */}
      <div className="flex-1 overflow-hidden flex flex-col gap-4 min-w-0">
        {/* Personal baseline card — shown above the batch detail */}
        {selectedBatchId && (
          <PersonalBaselineCard
            baseline={derivedBaseline}
            personalContext={
              // Show the first transaction's personal_context as a representative sample
              txns.length > 0 ? txns[0].personal_context : null
            }
          />
        )}

        {/* Batch detail content */}
        <div className="flex-1 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden flex flex-col">
          {/* Header */}
          <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FolderOpen className="w-4 h-4 text-blue-400" />
              <span className="text-sm font-semibold text-slate-200">
                {selectedBatchId
                  ? `Batch ${selectedBatchId.slice(0, 8)}…`
                  : 'Select a batch from the sidebar'}
              </span>
            </div>
            {batchDetail && (
              <span className="text-xs text-slate-500">
                {batchDetail.transaction_count} transactions
              </span>
            )}
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto">
            {!selectedBatchId && (
              <div className="flex flex-col items-center justify-center py-20 gap-3 text-slate-500">
                <FolderOpen className="w-10 h-10 opacity-30" />
                <p className="text-sm">Click an upload batch in the sidebar to view its transactions.</p>
              </div>
            )}

            {selectedBatchId && detailLoading && (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                <span className="text-sm">Loading batch…</span>
              </div>
            )}

            {selectedBatchId && !detailLoading && detailError && (
              <div className="m-4 p-4 rounded-xl bg-red-950/40 border border-red-800/40 text-sm text-red-400">
                {detailError}
              </div>
            )}

            {selectedBatchId && !detailLoading && !detailError && txns.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800 sticky top-0">
                    <tr>
                      <th className="py-3 px-4 font-semibold">Txn ID / Timestamp</th>
                      <th className="py-3 px-4 font-semibold">Merchant / Category</th>
                      <th className="py-3 px-4 font-semibold">Amount</th>
                      <th className="py-3 px-4 font-semibold">Risk Score</th>
                      <th className="py-3 px-4 font-semibold">Action</th>
                      <th className="py-3 px-4 font-semibold">Personal Context</th>
                      <th className="py-3 px-4 font-semibold text-right">Detail</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {txns.map((tx, i) => {
                      const ctx = tx.personal_context;
                      return (
                        <tr
                          key={tx.transaction_id ?? i}
                          className={`hover:bg-slate-800/40 transition cursor-pointer ${
                            (tx.action && tx.action !== 'allow') ? 'bg-amber-950/10' : ''
                          }`}
                          onClick={() => setSelectedTx(tx)}
                        >
                          <td className="py-3 px-4 font-mono">
                            <span className="font-semibold text-white block">{tx.transaction_id}</span>
                            <span className="text-[10px] text-slate-500">
                              {tx.timestamp ? new Date(tx.timestamp).toLocaleTimeString() : '—'}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <span className="font-medium text-slate-200 block">{tx.merchant}</span>
                            <span className="text-[10px] text-slate-400">{tx.merchant_category}</span>
                          </td>
                          <td className="py-3 px-4 font-semibold text-white">
                            ${(tx.amount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </td>
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2">
                              <div className="w-14 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${
                                    tx.risk_score > 0.75 ? 'bg-red-500' : tx.risk_score > 0.35 ? 'bg-amber-500' : 'bg-emerald-500'
                                  }`}
                                  style={{ width: `${Math.max(5, (tx.risk_score ?? 0) * 100)}%` }}
                                />
                              </div>
                              <span className="font-mono text-slate-300 font-medium">
                                {((tx.risk_score ?? 0) * 100).toFixed(0)}%
                              </span>
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            {tx.action && tx.risk_band ? (
                              <RiskBandBadge action={tx.action} band={tx.risk_band} />
                            ) : (
                              <span className="text-slate-500">—</span>
                            )}
                          </td>
                          <td className="py-3 px-4">
                            {/* Plain-language personal context labels — no raw numbers */}
                            {!ctx || ctx.insufficient_history ? (
                              <span className="text-[10px] text-slate-500 italic">ℹ️ Not enough history</span>
                            ) : (
                              <div className="flex flex-col gap-0.5">
                                {ctx.amount_zscore !== undefined && (() => {
                                  const z = ctx.amount_zscore!;
                                  if (z > 3)    return <span className="text-[10px] text-red-400 font-semibold">🔴 Way above norm</span>;
                                  if (z > 1.5)  return <span className="text-[10px] text-amber-400 font-semibold">🟡 Elevated spend</span>;
                                  if (z < -1.5) return <span className="text-[10px] text-blue-400 font-semibold">🔵 Below usual</span>;
                                  return          <span className="text-[10px] text-emerald-400 font-semibold">🟢 Typical spend</span>;
                                })()}
                                {ctx.category_match !== undefined && (
                                  <span className={`text-[10px] ${ctx.category_match ? 'text-emerald-400' : 'text-amber-400'}`}>
                                    {ctx.category_match ? '✅ Familiar category' : '⚠️ Unusual category'}
                                  </span>
                                )}
                                {ctx.time_match !== undefined && (
                                  <span className={`text-[10px] ${ctx.time_match ? 'text-emerald-400' : 'text-amber-400'}`}>
                                    {ctx.time_match ? '✅ Typical time' : '⚠️ Unusual time'}
                                  </span>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={(e) => { e.stopPropagation(); setSelectedTx(tx); }}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 text-blue-400 hover:bg-slate-700 transition text-[11px] font-medium"
                            >
                              <Eye className="w-3.5 h-3.5" />
                              <span>Audit</span>
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {selectedBatchId && !detailLoading && !detailError && txns.length === 0 && (
              <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
                No transactions found in this batch.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Audit modal — reuses existing TransactionModal unchanged */}
      <TransactionModal transaction={selectedTx} onClose={() => setSelectedTx(null)} />
    </div>
  );
};
