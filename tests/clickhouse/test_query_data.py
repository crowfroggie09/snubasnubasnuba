import pytest

from typing import List, Tuple

from snuba.clickhouse.astquery import AstSqlQuery
from snuba.clickhouse.columns import ColumnSet
from snuba.datasets.schemas.tables import TableSource
from snuba.query.conditions import binary_condition
from snuba.query.expressions import (
    Column,
    CurriedFunctionCall,
    FunctionCall,
    Literal,
)
from snuba.query.logical import OrderBy, OrderByDirection, Query
from snuba.request.request_settings import HTTPRequestSettings

test_cases = [
    (
        # Simple query with aliases and multiple tables
        Query(
            {},
            TableSource("my_table", ColumnSet([])),
            selected_columns=[
                Column(None, "column1", None),
                Column(None, "column2", "table1"),
                Column("al", "column3", None),
            ],
            condition=binary_condition(
                None,
                "eq",
                lhs=Column("al", "column3", None),
                rhs=Literal(None, "blabla"),
            ),
            groupby=[
                Column(None, "column1", None),
                Column(None, "column2", "table1"),
                Column("al", "column3", None),
                Column(None, "column4", None),
            ],
            having=binary_condition(
                None, "eq", lhs=Column(None, "column1", None), rhs=Literal(None, 123),
            ),
            order_by=[
                OrderBy(OrderByDirection.ASC, Column(None, "column1", None)),
                OrderBy(OrderByDirection.DESC, Column(None, "column2", "table1")),
            ],
        ),
        {
            "from": "FROM my_table",
            "group": "GROUP BY (column1, table1.column2, al, column4)",
            "having": "HAVING eq(column1, 123)",
            "order": "ORDER BY column1 ASC, table1.column2 DESC",
            "select": "SELECT column1, table1.column2, (column3 AS al)",
            "where": "WHERE eq(al, 'blabla')",
        },
    ),
    (
        # Query with complex functions
        Query(
            {},
            TableSource("my_table", ColumnSet([])),
            selected_columns=[
                CurriedFunctionCall(
                    "my_complex_math",
                    FunctionCall(
                        None,
                        "doSomething",
                        [
                            Column(None, "column1", None),
                            Column(None, "column2", "table1"),
                            Column("al", "column3", None),
                        ],
                    ),
                    [Column(None, "column1", None)],
                )
            ],
            condition=binary_condition(
                None,
                "and",
                lhs=binary_condition(
                    None,
                    "eq",
                    lhs=Column("al", "column3", None),
                    rhs=Literal(None, "blabla"),
                ),
                rhs=binary_condition(
                    None,
                    "neq",  # yes, not very smart
                    lhs=Column("al", "column3", None),
                    rhs=Literal(None, "blabla"),
                ),
            ),
            groupby=[
                CurriedFunctionCall(
                    "my_complex_math",
                    FunctionCall(
                        None,
                        "doSomething",
                        [
                            Column(None, "column1", None),
                            Column(None, "column2", "table1"),
                            Column("al", "column3", None),
                        ],
                    ),
                    [Column(None, "column1", None)],
                )
            ],
            order_by=[
                OrderBy(
                    OrderByDirection.ASC,
                    FunctionCall(None, "f", [Column(None, "column1", None)]),
                )
            ],
        ),
        {
            "from": "FROM my_table",
            "group": "GROUP BY (my_complex_math)",
            "order": "ORDER BY f(column1) ASC",
            "select": "SELECT (doSomething(column1, table1.column2, (column3 AS "
            "al))(column1) AS my_complex_math)",
            "where": "WHERE and(eq(al, 'blabla'), neq(al, 'blabla'))",
        },
    ),
    (
        # Query with escaping
        Query(
            {},
            TableSource("my_table", ColumnSet([])),
            selected_columns=[
                Column("al1", "field_##$$%", None),
                Column("al2", "f@!@", "t&^%$"),
            ],
            groupby=[
                Column("al1", "field_##$$%", None),
                Column("al2", "f@!@", "t&^%$"),
            ],
            order_by=[OrderBy(OrderByDirection.ASC, Column(None, "column1", None))],
        ),
        {
            "from": "FROM my_table",
            "group": "GROUP BY (al1, al2)",
            "order": "ORDER BY column1 ASC",
            "select": "SELECT (`field_##$$%` AS al1), (`t&^%$`.`f@!@` AS al2)",
        },
    ),
]


@pytest.mark.parametrize("query, data", test_cases)
def test_format_expressions(query: Query, data: List[Tuple[str, str]]) -> None:
    request_settings = HTTPRequestSettings()
    clickhouse_query = AstSqlQuery(query, request_settings)
    assert clickhouse_query.sql_data() == data


def test_format_clickhouse_specific_query() -> None:
    """
    Adds a few of the Clickhosue specific fields to the query.
    """

    query = Query(
        {"sample": 0.1, "totals": True, "limitby": (10, "environment")},
        TableSource("my_table", ColumnSet([])),
        selected_columns=[
            Column(None, "column1", None),
            Column(None, "column2", "table1"),
        ],
        condition=binary_condition(
            None, "eq", lhs=Column(None, "column1", None), rhs=Literal(None, "blabla"),
        ),
        groupby=[Column(None, "column1", None), Column(None, "column2", "table1")],
        having=binary_condition(
            None, "eq", lhs=Column(None, "column1", None), rhs=Literal(None, 123),
        ),
        order_by=[OrderBy(OrderByDirection.ASC, Column(None, "column1", None))],
        array_join=Column(None, "column1", None),
    )

    query.set_final(True)
    query.set_offset(50)
    query.set_limit(100)

    request_settings = HTTPRequestSettings()
    clickhouse_query = AstSqlQuery(query, request_settings)

    expected = {
        "from": "FROM my_table FINAL SAMPLE 0.1",
        "group": "GROUP BY (column1, table1.column2) WITH TOTALS",
        "having": "HAVING eq(column1, 123)",
        "array_join": "ARRAY JOIN column1",
        "limit": "LIMIT 100 OFFSET 50",
        "limitby": "LIMIT 10 BY environment",
        "order": "ORDER BY column1 ASC",
        "select": "SELECT column1, table1.column2",
        "where": "WHERE eq(column1, 'blabla')",
    }

    assert clickhouse_query.sql_data() == expected