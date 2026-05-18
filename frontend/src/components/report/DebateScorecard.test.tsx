import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DebateScorecard } from './DebateScorecard';
import type { DebateArtifact } from '../../types/index';

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

describe('DebateScorecard', () => {
  it('renders bull score, bear score, key disagreements, and open questions', () => {
    const debate: DebateArtifact = {
      enabled: true,
      status: 'ready',
      bull_score: 0.72,
      bear_score: 0.41,
      judge_score: 0.58,
      key_disagreements: [
        'Margin durability depends on services mix.',
        'China demand recovery remains contested.',
      ],
      open_questions: [
        'Can China demand recover by next quarter?',
        'Will buybacks offset slower unit growth?',
      ],
    };

    const text = renderText(<DebateScorecard debate={debate} />);

    expect(text).toContain('Bull');
    expect(text).toContain('72');
    expect(text).toContain('Bear');
    expect(text).toContain('41');
    expect(text).toContain('Margin durability depends on services mix.');
    expect(text).toContain('Can China demand recover by next quarter?');
  });
});
