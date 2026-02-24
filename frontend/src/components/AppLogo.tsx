import { APP_NAME } from '@/app-config'
import { cn } from '@/lib/utils'

/** Conduit logo: minimal flow/conduit symbol (SVG) */
function LogoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('shrink-0', className)}
      aria-hidden
    >
      <path
        d="M6 10h4l2 4-2 4H6V10zm10 0h4v8h-4l-2-4 2-4zm10 0h4v8h-4l-2-4 2-4z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M10 14h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

type AppLogoProps = {
  showName?: boolean
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function AppLogo({ showName = true, size = 'md', className }: AppLogoProps) {
  const iconSize = size === 'sm' ? 'h-6 w-6' : size === 'lg' ? 'h-10 w-10' : 'h-8 w-8'
  const textSize = size === 'sm' ? 'text-sm' : size === 'lg' ? 'text-xl' : 'text-base'

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <LogoIcon className={iconSize} />
      {showName && <span className={cn('font-semibold text-foreground', textSize)}>{APP_NAME}</span>}
    </div>
  )
}

export { LogoIcon }
