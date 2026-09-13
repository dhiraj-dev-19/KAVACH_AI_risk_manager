/**
 * HistorySidebar.tsx — Batch history sidebar for the JUDGE frontend.
 *
 * Fetches GET /transactions/batches (authenticated) and groups results into:
 *   Today / This week / Earlier
 * based on each batch's created_at timestamp.
 *
 * Clicking a batch entry calls onSelectBatch(batch_id) so the parent page
 * can fetch and display the full batch detail.
 */

import React, { useEffect, useState } from 'react';
import { fetchBatches } from '../services/api';
import type { BatchSummary } from '../types';
import { History, ChevronRight, AlertTriangle, Loader2, UploadCloud } from 'lucide-react';

interface Props {
  token: string;
  selectedBatchId: string | null;
  onSelectBatch: (batchId: string) => void;
}

// ── Date grouping helpers ─────────────────────────────────────────────────────

function startOfDayUTC(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
}

function groupBatches(batches: BatchSummary[]): {
  today: BatchSummary[];
  thisWeek: BatchSummary[];
  earlier: BatchSummary[];
} {
  const now = new Date();
  const todayStart = startOfDayUTC(now);
  const weekStart = new Date(todayStart.getTime() - 6 * 24 * 60 * 60 * 1000); // 7 days incl today

  const today: BatchSummary[] = [];
  const thisWeek: BatchSummary[] = [];
  const earlier: BatchSummary[] = [];

  for (const b of batches) {
    const d = new Date(b.created_at);
    if (d >= todayStart) {
      today.push(b);
    } else if (d >= weekStart) {
      thisWeek.push(b);
    } else {
      earlier.push(b);
    }
  }

  return { today, thisWeek, earlier };
}

function formatBatchTime(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

// ── Sub-component: one batch entry row ───────────────────────────────────────

const BatchRow: React.FC<{
  batch: BatchSummary;
  isSelected: boolean;
  onClick: () => void;
}> = ({ batch, isSelected, onClick }) => {
  const hasFlagged = batch.flagged_count > 0;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-lg transition-all group flex items-start justify-between gap-2 ${
        isSelected
          ? 'bg-blue-600/20 border border-blue-500/40 text-blue-300'
          : 'hover:bg-slate-800/60 border border-transparent text-slate-400 hover:text-slate-200'
      }`}
    >
      <div className="min-w-0">
        <p className="text-xs font-semibold truncate" title={batch.batch_id}>
          {batch.batch_id.slice(0, 8)}…
        </p>
        <p className="text-[10px] text-slate-500 mt-0.5">{formatBatchTime(batch.created_at)}</p>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10px] text-slate-500">{batch.row_count} rows</span>
          {hasFlagged && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-400 font-medium">
              <AlertTriangle className="w-2.5 h-2.5" />
              {batch.flagged_count} flagged
            </span>
          )}
        </div>
      </div>
      <ChevronRight
        className={`w-3.5 h-3.5 flex-shrink-0 mt-1 transition-transform ${
          isSelected ? 'rotate-90 text-blue-400' : 'group-hover:translate-x-0.5'
        }`}
      />
    </button>
  );
};

// ── Section label ─────────────────────────────────────────────────────────────

const SectionLabel: React.FC<{ label: string }> = ({ label }) => (
  <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest px-1 mb-1 mt-3 first:mt-0">
    {label}
  </p>
);

// ── Main sidebar component ────────────────────────────────────────────────────

export const HistorySidebar: React.FC<Props> = ({ token, selectedBatchId, onSelectBatch }) => {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchBatches(token)
      .then((res) => {
        if (!cancelled) {
          setBatches(res.batches || []);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err?.response?.data?.detail || err.message || 'Failed to load batches';
          setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [token]);

  const { today, thisWeek, earlier } = groupBatches(batches);

  return (
    <aside className="w-64 flex-shrink-0 bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <History className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-semibold text-slate-200">Upload History</span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-0.5">
        {loading && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            <span className="text-xs">Loading batches…</span>
          </div>
        )}

        {!loading && error && (
          <div className="p-3 rounded-lg bg-red-950/40 border border-red-800/40 text-xs text-red-400">
            {error}
          </div>
        )}

        {!loading && !error && batches.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500 gap-2">
            <UploadCloud className="w-8 h-8 opacity-40" />
            <p className="text-xs text-center">No uploads yet.<br />Upload a CSV to get started.</p>
          </div>
        )}

        {!loading && !error && batches.length > 0 && (
          <>
            {today.length > 0 && (
              <>
                <SectionLabel label="Today" />
                {today.map((b) => (
                  <BatchRow
                    key={b.batch_id}
                    batch={b}
                    isSelected={b.batch_id === selectedBatchId}
                    onClick={() => onSelectBatch(b.batch_id)}
                  />
                ))}
              </>
            )}

            {thisWeek.length > 0 && (
              <>
                <SectionLabel label="This Week" />
                {thisWeek.map((b) => (
                  <BatchRow
                    key={b.batch_id}
                    batch={b}
                    isSelected={b.batch_id === selectedBatchId}
                    onClick={() => onSelectBatch(b.batch_id)}
                  />
                ))}
              </>
            )}

            {earlier.length > 0 && (
              <>
                <SectionLabel label="Earlier" />
                {earlier.map((b) => (
                  <BatchRow
                    key={b.batch_id}
                    batch={b}
                    isSelected={b.batch_id === selectedBatchId}
                    onClick={() => onSelectBatch(b.batch_id)}
                  />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </aside>
  );
};
