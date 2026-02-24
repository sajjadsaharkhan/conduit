import * as React from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  onCheckedChange?: (checked: boolean) => void
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, checked, onCheckedChange, onChange, ...props }, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange?.(e)
      onCheckedChange?.(e.target.checked)
    }
    return (
      <label className={cn('relative inline-flex cursor-pointer items-center gap-2', className)}>
        <input
          type="checkbox"
          ref={ref}
          checked={checked}
          onChange={handleChange}
          className="sr-only"
          {...props}
        />
        <span
          className={cn(
            'flex h-4 w-4 shrink-0 items-center justify-center rounded border border-input bg-background ring-offset-background transition-colors focus-visible:outline-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
            checked && 'border-primary bg-primary text-primary-foreground'
          )}
        >
          {checked ? <Check className="h-3 w-3 text-primary-foreground" strokeWidth={2.5} /> : null}
        </span>
      </label>
    )
  }
)
Checkbox.displayName = 'Checkbox'

export { Checkbox }
