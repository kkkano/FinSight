import type { MouseEvent, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

interface TickerLinkProps {
  ticker: string;
  children?: ReactNode;
}

export function TickerLink({ ticker, children }: TickerLinkProps) {
  const navigate = useNavigate();
  const href = `/dashboard/${encodeURIComponent(ticker)}`;

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(href);
  };

  return (
    <a
      href={href}
      onClick={handleClick}
      className="font-mono text-t-accent hover:underline cursor-pointer"
      title={`查看 ${ticker} 看板`}
    >
      {children ?? ticker}
    </a>
  );
}
