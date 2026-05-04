from __future__ import annotations

import json
import re
import sys
from typing import Any

CITATION_RE = re.compile(r"^\[\d+\]$")

def _omit_nulls(d: dict) -> dict:
    """Return a copy of *d* with all None / empty-dict values removed."""
    return {k: v for k, v in d.items() if v is not None and v != {}}


def _is_citation(text: str) -> bool:
    return bool(CITATION_RE.match(text.strip()))


# ═══════════════════════════════════════════════════════════════════
# FORWARD  TipTap → Simple JSON
# ═══════════════════════════════════════════════════════════════════

def load_tiptap(filepath: str) -> dict:
    """Load raw TipTap JSON from *filepath*."""
    with open(filepath, encoding="utf-8") as fh:
        return json.load(fh)


def _marks_to_formatting(marks: list[dict]) -> dict:
    """
    Convert a list of TipTap mark objects into a flat formatting dict.
    Only includes non-None attributes.
    """
    fmt: dict[str, Any] = {}
    for mark in marks:
        mtype = mark.get("type", "")
        attrs = mark.get("attrs") or {}

        if mtype == "bold":
            fmt["bold"] = True
        elif mtype == "italic":
            fmt["italic"] = True
        elif mtype == "underline":
            fmt["underline"] = True
        elif mtype == "strike":
            fmt["strikethrough"] = True
        elif mtype == "superscript":
            fmt["superscript"] = True
        elif mtype == "subscript":
            fmt["subscript"] = True
        elif mtype == "highlight":
            color = attrs.get("color")
            if color:
                fmt["highlight"] = color
        elif mtype == "link":
            pass  # Links are intentionally omitted from Simple JSON (too verbose)
        elif mtype == "textStyle":
            family = attrs.get("fontFamily")
            size = attrs.get("fontSize")
            color = attrs.get("color")
            if family:
                fmt["fontFamily"] = family
            if size:
                fmt["fontSize"] = size
            if color:
                fmt["color"] = color

    return fmt


def extract_text_segments(content: list[dict]) -> list[dict]:
    """
    Convert a list of TipTap text nodes into clean segments.
    - Merges consecutive plain-text nodes (no marks).
    - Tags citation segments with ``is_citation: true``.
    - Never produces a segment whose ``formatting`` is empty.
    """
    segments: list[dict] = []

    for node in content:
        if node.get("type") != "text":
            continue

        text = node.get("text") or ""
        marks = node.get("marks") or []
        fmt = _marks_to_formatting(marks)

        seg: dict[str, Any] = {"text": text}
        if fmt:
            seg["formatting"] = fmt

        # Citation detection: superscript + link whose text matches [N]
        if fmt.get("superscript") and _is_citation(text):
            seg["is_citation"] = True

        # Merge with previous plain-text segment when both have no formatting
        if not fmt and segments and "formatting" not in segments[-1] and not segments[-1].get("is_citation"):
            segments[-1]["text"] += text
        else:
            segments.append(seg)

    return segments


def parse_heading(node: dict) -> dict:
    attrs = node.get("attrs") or {}
    content = node.get("content") or []

    segments = extract_text_segments(content)
    # Heading text: join all segments for simplicity; keep segments for fidelity
    text = "".join(s["text"] for s in segments)

    fmt: dict[str, Any] = {}
    for s in segments:
        fmt.update(s.get("formatting") or {})

    result: dict[str, Any] = {
        "type": "heading",
        "level": attrs.get("level") or 2,
    }
    toc_id = attrs.get("data-toc-id") or attrs.get("id")
    if toc_id:
        result["id"] = toc_id
        result["toc_id"] = toc_id
    result["text"] = text
    if fmt:
        result["formatting"] = fmt

    # Extra attrs
    for key in ("textAlign", "lineHeight", "indent", "margin"):
        v = attrs.get(key)
        if v is not None and v != {}:
            result[key] = v

    return result


