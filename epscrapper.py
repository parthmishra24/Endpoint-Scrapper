
import asyncio
import json
import time
import tempfile
import atexit
import csv
import subprocess
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
    """Return DOM-discovered endpoints and crawlable links.

    The collector searches common attributes across a wider range of tags to
    minimise missed resources. When ``same_origin`` is True, only links within
    ``base_origin`` are returned. The function also extracts anchor links that
    can be used for recursive crawling.
    """

    sel_attrs = [
        ("a", "href"),
        ("link", "href"),
        ("script", "src"),
        ("img", "src"),
        ("img", "srcset"),
        ("iframe", "src"),
        ("source", "src"),
        ("video", "src"),
        ("audio", "src"),
        ("form", "action"),
        ("embed", "src"),
    ]
    found = []
    crawl_links = set()
    for tag, attr in sel_attrs:
        elems = await page.query_selector_all(f"{tag}[{attr}]")
        for el in elems:
            val = await el.get_attribute(attr)
            if not val:
                continue
            candidates = [val]
            if attr == "srcset":
                candidates = [v.strip().split(" ")[0] for v in val.split(",") if v.strip()]
            for candidate in candidates:
                full_url = urljoin(page.url, candidate)
                if same_origin and not is_same_origin(full_url, base_origin):
                    continue
                found.append({"url": full_url, "source": "dom"})
                # only crawl same-origin anchor links to avoid wandering the web
                if tag == "a" and is_same_origin(full_url, base_origin):
                    crawl_links.add(full_url)
    return found, list(crawl_links)


async def scrape_current_page(page, base_origin, same_origin, stay):
    """Collect endpoints from the currently loaded page.

    Performs a simple scroll to trigger lazy loading and returns both
    discovered endpoints and links to potentially crawl.
    """

    dom_endpoints, crawl_links = await collect_dom_links(page, base_origin, same_origin)
    await page.mouse.wheel(0, 2000)
    await asyncio.sleep(stay)
    await page.mouse.wheel(0, -2000)
    more_endpoints, more_links = await collect_dom_links(page, base_origin, same_origin)
    dom_endpoints.extend(more_endpoints)
    crawl_links.extend(link for link in more_links if link not in crawl_links)
    return dom_endpoints, crawl_links

@app.callback()
def main_help(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        md = Markdown("""
# epscrapper CLI 🕵️‍♂️

Collect web endpoints from authenticated pages using Playwright and Chromium.

## 🚀 Usage

```bash
epscrapper --login LOGIN_URL --dashboard DASHBOARD_URL --sJ output.json
```

## 📌 Features

- Full login flow via Chromium (headless or headed)
- Waits until redirected to dashboard
- Press `[Enter]` to start capturing
- Captures:
  - DOM links (href/src/action)
  - Network requests (XHR/fetch/etc.)
- Saves endpoints as JSON, CSV, or plaintext
- Pip-installable as `epscrapper`

        """)
        console.print(md)

@app.command(help="🎯 Collect endpoints from a dashboard, optionally after login.")
def scrape(
    login: str = typer.Option(None, help="🔐 Login URL to start authentication."),
    dashboard: str = typer.Option(..., help="🎯 Dashboard URL to scrape."),
    s_p: Path = typer.Option(None, "--sP", help="💾 File path to save endpoints as plaintext."),
    s_j: Path = typer.Option(None, "--sJ", help="💾 File path to save endpoints as JSON."),
    s_c: Path = typer.Option(None, "--sC", help="💾 File path to save endpoints as CSV."),
    timeout: int = typer.Option(900, help="⏳ Max seconds to wait for dashboard (default: 900)"),
    stay: int = typer.Option(8, help="🕒 Seconds to wait on dashboard before scraping (default: 8)"),
    headless: bool = typer.Option(False, "--headless/--headed", help="🙈 Run browser in headless mode (default: headed)"),
    same_origin: bool = typer.Option(True, "--same-origin/--any-origin", help="🌐 Limit endpoints to dashboard domain."),
    include_static: bool = typer.Option(True, "--include-static/--only-api", help="📦 Include static files like .js/.css"),
    crawl: bool = typer.Option(False, "--crawl/--no-crawl", help="🧭 Crawl subpages recursively."),
):
    if not any([s_p, s_j, s_c]):
        raise typer.BadParameter("Please provide at least one output file via --sP, --sJ, or --sC.")
    asyncio.run(run_scraper(login, dashboard, s_p, s_j, s_c, timeout, stay, headless, same_origin, include_static, crawl))


@app.command(help="⬇️ Update epscrapper to the latest commit from GitHub.")
def update() -> None:
    """Clone or pull the latest changes from the repository."""
    repo_url = "https://github.com/parthmishra24/Endpoint-Scrapper.git"
    repo_dir = Path(__file__).resolve().parent
    try:
        if (repo_dir / ".git").exists():
            console.print("[cyan]Fetching latest changes...[/cyan]")
            subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, check=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_dir, check=True)
            console.print("[green]Update complete.[/green]")
        else:
            console.print("[cyan]Cloning repository...[/cyan]")
            dest = repo_dir.parent / "Endpoint-Scrapper"
            subprocess.run(["git", "clone", repo_url, str(dest)], check=True)
            console.print(f"[green]Repository cloned to {dest}[/green]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Update failed: {exc}[/red]")
        raise typer.Exit(code=1)

