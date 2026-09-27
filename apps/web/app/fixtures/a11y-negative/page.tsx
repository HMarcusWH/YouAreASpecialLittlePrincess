import { notFound } from "next/navigation";

export default function AccessibilityNegativeFixture() {
  if (process.env.PRINCESS_WEB_FIXTURES !== "1") notFound();
  return (
    <section className="stack">
      <h1>Accessibility negative control</h1>
      <p>This fixture is intentionally invalid and exists only to prove the automated gate fires.</p>
      <input type="text" />
    </section>
  );
}
