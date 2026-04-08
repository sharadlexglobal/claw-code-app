/**
 * Sulah Design System — "Midnight Authority"
 *
 * Design philosophy: The opposite of every Instagram template.
 * Where others shout, we whisper. Where others crowd, we breathe.
 * The emptiness IS the message. The restraint IS the authority.
 *
 * Think: Edward Tufte's data-ink ratio meets Dieter Rams' "less but better"
 * meets the weight of a Supreme Court judgment — sparse, precise, irreversible.
 */

// ── Colors ──────────────────────────────────────────────────────────────────

export const COLORS = {
  // Primary surfaces — subtle temperature shift across slides (narrative arc)
  midnight: '#0f1923',        // deep midnight — core knowledge slides
  midnightWarm: '#12202c',    // slightly warm — provocation/tension slides
  midnightLight: '#162230',   // lighter — resolution/clarity slides
  midnightDeep: '#0a1219',    // deepest — brand close

  // Text
  cream: '#f4f1eb',           // warm cream — primary text
  creamSoft: 'rgba(244, 241, 235, 0.85)', // 85% opacity — body text
  silver: '#8a9bb0',          // muted silver — secondary text, watermark

  // Accents
  gold: '#d4a853',            // Sulah gold — max 10% of any slide
  goldSoft: 'rgba(212, 168, 83, 0.6)',  // subtle gold — separator lines
  alertRed: '#c0392b',        // deep red — myth markers only

  // Functional
  transparent: 'transparent',
} as const;

// ── Typography ──────────────────────────────────────────────────────────────
// Google Fonts loaded at render time

export const FONTS = {
  headline: "'Playfair Display', 'DM Serif Display', Georgia, serif",
  body: "'Inter', 'Source Sans Pro', -apple-system, sans-serif",
} as const;

// ── Dimensions ──────────────────────────────────────────────────────────────

export const SLIDE = {
  width: 1080,
  height: 1350,    // 4:5 Instagram carousel ratio
  margin: 130,     // ~12% margin all sides
} as const;

// ── The Golden Line ─────────────────────────────────────────────────────────
// The thin gold separator — Sulah's signature. 1px. Never thicker.

export const GOLD_LINE = {
  height: 1,
  color: COLORS.goldSoft,
  width: '40%',    // never full width — restraint
} as const;

// ── Slide Background Temperature Map ────────────────────────────────────────
// Subtle 2-3% brightness shift creates unconscious narrative flow

export const SLIDE_BG: Record<string, string> = {
  provocation: COLORS.midnightWarm,
  context: COLORS.midnightWarm,
  statute: COLORS.midnight,
  insight: COLORS.midnight,
  data: COLORS.midnight,
  contrast: COLORS.midnight,
  synthesis: COLORS.midnightLight,
  action: COLORS.midnightLight,
  brand: COLORS.midnightDeep,
} as const;
