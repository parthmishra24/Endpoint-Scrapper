# epscrapper

Authenticated web endpoint collector powered by [Playwright](https://playwright.dev/).

## Installation
```
git clone https://github.com/parthmishra24/Endpoint-Scrapper.git
```
```
cd Endpoint-Scrapper
```
```
python3 -m venv venv
```
```
source venv/bin/activate
```
```
pip install -e .
```

After installation the `epscrapper` command becomes available globally.

To upgrade to the latest version at any time run:

```
epscrapper update
```

The command pulls the most recent commit from the official repository or
clones it if the current installation isn't a git checkout.

## Usage

```bash
epscrapper --login LOGIN_URL --dashboard DASHBOARD_URL --sJ output.json
```

Use `--sP` to save as plaintext and `--sC` for CSV output.

## Features

- Uses Chromium via Playwright for full authentication flows.
- Waits for redirect to your dashboard before capturing.
- Captures DOM links and network requests across all visited pages.
- Supports optional crawling of same-origin links with `--crawl` to uncover
  endpoints beyond the initial dashboard.
- Searches a wide range of HTML tags and attributes to minimize missed
  resources.
- Saves results as JSON, CSV, or plaintext files.

## Development

To work on the project locally install in editable mode:

```bash
pip install -e .
```

You'll also need to install Playwright browsers once:

```bash
playwright install
```