def parse_paragraph(node: dict) -> dict:
    attrs = node.get("attrs") or {}
    content = node.get("content") or []

    result: dict[str, Any] = {"type": "paragraph"}

    for key, default in [("textAlign", None), ("lineHeight", None),
                          ("indent", None), ("margin", {})]:
        v = attrs.get(key)
        if v is None:
            v = default
        if v is not None and v != {}:
            result[key] = v

    segments = extract_text_segments(content)
    if segments:
        result["segments"] = segments

    return result


def parse_blockquote(node: dict) -> dict:
    content = node.get("content") or []
    segments: list[dict] = []
    for child in content:
        if child.get("type") == "paragraph":
            segments.extend(extract_text_segments(child.get("content") or []))

    result: dict[str, Any] = {"type": "blockquote"}
    if segments:
        result["segments"] = segments
    return result


def _parse_list_item(item: dict) -> list[dict]:
    """
    Extract segments from all paragraph children of a listItem / taskItem.
    Returns a flat list of segments (multiple paragraphs → merged).
    """
    segments: list[dict] = []
    for child in item.get("content") or []:
        if child.get("type") == "paragraph":
            segments.extend(extract_text_segments(child.get("content") or []))
    return segments


def parse_ordered_list(node: dict) -> dict:
    attrs = node.get("attrs") or {}
    items_raw = node.get("content") or []

    list_items: list[dict] = []
    for idx, item in enumerate(items_raw, start=1):
        segs = _parse_list_item(item)
        entry: dict[str, Any] = {"index": idx}
        if segs:
            entry["segments"] = segs
        list_items.append(entry)

    result: dict[str, Any] = {
        "type": "ordered_list",
        "listType": attrs.get("listType") or "decimal",
    }
    if list_items:
        result["items"] = list_items
    return result


def parse_bullet_list(node: dict) -> dict:
    attrs = node.get("attrs") or {}
    items_raw = node.get("content") or []

    list_items: list[dict] = []
    for item in items_raw:
        segs = _parse_list_item(item)
        entry: dict[str, Any] = {}
        if segs:
            entry["segments"] = segs
        list_items.append(entry)

    result: dict[str, Any] = {
        "type": "bullet_list",
        "listType": attrs.get("listType") or "disc",
    }
    if list_items:
        result["items"] = list_items
    return result


def parse_task_list(node: dict) -> dict:
    items_raw = node.get("content") or []

    list_items: list[dict] = []
    for item in items_raw:
        item_attrs = item.get("attrs") or {}
        checked = item_attrs.get("checked") or False
        segs = _parse_list_item(item)
        # Simple flat text for task items (usually single text node)
        text = "".join(s["text"] for s in segs)
        entry: dict[str, Any] = {"checked": checked, "text": text}
        list_items.append(entry)

    result: dict[str, Any] = {"type": "task_list"}
    if list_items:
        result["items"] = list_items
    return result


def parse_code_block(node: dict) -> dict:
    attrs = node.get("attrs") or {}
    content = node.get("content") or []
    code = "".join(n.get("text") or "" for n in content if n.get("type") == "text")

    result: dict[str, Any] = {
        "type": "code_block",
        "language": attrs.get("language") or "plaintext",
    }
    theme = attrs.get("theme")
    if theme:
        result["theme"] = theme
    word_wrap = attrs.get("wordWrap")
    if word_wrap is not None:
        result["wordWrap"] = word_wrap
    result["code"] = code
    return result


def _parse_table_cell(cell: dict) -> dict:
    """Parse a tableHeader or tableCell node into a simple cell dict."""
    attrs = cell.get("attrs") or {}
    content = cell.get("content") or []

    # Gather all text segments from inner paragraphs
    segments: list[dict] = []
    for child in content:
        if child.get("type") == "paragraph":
            segments.extend(extract_text_segments(child.get("content") or []))

    simple_text = "".join(s["text"] for s in segments)

    cell_obj: dict[str, Any] = {"text": simple_text}

    # Rich segments only if there is actual formatting
    has_fmt = any("formatting" in s for s in segments)
    if has_fmt:
        cell_obj["segments"] = segments

    # Preserve span info and styling if non-default
    colspan = attrs.get("colspan") or 1
    rowspan = attrs.get("rowspan") or 1
    if colspan and colspan != 1:
        cell_obj["colspan"] = colspan
    if rowspan and rowspan != 1:
        cell_obj["rowspan"] = rowspan
    for key in ("align", "background", "color", "colwidth"):
        v = attrs.get(key)
        if v is not None:
            cell_obj[key] = v

    return cell_obj


