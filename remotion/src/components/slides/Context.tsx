/**
 * SLIDE: Context
 *
 * Sets the stage. Creates tension. "What most people believe..."
 * The typography hierarchy creates a reading path:
 * small label → medium heading → body text → silence.
 *
 * ANTI-PATTERN: Generic slides dump all text at the same size.
 * We create a visual staircase — the eye descends naturally.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Context: React.FC<SlideData> = (props) => (
  <SlideFrame type="context" slideNumber={props.slideNumber}>
    {/* Top breathing room */}
    <div style={{ flex: 0.8 }} />

    {/* Small label — the category whisper */}
    {props.tag && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 13,
          fontWeight: 700,
          color: COLORS.gold,
          letterSpacing: '4px',
          textTransform: 'uppercase' as const,
          marginBottom: 32,
        }}
      >
        {props.tag}
      </div>
    )}

    {/* Heading — the misconception stated plainly */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 38,
        lineHeight: 1.3,
        color: COLORS.cream,
        maxWidth: '90%',
      }}
    >
      {props.headline}
    </div>

    <GoldLine marginTop={36} marginBottom={36} />

    {/* Body — 2-3 lines, the common belief expanded */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 19,
        lineHeight: 1.7,
        color: COLORS.creamSoft,
        maxWidth: '88%',
      }}
    >
      {props.body}
    </div>

    {/* Bottom silence — the weight of what's coming */}
    <div style={{ flex: 1.5 }} />
  </SlideFrame>
);
