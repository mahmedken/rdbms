from __future__ import annotations

"""Lightweight SQL parser that produces the same field names expected by the
Executor and operators.  The only goal is to translate a subset of SQL into a
`pyparsing.ParseResults` object with attributes like `query_type`, `columns`,
`tables`, etc.  Extensive semantic checks were dropped for brevity; the
Executor/catalog raise errors later if metadata is missing or wrong."""

from pyparsing import (
    CaselessKeyword,
    Forward,
    Group,
    Literal,
    Optional,
    ParseException,
    ParseResults,
    Suppress,
    Word,
    alphanums,
    alphas,
    delimitedList,
    infixNotation,
    nums,
    oneOf,
    QuotedString,
    OpAssoc,
)

# ---------------------------------------------------------------------------
# basic atoms
# ---------------------------------------------------------------------------

ident = Word(alphas, alphanums + "_")
integer = Word(nums).setParseAction(lambda t: int(t[0]))
string_ = QuotedString("'")
literal = string_ | integer
STAR = Literal("*")

column_ref = Group(Optional(ident + Suppress("."))("table") + ident("column"))
agg_func = oneOf("MIN MAX SUM AVG COUNT", caseless=True)
agg_expr = Group(agg_func("function") + Suppress("(") + (STAR | column_ref)("argument") + Suppress(")"))(
    "aggregation"
)

expr_atom = literal | agg_expr | column_ref
comp_op = oneOf("= != < > <= >=", caseless=True)
cond = Forward()
_simple = Group(expr_atom + comp_op + expr_atom)
cond <<= infixNotation(_simple, [(CaselessKeyword("AND"), 2, OpAssoc.LEFT), (CaselessKeyword("OR"), 2, OpAssoc.LEFT)])

# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------

select_item = agg_expr | column_ref | STAR
table_ref = Group(ident("table") + Optional(Suppress(CaselessKeyword("AS")) + ident("alias")))
order_dir = Optional(oneOf("ASC DESC", caseless=True), default="ASC")("direction")
order_item = Group((agg_expr | column_ref) + order_dir)
select_stmt = (
    CaselessKeyword("SELECT")
    + delimitedList(select_item)("columns")
    + CaselessKeyword("FROM")
    + delimitedList(table_ref)("tables")
    + Optional(CaselessKeyword("WHERE") + cond)("where")
    + Optional(
        CaselessKeyword("GROUP")
        + CaselessKeyword("BY")
        + delimitedList(column_ref)("group_by")
        + Optional(CaselessKeyword("HAVING") + cond)("having")
    )
    + Optional(CaselessKeyword("ORDER") + CaselessKeyword("BY") + delimitedList(order_item)("order_by"))
    + Optional(CaselessKeyword("LIMIT") + integer("limit"))
).setParseAction(lambda t: t.__setitem__("query_type", "SELECT"))

# ---------------------------------------------------------------------------
# DDL + DML helpers
# ---------------------------------------------------------------------------

values_list = Suppress("(") + delimitedList(literal)("insert_values") + Suppress(")")
column_list = Suppress("(") + delimitedList(ident)("columns") + Suppress(")")

def _tag(qtype):
    return lambda t: t.__setitem__("query_type", qtype)

insert_stmt = (
    CaselessKeyword("INSERT")
    + CaselessKeyword("INTO")
    + ident("table_name")
    + Optional(column_list)
    + CaselessKeyword("VALUES")
    + values_list
).setParseAction(_tag("INSERT"))

update_assign = Group(ident("column") + Suppress("=") + literal("value"))
update_stmt = (
    CaselessKeyword("UPDATE")
    + ident("table_name")
    + CaselessKeyword("SET")
    + delimitedList(update_assign)("assignments")
    + Optional(CaselessKeyword("WHERE") + cond)("where")
).setParseAction(_tag("UPDATE"))

delete_stmt = (
    CaselessKeyword("DELETE")
    + CaselessKeyword("FROM")
    + ident("table_name")
    + Optional(CaselessKeyword("WHERE") + cond)("where")
).setParseAction(_tag("DELETE"))

# CREATE TABLE (col INT|STR, ..., PRIMARY KEY(col))
INT = CaselessKeyword("INT")
STR = CaselessKeyword("STR")
datatype = INT("type") | STR("type")
col_def = Group(ident("name") + datatype)
pk_def = Group(CaselessKeyword("PRIMARY") + CaselessKeyword("KEY") + Suppress("(") + ident("pk_column") + Suppress(")"))("primary_key")
create_table_stmt = (
    CaselessKeyword("CREATE")
    + CaselessKeyword("TABLE")
    + ident("table_name")
    + Suppress("(")
    + delimitedList(col_def)("columns")
    + Optional(Suppress(",") + pk_def)
    + Suppress(")")
).setParseAction(_tag("CREATE_TABLE"))

drop_table_stmt = (
    CaselessKeyword("DROP") + CaselessKeyword("TABLE") + ident("table_name")
).setParseAction(_tag("DROP_TABLE"))
create_index_stmt = (
    CaselessKeyword("CREATE") + CaselessKeyword("INDEX") + ident("table_name") + ident("column_name")
).setParseAction(_tag("CREATE_INDEX"))
drop_index_stmt = (
    CaselessKeyword("DROP") + CaselessKeyword("INDEX") + ident("table_name") + ident("column_name")
).setParseAction(_tag("DROP_INDEX"))

statement = select_stmt | insert_stmt | update_stmt | delete_stmt | create_table_stmt | drop_table_stmt | create_index_stmt | drop_index_stmt

# ---------------------------------------------------------------------------
# facade
# ---------------------------------------------------------------------------

class SQLParser:
    def parse(self, sql: str) -> ParseResults:
        try:
            return statement.parseString(sql, parseAll=True)
        except ParseException as e:
            raise ParseException(f"Error parsing SQL: {e}")
