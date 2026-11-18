"""Versioned report references attached to host-delivered results and reply plans."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3


def capture_read_receipt(row, pending, receipts):
    """Use native MCP results, never assistant prose or quoted report material."""
    p = row.get('payload', {})
    kind, call = p.get('type'), p.get('call_id')
    if row.get('type') == 'response_item' and kind == 'function_call' and call:
        name = p.get('name', '')
        if name.startswith('mcp__'):
            pending[call] = name.rsplit('__', 1)[-1]
        return
    if row.get('type') == 'response_item' and kind == 'function_call_output' and call in pending:
        tool, result = pending.pop(call), p.get('output')
    elif row.get('type') == 'event_msg' and kind == 'mcp_tool_call_end':
        if not isinstance(p.get('invocation'),dict) or not isinstance(p.get('result'),dict) or 'Ok' not in p['result']:return
        tool = p['invocation'].get('tool')
        result = p['result']['Ok']
    else:
        return
    from reading_tools import ALLOWED
    if tool not in ALLOWED:return
    if isinstance(result, str):
        try:result = json.loads(result)
        except ValueError:result = None
    if isinstance(result, dict) and result.get('isError'):return
    if isinstance(result, dict):
        receipt = (result.get('structuredContent') or {}).get('knowledge_application') if isinstance(result.get('structuredContent'),dict) else None
        blocks = result.get('content', [])
    else:
        receipt, blocks = None, result
    if not receipt and isinstance(blocks, list) and blocks and isinstance(blocks[-1],dict):
        try:envelope = json.loads(blocks[-1].get('text',''))
        except (ValueError,TypeError):envelope = None
        if isinstance(envelope,dict):receipt = envelope.get('knowledge_application')
    if isinstance(receipt,dict) and receipt.get('status')=='ok' and isinstance(receipt.get('read_id'),str) and receipt['read_id']==receipt.get('call_id'):
        receipts.add((tool,receipt['read_id']))
    else:
        # An unattributed result alongside a known one is not a single-source report.
        receipts.add((tool,''))


class ReportLinks:
    def __init__(self, path, conversation):
        self.path, self.conversation = str(path), conversation
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (conversation TEXT, id TEXT, version TEXT, body TEXT, PRIMARY KEY(conversation,id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS plans (conversation TEXT, id TEXT, refs TEXT, PRIMARY KEY(conversation,id))')
            db.execute('CREATE TABLE IF NOT EXISTS report_pages (conversation TEXT,id TEXT,version TEXT,offset INTEGER,next_offset INTEGER,PRIMARY KEY(conversation,id,version,offset))')
            db.execute('CREATE TABLE IF NOT EXISTS report_sources (conversation TEXT,id TEXT,version TEXT,task TEXT,query TEXT,PRIMARY KEY(conversation,id,version))')

    def register(self, event, application=None):
        result = deepcopy(event)
        body = result.get('payload', result)
        if body.get('event') != 'background_results':
            return result
        with closing(sqlite3.connect(self.path)) as db, db:
            for item in body.get('results', []):
                receipts = item.pop('_report_read_receipts', [])
                data = item.get('result') or {}
                agent, turn, text = item.get('agent_id'), data.get('turn_id'), data.get('last_agent_message')
                if not agent or not turn or not isinstance(text, str) or not text:
                    continue
                ref = dict(report_id=agent+':'+turn, version=hashlib.sha256(text.encode()).hexdigest())
                source = application.report_source_query(receipts) if application and receipts else None
                item.pop('source_query',None)
                db.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?,?)',
                           (self.conversation, ref['report_id'], ref['version'], json.dumps(item, ensure_ascii=False)))
                key=(self.conversation,ref['report_id'],ref['version'])
                if source:
                    db.execute('INSERT OR IGNORE INTO report_sources VALUES (?,?,?,?,?)',(*key,source['task_id'],source['query_id']))
                stored=db.execute('SELECT task,query FROM report_sources WHERE conversation=? AND id=? AND version=?',key).fetchone()
                if stored:item['source_query']=dict(zip(('task_id','query_id'),stored))
                item['report_ref'] = ref
                page = self._page(text, ref, 0)
                data['last_agent_message'] = page['text']
                item['report_page'] = {k:v for k,v in page.items() if k != 'text'}
                db.execute('INSERT OR IGNORE INTO report_pages VALUES (?,?,?,?,?)',
                    (self.conversation, ref['report_id'], ref['version'], 0, (page['next'] or {}).get('offset')))
        return result

    @staticmethod
    def _page(text, ref, offset):
        if type(offset) is not int or not 0 <= offset <= len(text):
            raise ValueError('invalid_report_offset')
        # Same UTF-8 bytes / 2 estimate as knowledge disclosure; preserve Unicode.
        fragment = text[offset:].encode('utf-8')[:1600].decode('utf-8', errors='ignore')
        end = offset + len(fragment)
        return dict(report_ref=ref, text=fragment, offset=offset,
                    estimated_tokens=(len(fragment.encode('utf-8'))+1)//2,
                    complete=end == len(text),
                    next={**ref, 'offset':end} if end < len(text) else None)

    def read(self, report_id, version, offset=0):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT body FROM reports WHERE conversation=? AND id=? AND version=?',
                             (self.conversation, report_id, version)).fetchone()
        if not row:
            raise ValueError('unknown_report_reference')
        text = json.loads(row[0])['result']['last_agent_message']
        return self._page(text, dict(report_id=report_id, version=version), offset)

    def page_access(self, args):
        if not isinstance(args,dict) or set(args)-{'report_id','version','offset','_reading','_knowledge'}:
            raise ValueError('invalid_report_arguments')
        if not all(isinstance(args.get(k),str) and args[k] for k in ('report_id','version')):
            raise ValueError('invalid_report_reference')
        key=(self.conversation,args.get('report_id'),args.get('version'))
        offset=args.get('offset',0)
        if type(offset) is not int or offset<0:raise ValueError('invalid_report_offset')
        with closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT 1 FROM reports WHERE conversation=? AND id=? AND version=?',key).fetchone()
            if not row:raise ValueError('unknown_report_reference')
            binding=db.execute('SELECT task,query FROM report_sources WHERE conversation=? AND id=? AND version=?',key).fetchone()
            source=dict(zip(('task_id','query_id'),binding)) if binding else None
            pages=dict(db.execute('SELECT offset,next_offset FROM report_pages WHERE conversation=? AND id=? AND version=?',key))
        reuse=offset==0 or offset in pages
        supplied=args.get('_reading')
        if supplied is not None and (not isinstance(supplied,dict) or not source or
                any(supplied.get(k)!=source[k] for k in ('task_id','query_id'))):raise ValueError('report_query_mismatch')
        if '_knowledge' in args and (not source or args['_knowledge']!={'decision_ids':[source['task_id']]}):raise ValueError('report_query_mismatch')
        if not reuse:
            if not source:raise ValueError('report_source_query_unverified: use the delivered preview')
            if not supplied:raise ValueError('report_query_required: use source_query in _reading')
            if offset not in pages.values():raise ValueError('report_page_not_advertised: follow next')
        return source, reuse

    def remember_page(self, page):
        ref=page['report_ref']
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR IGNORE INTO report_pages VALUES (?,?,?,?,?)',(self.conversation,
                ref['report_id'],ref['version'],page['offset'],(page['next'] or {}).get('offset')))

    def query_page(self, application, request_id, args):
        """Route a new page like other task reads; replay delivered pages without a new task read."""
        import time
        from pathlib import Path
        from knowledge_decision import query_task
        from knowledge_turn_budget import TurnBudget
        from research_trace import ResearchTrace
        tool='read_research_report'; token=None; started=time.monotonic()
        envelope=lambda body:dict(jsonrpc='2.0',id=request_id,result={
            'structuredContent':body,'content':[{'type':'text','text':json.dumps(body,ensure_ascii=False)}]})
        try:
            if application.context['conversation_id']!=self.conversation:raise ValueError('report_conversation_mismatch')
            source,reuse=self.page_access(args)
            working=dict(args)
            if source and reuse and '_reading' not in working:working['_reading']=dict(source)
            token,forward=application.prepare(tool,working)
            plain={k:v for k,v in forward.items() if k!='_reading'}
            if reuse:
                body=self.read(**plain);result=envelope({'material':body,'reused_page':True})
                budget=TurnBudget(application.context['budget_path'])
                return budget.deliver(budget.current(),tool,forward,result,time.monotonic()-started,
                    projector=lambda value:application.complete(token,value,time.monotonic()-started),application_call_id=token)
            task=query_task(application,source['task_id'])
            folder=Path(task['task_report']).parent
            ctx=json.loads((folder/'context.json').read_text(encoding='utf-8'))
            scope=ctx['audit_scope']
            if str(scope.get('account_id'))+':group:'+str(scope.get('group_id'))!=self.conversation:
                raise ValueError('reading_scope_mismatch')
            trace=ResearchTrace(dict(root=str(folder.parent),scope=scope)).bind_application(application)
            try:path,plain=trace.prepare(tool,forward)
            except ValueError as exc:
                trace.reject(tool,forward,exc)
                raise
            try:body=self.read(**plain)
            except (ValueError, TypeError) as exc:
                trace.complete(path,{'error':{'message':str(exc)}},time.monotonic()-started)
                raise
            result=trace.complete_and_deliver(path,envelope(body),time.monotonic()-started)
            result=application.complete(token,result,time.monotonic()-started,trace.evidence_reference(path))
            trace.record_delivery(path,result)
            if not result['result'].get('isError') and result['result']['structuredContent'].get('material') is not None:
                self.remember_page(body)
            return result
        except (TypeError,ValueError) as exc:
            error={'jsonrpc':'2.0','id':request_id,'result':{'isError':True,'content':[{'type':'text','text':str(exc)}]}}
            return application.complete(token,error,time.monotonic()-started) if token else error

    def prepare(self, arguments):
        clean = deepcopy(arguments)
        refs = clean.pop('research_reports', [])
        if not isinstance(refs, list):
            raise ValueError('invalid_report_references')
        unique = []
        with closing(sqlite3.connect(self.path)) as db:
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {'report_id', 'version'}:
                    raise ValueError('invalid_report_reference')
                if not db.execute('SELECT 1 FROM reports WHERE conversation=? AND id=? AND version=?',
                                  (self.conversation, ref['report_id'], ref['version'])).fetchone():
                    raise ValueError('unknown_report_reference')
                if ref not in unique:
                    unique.append(ref)
        return clean, unique

    def plan(self, body, refs):
        plan = body.get('plan_id')
        if not plan:
            return
        with closing(sqlite3.connect(self.path)) as db, db:
            # A plan's provenance stays fixed even when the caller retries planning.
            db.execute('INSERT OR IGNORE INTO plans VALUES (?,?,?)',
                       (self.conversation, plan, json.dumps(refs, ensure_ascii=False)))

    def association(self, plan):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT refs FROM plans WHERE conversation=? AND id=?',
                             (self.conversation, plan)).fetchone()
        return dict(plan_id=plan, conversation_id=self.conversation,
                    reports=json.loads(row[0]) if row else [],
                    basis='model_selected_reports' if row else 'plan_reference_missing')

    def schemas(self, tools):
        tools = deepcopy(tools)
        for tool in tools:
            if tool['name'] == 'plan_chat_reply':
                tool['inputSchema'].setdefault('properties', {})['research_reports'] = {
                    'type': 'array', 'items': {'type': 'object', 'properties': {
                        'report_id': {'type': 'string', 'description': 'report_ref.report_id from a delivered background result.'}, 'version': {'type': 'string', 'description': 'Exact report_ref.version content hash from the delivered background result.'}},
                        'required': ['report_id', 'version'], 'additionalProperties': False}}
                tool['description'] = tool.get('description', '') + ' 回答检索结果时，在 research_reports 中填写本次实际采用的后台结果 report_ref；普通聊天可省略。'
        tools.append({'name':'read_research_report',
            'description':'按 report_page.next 展开当前会话的后台报告，每次最多800估算token；保留report_ref用于回复关联。offset为字符位置，使用返回的next参数继续。',
            'inputSchema':{'type':'object','properties':{'report_id':{'type':'string', 'description': 'report_ref.report_id from a delivered background result.'},
                'version':{'type':'string', 'description': 'Exact report_ref.version content hash from the delivered background result.'},'offset':{'type':'integer','minimum':0,'default':0, 'description': 'Zero-based character offset; follow the returned continuation.'}},
                'required':['report_id','version'],'additionalProperties':False},
            'annotations':{'readOnlyHint':True}})
        return tools

    def response(self, response, tool, arguments, refs):
        from reading_result import body_of
        result = deepcopy(response)
        body = body_of({'result': result.get('result', {})})
        if not body or result.get('result', {}).get('isError'):
            return result
        if tool == 'plan_chat_reply':
            self.plan(body, refs)
        plan = body.get('plan_id', arguments.get('plan_id'))
        if tool not in ('plan_chat_reply', 'send_chat_reply') or not plan:
            return result
        projected = {**body, 'research_association': self.association(plan)}
        for block in result['result'].get('content', []):
            if block.get('type') == 'text':
                try:
                    if json.loads(block['text']) == body:
                        block['text'] = json.dumps(projected, ensure_ascii=False)
                except (ValueError, KeyError):
                    pass
        result['result']['structuredContent'] = projected
        return result
