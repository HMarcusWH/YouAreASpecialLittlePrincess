import "@princess/design-tokens/tokens.css";
import "@princess/report-web/report.css";
import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Princess — handwriting measured",
  description: "A private, measured report of your handwriting.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">Skip to content</a>
        <header className="site-header">
          <a href="/" className="brand">Princess</a>
          <nav aria-label="Main">
            <a href="/start">New analysis</a>
            <a href="/settings">Settings</a>
          </nav>
        </header>
        <main id="main" tabIndex={-1}>{children}</main>
      </body>
    </html>
  );
}
