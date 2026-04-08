/** Slide data passed as props from Content Factory */

export type SlideType =
  | 'provocation'
  | 'context'
  | 'statute'
  | 'insight'
  | 'data'
  | 'contrast'
  | 'synthesis'
  | 'action'
  | 'brand';

export interface SlideData {
  type: SlideType;
  slideNumber: number;
  totalSlides: number;

  // Content fields — each slide type uses a subset
  headline?: string;
  subheadline?: string;
  body?: string;
  tag?: string;           // e.g. "SECTION 498A IPC"
  statute?: string;       // e.g. "Section 154"
  actName?: string;       // e.g. "Code of Criminal Procedure"
  citation?: string;      // e.g. "Supreme Court, Lalita Kumari vs Govt. of UP (2014)"
  number?: string;        // e.g. "87%" — for data slides
  numberCaption?: string; // e.g. "of FIR refusals are illegal"

  // Contrast slide
  myth?: string;
  fact?: string;

  // Synthesis slide
  points?: string[];

  // Action slide
  steps?: string[];

  // Brand slide
  cta?: string;
}

export interface CarouselProps {
  slides: SlideData[];
}
