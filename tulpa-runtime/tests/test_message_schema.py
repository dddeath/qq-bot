import unittest
from chatlocal.agent_tools import tool
from chatlocal.mcp_chat_turns import schema
from chatlocal.mcp_tools import argument_problems

class MessageSchemaTests(unittest.TestCase):
    def test_text_cannot_carry_reaction_event_id(self):
        spec=next(s['parameters'] for s in schema(tool) if s['name']=='send_chat_reply')
        args={'session_id':'a'*32,'plan_id':'b'*32,'bubbles':[{'kind':'text','text':'hello','event_id':5}]}
        self.assertTrue(argument_problems(args,spec), 'MCP accepts event_id on text but dispatcher rejects it')

    def test_each_type_accepts_its_own_fields(self):
        spec=next(s['parameters'] for s in schema(tool) if s['name']=='send_chat_reply')
        for bubble in [{'kind':'text','text':'hello','quote':False}, {'kind':'sticker','sticker_id':'c'*32}, {'kind':'reaction','event_id':5,'reaction_id':'qq_like','operation':'add'}]:
            with self.subTest(kind=bubble['kind']):self.assertEqual(argument_problems({'session_id':'a'*32,'plan_id':'b'*32,'bubbles':[bubble]},spec),[])
    def test_missing_and_cross_type_fields_rejected(self):
        spec=next(s['parameters'] for s in schema(tool) if s['name']=='send_chat_reply')
        for bubble in [{'kind':'text'}, {'kind':'sticker','sticker_id':'c'*32,'text':'hello'}, {'kind':'reaction','event_id':5}, {'kind':'text','text':'hello','sticker_id':'c'*32}]:
            with self.subTest(bubble=bubble):self.assertTrue(argument_problems({'session_id':'a'*32,'plan_id':'b'*32,'bubbles':[bubble]},spec))
if __name__=='__main__':unittest.main()

