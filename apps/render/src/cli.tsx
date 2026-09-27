// princess-render: JSON on stdin, PDF/PNG bytes on stdout (or HTML with --html).
// Errors go to stderr as one code; exit status 2 for bad input, 1 otherwise.
import { parseInput, renderBytes, renderHtml } from "./render.tsx";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += (chunk as Buffer).byteLength;
    if (size > 2 * 1024 * 1024 + 1) throw new Error("input_too_large");
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main(): Promise<number> {
  let input;
  try {
    input = parseInput(await readStdin());
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : "bad_input"}\n`);
    return 2;
  }
  try {
    if (process.argv.includes("--html")) {
      process.stdout.write(renderHtml(input));
    } else {
      process.stdout.write(await renderBytes(input));
    }
    return 0;
  } catch (error) {
    const message = error instanceof Error && /^[a-z_]{1,64}$/.test(error.message) ? error.message : "render_failed";
    process.stderr.write(`${message}\n`);
    return 1;
  }
}

process.exitCode = await main();
