/**
 * SLIDE: Action — "Kya Karein?"
 *
 * 2-3 practical steps. This is the slide people screenshot.
 * Each step has a number in gold (not a bullet) that acts as
 * a visual anchor — like paragraph marks in a legal document.
 *
 * ANTI-PATTERN: Generic action slides use checkboxes, icons,
 * or colorful step-by-step graphics. We use typographic numbering
 * where the gold number IS the icon — minimal, precise, actionable.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Action: React.FC<SlideData> = (props) => (
  <SlideFrame type="action" slideNumber={props.slideNumber}>
    <div style={{ flex: 0.6 }} />

    {/* Section heading */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 34,
        color: COLORS.cream,
      }}
    >
      Kya karein?
    </div>

    <GoldLine marginTop={20} marginBottom={44} width="20%" />

    {/* Steps — gold number + cream text */}
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 36,
      }}
    >
      {(props.steps || []).map((step, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 24,
          }}
        >
          {/* Gold number — the visual anchor */}
          <div
            style={{
              fontFamily: FONTS.headline,
              fontSize: 36,
              color: COLORS.gold,
              lineHeight: 1,
              minWidth: 36,
            }}
          >
            {i + 1}
          </div>

          {/* Step text */}
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 19,
              lineHeight: 1.6,
              color: COLORS.cream,
              maxWidth: '85%',
              paddingTop: 4,
            }}
          >
            {step}
          </div>
        </div>
      ))}
    </div>

    <div style={{ flex: 1.5 }} />
  </SlideFrame>
);
