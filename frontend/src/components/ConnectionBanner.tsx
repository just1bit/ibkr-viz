import type { UserProfile } from '../lib/types'

interface Props {
  user: UserProfile
}

export function ConnectionBanner({ user }: Props) {
  if (user.flex_status === 'healthy' || user.flex_status === 'not_configured') {
    return null
  }

  const isRed = user.flex_status === 'needs_attention'

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
          ? 'Your IBKR Flex token needs attention. Please update your credentials in settings.'
          : 'Your IBKR connection is experiencing issues. Data may be stale.'}
      </span>
    </div>
  )
}
