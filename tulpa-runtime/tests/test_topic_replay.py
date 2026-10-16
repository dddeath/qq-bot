import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from topic_replay import replay
from topic_state import TopicState


def model_decision(*, topic_id, should_reply, direct, reason='fixture'):
    return dict(topic_id=topic_id,addressee='bot' if direct else 'group',
                intent='request' if direct else 'chat',reply_to_message_id=None,
                should_interject=should_reply,reason=reason)


class ReplayTests(unittest.TestCase):
    def test_missing_real_quote_keeps_current_direct_request(self):
        message=dict(id='1',at=0,text='还有一张呢',sender='owner',
                     segments=[dict(type='reply',onebot_message_id='outside')])
        def decide(r):
            return dict(topic_id=None,addressee='bot',intent='followup',reply_to_message_id='outside',
                        should_interject=False,reason='current request is clear')
        with tempfile.TemporaryDirectory() as d:
            run=replay([message],decide,lambda r:dict(action='create',title='图片',retire_topic_id=None),Path(d))
            result=json.loads((run/'results.json').read_text())
            self.assertEqual(result['errors'],0)
            self.assertEqual(result['messages'][0]['decision']['action'],'reply')
            self.assertEqual(result['messages'][0]['reference_status'],'missing_content')

    def test_member_identity_reaches_decision_without_changing_response_policy(self):
        seen=[]
        def decide(r):
            seen.append(r)
            return model_decision(topic_id='T001' if r['topics'] else None,should_reply=False,direct=True)
        profiles={'account:group:g':{'1000000010':dict(participant_type='ai',source='owner_confirmed',private_note='omit'),
                                     'unseen':dict(participant_type='ai',source='owner_confirmed')},
                  'other:group:g':{'person':dict(participant_type='ai',source='owner_confirmed')}}
        messages=[dict(id='1',at=0,text='question',sender='1000000010',group='account:group:g'),
                  dict(id='2',at=1,text='question',sender='person',group='account:group:g')]
        with tempfile.TemporaryDirectory() as d:
            run=replay(messages,decide,lambda r:dict(action='create',title='question',retire_topic_id=None),
                       Path(d),member_profiles=profiles)
            result=json.loads((run/'results.json').read_text())
            self.assertEqual(result['errors'],0)
            self.assertEqual(seen[1]['participant_profiles'],{'1000000010':{'participant_type':'ai','source':'owner_confirmed'}})
            self.assertEqual([r['participant_type'] for r in result['messages']],['ai','unknown'])
            self.assertEqual([r['decision']['action'] for r in result['messages']],['reply','reply'])
            self.assertEqual([r['decision']['probability'] for r in result['messages']],[1,1])

    def test_member_markdown_is_loaded_for_current_group_and_reported_separately(self):
        from topic_dialogue import load_member_profiles
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);member=root/'account'/'g'/'members'/'1000000010.md'
            member.parent.mkdir(parents=True)
            member.write_text('---\nqq_number: "1000000010"\nparticipant_type: ai\nsource: owner_confirmed\n---\n# Member\n',encoding='utf-8')
            profiles=load_member_profiles(root)
            run=replay([dict(id='1',at=0,text='question',sender='1000000010',group='account:group:g'),
                        dict(id='2',at=1,text='question',sender='person',group='account:group:g')],
                       lambda r:model_decision(topic_id='T001' if r['topics'] else None,should_reply=False,direct=True),
                       lambda r:dict(action='create',title='question',retire_topic_id=None),root/'runs',member_profiles=profiles)
            result=json.loads((run/'results.json').read_text())
            self.assertEqual(result['participant_types']['ai'],dict(messages=1,queued=1,errors=0))
            self.assertEqual(result['participant_types']['unknown'],dict(messages=1,queued=1,errors=0))
            text=(run/'report.md').read_text(encoding='utf-8')
            self.assertIn('成员类型',text)
            self.assertIn('另一 AI',text)

    def test_unseen_or_current_reply_anchor_is_reported_without_retry(self):
        for anchor in ('missing','1','future'):
            calls=[]
            def decide(r):
                calls.append(r)
                return dict(topic_id=None,addressee='bot',intent='request',reply_to_message_id=anchor,
                            should_interject=False,reason='invalid anchor')
            with tempfile.TemporaryDirectory() as d:
                run=replay([dict(id='1',at=0,text='request',sender='a')],decide,lambda r:None,Path(d))
                result=json.loads((run/'results.json').read_text())
                self.assertEqual(result['errors'],1)
                self.assertIn('visible past context',result['messages'][0]['error']['message'])
                self.assertEqual(result['final_state']['queue'],[])
                self.assertEqual(len(calls),1)

    def test_dialogue_highlights_actual_quotes_and_sender_exchange_without_future(self):
        seen=[]
        def decide(r):
            seen.append(r)
            return model_decision(topic_id='T001' if r['topics'] else None,should_reply=False,direct=False)
        messages=[dict(id='1',at=0,text='can you change this?',sender='a'),
                  dict(id='2',at=1,text='ask the owner',sender='bot',is_self=True,
                       segments=[dict(type='reply',onebot_message_id='1')]),
                  dict(id='3',at=2,text='you should do it',sender='a',segments=[dict(type='reply',onebot_message_id='2')]),
                  dict(id='4',at=3,text='future',sender='b')]
        with tempfile.TemporaryDirectory() as d:
            replay(messages,decide,lambda r:dict(action='create',title='name',retire_topic_id=None),Path(d))
        context=seen[2]['dialogue_context']
        self.assertEqual([m['id'] for m in context['quoted_messages']],['2'])
        self.assertEqual(context['sender_bot_exchanges'][0]['request']['id'],'1')
        self.assertEqual(context['sender_bot_exchanges'][0]['reply']['id'],'2')
        self.assertEqual(context['recent_bot_by_topic']['T001'][0]['id'],'2')
        self.assertNotIn('future',json.dumps(seen[2]))

    def test_addressed_request_queues_independently_of_interjection(self):
        decisions=[dict(topic_id=None,addressee='bot',intent='request',reply_to_message_id=None,
                        should_interject=False,reason='asks bot to act'),
                   dict(topic_id='T001',addressee='other',intent='question',reply_to_message_id='1',
                        should_interject=False,reason='asks another member')]
        def decide(r):return decisions[int(r['message']['id'])-1]
        with tempfile.TemporaryDirectory() as d:
            run=replay([dict(id='1',at=0,text='please change it',sender='a'),
                        dict(id='2',at=1,text='what do you think?',sender='b')],decide,
                       lambda r:dict(action='create',title='name',retire_topic_id=None),Path(d))
            result=json.loads((run/'results.json').read_text())
            self.assertEqual(result['errors'],0)
            self.assertEqual([r['decision']['action'] for r in result['messages']],['reply','observe'])
            self.assertEqual(result['messages'][0]['decision']['response_source'],'context')
            self.assertEqual(result['messages'][0]['maintainer_result']['intent'],'request')
            text=(run/'report.md').read_text(encoding='utf-8')
            for title in ('发言对象','交流意图','承接消息','判断耗时'):
                self.assertIn(title,text)

    def test_report_exposes_sources_probabilities_and_deferred_candidates(self):
        messages=[dict(id=str(i),at=i,text='question',sender='a',
                       segments=[{'type':'at','qq':'1000000011'}] if i==1 else [],is_self=i==5)
                  for i in range(1,7)]
        def decide(r):
            i=int(r['message']['id'])
            return model_decision(topic_id=r['topics'][0]['id'] if r['topics'] and i!=6 else None,
                        should_reply=i in (2,3,5,6),direct=i in (2,5,6))
        def main(r):return dict(action='defer' if r['message']['id']=='6' else 'create',title='能力',retire_topic_id=None)
        with tempfile.TemporaryDirectory() as d:
            run=replay(messages,decide,main,Path(d),state=TopicState(participation_probability=0))
            result=json.loads((run/'results.json').read_text(encoding='utf-8'))
            self.assertEqual(result['response_sources']['mention'],{'messages':1,'queued':1,'deferred':0})
            self.assertEqual(result['response_sources']['context'],{'messages':2,'queued':1,'deferred':1})
            self.assertEqual(result['response_sources']['participation'],{'messages':1,'queued':0,'deferred':0})
            self.assertEqual([r['decision']['response_source'] for r in result['messages']],
                             ['mention','context','participation','none','self','context'])
            self.assertEqual([q['message_id'] for q in result['final_state']['queue']],['1','2'])
            config=json.loads((run/'config.json').read_text())
            self.assertEqual((config['mention_reply_probability'],config['context_reply_probability']),(1,1))
            text=(run/'report.md').read_text(encoding='utf-8')
            self.assertIn('回应来源',text);self.assertIn('采用概率',text)

    def test_idle_timer_fires_at_deadline_between_sparse_messages(self):
        def main(r):return dict(action='create',title='闲聊',retire_topic_id=None)
        def decide(r):return model_decision(topic_id=None,should_reply=False,direct=False)
        with tempfile.TemporaryDirectory() as d:
            run=replay([dict(id='1',at=0,text='A',sender='a'),dict(id='2',at=1000,text='B',sender='b')],decide,main,Path(d))
            result=json.loads((run/'results.json').read_text(encoding='utf-8'))
            self.assertEqual([m['at'] for m in result['final_state']['maintenance'] if m['event']=='maintainer_released'],[600,1600])

    def test_historical_receipt_closes_only_its_original_target_at_receipt_time(self):
        def decide(r):return model_decision(topic_id=r['topics'][0]['id'] if r['topics'] else None,should_reply=True,direct=True)
        def main(r):return dict(action='create',title='问题',retire_topic_id=None)
        messages=[dict(id='1',at=0,text='问题',sender='a'),dict(id='2',at=20,text='历史回答',sender='bot',is_self=True,historical_reply_to='1')]
        with tempfile.TemporaryDirectory() as d:
            run=replay(messages,decide,main,Path(d))
            result=json.loads((run/'results.json').read_text(encoding='utf-8'))
            self.assertEqual(result['final_state']['queue'][0]['status'],'historical_confirmed')
            self.assertEqual(result['final_state']['topics'],[])
            self.assertEqual(result['messages'][0]['queue_checks'][0]['state'],'ready')

    def test_invalid_model_topic_is_reported_without_queue_or_fabricated_assignment(self):
        with tempfile.TemporaryDirectory() as d:
            run=replay([dict(id='1',at=0,text='hello',sender='a')],
                lambda r:model_decision(topic_id='invented',should_reply=True,direct=True),
                lambda r:None,Path(d))
            result=json.loads((run/'results.json').read_text())
            self.assertEqual(result['errors'],1)
            self.assertEqual(result['final_state']['queue'],[])
            self.assertIsNone(result['messages'][0]['assignment'])

    def test_controller_idle_recycles_topic_and_records_pending_disposition(self):
        def main(r):return dict(action='create',title=r['message']['text'],retire_topic_id=None)
        def decide(r):return model_decision(topic_id=None,should_reply=False,direct=r['message']['id']=='2')
        with tempfile.TemporaryDirectory() as d:
            run=replay([dict(id='1',at=0,text='观察',sender='a'),dict(id='2',at=600,text='请求',sender='b')],decide,main,Path(d))
            result=json.loads((run/'results.json').read_text(encoding='utf-8'))
            self.assertEqual(result['final_state']['topics'],[])
            self.assertEqual(result['final_state']['queue'][0]['status'],'cancelled')
            self.assertEqual([m['event'] for m in result['final_state']['maintenance']],
                ['maintainer_allocated','maintainer_released','maintainer_allocated','maintainer_released'])
            self.assertEqual(result['final_state']['maintenance'][-1]['cancelled_targets'],['2'])

    def test_replay_uses_only_past_input_and_creates_independent_evidence(self):
        seen=[]
        def maintainer(request):
            seen.append(request)
            return model_decision(topic_id=request['topics'][0]['id'] if request['topics'] else None,
                        should_reply=True, direct=False, reason='same game topic')
        def main(request):
            return dict(action='create',title='game',retire_topic_id=None,reason='new topic')
        messages=[dict(id='1',at=0,text='游戏',sender='a'),dict(id='2',at=20,text='机制',sender='b')]
        with tempfile.TemporaryDirectory() as d:
            a=replay(messages,maintainer,main,Path(d),state=TopicState(participation_probability=1))
            before={p.name:p.read_bytes() for p in a.iterdir() if p.is_file()}
            b=replay(messages,maintainer,main,Path(d),state=TopicState(participation_probability=1))
            self.assertNotEqual(a,b)
            self.assertEqual(before,{p.name:p.read_bytes() for p in a.iterdir() if p.is_file()})
            rows=json.loads((a/'results.json').read_text(encoding='utf-8'))['messages']
            self.assertEqual([r['assignment']['topic_id'] for r in rows],['T001','T001'])
            self.assertEqual([r['decision']['action'] for r in rows],['reply','reply'])
            self.assertNotIn('机制',json.dumps(seen[0],ensure_ascii=False))
            self.assertEqual(json.loads((a/'results.json').read_text())['qq_sends'],0)
            self.assertIn('分配',(a/'report.md').read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
