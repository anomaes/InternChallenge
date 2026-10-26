"""HTML email body -> readable plain text (block structure kept, tables as tab-separated rows)."""

import html
import re
from html.parser import HTMLParser

_BLOCK = {
    "p", "div", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "table", "blockquote", "pre", "hr",
}  # fmt: skip
_SKIP = {"script", "style", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._cell = False

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        if tag in _SKIP:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "tr":
            self.parts.append("\n")
            self._cell = False
        elif tag in ("td", "th"):
            if self._cell:
                self.parts.append("\t")
            self._cell = True
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK or tag == "tr":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(re.sub(r"[ \t\r\n]+", " ", data))


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = html.unescape("".join(parser.parts))
    lines = [ln.strip(" ") for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and out and not out[-1]:
            continue
        out.append(ln)
    return "\n".join(out).strip()
