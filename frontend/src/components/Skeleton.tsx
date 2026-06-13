export function Skeleton() {
  return (
    <div className="space-y-4 sm:space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-12">
        <div className="h-[280px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-4" />
        <div className="h-[280px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-8" />
      </div>

      <div className="h-[500px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2" />
    </div>
  )
}
