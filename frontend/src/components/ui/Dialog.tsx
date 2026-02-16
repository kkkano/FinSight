import type { MouseEvent, ReactNode } from 'react';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  labelledBy?: string;
  panelClassName?: string;
  overlayClassName?: string;
}

export function Dialog({
  open,
  onClose,
  children,
  labelledBy,
  panelClassName = '',
  overlayClassName = '',
}: DialogProps) {
  if (!open) return null;

  const handleBackdropClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  return (
    <div
      className={`fixed inset-0 z-50 p-4 bg-black/60 backdrop-blur-sm flex items-center justify-center ${overlayClassName}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      onMouseDown={handleBackdropClick}
    >
      <div className={panelClassName}>{children}</div>
    </div>
  );
}
