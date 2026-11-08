"""Turn Nexus page text (BBCode mixed with a little HTML) into plain text."""

from __future__ import annotations

import html
import re

_URL_TAG = re.compile(r"\[url=([^\]]+)\](.*?)\[/url\]", re.I | re.S)
_URL_BARE = re.compile(r"\[url\](.*?)\[/url\]", re.I | re.S)
_IMG = re.compile(r"\[img[^\]]*\].*?\[/img\]", re.I | re.S)
_YOUTUBE = re.compile(r"\[youtube\](.*?)\[/youtube\]", re.I | re.S)
_ANY_TAG = re.compile(r"\[/?[a-z*]+(?:=[^\]]*)?\]", re.I)
_HTML_TAG = re.compile(r"<[^>]+>")


def bbcode_to_text(source: str, *, keep_links: bool = False) -> str:
    """Readable text from a Nexus description. With ``keep_links`` a link keeps
    its address after the text, e.g. "SkyUI (https://www.nexusmods.com/...)"."""
    if not source:
        return ""
    s = source.replace("\r\n", "\n")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"\[br\]", "\n", s, flags=re.I)
    s = _IMG.sub("", s)
    s = _YOUTUBE.sub("(video)", s)

    def url(m: re.Match) -> str:
        target, label = m.group(1).strip("\"' "), m.group(2)
        label = _ANY_TAG.sub("", label).strip()
        if keep_links and target and target not in label:
            return f"{label} ({target})" if label else target
        return label or target
    s = _URL_TAG.sub(url, s)
    s = _URL_BARE.sub(lambda m: m.group(1), s)
    s = re.sub(r"\[\*\]", "\n• ", s)
    s = re.sub(r"\[line\]", "\n———\n", s, flags=re.I)
    s = re.sub(r"\[spoiler\]", "\n(spoiler) ", s, flags=re.I)
    s = re.sub(r"\[/?(?:list|center|left|right|quote|code|heading)[^\]]*\]", "\n", s, flags=re.I)
    s = _ANY_TAG.sub("", s)
    s = _HTML_TAG.sub("", s)
    s = html.unescape(s)
    lines = [line.strip() for line in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def nexus_mod_ids(source: str, game: str) -> set[int]:
    """Mod numbers of every link to a Nexus mod page of ``game`` in the text."""
    pattern = (r"nexusmods\.com/(?:games/)?" + re.escape(game) + r"/mods/(\d+)")
    return {int(m) for m in re.findall(pattern, source or "", flags=re.I)}
