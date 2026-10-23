"""Versioned report references attached to host-delivered results and reply plans."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3


class ReportLinks:
    def __init__(self, path, conversation):
        self.path, self.conversation = str(path), conversation
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (conversation TEXT, id TEXT, version TEXT, body TEXT, PRIMARY KEY(conversation,id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS plans (conversation TEXT, id TEXT, refs TEXT, PRIMARY KEY(conversation,id))')

    def register(self, event):
        result = deepcopy(event)
        body = result.get('payload', result)
        if body.get('event') != 'background_results':
            return result
        with closing(sqlite3.connect(self.path)) as db, db:
            for item in body.get('results', []):
                data = item.get('result') or {}
                agent, turn, text = item.get('agent_id'), data.get('turn_id'), data.get('last_agent_message')
                if not agent or not turn or not isinstance(text, str) or not text:
                    continue
                ref = dict(report_id=agent+':'+turn, version=hashlib.sha256(text.encode()).hexdigest())
                db.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?,?)',
                           (self.conversation, ref['report_id'], ref['version'], json.dumps(item, ensure_ascii=False)))
                item['report_ref'] = ref
                page = self._page(text, ref, 0)
                data['last_agent_message'] = page['text']
                item['report_page'] = {k:v for k,v in page.items() if k != 'text'}
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
                        'report_id': {'type': 'string'}, 'version': {'type': 'string'}},
                        'required': ['report_id', 'version'], 'additionalProperties': False}}
                tool['description'] = tool.get('description', '') + ' 回答检索结果时，在 research_reports 中填写本次实际采用的后台结果 report_ref；普通聊天可省略。'
        tools.append({'name':'read_research_report',
            'description':'按 report_page.next 展开当前会话的后台报告，每次最多800估算token；保留report_ref用于回复关联。offset为字符位置，使用返回的next参数继续。',
            'inputSchema':{'type':'object','properties':{'report_id':{'type':'string'},
                'version':{'type':'string'},'offset':{'type':'integer','minimum':0,'default':0}},
                'required':['report_id','version'],'additionalProperties':False},
            'annotations':{'readOnlyHint':True}})
        return tools

    def response(self, response, tool, arguments, refs):
        from research_feedback import body_of
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
