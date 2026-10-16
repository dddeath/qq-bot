"""Background state is used only to relax native stale checks."""
import tempfile,unittest
from topic_freshness import FreshnessTopics


class FreshnessTests(unittest.TestCase):
    def test_same_topic_grace_other_topic_and_unknown_after_grace(self):
        with tempfile.TemporaryDirectory() as root:
            decisions=iter([{'topic_id':'new'},{'topic_id':'new'},{'topic_id':'F1'}])
            state=FreshnessTopics(root,'g',lambda _:next(decisions))
            def event(i,text,at):
                return dict(id=i,conversation_id='g',content=text,received_at=at,sender_id='u')
            state.ingest(event(1,'ice floats',100),100)
            state.ingest(event(2,'python tuple',102),102)
            state.ingest(event(3,'explain density',103),103)
            self.assertTrue(state.allow(1,[3],100,145))
            self.assertFalse(state.allow(1,[3],100,146))
            self.assertTrue(state.allow(1,[2],100,146))
            self.assertFalse(state.allow(1,[999],100,146))
            self.assertTrue(state.allow(1,[999],100,120))
            # A native reread establishes a new snapshot; no topic tools needed.
            self.assertTrue(state.allow(1,[3],146,150))

    def test_ambiguous_message_does_not_become_evidence_of_unrelated_topic(self):
        with tempfile.TemporaryDirectory() as root:
            state=FreshnessTopics(root,'g',lambda _:dict(topic_id=None))
            for i in (1,2):
                state.ingest(dict(id=i,conversation_id='g',content='[image]',received_at=100+i,sender_id='u'),100+i)
            self.assertFalse(state.allow(1,[2],100,146))
