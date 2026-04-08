/**
 * SLIDE: Provocation
 *
 * One sentence. Maximum scale. 60% negative space.
 * The entire slide IS the hook statement.
 * Like a Supreme Court headnote — sparse, devastating, impossible to ignore.
 *
 * ANTI-PATTERN: Generic carousels put hooks in small text with decorative
 * backgrounds. We do the opposite — the text IS the background.
 * The emptiness around it creates gravitational pull.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Provocation: React.FC<SlideData> = (props) => (
  <SlideFrame type="provocation" slideNumber={props.slideNumber}>
    {/* Massive vertical space above — the silence before the statement */}
    <div style={{ flex: 1.2 }} />

    {/* The one statement — headline serif at maximum weight */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: props.headline && props.headline.length > 40 ? 48 : 56,
        lineHeight: 1.25,
        color: COLORS.cream,
        letterSpacing: '-0.5px',
        maxWidth: '95%',
      }}
    >
      {props.headline}
    </div>

    {/* Subtitle — only if absolutely needed for clarity */}
    {props.subheadline && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 20,
          color: COLORS.silver,
          marginTop: 24,
          lineHeight: 1.5,
        }}
      >
        {props.subheadline}
      </div>
    )}

    {/* The rest is silence */}
    <div style={{ flex: 2 }} />

    {/* Gold line + brand tagline at the very bottom */}
    <GoldLine width="30%" />
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 12,
        color: COLORS.silver,
        letterSpacing: '3px',
        textTransform: 'uppercase' as const,
        marginTop: 8,
      }}
    >
      SULAH — RESOLVE YOUR DISPUTES
    </div>
  </SlideFrame>
);
