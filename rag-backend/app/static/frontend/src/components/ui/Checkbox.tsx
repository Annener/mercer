import { forwardRef } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import { clsx } from './clsx';

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, className, ...rest },
  ref,
) {
  if (!label) {
    return (
      <input
        ref={ref}
        type="checkbox"
        className={clsx('h-4 w-4 rounded border-border text-primary', className)}
        {...rest}
      />
    );
  }
  return (
    <label className={clsx('inline-flex cursor-pointer items-center gap-2 text-sm', className)}>
      <input
        ref={ref}
        type="checkbox"
        className="h-4 w-4 rounded border-border text-primary"
        {...rest}
      />
      <span>{label}</span>
    </label>
  );
});