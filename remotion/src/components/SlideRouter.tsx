/**
 * SlideRouter — routes slide data to the correct component
 * based on slide type.
 */
import React from 'react';
import type { SlideData } from '../types';
import { Provocation } from './slides/Provocation';
import { Context } from './slides/Context';
import { Statute } from './slides/Statute';
import { Insight } from './slides/Insight';
import { Data } from './slides/Data';
import { Contrast } from './slides/Contrast';
import { Synthesis } from './slides/Synthesis';
import { Action } from './slides/Action';
import { Brand } from './slides/Brand';

const SLIDE_MAP: Record<string, React.FC<SlideData>> = {
  provocation: Provocation,
  context: Context,
  statute: Statute,
  insight: Insight,
  data: Data,
  contrast: Contrast,
  synthesis: Synthesis,
  action: Action,
  brand: Brand,
};

export const SlideRouter: React.FC<SlideData> = (props) => {
  const Component = SLIDE_MAP[props.type] || Insight;
  return <Component {...props} />;
};
