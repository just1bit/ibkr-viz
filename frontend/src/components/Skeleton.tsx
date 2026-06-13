export function Skeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[92px] animate-pulse rounded-[var(--radius-md)] border border-border bg-surface-2"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="h-[380px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-5" />
        <div className="h-[380px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-7" />
      </div>
      <div className="h-[320px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="h-[360px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-7" />
        <div className="h-[360px] animate-pulse rounded-[var(--radius-lg)] border border-border bg-surface-2 lg:col-span-5" />
      </div>
    </div>
  )
}
