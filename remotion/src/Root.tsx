/**
 * Remotion Root — registers the Sulah Carousel Still composition.
 *
 * Each slide is rendered as an individual Still (PNG).
 * Props are passed as JSON from the CLI or render script.
 */
import { Still } from 'remotion';
import { SlideRouter } from './components/SlideRouter';
import { SLIDE } from './theme';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Still
        id="SulahSlide"
        component={SlideRouter}
        width={SLIDE.width}
        height={SLIDE.height}
        defaultProps={{
          type: 'provocation' as const,
          slideNumber: 1,
          totalSlides: 10,
          headline: 'Newspaper mein bedakhal karna legally kuch nahi karta.',
        }}
      />
    </>
  );
};