def parse_table(node: dict) -> dict:
    rows_raw = node.get("content") or []
    rows: list[dict] = []

    for row_node in rows_raw:
        cells_raw = row_node.get("content") or []
        row_type = "header" if any(c.get("type") == "tableHeader" for c in cells_raw) else "body"
        cells = [_parse_table_cell(c) for c in cells_raw]
        rows.append({"row_type": row_type, "cells": cells})

    return {"type": "table", "rows": rows}


def parse_node(node: dict) -> dict | None:
    """Dispatch a single TipTap node to the right parser."""
    ntype = node.get("type") or ""
    dispatch = {
        "heading": parse_heading,
        "paragraph": parse_paragraph,
        "blockquote": parse_blockquote,
        "orderedList": parse_ordered_list,
        "bulletList": parse_bullet_list,
        "taskList": parse_task_list,
        "codeBlock": parse_code_block,
        "table": parse_table,
    }
    if ntype in dispatch:
        return dispatch[ntype](node)
    # Unknown / unsupported node — preserve type so nothing is lost
    return {"type": ntype, "_raw": node}


def tiptap_to_simple(tiptap_data: dict) -> dict:
    """Convert a full TipTap document dict to Simple JSON."""
    top_content = tiptap_data.get("content") or []
    nodes: list[dict] = []
    for raw_node in top_content:
        parsed = parse_node(raw_node)
        if parsed is not None:
            nodes.append(parsed)
    return {"document": {"nodes": nodes}}


def save_json(data: dict, filepath: str) -> None:
    """Save *data* to *filepath* as pretty-printed JSON."""
    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"[✓] Saved → {filepath}")


# ═══════════════════════════════════════════════════════════════════
# REVERSE  Simple JSON → TipTap
# ═══════════════════════════════════════════════════════════════════

def _formatting_to_marks(fmt: dict) -> list[dict]:
    """
    Convert a simple formatting dict back into TipTap mark objects.
    Preserves the original mark structure precisely.
    """
    marks: list[dict] = []

    # textStyle mark (fontFamily / fontSize / color)
    ts_attrs: dict[str, Any] = {
        "fontFamily": fmt.get("fontFamily", None),
        "fontSize": fmt.get("fontSize", None),
        "color": fmt.get("color", None),
    }
    if any(v is not None for v in ts_attrs.values()):
        marks.append({"type": "textStyle", "attrs": ts_attrs})

    # link mark — omitted (not stored in Simple JSON)

    # Simple boolean marks
    if fmt.get("bold"):
        marks.append({"type": "bold"})
    if fmt.get("italic"):
        marks.append({"type": "italic"})
    if fmt.get("strike") or fmt.get("strikethrough"):
        marks.append({"type": "strike"})
    if fmt.get("underline"):
        marks.append({"type": "underline"})
    if fmt.get("superscript"):
        marks.append({"type": "superscript"})
    if fmt.get("subscript"):
        marks.append({"type": "subscript"})

    # highlight
    highlight = fmt.get("highlight")
    if highlight:
        marks.append({"type": "highlight", "attrs": {"color": highlight}})

    return marks


def segments_to_tiptap_content(segments: list[dict]) -> list[dict]:
    """Convert simple ``segments`` list back to TipTap text nodes with marks."""
    nodes: list[dict] = []
    for seg in segments:
        text = seg.get("text") or ""
        fmt = seg.get("formatting") or {}
        marks = _formatting_to_marks(fmt)
        node: dict[str, Any] = {"type": "text", "text": text}
        if marks:
            node["marks"] = marks
        nodes.append(node)
    return nodes


