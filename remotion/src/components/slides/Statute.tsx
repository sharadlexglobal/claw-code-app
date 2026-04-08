/**
 * SLIDE: Statute
 *
 * The law citation AS the design element.
 * "Section 154" at 72pt in gold IS the visual.
 * The number has the weight of scripture.
 *
 * ANTI-PATTERN: Generic legal content buries citations in body text.
 * We elevate them to monumental scale — the law IS art.
 * Like numbers on a stock exchange board, impossible to look away.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Statute: React.FC<SlideData> = (props) => (
  <SlideFrame type="statute" slideNumber={props.slideNumber}>
    <div style={{ flex: 1 }} />

    {/* The statute number — monumental, gold, 72pt */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 72,
        color: COLORS.gold,
        letterSpacing: '-1px',
        lineHeight: 1.1,
      }}
    >
      {props.statute || 'Section 154'}
    </div>

    {/* Act name — silver, understated, counterweight to the gold monument */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 18,
        color: COLORS.silver,
        marginTop: 12,
        letterSpacing: '0.5px',
      }}
    >
      {props.actName}
    </div>

    <GoldLine marginTop={40} marginBottom={40} width="35%" />

    {/* The provision text — the quiet explanation beneath the monument */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 19,
        lineHeight: 1.65,
        color: COLORS.creamSoft,
        maxWidth: '85%',
      }}
    >
      {props.body}
    </div>

    {/* Citation — if provided */}
    {props.citation && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 13,
          color: COLORS.silver,
          marginTop: 28,
          fontStyle: 'italic',
          opacity: 0.7,
        }}
      >
        {props.citation}
      </div>
    )}

    <div style={{ flex: 1.5 }} />
  </SlideFrame>
);
