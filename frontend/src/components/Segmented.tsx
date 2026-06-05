interface Option<T extends string> {
  value: T
  label: string
}

interface SegmentedProps<T extends string> {
  options: Option<T>[]
  value: T
  onChange: (v: T) => void
  size?: 'sm' | 'md'
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
}: SegmentedProps<T>) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-[11px]' : 'px-3.5 py-1.5 text-[13px]'
  return (
    <div className="inline-flex items-center gap-0.5 rounded-[10px] border border-border bg-surface-2 p-0.5">
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`${pad} rounded-[8px] font-medium transition-all duration-200 ${
              active
                ? 'bg-surface text-text shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
