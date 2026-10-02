---
name: mineru-ocr
description: Convert screenshots, images, or PDFs into Markdown text using the MinerU API (free daily quota) and save them to disk. Use when the user wants to OCR / extract text from screenshots, 截图转文字, 图片转md, or batch-convert a folder of images.
---

# mineru-ocr

Sends images/PDFs to MinerU (https://mineru.net) and saves the recognized content as `.md` files.

## Setup
1. Get an API token at https://mineru.net/apiManage and `export MINERU_TOKEN=<token>`.
2. Needs Python 3 + `requests` (`pip install requests`).

## Usage
```bash
python .claude/skills/mineru-ocr/scripts/mineru_ocr.py <files-or-dirs...> -o <outdir> [--lang ch|en] [--model vlm|pipeline]
```
- Accepts png/jpg/jpeg/webp/bmp/gif/jp2/pdf; directories are scanned (non-recursive).
- Output: `<outdir>/<name>.md`, plus `<name>_images/` if MinerU extracted figures.
- Multiple files are sent in one batch to save quota/time.
- Flags: `--no-formula`, `--no-table`, `--no-ocr`, `--timeout SECS`.

## Notes
- Never print or commit the token; it comes only from `MINERU_TOKEN`.
- After running, read the produced `.md` and summarize/answer for the user; report any `FAILED` lines (often quota exhausted or file too large).
