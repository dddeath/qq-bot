"""Project Tulpa guidance into host-managed model turns without changing events."""
from copy import deepcopy


STATIC_FIELDS = ('persona_preset', 'persona_name', 'reminders', 'examples',
                 'examples_source', 'data_boundary')


class GuidanceProjection:
    def __init__(self):
        self.reset()

    def reset(self):
        self.delivered = None

    def prepare(self, event):
        projected = deepcopy(event)
        body = projected.get('payload', projected)
        next_call = body.get('next_call', {})
        if next_call.get('tool') == 'wait_chat_messages':
            body.pop('next_call')
        guidance = body.get('chat_guidance')
        if not isinstance(guidance, dict):
            return projected, None
        # Waiting and recovery are owned by the host, not per-message hints.
        guidance.pop('continue_with', None)
        guidance.pop('resume', None)
        learning = guidance.get('language_learning', {})
        if learning.get('enabled') is False:
            guidance['language_learning'] = {'enabled': False}
        reactions = guidance.get('reactions', {})
        if reactions.get('enabled') is False or reactions.get('authorized') is False:
            guidance['reactions'] = {key: reactions[key] for key in ('enabled', 'authorized')
                                     if key in reactions}
            notices = guidance.get('reaction_notices', {})
            if not notices.get('items') and not notices.get('new_items'):
                guidance.pop('reaction_notices', None)
        snapshot = {key: deepcopy(guidance[key]) for key in STATIC_FIELDS
                    if key in guidance}
        snapshot['prompt_version'] = guidance.get('prompt_version')
        if snapshot == self.delivered:
            for key in STATIC_FIELDS:
                guidance.pop(key, None)
        return projected, snapshot

    def commit(self, snapshot):
        if snapshot is not None:
            self.delivered = snapshot
