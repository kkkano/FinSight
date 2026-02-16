import type { ReactNode } from 'react';

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  testId?: string;
}

interface TabsProps<T extends string> {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  listClassName?: string;
  buttonClassName?: string;
  activeClassName?: string;
  inactiveClassName?: string;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  listClassName = '',
  buttonClassName = '',
  activeClassName = '',
  inactiveClassName = '',
}: TabsProps<T>) {
  return (
    <div role="tablist" className={listClassName}>
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            aria-disabled={item.disabled}
            disabled={item.disabled}
            data-testid={item.testId}
            onClick={() => onChange(item.value)}
            className={`${buttonClassName} ${active ? activeClassName : inactiveClassName}`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
