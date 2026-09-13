/**
 * PersonalBaselineCard.tsx — Shows a user's personal spend baseline and plain-language
 * deviation signals for the selected transaction / batch.
 *
 * Design rule: NO raw numbers (amount_zscore, etc.) are shown to the viewer.
 * Every signal is translated to a human label via threshold checks.
 */

import React from 'react';
import type { PersonalContext, UserBaseline } from '../types';
import { User, TrendingUp, Clock, Tag, Info } from 'lucide-react';

// ── Label translation helpers ─────────────────────────────────────────────────

function spendLabel(zscore: number): { emoji: string; text: string; color: string } {
  if (zscore > 3)   return { emoji: '🔴', text: 'Way above your norm',   color: 'text-red-400' };
  if (zscore > 1.5) return { emoji: '🟡', text: 'Elevated vs your usual', color: 'text-amber-400' };
  if (zscore < -1.5) return { emoji: '🔵', text: 'Below your usual',       color: 'text-blue-400' };
  return               { emoji: '🟢', text: 'Typical for you',           color: 'text-emerald-400' };
}

/** Convert a 24h hour integer to a 12h am/pm label. */
function hourLabel(h: number): string {
  if (h === 0) return '12am';
  if (h === 12) return '12pm';
  return h < 12 ? `${h}am` : `${h - 12}pm`;
}

/** Format a list of hours as compact groups, e.g. [9, 10, 14, 15] → "9am, 10am, 2pm, 3pm" */
function formatHours(hours: number[]): string {
  if (!hours || hours.length === 0) return '—';
  return hours.map(hourLabel).join(', ');
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  /** The aggregate baseline for this user (from compute_user_baseline output). */
  baseline?: UserBaseline | null;
  /** The per-transaction deviation signals (from compute_personal_deviation output). */
  personalContext?: PersonalContext | null;
}

export const PersonalBaselineCard: React.FC<Props> = ({ baseline, personalContext }) => {
  const hasContext = !!personalContext;
  const isInsufficient =
    personalContext?.insufficient_history || baseline?.insufficient_history;

  return (
    <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
        <User className="w-3.5 h-3.5 text-indigo-400" />
        <span>Your Personal Baseline</span>
      </div>

      {isInsufficient ? (
        /* Not enough history */
        <div className="flex items-start gap-2 p-3 rounded-lg bg-slate-800/60 border border-slate-700/40">
          <Info className="w-4 h-4 text-slate-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-slate-400 leading-relaxed">
            <span className="font-semibold text-slate-300">Not enough history yet.</span>{' '}
            Upload more transaction batches to build your personal spending profile.
          </p>
        </div>
      ) : (
        <>
          {/* Baseline summary rows */}
          {baseline && !baseline.insufficient_history && (
            <div className="grid grid-cols-1 gap-2 text-xs">
              {baseline.avg_amount !== undefined && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-800">
                  <span className="flex items-center gap-1.5 text-slate-400">
                    <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                    Avg spend
                  </span>
                  <span className="font-semibold text-slate-200">
                    ${baseline.avg_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}

              {baseline.top_categories && baseline.top_categories.length > 0 && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-800">
                  <span className="flex items-center gap-1.5 text-slate-400">
                    <Tag className="w-3.5 h-3.5 text-blue-400" />
                    Top category
                  </span>
                  <span className="font-semibold text-slate-200 truncate max-w-[120px]" title={baseline.top_categories[0]}>
                    {baseline.top_categories[0]}
                  </span>
                </div>
              )}

              {baseline.typical_hours && baseline.typical_hours.length > 0 && (
                <div className="flex items-center justify-between py-1.5">
                  <span className="flex items-center gap-1.5 text-slate-400">
                    <Clock className="w-3.5 h-3.5 text-purple-400" />
                    Typical hours
                  </span>
                  <span className="font-semibold text-slate-200 text-right max-w-[140px]">
                    {formatHours(baseline.typical_hours)}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Per-transaction deviation signals */}
          {hasContext && !isInsufficient && (
            <div className="mt-2 space-y-2">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                This transaction vs your profile
              </p>

              {/* Spend level */}
              {personalContext?.amount_zscore !== undefined && (() => {
                const label = spendLabel(personalContext.amount_zscore!);
                return (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
                    <span className="text-base leading-none">{label.emoji}</span>
                    <div>
                      <p className={`text-xs font-semibold ${label.color}`}>{label.text}</p>
                      <p className="text-[10px] text-slate-500">Spend amount</p>
                    </div>
                  </div>
                );
              })()}

              {/* Category */}
              {personalContext?.category_match !== undefined && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
                  <span className="text-base leading-none">
                    {personalContext.category_match ? '✅' : '⚠️'}
                  </span>
                  <div>
                    <p className={`text-xs font-semibold ${personalContext.category_match ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {personalContext.category_match ? 'Familiar category' : 'Unusual category for you'}
                    </p>
                    <p className="text-[10px] text-slate-500">Merchant category</p>
                  </div>
                </div>
              )}

              {/* Time of day */}
              {personalContext?.time_match !== undefined && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/30">
                  <span className="text-base leading-none">
                    {personalContext.time_match ? '✅' : '⚠️'}
                  </span>
                  <div>
                    <p className={`text-xs font-semibold ${personalContext.time_match ? 'text-emerald-400' : 'text-amber-400'}`}>
                      {personalContext.time_match ? 'Typical time of day' : 'Unusual hour for you'}
                    </p>
                    <p className="text-[10px] text-slate-500">Time of transaction</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
