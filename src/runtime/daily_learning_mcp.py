"""Only published learning reaches the character host; source material is separate."""
from typing import Annotated
from pydantic import Field
import json,os
from pathlib import Path
from daily_learning_worker import instance,collector

def main():
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    cfg=json.loads(Path(os.environ['QQ_DAILY_LEARNING_CONFIG']).read_text());k=instance(cfg)
    app=FastMCP('qq-daily-learning',instructions='Read learned expressions and meanings as optional chat reference. Record a completed search only when it filled a real information gap in a current-group message.')
    @app.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def read_group_learning(query:Annotated[str, Field(description='Optional term or phrase; empty returns recent clean learning for the bound group.')]='',limit:Annotated[int, Field(description='Maximum candidates requested; the service bounds the result count.')]=12)->dict:
        """Read clean learned expressions/meanings for this configured group; query may be a term or phrase. No audit materials."""
        return k.read(query,limit)
    @app.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def record_completed_search(message_id:Annotated[str, Field(description='Original current-group message ID or delivered event ID for the completed search.')],gap:Annotated[str, Field(description='The concrete information gap in that original message which this search filled.')],findings:Annotated[str, Field(description='Search findings actually obtained for the original message.')],sources:Annotated[list[str], Field(description='Nonempty list of URLs actually used by the completed search.')])->dict:
        """After search fills a key information gap, record the actual group message id (or event id), findings and source URLs. This saves materials for daily learning, not QQ replies."""
        collector(k,cfg['access_db'])
        with k.db() as d:
            rows=[json.loads(r[0]) for r in d.execute("SELECT body FROM materials WHERE kind='messages'")]
        candidates=[x for x in rows if x['id']==message_id]
        if not candidates:candidates=[x for x in rows if str(x.get('event_id'))==message_id]
        if len(candidates)!=1:raise ValueError('message_not_in_current_group')
        if not gap.strip() or not findings.strip() or not sources:raise ValueError('search_completion_required')
        return k.record_search(candidates[0]['id'],gap,findings,sources)
    app.run(transport='stdio')
if __name__=='__main__':main()

