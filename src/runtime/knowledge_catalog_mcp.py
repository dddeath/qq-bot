"""Progressively disclose scoped knowledge through the catalog read boundary."""
from typing import Annotated
from pydantic import Field
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
    def search_knowledge(query: Annotated[str, Field(description='Literal keywords or names for this search. Space-separated terms are supported.')], usage: Annotated[str, Field(description='expression, reference, profile, or empty to search all visible categories.')] = '', domain: Annotated[str, Field(description='Domain key from the knowledge index; empty searches all visible domains.')] = '', limit: Annotated[int, Field(description='Maximum candidates requested; the service bounds the result count.')] = 6) -> dict:
        """Find bounded candidates. usage: expression (social wording/context), reference (facts), profile (current-group members), or empty for all. Pass a candidate's read handle to read_knowledge; no full documents are returned."""
        return catalog.search(query, usage, domain, limit)

    @app.tool(annotations=annotations)
    def read_knowledge(entry_id: Annotated[str, Field(description='Catalog ID from search_knowledge results[].read; pass its entry_id, version and section.')], version: Annotated[str, Field(description='Opaque document version returned by search_knowledge; copy it unchanged.')], section: Annotated[int, Field(description='Zero-based section index from the returned read handle.')] = 0, offset: Annotated[int, Field(description='Zero-based character offset; use the complete returned next object for continuation.')] = 0) -> dict:
        """Read the selected version and section within the configured text budget. Use the returned next handle for remaining content. version_changed requires a fresh search. Budget values are estimates for fragment text, not billed tokens."""
        return catalog.read(entry_id, version, section, offset)

    return app


def main():
    entry_store = os.environ.get('QQ_KNOWLEDGE_ENTRY_STORE')
    if entry_store:
        from pathlib import Path
        from knowledge_entries import EntryStore
        from knowledge_entries_mcp import create_app as create_entry_app

        if not Path(entry_store).is_file():
            raise ValueError('knowledge_entry_store_missing')
        account = os.environ.get('QQ_KNOWLEDGE_ACCOUNT', '')
        group = os.environ.get('QQ_KNOWLEDGE_GROUP', '')
        collections = ['formal']
        if account.isdigit() and group.isdigit():
            collections += [f'learning:{account}:{group}', f'profile:{account}:{group}']
        create_entry_app(EntryStore(entry_store, collections), read_only=True).run(transport='stdio')
        return
    catalog = KnowledgeCatalog(os.environ['QQ_KNOWLEDGE_ROOT'],
        os.environ.get('QQ_KNOWLEDGE_ACCOUNT', ''), os.environ.get('QQ_KNOWLEDGE_GROUP', ''),
        os.environ.get('QQ_KNOWLEDGE_LEARNING_ROOT'),
        json.loads(os.environ.get('QQ_KNOWLEDGE_DISCLOSURE_POLICY', '{}')))
    create_app(catalog).run(transport='stdio')


if __name__ == '__main__':
    main()
