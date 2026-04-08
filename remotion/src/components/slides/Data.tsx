/**
 * SLIDE: Data
 *
 * A single number dominates the entire slide at 96pt.
 * "87%" IS the slide. The number IS the visual.
 *
 * ANTI-PATTERN: Generic infographics surround numbers with pie charts,
 * icons, and decorative elements. We strip everything away.
 * The number stands alone like a verdict — unarguable.
 *
 * Inspired by: Bloomberg terminal aesthetics, Swiss railway clocks,
 * the brutal clarity of a scoreboard.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Data: React.FC<SlideData> = (props) => (
  <SlideFrame type="data" slideNumber={props.slideNumber}>
    <div style={{ flex: 1 }} />

    {/* The number — volcanic, gold, 96pt. The slide IS this number. */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 108,
        color: COLORS.gold,
        letterSpacing: '-3px',
        lineHeight: 1,
      }}
    >
      {props.number || '87%'}
    </div>

    {/* What the number means — understated cream */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 22,
        color: COLORS.cream,
        marginTop: 16,
        lineHeight: 1.4,
        maxWidth: '80%',
      }}
    >
      {props.numberCaption}
    </div>

    <GoldLine marginTop={40} marginBottom={32} width="25%" />

    {/* Source citation — whisper-quiet silver italic */}
    {props.citation && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 14,
          color: COLORS.silver,
          fontStyle: 'italic',
          opacity: 0.7,
          lineHeight: 1.5,
        }}
      >
        {props.citation}
      </div>
    )}

    <div style={{ flex: 1.5 }} />
  </SlideFrame>
);
