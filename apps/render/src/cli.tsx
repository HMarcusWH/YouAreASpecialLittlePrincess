// princess-render: JSON on stdin, PDF/PNG bytes on stdout (or HTML with --html).
// --envelope-v3 is an explicit, independent private transport. Legacy input
// without that flag keeps the existing 2 MiB contract and v2 renderer.
import { parseInput, renderBytes, renderHtml, type RenderInput } from "./render.tsx";
import { parseV3Envelope, MAX_V3_INPUT_BYTES, type CheckedV3Envelope } from "./v3-input.ts";
import { renderBytesV3, renderHtmlV3 } from "./render-v3.tsx";

async function readStdin(limit: number): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += (chunk as Buffer).byteLength;
    if (size > limit) throw new Error("input_too_large");
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main(): Promise<number> {
  const v3 = process.argv.includes("--envelope-v3");
  let legacy: RenderInput | undefined;
  let candidate: CheckedV3Envelope | undefined;
  try {
    const raw = await readStdin(v3 ? MAX_V3_INPUT_BYTES : 2 * 1024 * 1024 + 1);
    if (v3) candidate = parseV3Envelope(raw);
    else legacy = parseInput(raw);
  } catch (error) {
    const message = error instanceof Error && /^[a-z_]{1,64}$/.test(error.message)
      ? error.message : "bad_input";
    process.stderr.write(message + "\n");
    return 2;
  }
  try {
    if (process.argv.includes("--html")) {
      process.stdout.write(candidate ? renderHtmlV3(candidate) : renderHtml(legacy!));
    } else {
      process.stdout.write(candidate ? await renderBytesV3(candidate) : await renderBytes(legacy!));
    }
    return 0;
  } catch (error) {
    const message = error instanceof Error && /^[a-z_]{1,64}$/.test(error.message)
      ? error.message : "render_failed";
    process.stderr.write(message + "\n");
    return 1;
  }
}

process.exitCode = await main();
