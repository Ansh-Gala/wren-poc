"""Compare two queries by what they mean, not by what they returned.

Result comparison alone is not enough. Asked for closed AR_PD_Suiting items,
the model filtered `workflow_code = 'AR_PD_Suiting'` rather than
`business_object_type`. Those two columns happen to agree on this data, so the
query returned the right four rows and scored as correct -- while resting on a
column that means something else and will diverge the moment the data changes.

So each query is reduced to a signature of the decisions it made -- tables,
projection, filters, joins, aggregates, grouping, ordering, limit -- and the
signatures are compared component by component. That keeps two properties
apart which result matching conflates:

  a query can return the right rows for the wrong reason  (caught here)
  a query can be written differently and still be right   (not penalised here)

Formatting, aliasing, predicate order and table alias names are all normalised
away. What survives is the choice of column, value, operator and shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

# Aggregates whose name matters. AVG and SUM over different columns are
# different questions; COUNT(*) and COUNT(1) are not.
_AGG_NAMES = ("count", "sum", "avg", "min", "max")


@dataclass
class SqlSignature:
    """The semantic decisions a query makes, with syntax normalised away."""

    tables: set[str] = field(default_factory=set)
    projection: set[str] = field(default_factory=set)
    filters: set[tuple[str, str, str]] = field(default_factory=set)
    joins: set[tuple[str, str]] = field(default_factory=set)
    aggregates: set[tuple[str, str]] = field(default_factory=set)
    grouping: set[str] = field(default_factory=set)
    ordering: tuple = ()
    limit: int | None = None
    distinct: bool = False
    parsed: bool = True

    def is_empty(self) -> bool:
        return not self.tables and not self.projection


def _alias_map(tree: exp.Expression) -> dict[str, str]:
    """alias -> real table name, so b.x and t.x resolve to their tables."""
    out: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        out[name] = name
        alias = table.alias
        if alias:
            out[alias] = name
    return out


def _qualify(column: exp.Column, aliases: dict[str, str], sole: str | None) -> str:
    """Fully qualified column name.

    An unprefixed column in a single-table query belongs to that table. In a
    join it is left bare rather than guessed at -- a wrong guess would create
    a false mismatch, which is worse than a slightly loose comparison.
    """
    name = column.name
    prefix = column.table
    if prefix:
        return f"{aliases.get(prefix, prefix)}.{name}"
    if sole:
        return f"{sole}.{name}"
    return name


_MIDNIGHT = (" 00:00:00", "T00:00:00", " 00:00:00.000000")


def _normalise_date(value: str) -> str:
    """Drop a midnight time component so date boundaries compare equal.

    DATE '2026-06-01', '2026-06-01' and '2026-06-01 00:00:00' are the same
    boundary written three ways; only the date part carries meaning.
    """
    v = value.strip()
    for suffix in _MIDNIGHT:
        if v.endswith(suffix):
            return v[: -len(suffix)].strip()
    return v


def _literal(node: exp.Expression) -> str:
    """Comparison value, normalised so 'Active' and "Active" agree."""
    if isinstance(node, exp.Literal):
        return _normalise_date(str(node.this))
    if isinstance(node, exp.Boolean):
        return str(node.this).lower()
    if isinstance(node, exp.Null):
        return "NULL"
    if isinstance(node, exp.Cast):
        return _literal(node.this)
    try:
        return _normalise_date(
            " ".join(node.sql(dialect="postgres").split()).strip("'\""))
    except Exception:
        return str(node)


_OPS = {
    exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=",
    exp.LT: "<", exp.LTE: "<=", exp.Like: "LIKE", exp.ILike: "ILIKE",
}


def signature(sql: str | None) -> SqlSignature:
    """Reduce a query to the decisions it makes."""
    sig = SqlSignature()
    if not sql or not sql.strip():
        sig.parsed = False
        return sig
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        sig.parsed = False
        return sig
    if tree is None:
        sig.parsed = False
        return sig

    aliases = _alias_map(tree)
    sig.tables = {t.name for t in tree.find_all(exp.Table) if t.name}
    sole = next(iter(sig.tables)) if len(sig.tables) == 1 else None

    # --- projection ---------------------------------------------------------
    selects = list(tree.selects) if hasattr(tree, "selects") else []
    sig.distinct = tree.args.get("distinct") is not None
    for item in selects:
        target = item.this if isinstance(item, exp.Alias) else item
        agg = None
        for node in target.find_all(exp.AggFunc):
            agg = node
            break
        if agg is not None:
            fname = agg.sql_name().lower() if hasattr(agg, "sql_name") else type(agg).__name__.lower()
            inner = agg.this
            if inner is None or isinstance(inner, exp.Star):
                col = "*"
            elif isinstance(inner, exp.Column):
                col = _qualify(inner, aliases, sole)
            else:
                col = " ".join(inner.sql(dialect="postgres").split())
            if fname in _AGG_NAMES:
                # COUNT(*) and COUNT(1) ask the same thing.
                if fname == "count" and col in ("*", "1"):
                    col = "*"
                sig.aggregates.add((fname, col))
                sig.projection.add(f"{fname}({col})")
                continue
        cols = list(target.find_all(exp.Column))
        if isinstance(target, exp.Star) or not cols:
            sig.projection.add("*" if isinstance(target, exp.Star) else
                               " ".join(target.sql(dialect="postgres").split()))
        else:
            for c in cols:
                sig.projection.add(_qualify(c, aliases, sole))

    # --- filters and joins --------------------------------------------------
    def record_predicate(node: exp.Expression) -> None:
        left, right = node.this, node.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            pair = tuple(sorted([_qualify(left, aliases, sole),
                                 _qualify(right, aliases, sole)]))
            sig.joins.add(pair)  # type: ignore[arg-type]
            return
        op = _OPS.get(type(node), type(node).__name__.upper())
        if isinstance(left, exp.Column):
            sig.filters.add((_qualify(left, aliases, sole), op, _literal(right)))
        elif isinstance(right, exp.Column):
            flip = {">": "<", "<": ">", ">=": "<=", "<=": ">="}.get(op, op)
            sig.filters.add((_qualify(right, aliases, sole), flip, _literal(left)))

    where = tree.args.get("where")
    scopes = [where] if where is not None else []
    for join in tree.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            scopes.append(on)

    for scope in scopes:
        for op_type in _OPS:
            for node in scope.find_all(op_type):
                record_predicate(node)
        for node in scope.find_all(exp.Between):
            col = node.this
            if isinstance(col, exp.Column):
                name = _qualify(col, aliases, sole)
                sig.filters.add((name, ">=", _literal(node.args.get("low"))))
                sig.filters.add((name, "<=", _literal(node.args.get("high"))))
        for node in scope.find_all(exp.In):
            col = node.this
            if isinstance(col, exp.Column):
                values = sorted(_literal(e) for e in (node.args.get("expressions") or []))
                sig.filters.add((_qualify(col, aliases, sole), "IN", ",".join(values)))
        for node in scope.find_all(exp.Is):
            col = node.this
            if isinstance(col, exp.Column):
                value = _literal(node.expression)
                # IS TRUE / IS FALSE are boolean tests, not null tests; fold
                # them into the same form a bare column predicate produces.
                op = "=" if value in ("true", "false") else "IS"
                sig.filters.add((_qualify(col, aliases, sole), op, value))
        # A bare boolean column used as a predicate, e.g. WHERE is_open_task.
        # Normalised to the same shape as "= true" so the two spellings of one
        # test do not read as a disagreement.
        for node in scope.find_all(exp.Column):
            parent = node.parent
            if isinstance(parent, (exp.Where, exp.And, exp.Or)):
                sig.filters.add((_qualify(node, aliases, sole), "=", "true"))

    # --- grouping, ordering, limit -----------------------------------------
    group = tree.args.get("group")
    if group is not None:
        for e in group.expressions:
            if isinstance(e, exp.Column):
                sig.grouping.add(_qualify(e, aliases, sole))

    # ORDER BY frequently names a select alias. "ORDER BY n DESC" and
    # "ORDER BY item_count DESC" are the same instruction when both aliases
    # were given to COUNT(*), so resolve an alias back to what it stands for
    # before comparing; otherwise every alias choice reads as a difference.
    select_aliases: dict[str, str] = {}
    for item in selects:
        if isinstance(item, exp.Alias) and item.alias:
            inner = item.this
            agg = next(iter(inner.find_all(exp.AggFunc)), None)
            if agg is not None:
                fname = (agg.sql_name().lower() if hasattr(agg, "sql_name")
                         else type(agg).__name__.lower())
                a_inner = agg.this
                if a_inner is None or isinstance(a_inner, exp.Star):
                    acol = "*"
                elif isinstance(a_inner, exp.Column):
                    acol = _qualify(a_inner, aliases, sole)
                else:
                    acol = " ".join(a_inner.sql(dialect="postgres").split())
                if fname == "count" and acol in ("*", "1"):
                    acol = "*"
                select_aliases[item.alias] = f"{fname}({acol})"
            elif isinstance(inner, exp.Column):
                select_aliases[item.alias] = _qualify(inner, aliases, sole)

    order = tree.args.get("order")
    if order is not None:
        seq = []
        for o in order.expressions:
            target = o.this
            if isinstance(target, exp.Column) and not target.table                     and target.name in select_aliases:
                key = select_aliases[target.name]
            elif isinstance(target, exp.Column):
                key = _qualify(target, aliases, sole)
            else:
                key = " ".join(target.sql(dialect="postgres").split())
                agg = next(iter(target.find_all(exp.AggFunc)), None)
                if agg is not None:
                    fname = (agg.sql_name().lower() if hasattr(agg, "sql_name")
                             else type(agg).__name__.lower())
                    a_inner = agg.this
                    acol = ("*" if a_inner is None or isinstance(a_inner, exp.Star)
                            else _qualify(a_inner, aliases, sole)
                            if isinstance(a_inner, exp.Column)
                            else " ".join(a_inner.sql(dialect="postgres").split()))
                    if fname == "count" and acol in ("*", "1"):
                        acol = "*"
                    key = f"{fname}({acol})"
            seq.append((key, "desc" if o.args.get("desc") else "asc"))
        sig.ordering = tuple(seq)

    lim = tree.args.get("limit")
    if lim is not None:
        try:
            sig.limit = int(lim.expression.this)
        except Exception:
            sig.limit = None
    return sig


# ------------------------------------------------------------------ compare --

PROJECTION_EXACT = "exact"
PROJECTION_SUPERSET = "superset"
PROJECTION_MISSING = "missing"
PROJECTION_SUBSTITUTED = "substituted"


@dataclass
class SemanticComparison:
    parsed: bool = True
    tables_match: bool = False
    filters_match: bool = False
    joins_match: bool = False
    aggregates_match: bool = False
    grouping_match: bool = False
    ordering_match: bool = False
    limit_match: bool = False
    projection_verdict: str = PROJECTION_EXACT
    issues: list[str] = field(default_factory=list)

    @property
    def semantically_correct(self) -> bool:
        """Every decision that changes meaning agrees.

        Projection is judged separately: an extra column is untidy, a wrong or
        missing one is not, so only the latter two count against correctness.
        """
        return (
            self.parsed
            and self.tables_match
            and self.filters_match
            and self.joins_match
            and self.aggregates_match
            and self.grouping_match
            and self.ordering_match
            and self.limit_match
            and self.projection_verdict in (PROJECTION_EXACT, PROJECTION_SUPERSET)
        )


def _bare(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def compare(expected_sql: str | None, generated_sql: str | None,
            ordered: bool = False) -> SemanticComparison:
    """Component-by-component comparison of two queries.

    ``ordered`` says whether the question actually demanded an order. When it
    did not, a query that sorts anyway is not wrong, so ordering is not checked.
    """
    exp_sig, act_sig = signature(expected_sql), signature(generated_sql)
    c = SemanticComparison()
    if not exp_sig.parsed or not act_sig.parsed:
        c.parsed = False
        c.issues.append("could not parse one of the queries")
        return c

    c.tables_match = exp_sig.tables == act_sig.tables
    if not c.tables_match:
        extra, missing = act_sig.tables - exp_sig.tables, exp_sig.tables - act_sig.tables
        c.issues.append(
            "tables differ"
            + (f"; unexpected {sorted(extra)}" if extra else "")
            + (f"; missing {sorted(missing)}" if missing else "")
        )

    # Filters are compared on the bare column name so that a single-table query
    # and an aliased join expressing the same predicate still agree.
    exp_f = {(_bare(col), op, val) for col, op, val in exp_sig.filters}
    act_f = {(_bare(col), op, val) for col, op, val in act_sig.filters}
    c.filters_match = exp_f == act_f
    if not c.filters_match:
        wrong_col = {f for f in act_f - exp_f
                     if f[0] not in {e[0] for e in exp_f}}
        wrong_val = {f for f in act_f - exp_f
                     if f[0] in {e[0] for e in exp_f}}
        if wrong_col:
            c.issues.append(f"filters on unexpected column(s): {sorted(wrong_col)}")
        if wrong_val:
            c.issues.append(f"filter value/operator differs: {sorted(wrong_val)}")
        missing = exp_f - act_f
        if missing:
            c.issues.append(f"missing filter(s): {sorted(missing)}")

    exp_j = {tuple(sorted(_bare(x) for x in pair)) for pair in exp_sig.joins}
    act_j = {tuple(sorted(_bare(x) for x in pair)) for pair in act_sig.joins}
    c.joins_match = exp_j == act_j
    if not c.joins_match:
        c.issues.append(f"join conditions differ: expected {sorted(exp_j)}, got {sorted(act_j)}")

    exp_a = {(f, _bare(col)) for f, col in exp_sig.aggregates}
    act_a = {(f, _bare(col)) for f, col in act_sig.aggregates}
    c.aggregates_match = exp_a == act_a
    if not c.aggregates_match:
        c.issues.append(f"aggregation differs: expected {sorted(exp_a)}, got {sorted(act_a)}")

    exp_g = {_bare(g) for g in exp_sig.grouping}
    act_g = {_bare(g) for g in act_sig.grouping}
    c.grouping_match = exp_g == act_g
    if not c.grouping_match:
        c.issues.append(f"grouping differs: expected {sorted(exp_g)}, got {sorted(act_g)}")

    if ordered:
        exp_o = tuple((_bare(k), d) for k, d in exp_sig.ordering)
        act_o = tuple((_bare(k), d) for k, d in act_sig.ordering)
        c.ordering_match = exp_o == act_o
        if not c.ordering_match:
            c.issues.append(f"ordering differs: expected {exp_o}, got {act_o}")
    else:
        c.ordering_match = True

    c.limit_match = exp_sig.limit == act_sig.limit
    if not c.limit_match:
        c.issues.append(f"limit differs: expected {exp_sig.limit}, got {act_sig.limit}")

    # Projection. Aggregate terms are already covered above, so compare the
    # plain columns and say which of the four things happened.
    exp_p = {_bare(p) for p in exp_sig.projection if "(" not in p}
    act_p = {_bare(p) for p in act_sig.projection if "(" not in p}
    if exp_p == act_p:
        c.projection_verdict = PROJECTION_EXACT
    elif exp_p and exp_p < act_p:
        c.projection_verdict = PROJECTION_SUPERSET
        c.issues.append(f"projection includes extra column(s): {sorted(act_p - exp_p)}")
    elif exp_p - act_p and not (act_p - exp_p):
        c.projection_verdict = PROJECTION_MISSING
        c.issues.append(f"projection missing: {sorted(exp_p - act_p)}")
    else:
        c.projection_verdict = PROJECTION_SUBSTITUTED
        c.issues.append(
            f"projection substituted: missing {sorted(exp_p - act_p)}, "
            f"unexpected {sorted(act_p - exp_p)}"
        )
    return c


# ------------------------------------------------------------ hallucination --

def _schema_index() -> tuple[set[str], dict[str, set[str]]]:
    """(table names, table -> columns) from the generated schema description."""
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[1] / "metadata" / "schema_description.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tables: set[str] = set()
    columns: dict[str, set[str]] = {}
    for table, spec in (doc.get("tables") or {}).items():
        tables.add(table)
        columns[table] = set((spec.get("columns") or {}).keys())
    return tables, columns


@dataclass
class SchemaCheck:
    """Whether a query stays inside the schema it was given."""

    parsed: bool = True
    unknown_tables: set[str] = field(default_factory=set)
    unknown_columns: set[str] = field(default_factory=set)

    @property
    def grounded(self) -> bool:
        return self.parsed and not self.unknown_tables and not self.unknown_columns


def check_against_schema(sql: str | None) -> SchemaCheck:
    """Flag tables and columns the database does not have.

    The prompt tells the model never to invent a name, and this is how that is
    verified rather than assumed. It is deliberately deterministic: asked for a
    column that does not exist, a system may reasonably refuse or return
    nothing, but inventing `profit_margin` and producing confident SQL is
    always wrong, and only a schema check catches it -- the query would fail at
    execution with an error that looks like any other.

    Aliases introduced by the query itself (a subquery or a computed column)
    are not schema names and are not reported.
    """
    check = SchemaCheck()
    if not sql or not sql.strip():
        check.parsed = False
        return check
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        check.parsed = False
        return check
    if tree is None:
        check.parsed = False
        return check

    known_tables, known_columns = _schema_index()
    used = {t.name for t in tree.find_all(exp.Table) if t.name}
    check.unknown_tables = used - known_tables

    # Names the query defines for itself are not schema references.
    self_defined = {a.alias for a in tree.find_all(exp.Alias) if a.alias}
    self_defined |= {t.alias for t in tree.find_all(exp.Table) if t.alias}
    self_defined |= {c.alias_or_name for c in tree.find_all(exp.CTE)}

    allowed: set[str] = set()
    for table in used & known_tables:
        allowed |= known_columns.get(table, set())

    for column in tree.find_all(exp.Column):
        name = column.name
        if not name or name == "*" or name in self_defined or name in allowed:
            continue
        # An unknown name is only reported when every table in the query is a
        # known one; otherwise the unknown table already explains it.
        if not check.unknown_tables:
            check.unknown_columns.add(name)
    return check
