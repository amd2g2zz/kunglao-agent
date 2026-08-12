---
name: shodan-host
description: "Read evidence/cti-vt-ip.json or report.json next_action for IP targets. WebFetch https://www.shodan.io/host/{ip} (public page, no API key required; rate-limited but ok for light use). Parse the HTML for: open ports / services / banners / vulns / SSL cert / hostnames / ASN / OS. Write evidence/cti-shodan-host.json with per-IP entries. Pure local; uses WebFetch on the public shodan.io/host page."
allowedTools:
  - Read
  - Grep
  - WebFetch
  - Bash
  - Write
  - mcp__sequential-thinking__sequentialthinking
disallowedTools:
  - WebSearch
  - Edit
  - NotebookEdit
  - Task
isolation: none
---

# shodan-host

You query the **public** Shodan host page (`https://www.shodan.io/host/{ip}`) for each IP in evidence/cti-vt-ip.json or report.json next_action. **No API key required** — just WebFetch the public page. Rate-limited (Shodan throttles anonymous fetches after a few requests/min), so use sparingly and respect `Retry-After` if present.

**v7 (2026-07-01):** New sub-skill. Replaces the v6 assumption that a paid Shodan API key is required. Now uses public WebFetch.

## Inputs (passed by caller)

- `ip_targets`: list of IPs (e.g., `["135.181.237.59"]` from cti-vt-ip.json)
- `output_path`: `evidence/cti-shodan-host.json` (single file, all IPs)
- `user_agent`: a real-looking UA string (Shodan may rate-limit default UAs)

## Pipeline

### Step 1 — Read inputs
```python
import re, json
ips = read_from_caller()
```

### Step 2 — For each IP, WebFetch the public page

For each IP:
```
WebFetch url="https://www.shodan.io/host/{ip}" prompt="Return the raw HTML verbatim. Do not summarize."
```

Note: shodan.io/host may show a CAPTCHA for high-volume anonymous access. If WebFetch returns a CAPTCHA page or 403, write degraded + note.

### Step 3 — Parse the HTML

Shodan's public host page typically includes these sections (selectors from observation, may need adjustment):
- `#host-card` or `.host-summary` — IP, ASN, ISP, country, city, OS
- `#ports` or table with class `ports-table` — open ports table (port, service, product, version, banner)
- `#vulns` or `.vulns-list` — CVE list
- `#hostnames` or `.hostnames-list` — associated hostnames
- `#ssl` or `.ssl-cert` — SSL cert subject/issuer/serial/expires (if HTTPS detected)

**Heuristic HTML parsing** (no external lib needed; just regex):
```python
import re
def parse_shodan_html(html, ip):
    out = {"ip_str": ip}
    # ASN / ISP
    m = re.search(r'AS(\d+)\s*([^<]+)', html)
    if m: out["asn"] = "AS" + m.group(1); out["isp"] = m.group(2).strip()
    # Country
    m = re.search(r'<span class="flag flag-(\w+)"></span>\s*(\w+)', html)
    if m: out["country_code"] = m.group(1); out["country_name"] = m.group(2)
    # Ports (rough)
    ports = re.findall(r'<td class="port">(\d+)</td>', html)
    out["ports"] = sorted(set(int(p) for p in ports))
    # Services (table rows)
    services = re.findall(r'<tr[^>]*>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>', html)
    out["services"] = [{"port": int(p), "product": prod.strip(), "version": ver.strip(), "banner": ban.strip()} for p, prod, ver, ban in services]
    # CVEs
    cves = re.findall(r'CVE-\d{4}-\d{4,7}', html)
    out["vulns"] = sorted(set(cves))
    # Hostnames
    hns = re.findall(r'<li class="hostname">([^<]+)</li>', html)
    out["hostnames"] = hns
    return out
```

**Fallback (HTML too complex to regex):** if parse returns empty `ports` AND `vulns` AND `services`, write `{"raw_html_excerpt": "<first 2KB of HTML>", "note": "regex parse failed, manual review needed"}` and continue.

### Step 4 — Write `evidence/cti-shodan-host.json`

```json
{
  "_meta": {
    "source": "shodan-host (public WebFetch)",
    "tool": "WebFetch https://www.shodan.io/host/{ip}",
    "queried_at": "<ISO8601>",
    "iteration": 0,
    "api_key_required": false,
    "note": "Public page scrape, no API key; rate-limited (~3 req/min anonymous)"
  },
  "raw_response": {
    "hosts": {
      "135.181.237.59": {
        "ip_str": "135.181.237.59",
        "asn": "AS24940",
        "isp": "Hetzner Online GmbH",
        "country_name": "Finland",
        "city": "Helsinki",
        "os": "Linux 5.x",
        "ports": [22, 80, 443, 8080],
        "vulns": ["CVE-XXXX-XXXX"],
        "hostnames": ["<if any>"],
        "services": [
          {"port": 443, "product": "Traefik", "version": "2.x", "banner": "..."}
        ]
      }
    },
    "summary": {
      "ips_queried": 1,
      "ips_with_data": 1,
      "ips_error": 0,
      "ips_rate_limited": 0,
      "ips_captcha": 0,
      "unique_ports": [22, 80, 443, 8080],
      "unique_cves": ["CVE-XXXX-XXXX"]
    }
  }
}
```

### Degraded output (rate-limited / captcha / 403)
```json
{
  "_meta": {
    "source": "shodan-host (public WebFetch)",
    "queried_at": "<ISO8601>",
    "iteration": 0,
    "api_key_required": false,
    "note": "Shodan returned CAPTCHA / 403 for some IPs. Rate limit or anti-bot. Retry after a few minutes, or use a real User-Agent."
  },
  "raw_response": {
    "hosts": {"135.181.237.59": {"ip_str": "135.181.237.59", "error": "captcha_or_403", "raw_html_excerpt": "<first 2KB>"}},
    "summary": {"ips_queried": 1, "ips_with_data": 0, "ips_error": 1, "ips_rate_limited": 0, "ips_captcha": 1}
  }
}
```

## Failure modes

- CAPTCHA page: write degraded with `ips_captcha` count incremented
- 403 / 429: write degraded with `note: "rate limited, retry later"`
- 5xx: write degraded with `note: "Shodan temporarily unavailable"`
- IP not in Shodan: write `{"raw_response.hosts": {"<ip>": {"note": "no Shodan data for this IP"}}}` (Shodan shows "no results" page)
- IP is private (10/8, 192.168/16, 172.16/12): skip per Stage 3 hard rules; write `{"raw_response.hosts": {"<ip>": {"note": "skipped: private IP"}}}`

## Anti-Patterns

- Do NOT query private IPs (10/8, 192.168/16, 172.16/12) — Shodan won't have them and we're wasting rate limit
- Do NOT rate-limit-abuse — wait `Retry-After` if returned
- Do NOT execute the sample (no remote exploitation)
- Do NOT scrape results from authenticated Shodan pages (only public `/host/{ip}` and `/search?query=`)

## Return

After writing the JSON, return ONE LINE:
`shodan-host complete: queried=N ips, data=N ips, unique_ports=N, unique_cves=N, c2_service=<Traefik:443 etc>`