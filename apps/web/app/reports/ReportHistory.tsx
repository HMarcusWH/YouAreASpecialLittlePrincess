import type { ReportPage } from "@princess/contracts";

type Locale = "en" | "sv";

const COPY = {
  en: {
    title: "Your reports",
    intro: "Reports saved to this current session or account. Cross-device account recovery is not available until sign-in is configured.",
    empty: "You do not have any saved reports yet.",
    start: "Start an analysis",
    open: "Open report",
    revision: "Revision",
    next: "Older reports",
    kinds: { INDIVIDUAL: "Individual report", PAIR: "Pair report", HISTORY: "History report" },
  },
  sv: {
    title: "Dina rapporter",
    intro: "Rapporter som sparats i den här sessionen eller på det här kontot. Återställning mellan enheter är inte tillgänglig förrän inloggning är konfigurerad.",
    empty: "Du har inga sparade rapporter ännu.",
    start: "Starta en analys",
    open: "Öppna rapport",
    revision: "Version",
    next: "Äldre rapporter",
    kinds: { INDIVIDUAL: "Individuell rapport", PAIR: "Parrapport", HISTORY: "Historikrapport" },
  },
} as const;

export function ReportHistory({ page, locale }: { page: ReportPage; locale: Locale }) {
  const c = COPY[locale];
  const formatter = new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-GB", { dateStyle: "medium" });
  return (
    <div className="stack report-history" lang={locale}>
      <header>
        <h1>{c.title}</h1>
        <p className="muted">{c.intro}</p>
      </header>
      {page.items.length === 0 ? (
        <section className="panel">
          <p>{c.empty}</p>
          <p><a className="button" href="/start">{c.start}</a></p>
        </section>
      ) : (
        <ol className="report-list">
          {page.items.map((item) => (
            <li key={item.report_id} className="panel report-list-item">
              <div>
                <h2>{c.kinds[item.kind]}</h2>
                <p className="muted">
                  <time dateTime={item.created_at}>{formatter.format(new Date(item.created_at))}</time>
                  {" · "}{c.revision} {item.revision}
                </p>
              </div>
              <a className="button button-secondary"
                 href={`/reports/${encodeURIComponent(item.report_id)}?locale=${locale}`}>{c.open}</a>
            </li>
          ))}
        </ol>
      )}
      {page.next_cursor && (
        <p>
          <a className="button button-secondary"
             href={`/reports?cursor=${encodeURIComponent(page.next_cursor)}&locale=${locale}`}>{c.next}</a>
        </p>
      )}
    </div>
  );
}
