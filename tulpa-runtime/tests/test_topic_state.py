import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from topic_state import TopicState, Limits


def message(i, at, text='hello', sender='a', **kw):
    return dict(id=str(i), at=at, text=text, sender=sender, **kw)


class TopicStateTests(unittest.TestCase):
    def test_capacity_pending_survives_until_assignment_or_window_expiry(self):
        state=TopicState(max_topics=1,group_limits=Limits(10,60,1000))
        state.receive(dict(id='a',at=0,sender='a',text='first'))
        first=state.create_topic('first',0)['id']
        state.assign('a',first,should_reply=False,direct=True,now=0)
        state.receive(dict(id='b',at=1,sender='b',text='next'))
        state.defer_assignment('b',dict(addressee='bot',intent='question'),1)
        self.assertEqual([x['message']['id'] for x in state.view(2)['pending_assignments']],['b'])
        state.complete_reply('Ra',3,outcome='simulated_complete')
        state.retire_topic(first,3,reason='completed')
        second=state.create_topic('next',3)['id']
        state.assign('b',second,should_reply=False,direct=True,now=3)
        self.assertEqual(state.view(3)['pending_assignments'],[])
        state.receive(dict(id='c',at=4,sender='c',text='expire'))
        state.defer_assignment('c',dict(addressee='bot',intent='question'),4)
        self.assertEqual(state.view(65)['pending_assignments'],[])
        self.assertTrue(any(x['event']=='pending_expired' and x['message_id']=='c' for x in state.view(65)['maintenance']))

    def test_probability_boundaries_own_messages_and_real_mentions(self):
        for key in ('mention_reply_probability','context_reply_probability','participation_probability'):
            for value in (-0.01,1.01,float('nan')):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):TopicState(**{key:value})
        for key,segments,direct in [('mention_reply_probability',[{'type':'at','qq':'1000000011'}],False),
                                    ('context_reply_probability',[],True),('participation_probability',[],False)]:
            for probability,draw,action in [(0,0,'observe'),(1,1,'reply'),(.5,.499,'reply'),(.5,.5,'observe')]:
                with self.subTest(key=key,probability=probability,draw=draw):
                    s=TopicState(**{key:probability});t=s.create_topic('t',0)['id']
                    s.receive(message(1,0,segments=segments))
                    self.assertEqual(s.assign('1',t,should_reply=True,direct=direct,now=0,draw=draw)['action'],action)
        s=TopicState();t=s.create_topic('t',0)['id']
        s.receive(message(1,0,is_self=True,segments=[{'type':'at','qq':'1000000011'}]))
        self.assertEqual(s.assign('1',t,should_reply=True,direct=True,now=0,draw=0)['action'],'observe')

    def test_reply_sources_have_independent_probabilities_and_one_draw(self):
        s=TopicState(mention_reply_probability=0, context_reply_probability=1,
                     participation_probability=0.25)
        t=s.create_topic('question',0)['id']
        cases=[('1',True,True,[{'type':'at','qq':'1000000011'}],0,'mention','observe'),
               ('2',True,True,[],1,'context','reply'),
               ('3',True,False,[],0.25,'participation','observe'),
               ('4',True,False,[],0.24,'participation','reply'),
               ('5',False,False,[{'type':'at','qq':'someone_else'}],0,'none','observe')]
        for i,should,direct,segments,draw,source,action in cases:
            s.receive(message(i,0,segments=segments))
            d=s.assign(i,t,should_reply=should,direct=direct,now=0,draw=draw)
            self.assertEqual((d['response_source'],d['action']),(source,action))
        self.assertEqual([q['message_id'] for q in s.view(0)['queue']],['2','4'])
        self.assertEqual(s.assign('3',t,should_reply=True,direct=False,now=0,draw=0)['action'],'observe')

    def test_truncated_text_is_not_reintroduced_through_raw_segments(self):
        s=TopicState(message_chars=3)
        s.receive(message(1,0,'abcdef',segments=[{'type':'text','text':'abcdef'},{'type':'at','qq':'bot'}]))
        m=s.view(0)['messages'][0]
        self.assertEqual(m['text'],'abc')
        self.assertNotIn('abcdef',str(m))
        self.assertEqual(m['segments'],[{'type':'at','qq':'bot'}])

    def test_revised_reply_can_return_to_queue_after_main_refresh(self):
        s=TopicState();t=s.create_topic('t',0)['id']
        s.receive(message(1,0));s.assign('1',t,should_reply=True,direct=True,now=0)
        s.refresh_reply('R1',50,unchanged=False)
        self.assertEqual(s.check_reply('R1',50)['state'],'needs_revision')
        s.refresh_reply('R1',51,unchanged=True)
        self.assertEqual(s.check_reply('R1',51)['state'],'ready')

    def test_record_evictions_are_visible_in_maintenance_results(self):
        s=TopicState(group_limits=Limits(1,60,20),topic_limits=Limits(1,60,20))
        t=s.create_topic('topic',0)['id']
        for i in (1,2):
            s.receive(message(i,i));s.assign(str(i),t,should_reply=False,direct=False,now=i)
        evictions=[e for e in s.view(2)['maintenance'] if e['event']=='records_evicted']
        self.assertEqual([(e['scope'],e['message_ids']) for e in evictions],[('group',['1']),(t,['1'])])

    def test_completed_reply_releases_idle_topic_and_completion_is_terminal(self):
        s=TopicState();t=s.create_topic('question',0)['id']
        s.receive(message('1',0));s.assign('1',t,should_reply=True,direct=True,now=0)
        s.complete_reply('R1',10,outcome='historical_confirmed')
        s.retire_topic(t,600,reason='idle')
        self.assertEqual(s.view(600)['topics'],[])
        self.assertEqual(s.check_reply('R1',600)['state'],'historical_confirmed')
        with self.assertRaises(ValueError):s.refresh_reply('R1',601,unchanged=True)

    def test_snapshot_grace_is_topic_local_and_cancel_is_immediate(self):
        s = TopicState()
        a=s.create_topic('weather',0)['id']; b=s.create_topic('game',0)['id']
        s.receive(message(1,0));s.assign('1',a,should_reply=True,direct=True,now=0)
        s.receive(message(2,1));s.assign('2',b,should_reply=True,direct=True,now=1)
        self.assertEqual(s.check_reply('R1',100)['state'],'ready')
        s.receive(message(3,101));s.assign('3',a,should_reply=False,direct=False,now=101)
        self.assertEqual(s.check_reply('R1',101)['state'],'needs_refresh')
        s.refresh_reply('R1',101, unchanged=True)
        s.receive(message(4,102));s.assign('4',a,should_reply=False,direct=False,now=102)
        self.assertEqual(s.check_reply('R1',146)['state'],'ready')
        self.assertEqual(s.check_reply('R1',146.001)['state'],'needs_refresh')
        s.cancel_target('1',147,reason='recalled')
        self.assertEqual(s.check_reply('R1',147)['state'],'cancelled')
        self.assertEqual(s.check_reply('R2',147)['state'],'ready')

    def test_assignment_bounded_topic_records_and_independent_reply_queue(self):
        s = TopicState(topic_limits=Limits(2, 10, 8), participation_probability=0.5)
        a = s.create_topic('weather', 0)['id']
        b = s.create_topic('game', 0)['id']
        for i, t in [(1, a), (2, b), (3, a)]:
            s.receive(message(i, i, 'abcd', sender='same'))
            s.assign(str(i), t, should_reply=True, direct=True, now=i)
        self.assertEqual([q['topic_id'] for q in s.view(3)['queue']], [a,b,a])
        s.receive(message(4,4,'wxyz'))
        s.assign('4', a, should_reply=True, direct=False, now=4, draw=0.8)
        self.assertEqual([m['id'] for m in s.view(4)['topics'][0]['messages']], ['3','4'])
        self.assertEqual(len(s.view(4)['queue']), 3)
        self.assertEqual(s.assign('4', a, should_reply=True, direct=False, now=4, draw=0.1)['action'], 'observe')
        self.assertEqual(s.expired_topics(603), [b])
        with self.assertRaises(ValueError):
            s.retire_topic(a, 604, reason='idle')
        s.retire_topic(a, 604, reason='idle', pending_disposition='cancel')
        self.assertEqual([q['status'] for q in s.view(604)['queue']], ['cancelled','queued','cancelled'])

    def test_main_owns_five_topic_lifecycle_and_maintainer_release(self):
        s = TopicState()
        with self.assertRaises(PermissionError):
            s.create_topic('x', 0, actor='maintainer')
        ids = [s.create_topic(str(i), 0)['id'] for i in range(5)]
        with self.assertRaises(ValueError):
            s.create_topic('sixth', 1)
        self.assertEqual(s.expired_topics(599), [])
        self.assertEqual(s.expired_topics(600), ids)
        s.retire_topic(ids[0], 600, reason='idle')
        t = s.create_topic('replacement', 600)
        self.assertNotIn(t['maintainer_id'], [x['maintainer_id'] for x in s.view(0)['topics'] if x['id'] != t['id']])
        self.assertEqual(s.view(600)['maintenance'][5]['event'], 'maintainer_released')
        self.assertEqual(len(s.view(600)['topics']), 5)

    def test_group_window_applies_count_age_and_character_limits(self):
        s = TopicState(group_limits=Limits(2, 10, 8), message_chars=5)
        s.receive(message(1, 0, 'abcdef'))
        s.receive(message(2, 1, 'xyz'))
        self.assertEqual([m['text'] for m in s.view(1)['messages']], ['abcde', 'xyz'])
        s.receive(message(3, 2, '12345'))
        self.assertEqual([m['id'] for m in s.view(2)['messages']], ['2', '3'])
        self.assertEqual(s.view(12)['messages'][0]['id'], '3')
        self.assertEqual(s.view(13)['messages'], [])


if __name__ == '__main__':
    unittest.main()
