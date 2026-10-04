// Native rendering of the accepted Dossier tokens (design-tokens/1.0). Colours
// and spacing are shared; fonts use reviewed platform fallbacks (no remote font
// hosting): a serif for reading text and a monospace face for numeric values.
import { tokens } from "@princess/design-tokens";
import { Platform } from "react-native";

export type Scheme = "light" | "dark";
export type Palette = { readonly [K in keyof typeof tokens.color.light]: string };

export interface Theme {
  readonly scheme: Scheme;
  readonly color: Palette;
  readonly serif: string;
  readonly mono: string;
  readonly sans: string;
  readonly chart: readonly string[];
  /** Evidence/specimen light-table colours stay fixed across light/night report themes. */
  readonly plate: { readonly surface: string; readonly border: string; readonly ink: string };
}

const SERIF = Platform.select({ ios: "Georgia", android: "serif", default: "serif" });
const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" });
const SANS = Platform.select({ ios: "System", android: "sans-serif", default: "System" });

export function themeFor(scheme: Scheme): Theme {
  return {
    scheme,
    color: tokens.color[scheme],
    serif: SERIF,
    mono: MONO,
    sans: SANS,
    chart: tokens.chart.series,
    // v3 keeps handwriting/evidence plates on the light-table palette even in night mode.
    plate: {
      surface: tokens.color.light["surface-raised"],
      border: tokens.color.light.border,
      ink: tokens.color.light.text,
    },
  };
}

function px(value: string): number {
  return value.endsWith("rem") ? Number.parseFloat(value) * 16 : Number.parseFloat(value);
}

export const space = (step: keyof typeof tokens.space): number => px(tokens.space[step]);
export const radius = (size: keyof typeof tokens.radius): number => px(tokens.radius[size]);
export const fontSize = (size: keyof typeof tokens.font.size): number => px(tokens.font.size[size]);
export const MIN_TOUCH = px(tokens.target["min-touch"]);
/** Content column width on tablets; phones use the full width with gutters. */
export const MAX_COLUMN = 760;
export const WIDE_LAYOUT = px(tokens.breakpoint.lg);

export const EVIDENCE_COLOR = {
  MEASURED: "evidence-measured", COMPUTATIONAL_PROXY: "evidence-proxy", REFERENCE_STATISTIC: "evidence-reference",
  AUTHORED_CONTENT: "evidence-authored", TRADITIONAL_ASSOCIATION: "evidence-traditional", AI_SYNTHESIS: "evidence-ai",
} as const;
