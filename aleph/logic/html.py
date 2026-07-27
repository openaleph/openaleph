import logging
from html import escape

import nh3
from flask_babel import gettext

log = logging.getLogger(__name__)

# Tags removed together with their content. `script` and `style` must be
# listed explicitly: passing `clean_content_tags` replaces ammonia's built-in
# {script, style} default. `title` and `noscript` are included because
# html5ever treats their content as text that would otherwise leak into the
# visible output.
KILL_TAGS = {
    "area",
    "audio",
    "base",
    "bgsound",
    "embed",
    "frame",
    "frameset",
    "head",
    "iframe",
    "img",
    "input",
    "link",
    "map",
    "meta",
    "nav",
    "noscript",
    "object",
    "plaintext",
    "script",
    "style",
    "svg",
    "title",
    "track",
    "video",
}

ALLOWED_TAGS = nh3.ALLOWED_TAGS - KILL_TAGS

# nh3's per-tag defaults, minus killed tags (ammonia rejects a tag appearing
# in both `clean_content_tags` and `attributes`), plus presentational
# attributes allowed on all tags – lxml's Cleaner used to keep these via its
# `safe_attrs` list, and dropping them breaks e.g. table-based email layouts.
ALLOWED_ATTRIBUTES = {
    tag: attrs for tag, attrs in nh3.ALLOWED_ATTRIBUTES.items() if tag not in KILL_TAGS
}
ALLOWED_ATTRIBUTES["*"] = {
    "align",
    "border",
    "cellpadding",
    "cellspacing",
    "class",
    "dir",
    "height",
    "id",
    "lang",
    "name",
    "title",
    "valign",
    "width",
}

CLEAN_ARGS = {
    "tags": ALLOWED_TAGS,
    "clean_content_tags": KILL_TAGS,
    "attributes": ALLOWED_ATTRIBUTES,
    "link_rel": "nofollow noreferrer external noopener",
    "set_tag_attribute_values": {"a": {"target": "_blank"}},
}


def sanitize_html(html_text: str | None, base_url: str | None) -> str | None:
    """Remove anything from the given HTML that must not show up in the UI."""
    if html_text is None or not len(html_text.strip()):
        return None
    try:
        if base_url is not None and len(base_url.strip()):
            try:
                return nh3.clean(
                    html_text,
                    url_relative=("rewrite_with_base", base_url),
                    **CLEAN_ARGS,
                )
            except ValueError:
                # the base URL could not be parsed; keep links untouched
                pass
        return nh3.clean(html_text, **CLEAN_ARGS)
    except Exception as exc:
        log.warning("HTML sanitizer failure [%s]: %s", type(exc), exc)
        return gettext("[HTML removed: could not be sanitized]")


def html_link(text: str | None, link: str | None) -> str:
    text = text or "[untitled]"
    text = escape(text)

    if link is None:
        return f"<span class='reference'>{text}</span>"

    link = escape(link)
    return f"<a class='reference' href='{link}'>{text}</a>"
