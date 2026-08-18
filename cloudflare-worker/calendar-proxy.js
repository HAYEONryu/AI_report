// Free-tier Cloudflare Worker: proxies investing.com's economic calendar
// widget so GitHub Actions (whose IP range Cloudflare bot-management blocks
// outright, independent of TLS fingerprint — confirmed via live testing)
// can still reach it, routed through Cloudflare's own edge network instead.
//
// Deploy: Cloudflare dashboard -> Workers & Pages -> Create -> paste this in
// the editor -> Deploy. Copy the resulting https://xxxx.workers.dev URL and
// set it as the CALENDAR_PROXY_URL secret (see test.md).
//
// ponytail: no auth token, relying on URL obscurity only. This proxies one
// fixed, public, read-only GET target — add a shared-secret header check
// here + in collectors/calendar.py if the URL ever leaks and gets abused.

const TARGET =
  "https://sslecal2.investing.com/?columns=exc_flag,exc_currency,exc_importance,exc_actual,exc_forecast,exc_previous" +
  "&features=datepicker,timezone&countries=5,37&calType=week&timeZone=88&lang=1";

export default {
  async fetch() {
    const upstream = await fetch(TARGET, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        Referer: "https://www.investing.com/",
      },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  },
};
