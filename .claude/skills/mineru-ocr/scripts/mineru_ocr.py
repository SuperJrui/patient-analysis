#!/usr/bin/env python3
"""Batch-convert screenshots/images (or PDFs) to Markdown via the MinerU v4 API.

    export MINERU_TOKEN=...      # or put MINERU_TOKEN=... in a .env file
    python mineru_ocr.py ./screenshots -r -o out/
    python mineru_ocr.py a.png b.jpg -o out/ --lang en

Folder inputs keep their sub-folder layout under the output dir, e.g.
screenshots/day1/a.png -> out/day1/a.md. Files whose .md already exists are
skipped (use --force to redo), so an interrupted run can simply be re-run and
the daily free quota isn't wasted. Exit code is 1 if any file failed.
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
MAX_BATCH = 50


def die(msg):
    sys.exit(f"error: {msg}")


def load_dotenv():
    for d in (Path.cwd(), Path(__file__).resolve().parent):
        env = d / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                k, sep, v = line.strip().partition("=")
                if sep and not k.startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def retry(fn, tries=4):
    for i in range(tries):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout):
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def api(method, path, token, **kw):
    def call():
        r = requests.request(method, BASE + path, timeout=60,
                             headers={"Authorization": f"Bearer {token}"}, **kw)
        r.raise_for_status()
        return r.json()
    body = retry(call)
    if body.get("code") != 0:
        raise RuntimeError(f"{path}: {body.get('msg')} (code {body.get('code')})")
    return body["data"]


def collect(inputs, recursive):
    """Return [(source_path, relative_output_stem)]."""
    items = []
    for p in map(Path, inputs):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in EXTS:
                    items.append((f, f.relative_to(p).with_suffix("")))
        elif p.is_file() and p.suffix.lower() in EXTS:
            items.append((p, Path(p.stem)))
        else:
            print(f"skip (not found/unsupported): {p}", file=sys.stderr)
    # disambiguate colliding output names
    seen = {}
    out = []
    for f, stem in items:
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        out.append((f, stem if n == 0 else stem.with_name(f"{stem.name}_{n}")))
    return out


def save(stem, zip_url, outdir):
    def dl():
        r = requests.get(zip_url, timeout=120)
        r.raise_for_status()
        return r
    with zipfile.ZipFile(io.BytesIO(retry(dl).content)) as z:
        names = z.namelist()
        md = next((n for n in names if n.endswith("full.md")), None)
        if not md:
            raise RuntimeError("no markdown in result")
        target = outdir / stem.with_suffix(".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        text = z.read(md).decode("utf-8")
        imgs = [n for n in names if n.startswith("images/") and not n.endswith("/")]
        if imgs:
            imgdir = target.parent / f"{stem.name}_images"
            imgdir.mkdir(exist_ok=True)
            for n in imgs:
                (imgdir / Path(n).name).write_bytes(z.read(n))
            text = text.replace("images/", f"{imgdir.name}/")
        target.write_text(text, encoding="utf-8")
    return target


def run_batch(items, token, args, outdir, failed):
    entries = [{"name": f.name, "data_id": str(i), "is_ocr": args.ocr}
               for i, (f, _) in enumerate(items)]
    data = api("POST", "/file-urls/batch", token, json={
        "files": entries, "model_version": args.model,
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table, "language": args.lang})
    batch_id, urls = data["batch_id"], data["file_urls"]
    pending = set(range(len(items)))
    for i, ((f, _), url) in enumerate(zip(items, urls)):
        try:
            # bare PUT: a Content-Type header would break the signed URL
            retry(lambda: requests.put(url, data=f.read_bytes(), timeout=300).raise_for_status())
        except Exception as e:
            failed.append((f, f"upload: {e}"))
            pending.discard(i)
    print(f"batch {batch_id}: {len(pending)} file(s) processing...", file=sys.stderr)

    deadline = time.time() + args.timeout
    while pending:
        if time.time() > deadline:
            for i in pending:
                failed.append((items[i][0], "timeout"))
            return
        time.sleep(3)
        for item in api("GET", f"/extract-results/batch/{batch_id}", token)["extract_result"]:
            i = int(item["data_id"]) if str(item.get("data_id", "")).isdigit() else None
            if i not in pending:
                continue
            f, stem = items[i]
            if item["state"] == "done":
                try:
                    print(f"saved {save(stem, item['full_zip_url'], outdir)}")
                except Exception as e:
                    failed.append((f, str(e)))
                pending.discard(i)
            elif item["state"] == "failed":
                failed.append((f, item.get("err_msg") or "failed"))
                pending.discard(i)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image/PDF files or directories")
    ap.add_argument("-o", "--out", default="mineru_out", help="output directory")
    ap.add_argument("-r", "--recursive", action="store_true", help="scan sub-folders")
    ap.add_argument("--force", action="store_true", help="re-convert even if .md exists")
    ap.add_argument("--lang", default="ch", help="OCR language (ch, en, ...)")
    ap.add_argument("--model", default="vlm", choices=["vlm", "pipeline"])
    ap.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--no-formula", action="store_true")
    ap.add_argument("--no-table", action="store_true")
    ap.add_argument("--timeout", type=int, default=900, help="max seconds per batch")
    args = ap.parse_args()

    load_dotenv()
    token = os.environ.get("MINERU_TOKEN") or die("set MINERU_TOKEN (https://mineru.net/apiManage)")
    outdir = Path(args.out)
    items = collect(args.inputs, args.recursive)
    if not items:
        die("no supported input files")
    if not args.force:
        todo = [(f, s) for f, s in items if not (outdir / s.with_suffix(".md")).exists()]
        if len(todo) < len(items):
            print(f"skipping {len(items) - len(todo)} already converted", file=sys.stderr)
        items = todo
    print(f"{len(items)} file(s) to convert", file=sys.stderr)

    failed = []
    for i in range(0, len(items), MAX_BATCH):
        try:
            run_batch(items[i:i + MAX_BATCH], token, args, outdir, failed)
        except Exception as e:  # e.g. quota exhausted: stop, finished files are kept
            failed += [(f, str(e)) for f, _ in items[i:i + MAX_BATCH]]
            print(f"stopping: {e}", file=sys.stderr)
            failed += [(f, "not attempted") for f, _ in items[i + MAX_BATCH:]]
            break
    if failed:
        print(f"\n{len(failed)} failed:", file=sys.stderr)
        for f, why in failed:
            print(f"  {f}: {why}", file=sys.stderr)
        print("Re-run the same command later to retry only these.", file=sys.stderr)
        sys.exit(1)
    print("done")


if __name__ == "__main__":
    main()
