export function Skeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-[92px] animate-pulse rounded-[var(--radius-md)] border border-border bg-surface-2"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="h-[420px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2" />
        <div className="h-[420px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2" />
      </div>
    </div>
  )
}