def _default_para_attrs(**overrides) -> dict:
    base = {"indent": None, "textAlign": None, "lineHeight": 1.5, "margin": {}}
    base.update(overrides)
    return base


def _default_cell_attrs(extra: dict | None = None) -> dict:
    base: dict[str, Any] = {
        "colspan": 1,
        "rowspan": 1,
        "colwidth": None,
        "align": None,
        "background": None,
        "color": None,
    }
    if extra:
        base.update(extra)
    return base


def _wrap_in_paragraph(content_nodes: list[dict], para_attrs: dict | None = None) -> dict:
    attrs = para_attrs or _default_para_attrs()
    node: dict[str, Any] = {"type": "paragraph", "attrs": attrs}
    if content_nodes:
        node["content"] = content_nodes
    return node


def simple_to_tiptap_node(node: dict) -> dict | None:  # noqa: C901
    """Convert a single simple-format node back to TipTap format."""
    ntype = node.get("type") or ""

    # ── Heading ─────────────────────────────────────────────────────
    if ntype == "heading":
        level = node.get("level") or 2
        toc_id = node.get("toc_id") or node.get("id")
        fmt = node.get("formatting") or {}
        text = node.get("text") or ""

        # Reconstruct attrs
        attrs: dict[str, Any] = {
            "indent": node.get("indent"),
            "textAlign": node.get("textAlign"),
            "lineHeight": node.get("lineHeight") or "1.375",
            "margin": node.get("margin") or {},
            "id": toc_id,
            "data-toc-id": toc_id,
            "level": level,
        }

        # Build text node
        marks = _formatting_to_marks(fmt)
        text_node: dict[str, Any] = {"type": "text", "text": text}
        if marks:
            text_node["marks"] = marks

        return {"type": "heading", "attrs": attrs, "content": [text_node]}

    # ── Paragraph ───────────────────────────────────────────────────
    if ntype == "paragraph":
        attrs = {
            "indent": node.get("indent"),
            "textAlign": node.get("textAlign"),
            "lineHeight": node.get("lineHeight") or 1.5,
            "margin": node.get("margin") or {},
        }
        segments = node.get("segments") or []
        content_nodes = segments_to_tiptap_content(segments)
        result: dict[str, Any] = {"type": "paragraph", "attrs": attrs}
        if content_nodes:
            result["content"] = content_nodes
        return result

    # ── Blockquote ──────────────────────────────────────────────────
    if ntype == "blockquote":
        segments = node.get("segments") or []
        para_attrs = _default_para_attrs(textAlign="start")
        inner_para = _wrap_in_paragraph(segments_to_tiptap_content(segments), para_attrs)
        return {"type": "blockquote", "content": [inner_para]}

    # ── Ordered list ────────────────────────────────────────────────
    if ntype == "ordered_list":
        list_type = node.get("listType") or "decimal"
        items_raw = node.get("items") or []
        list_items: list[dict] = []
        for item in items_raw:
            segs = item.get("segments") or []
            # Each listItem in TipTap wraps paragraph(s)
            # We keep a single paragraph per item (restoring split paragraphs
            # exactly is impossible without original split markers, so one para)
            para_attrs = _default_para_attrs(textAlign="start")
            inner = _wrap_in_paragraph(segments_to_tiptap_content(segs), para_attrs)
            list_items.append({
                "type": "listItem",
                "attrs": {"indent": None},
                "content": [inner],
            })
        return {
            "type": "orderedList",
            "attrs": {"margin": {}, "start": 1, "listType": list_type},
            "content": list_items,
        }

    # ── Bullet list ─────────────────────────────────────────────────
    if ntype == "bullet_list":
        list_type = node.get("listType") or "disc"
        items_raw = node.get("items") or []
        list_items = []
        for item in items_raw:
            segs = item.get("segments") or []
            para_attrs = _default_para_attrs()
            inner = _wrap_in_paragraph(segments_to_tiptap_content(segs), para_attrs)
            list_items.append({
                "type": "listItem",
                "attrs": {"indent": None},
                "content": [inner],
            })
        return {
            "type": "bulletList",
            "attrs": {"margin": {}, "listType": list_type},
            "content": list_items,
        }

    # ── Task list ───────────────────────────────────────────────────
    if ntype == "task_list":
        items_raw = node.get("items") or []
        task_items: list[dict] = []
        for item in items_raw:
            checked = item.get("checked") or False
            text_val = item.get("text") or ""
            inner_para = _wrap_in_paragraph(
                [{"type": "text", "text": text_val}],
                _default_para_attrs(textAlign="start"),
            )
            task_items.append({
                "type": "taskItem",
                "attrs": {"indent": None, "checked": checked},
                "content": [inner_para],
            })
        return {
            "type": "taskList",
            "attrs": {"margin": {}},
            "content": task_items,
        }

    # ── Code block ──────────────────────────────────────────────────
    if ntype == "code_block":
        attrs = {
            "margin": {},
            "language": node.get("language") or "plaintext",
        }
        theme = node.get("theme")
        if theme:
            attrs["theme"] = theme
        word_wrap = node.get("wordWrap")
        if word_wrap is not None:
            attrs["wordWrap"] = word_wrap
        code = node.get("code") or ""
        return {
            "type": "codeBlock",
            "attrs": attrs,
            "content": [{"type": "text", "text": code}],
        }

    # ── Table ───────────────────────────────────────────────────────
    if ntype == "table":
        rows_simple = node.get("rows") or []
        tiptap_rows: list[dict] = []

        for row in rows_simple:
            row_type = row.get("row_type") or "body"
            cell_tag = "tableHeader" if row_type == "header" else "tableCell"
            cells_simple = row.get("cells") or []
            tiptap_cells: list[dict] = []

            for cell_obj in cells_simple:
                if isinstance(cell_obj, str):
                    # Simplified format: cell is just a string
                    cell_text = cell_obj
                    segments: list[dict] = []
                    extra_attrs: dict = {}
                else:
                    cell_text = cell_obj.get("text") or ""
                    segments = cell_obj.get("segments") or []
                    extra_attrs = {
                        k: cell_obj.get(k)
                        for k in ("colspan", "rowspan", "align", "background",
                                  "color", "colwidth")
                        if k in cell_obj and cell_obj.get(k) is not None
                    }

                cell_attrs = _default_cell_attrs(extra_attrs)

                if segments:
                    inner_content = segments_to_tiptap_content(segments)
                else:
                    inner_content = [{"type": "text", "text": cell_text}]

                para_attrs = _default_para_attrs()
                inner_para = _wrap_in_paragraph(inner_content, para_attrs)

                tiptap_cells.append({
                    "type": cell_tag,
                    "attrs": cell_attrs,
                    "content": [inner_para],
                })

            tiptap_rows.append({"type": "tableRow", "content": tiptap_cells})

        return {
            "type": "table",
            "attrs": {"margin": {}},
            "content": tiptap_rows,
        }

    # ── Unknown / raw passthrough ────────────────────────────────────
    raw = node.get("_raw")
    if raw:
        return raw
    return None


