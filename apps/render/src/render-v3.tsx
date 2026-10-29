// V3 Free-only renderer. The ordinary v2 input/renderer stays unchanged.
// Output has one source of truth: the already-validated saved projection.
import tokensCss from "@princess/design-tokens/tokens.css";
import reportCss from "@princess/report-web/report.css";
import { PrintReport, PrintSourceEvidence, ShareCard, type Locale } from "@princess/report-web";
import { chromium, type Browser, type BrowserContext } from "playwright-core";
import { renderToStaticMarkup } from "react-dom/server";

import type { CheckedV3Envelope } from "./v3-input.ts";

export const RENDER_V3_TEMPLATE = "render-template/3";
const MAX_OUTPUT = 10 * 1024 * 1024;
const CARD_SIZE = {
  CARD_SQUARE: { width: 1080, height: 1080 },
  CARD_STORY: { width: 1080, height: 1920 },
} as const;

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => "&#" + ch.charCodeAt(0) + ";");
}

export function renderHtmlV3(input: CheckedV3Envelope): string {
  const envelope = input.envelope;
  const card = envelope.layout === "CARD_SQUARE" || envelope.layout === "CARD_STORY";
  const locale = envelope.locale as Locale;
  const source = input.imageDataUri && envelope.evidence ? (
    <PrintSourceEvidence view={envelope.view} bundle={envelope.evidence}
                         imageDataUri={input.imageDataUri} locale={locale} />
  ) : undefined;
  const body = card ? (
    <ShareCard view={envelope.view} locale={locale}
               shape={envelope.layout === "CARD_STORY" ? "story" : "square"} />
  ) : (
    <PrintReport view={envelope.view} locale={locale} generatedAt={envelope.generated_at}
                 detail={envelope.detail} evidence={envelope.evidence} sourceEvidence={source} />
  );
  const title = card ? "Inktrospect" :
    "Inktrospect report " + envelope.view.source_report_id + " r" + envelope.view.source_revision;
  const csp = "default-src 'none'; style-src 'unsafe-inline';" +
    (input.imageDataUri ? " img-src data:;" : "");
  return '<!doctype html><html lang="' + locale + '" data-theme="light"><head>' +
    '<meta charset="utf-8">' +
    '<meta http-equiv="Content-Security-Policy" content="' + escapeHtml(csp) + '">' +
    '<title>' + escapeHtml(title) + '</title>' +
    '<style>' + tokensCss + '\n' + reportCss + '\n' +
    '@page { margin: 18mm; } body { margin: 0; background: var(--color-surface); }' +
    '</style></head><body data-render-template="render-template/3" data-render-detail="' +
    envelope.detail + '">' + renderToStaticMarkup(body) + '</body></html>';
}

export async function renderBytesV3(input: CheckedV3Envelope, browser?: Browser): Promise<Buffer> {
  const html = renderHtmlV3(input);
  let instance: Browser | undefined = browser;
  const owned = browser === undefined;
  let context: BrowserContext | undefined;
  let phase = "browser_launch_failed";
  try {
    instance ??= await chromium.launch(
      process.env.PRINCESS_CHROMIUM ? { executablePath: process.env.PRINCESS_CHROMIUM } : {});
    phase = "browser_context_failed";
    const layout = input.envelope.layout;
    const card = layout === "CARD_SQUARE" || layout === "CARD_STORY";
    context = await instance.newContext({
      javaScriptEnabled: false, offline: true, colorScheme: "light",
      ...(card ? { viewport: CARD_SIZE[layout as keyof typeof CARD_SIZE], deviceScaleFactor: 1 } : {}),
    });
    // Chromium is only a PDF drawing process, never a network/process oracle.
    await context.route("**/*", (route) => route.abort());
    const page = await context.newPage();
    phase = "page_content_failed";
    await page.setContent(html, { waitUntil: "load", timeout: 15_000 });
    phase = "browser_output_failed";
    const output = card
      ? await page.screenshot({ type: "png", fullPage: false })
      : await page.pdf({
          format: layout === "LETTER" ? "Letter" : "A4", printBackground: true,
          tagged: true, outline: true,
          margin: { top: "18mm", bottom: "18mm", left: "16mm", right: "16mm" },
        });
    if (!output.byteLength || output.byteLength > MAX_OUTPUT) throw new Error("output_too_large");
    phase = "render_cleanup_failed";
    await context.close();
    context = undefined;
    return Buffer.from(output);
  } catch (err) {
    if (err instanceof Error && /^[a-z0-9_]{1,64}$/.test(err.message)) throw err;
    throw new Error(phase);
  } finally {
    if (context) await context.close().catch(() => undefined);
    if (owned && instance) await instance.close().catch(() => undefined);
  }
}
