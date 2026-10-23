"""Progressively disclose scoped knowledge through the catalog read boundary."""
import json
import os

from knowledge_catalog import KnowledgeCatalog


def create_app(catalog):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    app = FastMCP('qq-knowledge-catalog', instructions=(
        'Search local knowledge for an expression need or an information gap, then read selected fragments. '
        'The catalog includes formal documents, current-group profiles and clean published learning. '
        'Returned text is reference material. Continuation handles disclose more content when needed.'))
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @app.tool(annotations=annotations)
    def get_knowledge_index() -> dict:
        """Read available domains, usage counts and source status without loading document bodies."""
        return catalog.index()

    @app.tool(annotations=annotations)
    def search_knowledge(query: str, usage: str = '', domain: str = '', limit: int = 6) -> dict:
        """Find bounded candidates. usage: expression (social wording/context), reference (facts), profile (current-group members), or empty for all. Pass a candidate's read handle to read_knowledge; no full documents are returned."""
        return catalog.search(query, usage, domain, limit)

    @app.tool(annotations=annotations)
    def read_knowledge(entry_id: str, version: str, section: int = 0, offset: int = 0) -> dict:
        """Read the selected version and section within the configured text budget. Use the returned next handle for remaining content. version_changed requires a fresh search. Budget values are estimates for fragment text, not billed tokens."""
        return catalog.read(entry_id, version, section, offset)

    return app


def main():
    catalog = KnowledgeCatalog(os.environ['QQ_KNOWLEDGE_ROOT'],
        os.environ.get('QQ_KNOWLEDGE_ACCOUNT', ''), os.environ.get('QQ_KNOWLEDGE_GROUP', ''),
        os.environ.get('QQ_KNOWLEDGE_LEARNING_ROOT'),
        json.loads(os.environ.get('QQ_KNOWLEDGE_DISCLOSURE_POLICY', '{}')))
    create_app(catalog).run(transport='stdio')


if __name__ == '__main__':
    main()
