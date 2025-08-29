# epscrapper

Authenticated web endpoint collector powered by [Playwright](https://playwright.dev/).

## Installation

```bash
pip install .
```

After installation the `epscrapper` command becomes available globally.

## Usage

```bash
epscrapper --login LOGIN_URL --dashboard DASHBOARD_URL --save output.json
```

## Features

- Uses Chromium via Playwright for full authentication flows.
- Waits for redirect to your dashboard before capturing.
- Collects DOM links and network requests.
- Saves results as a structured JSON file.

## Development

To work on the project locally install in editable mode:

```bash
pip install -e .
```

You'll also need to install Playwright browsers once:

```bash
playwright install
```

