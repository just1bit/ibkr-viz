import type { ReactNode } from 'react'

export function CardTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-[17px] font-semibold tracking-tight text-text">{children}</h2>
}

export function CardDate({ date }: { date: string }) {
  return <span className="text-[11px] tabular-nums text-faint sm:text-[12px]">{date}</span>
}

export function PositionCount({ count }: { count: number }) {
  return (
    <span className="shrink-0 text-[11px] tabular-nums text-faint sm:text-[12px]">
      {count} {count === 1 ? 'position' : 'positions'}
    </span>
  )
}
