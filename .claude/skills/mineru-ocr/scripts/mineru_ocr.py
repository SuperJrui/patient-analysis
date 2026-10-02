#!/usr/bin/env python3
"""Convert screenshots/images (or PDFs) to Markdown via the MinerU v4 API.

Usage:
    export MINERU_TOKEN=...            # from https://mineru.net/apiManage
    python mineru_ocr.py shot1.png shot2.jpg -o out/
    python mineru_ocr.py ./screenshots/ -o out/ --lang ch

Each input produces <out>/<stem>.md (and <stem>_images/ if MinerU returns any).
"""
import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE = os.environ.get("MINERU_BASE", "https://mineru.net/api/v4")
EXTS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".pdf"}
MAX_BATCH = 50  # stay well below the API's per-batch file limit


def die(msg):
    sys.exit(f"error: {msg}")


def api(method, path, token, **kw):
    r = requests.request(
        method, BASE + path, timeout=60,
        headers={"Authorization": f"Bearer {token}"}, **kw)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        die(f"{path}: {body.get('msg')} (code {body.get('code')})")
    return body["data"]


def collect(inputs):
    files = []
    for p in map(Path, inputs):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in EXTS)
        elif p.suffix.lower() in EXTS:
            files.append(p)
        else:
            print(f"skip (unsupported): {p}", file=sys.stderr)
    return files


def run_batch(files, token, args, outdir):
    # unique data_id lets us map results back even with duplicate file names
    entries = [{"name": f.name, "data_id": str(i), "is_ocr": args.ocr}
               for i, f in enumerate(files)]
    data = api("POST", "/file-urls/batch", token, json={
        "files": entries,
        "model_version": args.model,
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table,
        "language": args.lang,
    })
    batch_id, urls = data["batch_id"], data["file_urls"]
    for f, url in zip(files, urls):
        with open(f, "rb") as fh:
            # must be a bare PUT: no Content-Type, or the signature fails
            requests.put(url, data=fh, timeout=300).raise_for_status()
    print(f"uploaded {len(files)} file(s), batch {batch_id}; waiting...", file=sys.stderr)

    done, deadline = set(), time.time() + args.timeout
    while len(done) < len(files):
        if time.time() > deadline:
            die(f"timed out after {args.timeout}s (batch {batch_id})")
        time.sleep(3)
        res = api("GET", f"/extract-results/batch/{batch_id}", token)["extract_result"]
        for item in res:
            idx = int(item.get("data_id", -1)) if str(item.get("data_id", "")).isdigit() else None
            if idx is None:  # fall back to file name
                idx = next((i for i, f in enumerate(files) if f.name == item["file_name"]), None)
            if idx is None or idx in done:
                continue
            if item["state"] == "done":
                save(files[idx], item["full_zip_url"], outdir)
                done.add(idx)
            elif item["state"] == "failed":
                print(f"FAILED {files[idx]}: {item.get('err_msg')}", file=sys.stderr)
                done.add(idx)


def save(src, zip_url, outdir):
    r = requests.get(zip_url, timeout=120)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        md = next((n for n in names if n.endswith("full.md")), None)
        if not md:
            print(f"no markdown in result for {src}", file=sys.stderr)
            return
        target = outdir / f"{src.stem}.md"
        target.write_bytes(z.read(md))
        imgs = [n for n in names if n.startswith("images/") and not n.endswith("/")]
        if imgs:
            imgdir = outdir / f"{src.stem}_images"
            imgdir.mkdir(exist_ok=True)
            for n in imgs:
                (imgdir / Path(n).name).write_bytes(z.read(n))
            # rewrite relative image links to the extracted folder
            text = target.read_text(encoding="utf-8").replace("images/", f"{imgdir.name}/")
            target.write_text(text, encoding="utf-8")
    print(f"saved {target}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image/PDF files or directories")
    ap.add_argument("-o", "--out", default="mineru_out", help="output directory")
    ap.add_argument("--lang", default="ch", help="OCR language (ch, en, ...)")
    ap.add_argument("--model", default="vlm", choices=["vlm", "pipeline"])
    ap.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--no-formula", action="store_true")
    ap.add_argument("--no-table", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    token = os.environ.get("MINERU_TOKEN") or die("set MINERU_TOKEN (get one at https://mineru.net/apiManage)")
    files = collect(args.inputs)
    if not files:
        die("no supported input files")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(files), MAX_BATCH):
        run_batch(files[i:i + MAX_BATCH], token, args, outdir)


if __name__ == "__main__":
    main()
