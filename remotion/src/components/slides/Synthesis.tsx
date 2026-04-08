/**
 * SLIDE: Synthesis — "Yaad Rakhiye"
 *
 * The recap. 3-4 takeaways, each on its own line with generous spacing.
 * Should feel like a page from a beautifully typeset book —
 * where line-spacing itself is a design element.
 *
 * ANTI-PATTERN: Generic recap slides use bullet points or numbered lists
 * with tight spacing. We use line-as-breath — each point floats
 * in its own pool of silence. No bullets. Just text and space.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Synthesis: React.FC<SlideData> = (props) => (
  <SlideFrame type="synthesis" slideNumber={props.slideNumber}>
    <div style={{ flex: 0.6 }} />

    {/* Section label in gold */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 32,
        color: COLORS.gold,
        marginBottom: 12,
      }}
    >
      Yaad rakhiye
    </div>

    <GoldLine marginTop={16} marginBottom={44} width="20%" />

    {/* Points — each one a standalone line, generous spacing */}
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 32,
      }}
    >
      {(props.points || []).map((point, i) => (
        <div
          key={i}
          style={{
            fontFamily: FONTS.body,
            fontSize: 20,
            lineHeight: 1.6,
            color: COLORS.cream,
            maxWidth: '90%',
            paddingLeft: 0,
          }}
        >
          {point}
        </div>
      ))}
    </div>

    <div style={{ flex: 1.5 }} />
  </SlideFrame>
);
