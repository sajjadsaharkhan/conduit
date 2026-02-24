import * as React from 'react'
import { cn } from '@/lib/utils'

type TooltipProps = {
  content: React.ReactNode
  children: React.ReactNode
  side?: 'top' | 'bottom'
  className?: string
}

export function Tooltip({ content, children, side = 'top', className }: TooltipProps) {
  const triggerRef = React.useRef<HTMLSpanElement>(null)
  const [visible, setVisible] = React.useState(false)
  const [coords, setCoords] = React.useState({ top: -9999, left: -9999 })
  const tooltipRef = React.useRef<HTMLSpanElement>(null)

  const updatePosition = React.useCallback(() => {
    const el = triggerRef.current
    const tip = tooltipRef.current
    if (!el || !tip) return
    const rect = el.getBoundingClientRect()
    const tipRect = tip.getBoundingClientRect()
    const padding = 8
    let top: number
    let left = rect.left + rect.width / 2 - tipRect.width / 2
    left = Math.max(padding, Math.min(left, window.innerWidth - tipRect.width - padding))
    if (side === 'top') {
      top = rect.top - tipRect.height - padding
    } else {
      top = rect.bottom + padding
    }
    setCoords({ top, left })
  }, [side])

  const show = React.useCallback(() => {
    setVisible(true)
  }, [])

  const hide = React.useCallback(() => {
    setVisible(false)
  }, [])

  React.useEffect(() => {
    if (!visible) return
    const id = requestAnimationFrame(() => {
      updatePosition()
    })
    return () => cancelAnimationFrame(id)
  }, [visible, updatePosition, content])

  return (
    <>
      <span
        ref={triggerRef}
        className={cn('relative inline-flex', className)}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        <span className="inline-flex rounded p-0.5 hover:bg-muted/50 focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2">
          {children}
        </span>
      </span>
      <span
        ref={tooltipRef}
        role="tooltip"
        className={cn(
          'fixed z-[100] max-w-[260px] rounded-md border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg',
          'whitespace-normal break-words',
          'transition-opacity duration-200',
          visible ? 'opacity-100' : 'opacity-0 pointer-events-none'
        )}
        style={{
          top: coords.top,
          left: coords.left,
          visibility: visible ? 'visible' : 'hidden',
        }}
      >
        {content}
      </span>
    </>
  )
}
