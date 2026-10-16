import time


def send_next(bridge, qq, clock=time.time):
    job = bridge.claim_reply(clock())
    if not job:
        return None
    try:
        login = qq('get_login_info', {})
        if login.get('retcode') != 0 or str(login.get('data', {}).get('user_id')) != job['account']:
            raise ValueError('QQ account mismatch')
        result = qq('send_group_msg', {'group_id':int(job['group']),
                    'message':[{'type':'text','data':{'text':job['answer']}}]})
        receipt = (result.get('data') or {}).get('message_id')
        if result.get('status') != 'ok' or result.get('retcode') != 0 or receipt is None:
            raise ValueError('send receipt missing')
        bridge.sent(job['id'], receipt=str(receipt), now=clock())
    except Exception as e:
        bridge.unknown(job['id'], type(e).__name__ + ': ' + str(e), clock())
    return bridge.get(job['id'])
