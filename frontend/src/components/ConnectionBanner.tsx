import type { Status, UserProfile } from '../lib/types'

interface Props {
  user: UserProfile
  status?: Status | null
}

export function ConnectionBanner({ user, status }: Props) {
  const flexStatus = status?.flex_status ?? user.flex_status
  if (flexStatus === 'healthy' || flexStatus === 'not_configured') {
    return null
  }

  const isRed = flexStatus === 'needs_attention'
  const detail = status?.last_error_detail

  return (
    <div
      className={`flex items-center justify-center gap-2 px-4 py-2 text-center text-[13px] ${
        isRed
          ? 'bg-neg/10 text-neg'
          : 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
      }`}
    >
      <span className="text-[15px]">{isRed ? '⚠' : 'ℹ'}</span>
      <span>
        {isRed
          ? detail || 'Your IBKR Flex credentials need attention. Please check settings.'
          : detail || 'The latest IBKR refresh failed. The app will retry automatically.'}
      </span>
    </div>
  )
}