def simple_to_tiptap(simple_data: dict) -> dict:
    """Convert a full Simple JSON document back to TipTap format."""
    nodes_simple = simple_data.get("document", {}).get("nodes") or []
    content: list[dict] = []
    for snode in nodes_simple:
        tt = simple_to_tiptap_node(snode)
        if tt is not None:
            content.append(tt)
    return {"type": "doc", "content": content}


# ═══════════════════════════════════════════════════════════════════
# VERIFY ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════

def verify_roundtrip(original_path: str, simple_path: str) -> bool:
    """
    Load original TipTap JSON and simple JSON, convert simple → TipTap,
    then compare node counts and spot-check structure.

    Returns True if the round-trip is structurally consistent.
    """
    print("\n[verify_roundtrip]")
    original = load_tiptap(original_path)
    simple = load_tiptap(simple_path)

    reconstructed = simple_to_tiptap(simple)

    orig_nodes = original.get("content") or []
    recon_nodes = reconstructed.get("content") or []

    print(f"  Original nodes : {len(orig_nodes)}")
    print(f"  Reconstructed  : {len(recon_nodes)}")

    match = len(orig_nodes) == len(recon_nodes)
    if match:
        print("  [✓] Node count matches.")
    else:
        print("  [✗] Node count MISMATCH!")

    # Per-node type check
    mismatches = 0
    for i, (o, r) in enumerate(zip(orig_nodes, recon_nodes)):
        ot = o.get("type")
        rt = r.get("type")
        if ot != rt:
            print(f"  [✗] Node #{i}: original type='{ot}', reconstructed type='{rt}'")
            mismatches += 1

    if mismatches == 0 and match:
        print("  [✓] All node types match. Round-trip OK.")
        return True
    else:
        print(f"  [✗] {mismatches} type mismatch(es). Round-trip has differences.")
        return False


