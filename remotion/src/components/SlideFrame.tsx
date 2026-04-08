/**
 * SlideFrame — The bones of every Sulah slide.
 *
 * Not a "card" or "container" — a frame of silence
 * within which one idea breathes at maximum scale.
 */
import React from 'react';
import { COLORS, SLIDE, FONTS, SLIDE_BG } from '../theme';
import type { SlideType } from '../types';

interface SlideFrameProps {
  type: SlideType;
  children: React.ReactNode;
  slideNumber?: number;
}

export const SlideFrame: React.FC<SlideFrameProps> = ({
  type,
  children,
  slideNumber,
}) => {
  const bg = SLIDE_BG[type] || COLORS.midnight;

  return (
    <div
      style={{
        width: SLIDE.width,
        height: SLIDE.height,
        backgroundColor: bg,
        position: 'relative',
        overflow: 'hidden',
        fontFamily: FONTS.body,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Content area with margins */}
      <div
        style={{
          position: 'absolute',
          top: SLIDE.margin,
          left: SLIDE.margin,
          right: SLIDE.margin,
          bottom: SLIDE.margin,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {children}
      </div>

      {/* Sulah watermark — bottom right, near-invisible authority */}
      <div
        style={{
          position: 'absolute',
          bottom: SLIDE.margin * 0.65,
          right: SLIDE.margin,
          fontFamily: FONTS.headline,
          fontSize: 13,
          color: COLORS.silver,
          opacity: 0.5,
          letterSpacing: '2px',
        }}
      >
        Sulah
      </div>

      {/* Slide number — bottom left, whisper-quiet */}
      {slideNumber && (
        <div
          style={{
            position: 'absolute',
            bottom: SLIDE.margin * 0.65,
            left: SLIDE.margin,
            fontFamily: FONTS.body,
            fontSize: 11,
            color: COLORS.silver,
            opacity: 0.3,
            letterSpacing: '1px',
          }}
        >
          {String(slideNumber).padStart(2, '0')}
        </div>
      )}
    </div>
  );
};
