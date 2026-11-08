import { X } from 'lucide-react';
import styles from './RightPanelDesign.module.css';

export function RightPanelHeader({ symbols, selected, onSelect, onCollapse }: {
  symbols: string[]; selected?: string; onSelect: (symbol: string) => void; onCollapse: () => void;
}) {
  return <div className={styles.header}>
    <span className={styles.headerLabel}>相关标的</span>
    <div className={styles.chips}>{symbols.map((symbol) => <button type="button" key={symbol}
      className={`num ${styles.chip} ${selected === symbol ? styles.chipActive : ''}`} aria-pressed={selected === symbol}
      onClick={() => onSelect(symbol)}>{symbol}</button>)}</div>
    <button type="button" className={styles.close} onClick={onCollapse} aria-label="收起面板"><X size={15} /></button>
  </div>;
}
