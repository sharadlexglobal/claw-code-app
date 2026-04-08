/**
 * GoldLine — Sulah's signature divider.
 *
 * 1px thin. Never thicker. 40% width. Left-aligned.
 * The restraint of this line communicates more authority
 * than any bold separator ever could.
 */
import React from 'react';
import { GOLD_LINE } from '../theme';

interface GoldLineProps {
  width?: string;
  marginTop?: number;
  marginBottom?: number;
  align?: 'left' | 'center';
}

export const GoldLine: React.FC<GoldLineProps> = ({
  width = GOLD_LINE.width,
  marginTop = 40,
  marginBottom = 40,
  align = 'left',
}) => (
  <div
    style={{
      width,
      height: GOLD_LINE.height,
      backgroundColor: GOLD_LINE.color,
      marginTop,
      marginBottom,
      alignSelf: align === 'center' ? 'center' : 'flex-start',
    }}
  />
);
