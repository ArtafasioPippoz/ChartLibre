"""Run the tests and write one HTML page with the results, the failures and the figures the tests chose to show.

    .python/bin/python3 dev/tools/test_report.py [-o report.html] [--open] [pytest arguments...]

Figures: a test asks for the ``report_image`` fixture and calls ``report_image(figure, "caption")``; the page shows
them under that test. A PDF is the page printed from a browser (no extra dependency).
"""
from __future__ import annotations

import argparse
import base64
import html
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLOURS = {"passed": "#1a7f37", "failed": "#cf222e", "error": "#cf222e", "skipped": "#9a6700"}


def _safe(nodeid: str) -> str:
    return re.sub(r"[^\w.-]+", "_", nodeid)


def _cases(xml_path: Path) -> list[dict]:
    cases = []
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        status, detail = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                status = "error" if tag == "error" else "failed" if tag == "failure" else "skipped"
                detail = (node.get("message") or "") + "\n" + (node.text or "")
                break
        module = (case.get("classname") or "").replace(".", "/")
        cases.append({"id": f"{module}.py::{case.get('name')}", "name": case.get("name") or "",
                      "module": case.get("classname") or "", "time": float(case.get("time") or 0),
                      "status": status, "detail": detail.strip()})
    return cases


def _figures(images: Path, case_id: str) -> str:
    out = []
    for png in sorted(images.glob(f"{_safe(case_id)}__*.png")):
        caption = png.with_suffix(".txt")
        text = html.escape(caption.read_text(encoding="utf-8")) if caption.exists() else ""
        data = base64.b64encode(png.read_bytes()).decode("ascii")
        out.append(f'<figure><img src="data:image/png;base64,{data}" alt="">'
                   f"<figcaption>{text}</figcaption></figure>")
    return "".join(out)


def build_page(cases: list[dict], images: Path, command: str, seconds: float) -> str:
    counts = {status: sum(1 for c in cases if c["status"] == status) for status in COLOURS}
    rows = []
    by_module: dict[str, list[dict]] = {}
    for case in cases:
        by_module.setdefault(case["module"], []).append(case)
    for module, group in by_module.items():
        bad = sum(c["status"] in ("failed", "error") for c in group)
        rows.append(f'<details {"open" if bad else ""}><summary><b>{html.escape(module)}</b> '
                    f'- {len(group)} tests{f", <span style=color:{COLOURS['failed']}>{bad} failed</span>" if bad else ""}'
                    "</summary><table>")
        for case in group:
            colour = COLOURS[case["status"]]
            rows.append(f'<tr><td style="color:{colour};width:5em">{case["status"]}</td>'
                        f'<td>{html.escape(case["name"])}</td><td class=t>{case["time"]:.2f}s</td></tr>')
            figures = _figures(images, case["id"])
            if case["detail"]:
                rows.append(f'<tr><td></td><td colspan=2><pre>{html.escape(case["detail"][:4000])}</pre></td></tr>')
            if figures:
                rows.append(f'<tr><td></td><td colspan=2 class=figs>{figures}</td></tr>')
        rows.append("</table></details>")
    summary = " &nbsp; ".join(f'<span style="color:{COLOURS[k]}"><b>{v}</b> {k}</span>' for k, v in counts.items() if v)
    return f"""<!doctype html><meta charset="utf-8"><title>ChartLibre test report</title>
<style>body{{font:14px -apple-system,Segoe UI,sans-serif;margin:2em auto;max-width:980px;color:#222}}
table{{width:100%;border-collapse:collapse;margin:.4em 0 1em}}td{{padding:2px 6px;border-bottom:1px solid #eee;vertical-align:top}}
.t{{text-align:right;color:#888;width:5em}}pre{{background:#f6f8fa;padding:8px;overflow:auto;font-size:12px}}
.figs figure{{display:inline-block;margin:6px 10px 6px 0}}.figs img{{max-width:420px;border:1px solid #ddd}}
figcaption{{font-size:12px;color:#666}}summary{{cursor:pointer;padding:3px 0}}@media print{{details{{display:block}}}}</style>
<h1>ChartLibre test report</h1><p>{datetime.now():%Y-%m-%d %H:%M} &middot; {len(cases)} tests in {seconds:.0f}s &middot;
<code>{html.escape(command)}</code></p><p>{summary}</p>{"".join(rows)}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", default="test_report.html")
    parser.add_argument("--open", action="store_true", help="show the page in the browser when done")
    options, pytest_args = parser.parse_known_args()
    work = Path(tempfile.mkdtemp(prefix="chartlibre_report_"))
    images, xml_path = work / "images", work / "junit.xml"
    environment = {**os.environ, "CHARTLIBRE_REPORT_IMAGES": str(images), "QT_QPA_PLATFORM": "offscreen"}
    command = [sys.executable, "-m", "pytest", f"--junitxml={xml_path}", "-q", *(pytest_args or ["dev/tests"])]
    started = datetime.now()
    code = subprocess.run(command, cwd=ROOT, env=environment).returncode
    if not xml_path.exists():
        print("pytest wrote no result file", file=sys.stderr)
        return code or 1
    page = build_page(_cases(xml_path), images, "pytest " + " ".join(pytest_args or ["dev/tests"]),
                      (datetime.now() - started).total_seconds())
    target = Path(options.output).resolve()
    target.write_text(page, encoding="utf-8")
    print(f"Report: {target}")
    if options.open:
        webbrowser.open(target.as_uri())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