async def run_scraper(login, dashboard, s_p, s_j, s_c, timeout, stay, headless, same_origin, include_static, crawl):
    login_url = None if not login else (login if "://" in login else f"https://{login}")
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
        if login_url:
            await page.goto(login_url)
            console.print("[green]Login window ready. Waiting for redirect to dashboard...[/green]")
            dash = await wait_for_dashboard(context, dashboard_url, timeout)
            await dash.bring_to_front()
        else:
            await page.goto(dashboard_url)
            dash = page

        console.print("[yellow]Press [Enter] to start scraping...[/yellow]")
        input()

        def on_request(req):
            try:
                if same_origin and not is_same_origin(req.url, base_origin):
                    return
                if not include_static and not guess_api_like(req.resource_type, req.url):
                    return
                endpoints.append({
                    "url": req.url,
                    "source": "network",
                    "type": req.resource_type,
                    "method": req.method,
                })
            except Exception:
                pass

        # capture network requests from all pages in the context
        context.on("request", on_request)

        # scrape the dashboard itself
        dom_eps, crawl_links = await scrape_current_page(dash, base_origin, same_origin, stay)
        endpoints.extend(dom_eps)

        # simple BFS crawl of same-origin anchor links
        if crawl:
            visited = {dashboard_url}
            queue = [link for link in crawl_links if link not in visited]
            while queue:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                page = await context.new_page()
                try:
                    await page.goto(url)
                    sub_eps, sub_links = await scrape_current_page(page, base_origin, same_origin, stay)
                    endpoints.extend(sub_eps)
                    for l in sub_links:
                        if l not in visited and l not in queue:
                            queue.append(l)
                except Exception:
                    pass
                finally:
                    await page.close()

        await context.close()

    seen = set()
    unique_eps = []
    for ep in endpoints:
        if ep["url"] not in seen:
            unique_eps.append(ep)
            seen.add(ep["url"])

    outputs = []
    if s_j:
        s_j.parent.mkdir(parents=True, exist_ok=True)
        s_j.write_text(json.dumps(unique_eps, indent=2))
        outputs.append(str(s_j))
    if s_p:
        s_p.parent.mkdir(parents=True, exist_ok=True)
        s_p.write_text("\n".join(ep["url"] for ep in unique_eps))
        outputs.append(str(s_p))
    if s_c:
        s_c.parent.mkdir(parents=True, exist_ok=True)
        with s_c.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["url", "source", "type", "method"])
            writer.writeheader()
            writer.writerows(unique_eps)
        outputs.append(str(s_c))
    table = Table(title="Scrape Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Endpoints", str(len(unique_eps)))
    if outputs:
        table.add_row("Saved to", ", ".join(outputs))
    else:
        table.add_row("Saved to", "-")
    table.add_row("Dashboard", dashboard_url)
    console.print(table)

if __name__ == "__main__":
    app()

