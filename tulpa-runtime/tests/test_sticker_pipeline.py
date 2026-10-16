"""Offline image-read, reusable-candidate and catalogue-search boundaries."""
import json
from types import SimpleNamespace
from test_community_media import MediaTests


class StickerPipelineTests(MediaTests):
    def setUp(self):
        super().setUp()
        self.media.chat.turns = SimpleNamespace(before_dispatch=lambda: None)
        with self.connect() as db:
            db.execute('CREATE TABLE calls(grant_id TEXT, tool TEXT, at REAL)')

    def test_viewed_admin_description_becomes_reusable_candidate(self):
        listed, _ = self.call('list_chat_stickers', source='community', query='招呼')
        sticker = listed['items'][0]['sticker_id']
        before, _ = self.media.candidates(self.grant, self.row, [])
        self.assertEqual(before, [])
        self.call('read_chat_sticker', sticker_id=sticker)
        after, _ = self.media.candidates(self.grant, self.row, [{'content': '招呼'}])
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]['model_note'], '挥手招呼')
        self.assertTrue(after[0]['sendable'])

    def test_synonym_search_works_before_and_after_understanding(self):
        config = self.root / 'mcp-community.json'
        data = json.loads(config.read_text())
        data['items'][0].update(description='自嘲糗照', tags=['糗照', '自嘲'])
        config.write_text(json.dumps(data))
        listed, _ = self.call('list_chat_stickers', source='community', query='黑历史')
        self.assertEqual(listed['matched'], 1)
        self.assertFalse(listed['items'][0]['sendable'])
        self.call('read_chat_sticker', sticker_id=listed['items'][0]['sticker_id'])
        known, _ = self.call('list_chat_stickers', source='library', query='黑历史')
        self.assertEqual(known['matched'], 1)
        self.assertTrue(known['items'][0]['sendable'])

    def test_model_understanding_survives_reread_and_new_session(self):
        listed, _ = self.call('list_chat_stickers', source='community')
        sid = listed['items'][0]['sticker_id']
        self.call('read_chat_sticker', sticker_id=sid)
        self.call('note_chat_sticker', sticker_id=sid, description='挥手告别', tags=['告别'])
        self.call('read_chat_sticker', sticker_id=sid)
        self.sid = 'b' * 32
        self.row = dict(self.row, id=self.sid)
        with self.connect() as db:
            db.execute('INSERT INTO chat_sessions VALUES(?,1)', (self.sid,))
        candidates, _ = self.media.candidates(self.grant, self.row, [])
        self.assertEqual(candidates[0]['model_note'], '挥手告别')

    def test_uncertain_understanding_is_not_promoted_by_reread(self):
        listed, _ = self.call('list_chat_stickers', source='community')
        sid = listed['items'][0]['sticker_id']
        self.call('read_chat_sticker', sticker_id=sid)
        self.call('note_chat_sticker', sticker_id=sid, description='看不清动作', uncertainty='需确认')
        self.call('read_chat_sticker', sticker_id=sid)
        candidates, _ = self.media.candidates(self.grant, self.row, [])
        self.assertEqual(candidates, [])

    def test_unknown_catalogue_image_still_requires_view(self):
        listed, _ = self.call('list_chat_stickers', source='community')
        with self.assertRaises(ValueError):
            self.call('note_chat_sticker', sticker_id=listed['items'][0]['sticker_id'], description='猜测')
        self.assertEqual(self.media.candidates(self.grant, self.row, [])[0], [])

    def test_new_image_without_description_requests_understanding(self):
        config = self.root / 'mcp-community.json'
        data = json.loads(config.read_text())
        data['items'][0]['description'] = ''
        config.write_text(json.dumps(data))
        listed, _ = self.call('list_chat_stickers', source='community')
        info, _ = self.call('read_chat_sticker', sticker_id=listed['items'][0]['sticker_id'])
        self.assertFalse(info['reusable'])
        self.assertEqual(info['understanding_next_call']['tool'], 'note_chat_sticker')

    def test_search_scopes_and_multiple_concepts(self):
        self.assertEqual(self.call('list_chat_stickers', source='community', query='挥手 开心')[0]['matched'], 0)
        self.assertEqual(self.call('list_chat_stickers', source='community', query='不存在的词')[0]['matched'], 0)
        self.row = dict(self.row, conversation_id='123:group:999')
        self.assertEqual(self.call('list_chat_stickers', source='community', query='招呼')[0]['matched'], 0)


if __name__ == '__main__':
    import unittest
    unittest.main()
