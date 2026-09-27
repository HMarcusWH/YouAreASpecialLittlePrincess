export default function Home() {
  return (
    <div className="stack">
      <h1>Your handwriting, measured</h1>
      <p>
        Upload a photo of a page you wrote. You get a private report of what can actually be measured: slant,
        spacing, baseline, size and more, each labelled as measured or computed, with what could not be measured
        said plainly.
      </p>
      <p className="muted">
        The free report is produced by deterministic image measurement only. No AI is involved, nothing is ranked
        against other writers, and your image is not kept unless you choose to keep it.
      </p>
      <p><a className="button" href="/start">Start an analysis</a></p>
    </div>
  );
}