# ═══════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main() -> None:  # noqa: C901
    usage = (
        "Usage:\n"
        "  python json_converter.py forward  <input_tiptap.json>  <output_simple.json>\n"
        "  python json_converter.py reverse  <input_simple.json>  <output_tiptap.json>\n"
        "  python json_converter.py verify   <original_tiptap.json>  <simple.json>\n"
        "\n"
        "Defaults (when no file paths given):\n"
        "  forward  → editor-content.json  →  output_simple.json\n"
        "  reverse  → output_simple.json   →  output_tiptap.json\n"
        "  verify   → editor-content.json     output_simple.json\n"
        "\n"
        "Tip: wrap paths with spaces in quotes, e.g:\n"
        '  python json_converter.py forward "editor-content.json" "output_simple.json"\n'
    )

    # ── Determine command ────────────────────────────────────────────
    args = sys.argv[1:]

    # No arguments at all → run forward with defaults
    if not args:
        command = "reverse"
        extra: list[str] = []
    else:
        command = args[0].lower()
        extra = args[1:]

    if command not in ("forward", "reverse", "verify"):
        print(f"Unknown command: '{command}'\n")
        print(usage)
        sys.exit(1)

    # ── Resolve file paths ───────────────────────────────────────────
    # PowerShell splits unquoted paths-with-spaces into multiple argv tokens.
    # Strategy: scan tokens left-to-right; the first token ending in .json
    # (case-insensitive) marks the end of the INPUT path. Tokens after that
    # form the OUTPUT path. Missing paths fall back to sensible defaults.

    def _resolve(extra_args: list[str], default_in: str, default_out: str):
        """Return (in_path, out_path) from extra_args or defaults."""
        if not extra_args:
            return default_in, default_out

        in_parts: list[str] = []
        out_parts: list[str] = []
        split_done = False
        for token in extra_args:
            if not split_done and token.lower().endswith(".json"):
                in_parts.append(token)
                split_done = True
            elif split_done:
                out_parts.append(token)
            else:
                in_parts.append(token)

        in_path  = " ".join(in_parts)  if in_parts  else default_in
        out_path = " ".join(out_parts) if out_parts else default_out
        return in_path, out_path

    # ── Execute ──────────────────────────────────────────────────────
    if command == "forward":
        in_path, out_path = _resolve(extra, "editor-content new.json", "output_simple.json")
        print(f"[forward]  {in_path}  →  {out_path}")
        data = load_tiptap(in_path)
        simple = tiptap_to_simple(data)
        save_json(simple, out_path)

    elif command == "reverse":
        in_path, out_path = _resolve(extra, "output_simple.json", "output_tiptap.json")
        print(f"[reverse]  {in_path}  →  {out_path}")
        simple_data = load_tiptap(in_path)
        tiptap = simple_to_tiptap(simple_data)
        save_json(tiptap, out_path)

    elif command == "verify":
        in_path, out_path = _resolve(extra, "editor-content.json", "output_simple.json")
        ok = verify_roundtrip(in_path, out_path)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
