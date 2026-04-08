/**
 * SLIDE: Brand Close
 *
 * "Sulah" in large serif. "Resolve Your Disputes" below.
 * One-line CTA. Maximum restraint.
 *
 * This slide is 80% negative space. The brand name floats
 * at the visual center of gravity (slightly above mathematical center).
 * Pure presence. No decoration. No contact info. No solicitation.
 *
 * ANTI-PATTERN: Most brand slides are logo-heavy with social handles,
 * phone numbers, and "Follow us!" CTAs. We have NOTHING except
 * the name, the tagline, and a whispered CTA.
 * The emptiness communicates: "We don't need to sell. We are."
 */
import React from 'react';
import { SlideFrame } from '../SlideFrame';
import { GoldLine } from '../GoldLine';
import { COLORS, FONTS } from '../../theme';
import type { SlideData } from '../../types';

export const Brand: React.FC<SlideData> = (props) => (
  <SlideFrame type="brand">
    <div style={{ flex: 1.6 }} />

    {/* Brand name — the only thing that matters */}
    <div
      style={{
        fontFamily: FONTS.headline,
        fontSize: 64,
        color: COLORS.cream,
        letterSpacing: '2px',
        textAlign: 'center' as const,
        alignSelf: 'center',
      }}
    >
      Sulah
    </div>

    {/* Tagline — silver, understated */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 17,
        color: COLORS.silver,
        letterSpacing: '4px',
        textTransform: 'uppercase' as const,
        textAlign: 'center' as const,
        alignSelf: 'center',
        marginTop: 16,
      }}
    >
      Resolve Your Disputes
    </div>

    <GoldLine width="15%" marginTop={48} marginBottom={48} align="center" />

    {/* CTA — the gentlest possible nudge */}
    <div
      style={{
        fontFamily: FONTS.body,
        fontSize: 16,
        color: COLORS.creamSoft,
        textAlign: 'center' as const,
        alignSelf: 'center',
        lineHeight: 1.6,
        maxWidth: '70%',
      }}
    >
      {props.cta || 'Save karke rakho. Share karke help karo.'}
    </div>

    <div style={{ flex: 2 }} />
  </SlideFrame>
);
