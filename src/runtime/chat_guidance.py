"""Project Tulpa guidance into host-managed model turns without changing events."""
from copy import deepcopy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions'))
from host_wait import project_body


FIXED_FIELDS = ('persona_preset', 'persona_name', 'examples_source', 'data_boundary')
SCENE_FIELDS = ('reminders', 'examples')
STATIC_FIELDS = FIXED_FIELDS + SCENE_FIELDS


class GuidanceProjection:
    def __init__(self):
        self.reset()

    def reset(self):
        self.delivered = None

    def prepare(self, event):
        projected = deepcopy(event)
        body = project_body(projected.get('payload', projected))
        if 'payload' in projected:
            projected['payload'] = body
        else:
            projected = body
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
        if self.delivered is not None and snapshot['prompt_version'] == self.delivered['prompt_version']:
            for key in STATIC_FIELDS:
                if key in snapshot and snapshot[key] == self.delivered.get(key):
                    guidance.pop(key, None)
            old = self.delivered.get('reminders')
            new = snapshot.get('reminders')
            if isinstance(old, list) and isinstance(new, list) and old != new:
                guidance.pop('reminders', None)
                guidance['reminders_update'] = {
                    'remove': [item for item in old if item not in new],
                    'add': [item for item in new if item not in old],
                }
        return projected, snapshot

    def commit(self, snapshot):
        if snapshot is not None:
            self.delivered = snapshot
