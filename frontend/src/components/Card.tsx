import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  /** Render with no inner padding (charts manage their own). */
  flush?: boolean
}

export function Card({ children, className = '', flush = false }: CardProps) {
  return (
    <div
      className={`rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow)] ${
        flush ? '' : 'p-5 sm:p-6'
      } ${className}`}
    >
      {children}
    </div>
  )
}
