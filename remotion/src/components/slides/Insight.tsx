/**
 * SLIDE: Insight
 *
 * Pure knowledge delivery. One truth, stated with Feynman clarity.
 * The headline carries all the weight. Body is the gentle landing.
 *
 * ANTI-PATTERN: Most carousels have equal-sized text blocks that
 * look like PowerPoint. We create a single focal point —
 * like a spotlight on a dark stage. One idea, nothing else.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Insight: React.FC<SlideData> = (props) => (
  <SlideFrame type="insight" slideNumber={props.slideNumber}>
    <div style={{ flex: 1 }} />

    {/* Tag label — subtle gold marker */}
    {props.tag && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 12,
          fontWeight: 700,
          color: COLORS.gold,
          letterSpacing: '4px',
          textTransform: 'uppercase' as const,
          marginBottom: 28,
        }}
      >
        {props.tag}
      </div>
    )}

    {/* The truth — medium-large serif, warm cream */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 36,
        lineHeight: 1.35,
        color: COLORS.cream,
        maxWidth: '92%',
      }}
    >
      {props.headline}
    </div>

    <GoldLine marginTop={32} marginBottom={32} />

    {/* Explanation — Feynman simple, 3 lines max */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 18,
        lineHeight: 1.7,
        color: COLORS.creamSoft,
        maxWidth: '85%',
      }}
    >
      {props.body}
    </div>

    <div style={{ flex: 1.8 }} />
  </SlideFrame>
);
