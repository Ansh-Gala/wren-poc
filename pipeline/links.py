"""What a row can open: a page, a file, or one of the app's popups.

`columns` is stripped from a response when debug is off -- it holds raw
database column names -- so the frontend receives headings and rows and no
way to tell which cell opens what. The positions are named here, on the
server, where the real column names are still in hand.

One link per product.yaml entity with `open`, when the answer projected what
it opens:

  value_at  the position of the value opened (the id, or a file address)
  at        the readable cell made clickable (the title, else the value);
            absent for a button, which gets a column of its own
  action    url, download or popup, with url and encode, or popup and
            param, as product.yaml gives them
  button    the button's text, for a button

Two positions rather than one, because the cell a person clicks is not the
cell holding the value: an issue is opened by its id, but the readable cell is
its title, and a grid of primary keys is not something anyone wants to read.
When only the value column is projected, `at` falls back to it.

Positions and product.yaml's own strings only, naming no table or SQL, so
they survive redaction.

Ported from the Drupal module's Links.
"""

from __future__ import annotations


def _first(names: list[str], candidates) -> int | None:
    for i, name in enumerate(names):
        if name in candidates:
            return i
    return None


def indices(columns: list[str] | None) -> list[dict]:
    """The links an answer with these columns carries, in product.yaml order.

    The first occurrence of a name wins, matching `initiative.indices`: a
    result may project one name twice, and the frontend keys its rows by
    index. A cell takes the first link that claims it.
    """
    from pipeline.metadata import profile

    names = [str(c) for c in (columns or [])]
    out: list[dict] = []
    claimed: set[int] = set()
    for link in profile().links():
        value_at = _first(names, link["value_columns"])
        if value_at is None:
            continue
        opened = link["open"]
        item: dict = {"value_at": value_at}
        if "download" in opened:
            item["action"] = "download"
        elif "popup" in opened:
            item.update(action="popup", popup=str(opened["popup"]), param=str(opened["param"]))
        else:
            item.update(action="url", url=str(opened["url"]),
                        encode=str(opened.get("encode") or "plain"))

        if "button" in opened:
            item["button"] = str(opened["button"])
        else:
            label_at = _first(names, link["label_columns"])
            item["at"] = label_at if label_at is not None else value_at
            if item["at"] in claimed:
                continue
            claimed.add(item["at"])
        out.append(item)
    return out


def with_links(result, columns: list[str] | None):
    """A result with what its rows can open attached.

    Additive, like every other presentation field: `columns` and `rows` keep
    exactly what PostgreSQL said. Anything that is not a result passes through
    -- a clarification has no rows, and a count has nothing to follow.

    `columns` is passed in rather than read off the result because this has to
    run against the real column names, and the caller is the last place that
    still holds them.
    """
    if not isinstance(result, dict):
        return result

    links = indices(columns)
    if not links:
        # Nothing to open. Say so by omission rather than by an empty list.
        return result
    return {**result, "links": links}
