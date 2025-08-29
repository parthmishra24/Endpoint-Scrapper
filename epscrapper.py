
import asyncio
import json
import time
import tempfile
import atexit
from pathlib import Path
from urllib.parse import urlparse, urljoin

import typer
import tldextract
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from playwright.async_api import async_playwright

console = Console()
app = typer.Typer(help="🔍 epscrapper: Authenticated Web Endpoint Collector")

def normalize_origin(url: str) -> str:
    p = urlparse(url if "://" in url else f"https://{url}")
    return f"{p.scheme or 'https'}://{p.netloc or p.path}"

def is_same_origin(u1, u2) -> bool:
    return urlparse(u1).scheme == urlparse(u2).scheme and urlparse(u1).netloc == urlparse(u2).netloc

def guess_api_like(resource_type: str, url: str) -> bool:
    rt = resource_type.lower()
    if rt in {"xhr", "fetch", "document"}:
        return True
    path = urlparse(url).path.lower()
    return any(k in path for k in ["/api/", "/v1/", "/graphql", "/rest/"])

async def wait_for_dashboard(context, expected_url, timeout) -> object:
    expected_origin = normalize_origin(expected_url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for page in context.pages:
            if not page.url:
                continue
            if is_same_origin(page.url, expected_origin) or page.url.startswith(expected_url):
                return page
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for dashboard at {expected_origin}")

async def collect_dom_links(page, base_origin, same_origin=True):
    sel_attrs = [("a", "href"), ("script", "src"), ("img", "src"), ("form", "action")]
    found = []
    for tag, attr in sel_attrs:
        elems = await page.query_selector_all(f"{tag}[{attr}]")
        for el in elems:
            val = await el.get_attribute(attr)
            if not val:
                continue
            full_url = urljoin(page.url, val)
            if same_origin and not is_same_origin(full_url, base_origin):
                continue
            found.append({"url": full_url, "source": "dom"})
    return found

@app.callback()
def main_help(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        md = Markdown("""
# epscrapper CLI 🕵️‍♂️

Collect web endpoints from authenticated pages using Playwright and Chromium.

## 🚀 Usage

```bash
epscrapper --login LOGIN_URL --dashboard DASHBOARD_URL --save output.json
```

## 📌 Features

- Full login flow via Chromium (headless or headed)
- Waits until redirected to dashboard
- Press `[Enter]` to start capturing
- Captures:
  - DOM links (href/src/action)
  - Network requests (XHR/fetch/etc.)
- Outputs a JSON file with endpoint metadata
- Pip-installable as `epscrapper`

        """)
        console.print(md)

@app.command(help="🎯 Authenticate and collect endpoints from your dashboard.")
def scrape(
    login: str = typer.Option(..., help="🔐 Login URL to start authentication."),
    dashboard: str = typer.Option(..., help="🎯 Final dashboard URL after auth redirect."),
    save: Path = typer.Option(..., help="💾 File path to save output JSON."),
    timeout: int = typer.Option(900, help="⏳ Max seconds to wait for dashboard (default: 900)"),
    stay: int = typer.Option(8, help="🕒 Seconds to wait on dashboard before scraping (default: 8)"),
    headless: bool = typer.Option(False, "--headless/--headed", help="🙈 Run browser in headless mode (default: headed)"),
    same_origin: bool = typer.Option(True, "--same-origin/--any-origin", help="🌐 Limit endpoints to dashboard domain."),
    include_static: bool = typer.Option(True, "--include-static/--only-api", help="📦 Include static files like .js/.css"),
    crawl: bool = typer.Option(False, "--crawl/--no-crawl", help="🧭 (Placeholder) Crawl subpages recursively."),
):
    asyncio.run(run_scraper(login, dashboard, save, timeout, stay, headless, same_origin, include_static, crawl))

async def run_scraper(login, dashboard, save, timeout, stay, headless, same_origin, include_static, crawl):
    login_url = login if "://" in login else f"https://{login}"
    dashboard_url = dashboard if "://" in dashboard else f"https://{dashboard}"
    base_origin = normalize_origin(dashboard_url)
    tmp_profile = tempfile.TemporaryDirectory()
    atexit.register(tmp_profile.cleanup)
    endpoints = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=tmp_profile.name,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto(login_url)
        console.print("[green]Login window ready. Waiting for redirect to dashboard...[/green]")
        dash = await wait_for_dashboard(context, dashboard_url, timeout)
        await dash.bring_to_front()

        console.print("[yellow]Press [Enter] to start scraping...[/yellow]")
        input()

        def on_request(req):
            try:
                if same_origin and not is_same_origin(req.url, base_origin):
                    return
                if not include_static and not guess_api_like(req.resource_type, req.url):
                    return
                endpoints.append({"url": req.url, "source": "network", "type": req.resource_type})
            except:
                pass

        dash.on("requestfinished", on_request)
        endpoints += await collect_dom_links(dash, base_origin, same_origin)
        await dash.mouse.wheel(0, 2000)
        await asyncio.sleep(stay)
        await dash.mouse.wheel(0, -2000)
        endpoints += await collect_dom_links(dash, base_origin, same_origin)

        if crawl:
            console.print("[cyan]Crawling is not yet implemented. Placeholder active.[/cyan]")

        await context.close()

    seen = set()
    unique_eps = []
    for ep in endpoints:
        if ep["url"] not in seen:
            unique_eps.append(ep)
            seen.add(ep["url"])

    save.parent.mkdir(parents=True, exist_ok=True)
    save.write_text(json.dumps(unique_eps, indent=2))
    table = Table(title="Scrape Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Endpoints", str(len(unique_eps)))
    table.add_row("Saved to", str(save))
    table.add_row("Dashboard", dashboard_url)
    console.print(table)

if __name__ == "__main__":
    app()

