import { useEffect, useMemo, useState } from 'react'
import type { Portfolio, Targets } from '../lib/types'
import { fmtUSD } from '../lib/format'

interface Props {
  portfolio: Portfolio
  /** Saved target weights for the current account ({} when none set). */
  savedTargets: Targets
  onSave: (t: Targets) => Promise<void>
  hidden: boolean
}

interface Row {
  name: string
  value: number
  curPct: number
}

const round1 = (n: number) => Math.round(n * 10) / 10

export function RebalanceCard({ portfolio, savedTargets, onSave, hidden }: Props) {
  const rows = useMemo<Row[]>(() => {
    const items = [...portfolio.ticker_summary].sort((a, b) => b.value - a.value)
    const total = items.reduce((s, x) => s + x.value, 0)
    return items.map((x) => ({
      name: x.name,
      value: x.value,
      curPct: total > 0 ? (x.value / total) * 100 : 0,
    }))
  }, [portfolio])

  const total = rows.reduce((s, r) => s + r.value, 0)

  // Default each target to the saved value, falling back to the current weight.
  const defaults = useMemo(() => {
    const d: Record<string, string> = {}
    for (const r of rows) {
      const saved = savedTargets[r.name]
      d[r.name] = String(saved != null ? saved : round1(r.curPct))
    }
    return d
  }, [rows, savedTargets])

  const [edits, setEdits] = useState<Record<string, string>>(defaults)
  const [saving, setSaving] = useState(false)

  // Re-seed inputs when the account / portfolio / saved targets change.
  useEffect(() => setEdits(defaults), [defaults])

  const tgtPct = (name: string) => {
    const v = parseFloat(edits[name])
    return Number.isFinite(v) ? v : 0
  }

  const targetSum = rows.reduce((s, r) => s + tgtPct(r.name), 0)
  const balanced = Math.abs(targetSum - 100) < 0.1
  const dirty = rows.some((r) => String(tgtPct(r.name)) !== String(round1(savedTargets[r.name] ?? r.curPct)))

  const setTarget = (name: string, value: string) =>
    setEdits((e) => ({ ...e, [name]: value }))

  const reset = () => {
    const d: Record<string, string> = {}
    for (const r of rows) d[r.name] = String(round1(r.curPct))
    setEdits(d)
  }

  const save = async () => {
    setSaving(true)
    try {
      const payload: Targets = {}
      for (const r of rows) payload[r.name] = tgtPct(r.name)
      await onSave(payload)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full flex-col rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)]">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 sm:px-6">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold tracking-tight text-text">
            Rebalance
          </h2>
          <span
            className={`text-[12px] font-medium tnum ${
              balanced ? 'text-faint' : 'text-warn'
            }`}
          >
            Targets {targetSum.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={reset}
            className="rounded-[8px] px-2.5 py-1 text-[12px] font-medium text-faint transition-colors hover:text-text"
          >
            Reset
          </button>
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="rounded-[8px] bg-accent px-3 py-1 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 px-5 pb-1 text-[10px] font-medium uppercase tracking-wide text-faint sm:px-6">
        <span className="flex-1">Holding</span>
        <span className="w-14 text-right">Current</span>
        <span className="w-16 text-right">Target</span>
        <span className="w-14 text-right">Drift</span>
        <span className="w-[88px] text-right">Action</span>
      </div>

      <div className="scroll-thin flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 pb-4 sm:px-4">
        {rows.map((r) => {
          const tgt = tgtPct(r.name)
          const trade = (total * tgt) / 100 - r.value
          const driftPp = r.curPct - tgt
          // Ignore dust trades below 0.05% of the book.
          const action =
            Math.abs(trade) < total * 0.0005
              ? null
              : trade < 0
                ? { label: 'Sell', amt: -trade, tone: 'text-neg' }
                : { label: 'Buy', amt: trade, tone: 'text-pos' }
          return (
            <div
              key={r.name}
              className="flex items-center gap-2 rounded-[8px] px-2 py-1.5 hover:bg-surface-2"
            >
              <span className="flex-1 truncate text-[12px] font-medium text-text">
                {r.name}
              </span>
              <span className="w-14 text-right tnum text-[12px] text-muted">
                {r.curPct.toFixed(1)}%
              </span>
              <span className="w-16 text-right">
                <input
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step={0.5}
                  value={edits[r.name] ?? ''}
                  onChange={(e) => setTarget(r.name, e.target.value)}
                  className="w-14 rounded-[6px] border border-border bg-surface-2 px-1.5 py-0.5 text-right tnum text-[12px] text-text outline-none focus:border-accent"
                />
              </span>
              <span
                className={`w-14 text-right tnum text-[11px] ${
                  Math.abs(driftPp) < 0.05 ? 'text-faint' : 'text-muted'
                }`}
              >
                {driftPp >= 0 ? '+' : ''}
                {driftPp.toFixed(1)}
              </span>
              <span
                className={`w-[88px] text-right tnum text-[11px] font-medium ${
                  action ? action.tone : 'text-faint'
                }`}
              >
                {action
                  ? `${action.label} ${fmtUSD(action.amt, hidden)}`
                  : '—'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
