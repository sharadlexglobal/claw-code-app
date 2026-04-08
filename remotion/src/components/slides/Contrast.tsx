/**
 * SLIDE: Contrast (Myth vs Fact)
 *
 * Two zones. Top: the myth in red. Bottom: the fact in gold.
 * Between them: the gold line acts as a knife — cutting
 * the misconception cleanly from the truth.
 *
 * ANTI-PATTERN: Generic myth/fact slides use side-by-side boxes
 * with checkmarks and X icons. We use vertical spatial separation —
 * the myth physically descends while the fact rises.
 * The gold line is the moment of revelation.
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Contrast: React.FC<SlideData> = (props) => (
  <SlideFrame type="contrast" slideNumber={props.slideNumber}>
    <div style={{ flex: 0.8 }} />

    {/* MYTH zone — the misconception */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 12,
        fontWeight: 700,
        color: COLORS.alertRed,
        letterSpacing: '5px',
        textTransform: 'uppercase' as const,
        marginBottom: 20,
      }}
    >
      MYTH
    </div>
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 28,
        lineHeight: 1.35,
        color: COLORS.cream,
        opacity: 0.75,
        maxWidth: '90%',
      }}
    >
      &ldquo;{props.myth}&rdquo;
    </div>

    {/* The gold knife — separating myth from reality */}
    <GoldLine marginTop={50} marginBottom={50} width="50%" />

    {/* FACT zone — the truth */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 12,
        fontWeight: 700,
        color: COLORS.gold,
        letterSpacing: '5px',
        textTransform: 'uppercase' as const,
        marginBottom: 20,
      }}
    >
      FACT
    </div>
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 28,
        lineHeight: 1.35,
        color: COLORS.cream,
        maxWidth: '90%',
      }}
    >
      {props.fact}
    </div>

    {/* Citation */}
    {props.citation && (
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 13,
          color: COLORS.silver,
          marginTop: 28,
          fontStyle: 'italic',
          opacity: 0.6,
        }}
      >
        {props.citation}
      </div>
    )}

    <div style={{ flex: 1.2 }} />
  </SlideFrame>
);
