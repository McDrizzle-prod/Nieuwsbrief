"""Bundel de nieuwsbrief tot één los HTML-bestand (met de gegevens erin).

Handig om de complete site offline te bekijken of als één bestand te delen.

    python tools/bundel.py walletbrief.html
    python tools/bundel.py --fragment voorbeeld.html   # zonder <html>/<head>/<body>
"""

from __future__ import annotations

import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")


def read(*parts: str) -> str:
    with open(os.path.join(SITE, *parts), encoding="utf-8") as fh:
        return fh.read()


def bundle(fragment: bool) -> str:
    index = read("index.html")
    title = re.search(r"<title>.*?</title>", index, re.S).group(0)
    fonts = re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com[^>]+>', index).group(0)
    icon = re.search(r'<link rel="icon"[^>]+>', index).group(0)
    body = re.search(r"<!-- inhoud:begin -->(.*?)<!-- inhoud:einde -->", index, re.S).group(1)
    items = json.loads(read("data", "items.json"))
    config = json.loads(read("data", "config.json"))
    data = {"items": items["items"], "generated": items["generated"], "config": config}
    data_js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    head = f"{title}\n{fonts}\n{icon}\n<style>\n{read('assets', 'style.css')}\n</style>"
    scripts = f"<script>window.NIEUWSBRIEF_DATA = {data_js};</script>\n<script>\n{read('assets', 'app.js')}\n</script>"
    if fragment:
        return f"{head}\n{body}\n{scripts}\n"
    return (f'<!doctype html>\n<html lang="nl">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}\n</head>\n<body>\n{body}\n{scripts}\n</body>\n</html>\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uitvoer")
    parser.add_argument("--fragment", action="store_true", help="zonder <html>, <head> en <body>")
    args = parser.parse_args()
    with open(args.uitvoer, "w", encoding="utf-8") as fh:
        fh.write(bundle(args.fragment))
    print(f"Geschreven: {args.uitvoer} ({os.path.getsize(args.uitvoer) // 1024} kB)")


if __name__ == "__main__":
    main()
