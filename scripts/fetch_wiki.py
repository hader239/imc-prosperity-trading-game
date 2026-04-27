"""Walk the public Prosperity 4 Notion wiki and dump each page as markdown.

Usage (from the repo root):
    python3 scripts/fetch_wiki.py docs/wiki

Stdlib only. Uses Notion's unofficial loadPageChunk endpoint (the same one
the rendered notion.site SPA hits). No auth needed because the wiki is
shared publicly. If IMC ever moves the root page, refresh ROOT_PAGE_ID
below by grepping `pageId` out of a curl of the public URL.
"""

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT_PAGE_ID = "321e8453-a093-805f-bd4b-de63ccbf9218"  # Prosperity 4 Wiki
BASE = "https://imc-prosperity.notion.site/api/v3"
OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/notion_out")
OUT_DIR.mkdir(parents=True, exist_ok=True)


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def post(path: str, body: dict) -> dict:
    req = Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
            "Referer": "https://imc-prosperity.notion.site/prosperity-4-wiki",
            "Origin": "https://imc-prosperity.notion.site",
            "x-notion-active-user-header": "",
        },
        method="POST",
    )
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_page(page_id: str) -> dict:
    """Fetch all chunks for a page and merge their record maps."""
    merged = {"block": {}, "collection": {}, "collection_view": {}}
    cursor = {"stack": []}
    chunk_no = 0
    while True:
        resp = post(
            "/loadPageChunk",
            {
                "pageId": page_id,
                "limit": 100,
                "cursor": cursor,
                "chunkNumber": chunk_no,
                "verticalColumns": False,
            },
        )
        rm = resp.get("recordMap", {})
        for k in merged:
            merged[k].update(rm.get(k, {}))
        cursor = resp.get("cursor", {"stack": []})
        if not cursor.get("stack"):
            break
        chunk_no += 1
        time.sleep(0.1)
    return merged


def block_value(block: dict) -> dict:
    v = block.get("value", {})
    return v.get("value", v)  # Notion sometimes wraps in another value


def title_text(props: dict) -> str:
    parts = props.get("title") or []
    return "".join(seg[0] for seg in parts if seg)


def rich_text(props: dict) -> str:
    parts = props.get("title") or []
    out = []
    for seg in parts:
        if not seg:
            continue
        text = seg[0]
        annotations = seg[1] if len(seg) > 1 else []
        # extract link
        link = None
        for ann in annotations:
            if ann and ann[0] == "a" and len(ann) > 1:
                link = ann[1]
        if link:
            out.append(f"[{text}]({link})")
        else:
            out.append(text)
    return "".join(out)


def render_block(block_id: str, blocks: dict, depth: int = 0) -> str:
    if block_id not in blocks:
        return ""
    v = block_value(blocks[block_id])
    btype = v.get("type")
    props = v.get("properties", {})
    children = v.get("content", [])
    indent = "  " * depth
    text = rich_text(props)

    out = []
    if btype == "header":
        out.append(f"## {text}")
    elif btype == "sub_header":
        out.append(f"### {text}")
    elif btype == "sub_sub_header":
        out.append(f"#### {text}")
    elif btype == "text":
        if text.strip():
            out.append(f"{indent}{text}")
    elif btype == "bulleted_list":
        out.append(f"{indent}- {text}")
    elif btype == "numbered_list":
        out.append(f"{indent}1. {text}")
    elif btype == "to_do":
        checked = props.get("checked", [["No"]])[0][0] == "Yes"
        box = "[x]" if checked else "[ ]"
        out.append(f"{indent}- {box} {text}")
    elif btype == "quote":
        out.append(f"{indent}> {text}")
    elif btype == "callout":
        out.append(f"{indent}> 💡 {text}")
    elif btype == "code":
        lang = (props.get("language") or [["plain"]])[0][0].lower()
        out.append(f"```{lang}\n{text}\n```")
    elif btype == "divider":
        out.append("---")
    elif btype == "page":
        # Inline link to a child page (the walker also recurses into it)
        out.append(f"- [{text}](./{slugify(text)}/index.md)")
    elif btype == "image":
        src = (
            (v.get("format") or {}).get("display_source")
            or v.get("properties", {}).get("source", [[""]])[0][0]
        )
        out.append(f"![image]({src})")
    elif btype == "bookmark":
        link = (props.get("link") or [[""]])[0][0]
        out.append(f"[{text or link}]({link})")
    elif btype == "column_list" or btype == "column":
        pass  # render children inline
    elif btype == "table":
        out.append(_render_table(block_id, blocks))
    elif btype == "table_row":
        return ""  # handled by table renderer
    else:
        if text.strip():
            out.append(f"{indent}{text}")

    # Recurse children, except for tables (handled) and pages (link only)
    if btype not in {"table", "page"}:
        for cid in children:
            child_md = render_block(cid, blocks, depth + (1 if btype.endswith("list") else 0))
            if child_md:
                out.append(child_md)

    return "\n".join(s for s in out if s)


