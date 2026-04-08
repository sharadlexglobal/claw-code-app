/**
 * Sulah Carousel Renderer
 *
 * Usage from CLI:
 *   node render.mjs '{"slides": [...]}' ./output
 *
 * Usage from Python:
 *   subprocess.run(["node", "remotion/render.mjs", json_string, output_dir])
 *
 * Renders each slide as a PNG: slide_01.png, slide_02.png, etc.
 * Returns JSON to stdout with results.
 */
import { bundle } from '@remotion/bundler';
import { renderStill, ensureBrowser } from '@remotion/renderer';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error('Usage: node render.mjs \'<json_props>\' <output_dir>');
    process.exit(1);
  }

  const slidesData = JSON.parse(args[0]);
  const outputDir = args[1];
  const slides = slidesData.slides || [];

  if (slides.length === 0) {
    console.error('No slides provided');
    process.exit(1);
  }

  // Ensure output directory exists
  fs.mkdirSync(outputDir, { recursive: true });

  // Ensure headless browser is available
  await ensureBrowser();

  // Bundle the Remotion project
  console.error(`[REMOTION] Bundling project...`);
  const bundleLocation = await bundle({
    entryPoint: path.join(__dirname, 'src/index.ts'),
    onProgress: (progress) => {
      if (progress % 25 === 0) {
        console.error(`[REMOTION] Bundle progress: ${progress}%`);
      }
    },
  });
  console.error(`[REMOTION] Bundle complete: ${bundleLocation}`);

  // Render each slide
  const results = [];
  for (let i = 0; i < slides.length; i++) {
    const slide = slides[i];
    const slideNum = String(i + 1).padStart(2, '0');
    const outputPath = path.join(outputDir, `slide_${slideNum}.png`);

    console.error(`[REMOTION] Rendering slide ${i + 1}/${slides.length}: ${slide.type}`);

    try {
      await renderStill({
        composition: {
          id: 'SulahSlide',
          width: 1080,
          height: 1350,
          durationInFrames: 1,
          fps: 1,
          defaultProps: slide,
          defaultCodec: null,
          props: slide,
        },
        serveUrl: bundleLocation,
        output: outputPath,
        inputProps: slide,
        imageFormat: 'png',
        scale: 1,
        chromiumOptions: {
          enableMultiProcessOnLinux: true,
        },
      });

      const stats = fs.statSync(outputPath);
      results.push({
        slide: i + 1,
        type: slide.type,
        file: `slide_${slideNum}.png`,
        path: outputPath,
        size: stats.size,
        status: 'ok',
      });
      console.error(`[REMOTION] ✓ slide_${slideNum}.png (${(stats.size / 1024).toFixed(1)}KB)`);
    } catch (err) {
      results.push({
        slide: i + 1,
        type: slide.type,
        file: `slide_${slideNum}.png`,
        status: 'error',
        error: err.message,
      });
      console.error(`[REMOTION] ✗ slide_${slideNum}.png: ${err.message}`);
    }
  }

  // Output results as JSON to stdout
  console.log(JSON.stringify({
    total: slides.length,
    rendered: results.filter(r => r.status === 'ok').length,
    outputDir,
    files: results,
  }));
}

main().catch((err) => {
  console.error(`[REMOTION] Fatal error: ${err.message}`);
  process.exit(1);
});
