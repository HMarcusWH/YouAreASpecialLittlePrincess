// Renders one saved, already-authorized projection to PDF or PNG. The page is
// static: JavaScript is disabled and every network request is aborted, so a
// hostile string in a fact can neither run nor fetch anything.
import tokensCss from "@princess/design-tokens/tokens.css";
import reportCss from "@princess/report-web/report.css";
import { parseReportView } from "@princess/api-client";
import { PrintReport, ShareCard, type Locale } from "@princess/report-web";
import { chromium, type Browser } from "playwright-core";
import { renderToStaticMarkup } from "react-dom/server";

export const TEMPLATE_VERSION = "render-template/2";
export type Layout = "A4" | "LETTER" | "CARD_SQUARE" | "CARD_STORY";
const LAYOUTS = new Set<Layout>(["A4", "LETTER", "CARD_SQUARE", "CARD_STORY"]);
const CARD_SIZE = { CARD_SQUARE: { width: 1080, height: 1080 }, CARD_STORY: { width: 1080, height: 1920 } } as const;
export const MAX_INPUT_BYTES = 2 * 1024 * 1024;
export const MAX_OUTPUT_BYTES = 10 * 1024 * 1024;

export interface RenderInput {
  readonly view: unknown;
  readonly layout: Layout;
  readonly locale: Locale;
  readonly generated_at: string;
}

export function parseInput(raw: string): RenderInput {
  if (Buffer.byteLength(raw) > MAX_INPUT_BYTES) throw new Error("input_too_large");
  const input = JSON.parse(raw) as Partial<RenderInput>;
  if (!LAYOUTS.has(input.layout as Layout)) throw new Error("unknown_layout");
  if (input.locale !== "en" && input.locale !== "sv") throw new Error("unsupported_locale");
  if (typeof input.generated_at !== "string" || !/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(input.generated_at)) {
    throw new Error("invalid_generated_at");
  }
  return input as RenderInput;
}

export function renderHtml(input: RenderInput): string {
  const view = parseReportView(input.view);
  const card = input.layout === "CARD_SQUARE" || input.layout === "CARD_STORY";
  if (card && view.projection !== "SHARE") throw new Error("cards_render_share_projections_only");
  if (!card && view.projection !== "EXPORT") throw new Error("documents_render_export_projections_only");
  const body = card
    ? renderToStaticMarkup(<ShareCard view={view} locale={input.locale}
                                      shape={input.layout === "CARD_STORY" ? "story" : "square"} />)
    : renderToStaticMarkup(<PrintReport view={view} locale={input.locale} generatedAt={input.generated_at} />);
  const title = card ? "Inktrospect" : `Inktrospect report ${view.source_report_id} r${view.source_revision}`;
  return `<!doctype html><html lang="${input.locale}" data-theme="light"><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">` +
    `<title>${escapeHtml(title)}</title><style>${tokensCss}\n${reportCss}\n` +
    `@page { margin: 18mm; } body { margin: 0; background: var(--color-surface); }</style></head>` +
    `<body>${body}</body></html>`;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export async function renderBytes(input: RenderInput, browser?: Browser): Promise<Buffer> {
  const html = renderHtml(input);
  const owned = browser === undefined;
  const instance = browser ?? await chromium.launch(
    process.env.PRINCESS_CHROMIUM ? { executablePath: process.env.PRINCESS_CHROMIUM } : {});
  try {
    const card = input.layout === "CARD_SQUARE" || input.layout === "CARD_STORY";
    const context = await instance.newContext({
      javaScriptEnabled: false, offline: true, colorScheme: "light",
      ...(card ? { viewport: CARD_SIZE[input.layout as keyof typeof CARD_SIZE], deviceScaleFactor: 1 } : {}),
    });
    await context.route("**/*", (route) => route.abort());
    const page = await context.newPage();
    await page.setContent(html, { waitUntil: "load", timeout: 15_000 });
    const bytes = card
      ? await page.screenshot({ type: "png", fullPage: false })
      : await page.pdf({ format: input.layout === "LETTER" ? "Letter" : "A4", printBackground: true, tagged: true,
                         outline: true, margin: { top: "18mm", bottom: "18mm", left: "16mm", right: "16mm" } });
    await context.close();
    if (bytes.byteLength > MAX_OUTPUT_BYTES) throw new Error("output_too_large");
    return Buffer.from(bytes);
  } finally {
    if (owned) await instance.close();
  }
}
