from mcp.server import MCPServer
from nl2sql import ask_database

mcp = MCPServer("telocan")


@mcp.tool()
def query_telecom_db(question: str) -> dict:
    """Answer a natural language question about telecom customers, packages,
    subscriptions, usage, or invoices by generating and running a SQL query.
    Returns the generated SQL and the resulting rows.

    Args:
        question: A natural language question about the telecom data, e.g.
            "how many prepaid customers do I have" or "which invoices are overdue".

    Returns:
        A dict with three keys: "question" (the original input), "sql" (the
        generated SELECT statement that was run), and "rows" (a list of dicts,
        one per result row, column name to value).
    """
    return ask_database(question)


if __name__ == "__main__":
    mcp.run()