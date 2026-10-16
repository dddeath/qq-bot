import json,sqlite3,tempfile,unittest
from pathlib import Path
from sessions import Sessions
from control_plane import ControlPlane
from bot_gallery import resolve_gallery

class BotGalleryTests(unittest.TestCase):
 def test_bot_update_is_shared_by_new_groups_but_not_other_accounts(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'control.db') as sessions:
   plane=ControlPlane(sessions)
   body={'account_id':'123','bindings':{},'gallery':{'directory':tmp,'items':[{'file':'hello.png'}],'generated_directory':tmp+'/generated'}}
   bot=plane.put('bot','dragon',body)
   pointer={'bot_gallery':{'database':str(Path(tmp)/'control.db'),'bot_id':'dragon'}}
   self.assertEqual(resolve_gallery(pointer,'123:group:456'),body['gallery'])
   self.assertEqual(resolve_gallery(pointer,'123:group:999'),body['gallery'])
   self.assertIsNone(resolve_gallery(pointer,'321:group:999'))
   body['gallery']['items'].append({'file':'new.png'})
   plane.put('bot','dragon',body,expected_version=bot['version'])
   self.assertEqual(len(resolve_gallery(pointer,'123:group:777')['items']),2)
 def test_missing_bot_never_falls_back_to_legacy_other_bot_gallery(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'control.db') as sessions:
   ControlPlane(sessions)
   config={'bot_gallery':{'database':str(Path(tmp)/'control.db'),'bot_id':'absent'},'conversation_ids':['123:group:456'],'directory':tmp}
   self.assertIsNone(resolve_gallery(config,'123:group:456'))
 def test_legacy_scope_is_preserved(self):
  config={'conversation_ids':['123:group:456'],'directory':'/images','items':[]}
  self.assertEqual(resolve_gallery(config,'123:group:456'),config)
  self.assertIsNone(resolve_gallery(config,'123:group:999'))

if __name__=='__main__':unittest.main()
