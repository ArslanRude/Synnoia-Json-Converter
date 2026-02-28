from __future__ import annotations
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, HttpUrl


# ──────────────────────────────────────────────
#  FORMATTING
# ──────────────────────────────────────────────

class Formatting(BaseModel):
    """
    Inline text formatting options.
    Only include fields that are actually applied — all are optional.
    """
    bold:          Optional[bool] = None
    italic:        Optional[bool] = None
    underline:     Optional[bool] = None
    strikethrough: Optional[bool] = None
    superscript:   Optional[bool] = None
    subscript:     Optional[bool] = None
    fontSize:      Optional[str]  = None   # e.g. "14px", "30px"
    fontFamily:    Optional[str]  = None   # e.g. "Impact", "Times New Roman"
    color:         Optional[str]  = None   # hex e.g. "#CD4A3F"
    highlight:     Optional[str]  = None   # hex e.g. "#83d3ff"
    link:          Optional[str]  = None   # URL string

    model_config = {"extra": "forbid"}


# ──────────────────────────────────────────────
#  SEGMENT  (shared by paragraph, blockquote, list items)
# ──────────────────────────────────────────────

class Segment(BaseModel):
    """
    A run of text with optional formatting.
    A paragraph or list item is made of one or more segments.
    """
    text:        str                   = Field(..., description="Raw text content")
    is_citation: Optional[bool]        = Field(None, description="True for citation refs like [2], [35]")
    formatting:  Optional[Formatting]  = None

    model_config = {"extra": "forbid"}


# ──────────────────────────────────────────────
#  NODE TYPES
# ──────────────────────────────────────────────

class HeadingNode(BaseModel):
    """H1 / H2 / H3 section heading."""
    type:       Literal["heading"]
    level:      Literal[1, 2, 3]       = Field(..., description="1=H1, 2=H2, 3=H3")
    text:       str                    = Field(..., description="Heading text")
    id:         Optional[str]          = Field(None, description="Unique anchor ID")
    toc_id:     Optional[str]          = Field(None, description="Table-of-contents ID")
    lineHeight: Optional[str]          = None   # e.g. "1.375", "1.6"
    formatting: Optional[Formatting]   = None   # e.g. bold heading

    model_config = {"extra": "forbid"}


class Margin(BaseModel):
    top:    Optional[str] = None
    bottom: Optional[str] = None

    model_config = {"extra": "forbid"}


class ParagraphNode(BaseModel):
    """Body text paragraph — one or more segments."""
    type:       Literal["paragraph"]
    textAlign:  Optional[Literal["start", "center", "end", "justify"]] = None
    lineHeight: Optional[Union[float, str]]  = None   # 1.5 or "2"
    indent:     Optional[int]                = None
    margin:     Optional[Margin]             = None
    segments:   Optional[list[Segment]]      = None   # None = empty paragraph

    model_config = {"extra": "forbid"}


class BlockquoteNode(BaseModel):
    """Blockquote / pull-quote block."""
    type:     Literal["blockquote"]
    segments: list[Segment]

    model_config = {"extra": "forbid"}


# ── Lists ──────────────────────────────────────

class ListItem(BaseModel):
    """One item inside an ordered or bullet list."""
    index:    Optional[int]    = Field(None, description="Item number (ordered lists only)")
    segments: list[Segment]

    model_config = {"extra": "forbid"}


class OrderedListNode(BaseModel):
    """Numbered list."""
    type:     Literal["ordered_list"]
    listType: Literal["decimal", "lower-alpha", "upper-alpha", "lower-roman"] = "decimal"
    items:    list[ListItem]

    model_config = {"extra": "forbid"}


class BulletListNode(BaseModel):
    """Unordered / bullet list."""
    type:     Literal["bullet_list"]
    listType: Literal["disc", "circle", "square"] = "disc"
    items:    list[ListItem]

    model_config = {"extra": "forbid"}


class TaskItem(BaseModel):
    """Single checkbox item inside a task list."""
    checked: bool
    text:    str

    model_config = {"extra": "forbid"}


class TaskListNode(BaseModel):
    """Checklist / task list."""
    type:  Literal["task_list"]
    items: list[TaskItem]

    model_config = {"extra": "forbid"}


# ── Code Block ────────────────────────────────

class CodeBlockNode(BaseModel):
    """Preformatted code block."""
    type:     Literal["code_block"]
    code:     str                                       = Field(..., description="Code content")
    language: Optional[str]                             = "plaintext"
    theme:    Optional[Literal["light", "dark"]]        = "light"
    wordWrap: Optional[bool]                            = True

    model_config = {"extra": "forbid"}


# ── Table ─────────────────────────────────────

class TableCell(BaseModel):
    """Single cell in a table row."""
    text:       str
    colspan:    Optional[int]  = 1
    rowspan:    Optional[int]  = 1
    align:      Optional[Literal["left", "center", "right"]] = None
    background: Optional[str]  = None   # hex color
    color:      Optional[str]  = None   # hex color

    model_config = {"extra": "forbid"}


class TableRow(BaseModel):
    """One row in a table."""
    row_type: Literal["header", "body"]
    cells:    list[TableCell]

    model_config = {"extra": "forbid"}


class TableNode(BaseModel):
    """Data table with header and body rows."""
    type: Literal["table"]
    rows: list[TableRow]

    model_config = {"extra": "forbid"}


# ──────────────────────────────────────────────
#  UNION OF ALL NODE TYPES
# ──────────────────────────────────────────────

Node = Union[
    HeadingNode,
    ParagraphNode,
    BlockquoteNode,
    OrderedListNode,
    BulletListNode,
    TaskListNode,
    CodeBlockNode,
    TableNode,
]


# ──────────────────────────────────────────────
#  TOP-LEVEL DOCUMENT
# ──────────────────────────────────────────────

class DocumentBody(BaseModel):
    nodes: list[Node] = Field(..., description="All document nodes in reading order")

    model_config = {"extra": "forbid"}


class Document(BaseModel):
    """Root document model — use this as the LLM structured output type."""
    document: DocumentBody

    model_config = {"extra": "forbid"}

