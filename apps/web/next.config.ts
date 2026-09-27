import type { NextConfig } from "next";

// Presentation only: no business logic, provider SDK or database access lives
// in this app (ADR-001). Security headers apply to every route.
const securityHeaders = [
  { key: "Content-Security-Policy",
    value: "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; " +
           "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; " +
           "form-action 'self'; object-src 'none'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
];

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@princess/api-client", "@princess/contracts", "@princess/design-tokens",
                      "@princess/report-core", "@princess/report-web"],
  typescript: { tsconfigPath: "tsconfig.json" },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default config;