def _render_table(table_id: str, blocks: dict) -> str:
    v = block_value(blocks[table_id])
    rows = v.get("content", [])
    fmt = v.get("format", {})
    col_order = fmt.get("table_block_column_order", [])

    md_rows = []
    for i, rid in enumerate(rows):
        rv = block_value(blocks.get(rid, {}))
        cells = rv.get("properties", {})
        row_cells = []
        for col in col_order:
            cell = cells.get(col, [[""]])
            txt = "".join(seg[0] for seg in cell if seg)
            row_cells.append(txt.replace("\n", " "))
        md_rows.append("| " + " | ".join(row_cells) + " |")
        if i == 0:
            md_rows.append("|" + "|".join(["---"] * len(col_order)) + "|")
    return "\n".join(md_rows)


def slugify(s: str) -> str:
    import re

    s = s.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-") or "untitled"


def _walk_content_ids(root_id: str, blocks: dict):
    """Yield every descendant block id (DFS, excluding root)."""
    seen = set()
    stack = [root_id]
    while stack:
        bid = stack.pop()
        if bid in seen:
            continue
        seen.add(bid)
        if bid not in blocks:
            continue
        v = block_value(blocks[bid])
        for cid in v.get("content", []) or []:
            if cid != bid:
                yield cid
                stack.append(cid)


def render_page(page_id: str, blocks: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (title, markdown, list of (child_page_id, child_title))."""
    if page_id not in blocks:
        return "", "", []
    v = block_value(blocks[page_id])
    title = title_text(v.get("properties", {}))
    children = v.get("content", [])
    md_parts = [f"# {title}\n"]

    # Find every descendant page (sub-pages can be nested inside column_list)
    child_pages: list[tuple[str, str]] = []
    seen_child_ids: set[str] = set()
    for did in _walk_content_ids(page_id, blocks):
        dv = block_value(blocks.get(did, {}))
        if dv.get("type") == "page" and did != page_id and did not in seen_child_ids:
            ctitle = title_text(dv.get("properties", {}))
            child_pages.append((did, ctitle))
            seen_child_ids.add(did)

    # Render direct content children. Page links are listed below the body.
    for cid in children:
        if cid not in blocks:
            continue
        md = render_block(cid, blocks)
        if md:
            md_parts.append(md)

    return title, "\n\n".join(md_parts), child_pages


def walk(page_id: str, out_dir: Path, depth: int = 0):
    print(f"{'  ' * depth}fetching {page_id[:8]}…", flush=True)
    blocks = load_page(page_id).get("block", {})
    title, md, child_pages = render_page(page_id, blocks)
    if not title:
        title = "untitled"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.md").write_text(md)
    print(f"{'  ' * depth}wrote {out_dir / 'index.md'} ({title})")
    for cid, ctitle in child_pages:
        sub = out_dir / slugify(ctitle)
        walk(cid, sub, depth + 1)
        time.sleep(0.2)


if __name__ == "__main__":
    walk(ROOT_PAGE_ID, OUT_DIR)
