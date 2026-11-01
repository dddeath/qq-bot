"""Private management API schemas and dispatch; never registered with a chat bot."""
from control_plane import ControlPlane
import configuration_schema


def tools():
    string={'type':'string'}
    ref={'type':'object','properties':{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.'),'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'version':{'type':'integer', 'description': 'Required fixed configuration version from configuration_get.'}},'required':['kind','id','version'],'additionalProperties':False}
    specs=[
        ('configuration_schema',{},[]),
        ('configuration_versions',{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.'),'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.')},['kind','id']),
        ('configuration_relations',{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.'),'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'version':{'type':'integer','minimum':1, 'description': 'Immutable configuration version. Omit where optional to read the latest version.'}},['kind','id']),
        ('configuration_validate',{'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'base_version':{'type':'integer','minimum':1, 'description': 'Version being edited; save rejects a concurrent newer version.'},
            'changes':{'type':'object', 'description': 'Partial Bot fields using configuration_schema; omitted fields are retained. Saving does not apply them to a running session.'}},['id','base_version','changes']),
        ('configuration_update',{'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'base_version':{'type':'integer','minimum':1, 'description': 'Version being edited; save rejects a concurrent newer version.'},
            'changes':dict(configuration_schema.schema()['changes'],description='Partial Bot fields using configuration_schema; omitted fields are retained. Saving does not apply them to a running session.'),'request_id':{'type':'string','minLength':1, 'description': 'Stable request identifier for one operation; reuse unchanged arguments after an uncertain response.'}},
            ['id','base_version','changes','request_id']),
        ('session_configuration_binding',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.')},['session_id']),
        ('session_bind_configuration',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.'),'bot_ref':dict(ref, description='Fixed Bot reference {kind:"bot", id, version}; obtain from configuration_get.'),'expected_revision':dict(string, description='Exact binding revision from session_configuration_binding; stale revisions are rejected.'),
            'request_id':{'type':'string','minLength':1, 'description': 'Stable request identifier for one operation; reuse unchanged arguments after an uncertain response.'}},['session_id','bot_ref','expected_revision','request_id']),
        ('configuration_list',{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.')},[]),
        ('configuration_get',{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.'),'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'version':{'type':'integer', 'description': 'Optional immutable configuration version. Omit to read the latest version.'}},['kind','id']),
        ('configuration_put',{'kind':dict(string, description='Configuration kind: bot, learning_job or tool_profile.'),'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'body':{'type':'object', 'description': 'Complete configuration body for the selected kind; use configuration_get and configuration_schema to inspect the shape.'},'expected_version':{'type':'integer', 'description': 'Expected current configuration version; default 0 is only for a new object. Existing objects require their current version.'}},['kind','id','body']),
        ('bot_inherit',{'id':dict(string, description='Logical configuration object ID; use configuration_list to discover existing IDs.'),'source_bot_ref':dict(ref, description='Fixed source Bot reference {kind:"bot", id, version} from configuration_get.'),'account_id':dict(string, description='QQ login account ID as a decimal string.'),'bindings':{'type':'object', 'description': 'Target Bot bindings, including its own permitted groups; copied tool configuration keeps its fixed reference.'},'disabled_tools':{'type':'object', 'description': 'Tool exclusions keyed by MCP server for the inherited profile.'},'persona_ref':dict(string, description='Persona resource reference for the target Bot, not inline persona text.')},['id','source_bot_ref','account_id','bindings']),
        ('session_bind',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.'),'purpose':dict(string, description='Session role: chat, learning, research or screening.'),'bot_ref':dict(ref, description='Fixed Bot reference {kind:"bot", id, version}; obtain from configuration_get.'),'runtime_refs':{'type':'object', 'description': 'Runtime resource references for this Session; see session_effective_configuration for existing fields.'}},['session_id','purpose']),
        ('session_effective_configuration',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.')},['session_id']),
        ('session_publish_runtime',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.'),'release':dict(string, description='Absolute release directory actually selected for this session.'),'run_path':dict(string, description='Absolute runtime Run directory on the executing host; not the registry Session ID.'),'tool_snapshot':dict(string, description='Absolute path to the tool snapshot actually selected for this run.')},['session_id','release','run_path']),
        ('session_rollback_publication',{'receipt':{'type':'object', 'description': 'Complete publication receipt previously returned by session_publish_runtime; preserve all guard fields.'}},['receipt']),
        ('session_runs',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.')},['session_id']),
        ('session_export_tools',{'session_id':dict(string, description='Unified registry Session ID, not a native model thread or Tulpa chat ID.'),'directory':dict(string, description='Absolute new output directory on the executing host. Existing output may be rejected.'),'python':dict(string, description='Python executable on the executing host used in generated MCP commands.'),'proxy':dict(string, description='Absolute tool-proxy script path on the executing host.')},['session_id','directory','python','proxy']),
        ('session_export_runtime_configuration',{'session_ids':{'type':'array','items':string, 'description': 'Unified Session IDs whose fixed bindings form this runtime export.'},
            'expected_revisions':{'type':'object', 'description': 'Map of each Session ID to its binding revision returned by session_configuration_binding.'},'directory':dict(string, description='Absolute new output directory on the executing host. Existing output may be rejected.'),'screening_runtime':{'type':'object', 'description': 'Host screening runtime parameters used when exporting the bound screening consumer.'},
            'python':dict(string, description='Python executable on the executing host used in generated MCP commands.'),'proxy':dict(string, description='Absolute tool-proxy script path on the executing host.')},['session_ids','expected_revisions','directory','screening_runtime','python','proxy']),
        ('runtime_configuration_status',{'config_path':dict(string, description='Absolute path to the exported runtime configuration to inspect or apply.')},['config_path']),
        ('runtime_application_preview',{'config_path':dict(string, description='Absolute path to the exported runtime configuration to inspect or apply.'),'previous_config_path':dict(string, description='Absolute path to the previously loaded configuration used as the rollback baseline.')},['config_path','previous_config_path']),
        ('runtime_application_start',{'preview':{'type':'object', 'description': 'Complete unchanged result from runtime_application_preview; it binds the target, baseline and Session revisions.'},'request_id':dict(string, description='Stable request identifier for one operation; reuse unchanged arguments after an uncertain response.'),'directory':dict(string, description='Absolute new output directory on the executing host. Existing output may be rejected.')},['preview','request_id','directory']),
        ('runtime_application_get',{'operation_id':dict(string, description='Application operation ID returned by runtime_application_start or runtime_application_rollback.')},['operation_id']),
        ('runtime_application_execute',{'operation_id':dict(string, description='Application operation ID returned by runtime_application_start or runtime_application_rollback.')},['operation_id']),
        ('runtime_application_rollback',{'operation_id':dict(string, description='Application operation ID returned by runtime_application_start or runtime_application_rollback.'),'request_id':dict(string, description='Stable request identifier for one operation; reuse unchanged arguments after an uncertain response.'),'directory':dict(string, description='Absolute new output directory on the executing host. Existing output may be rejected.')},['operation_id','request_id','directory']),
    ]
    descriptions = {
        'configuration_list':'List current configuration objects and their latest immutable versions. Optional kind filters bot, learning_job or tool_profile; writes nothing.',
        'configuration_get':'Read one configuration object at a fixed version, or its latest version when omitted. Returns ref and body; this is saved state, not proof of runtime loading.',
        'configuration_put':'Store a complete configuration body as a new immutable version, requiring expected_version to match the current version (default 0 creates a new object). Does not bind Sessions or reload consumers.',
        'bot_inherit':'Create a Bot configuration using a fixed source Bot tool profile with target account, group bindings and optional exclusions. Returns saved configuration; does not start chat.',
        'session_bind':'Replace the unified Session overlay with purpose, bot_ref and runtime_refs. Omitted optional references clear the previous overlay values, including publication references; read session_effective_configuration and copy values you intend to retain. Does not start or reload a process.',
        'session_effective_configuration':'Read the effective saved references and resolved configuration for a unified Session. Actual consumer loading evidence is available separately through runtime_configuration_status.',
        'session_publish_runtime':'Register the selected release, run_path and optional tool snapshot for this Session. Returns a guarded publication receipt usable by session_rollback_publication; does not start a process.',
        'session_rollback_publication':'Restore the publication recorded in a prior session_publish_runtime receipt if its guards still match. Restores registration only; does not stop or reload chat.',
        'session_runs':'List recorded Runs for the unified Session with their status and execution receipts; native thread IDs remain separate.',
        'session_export_tools':'Write the Session-bound tool snapshot and MCP launch configuration to a new directory. Returns artifact paths; does not apply them to a live process.',

        'configuration_schema':'Read the shared Bot edit schema; omitted fields are preserved. No runtime defaults are inserted.',
        'configuration_validate':'Preview a partial Bot edit against a fixed base_version. Returns field errors and diff; writes nothing.',
        'configuration_update':'Save a partial Bot edit as an immutable version. Reuse request_id only for the same operation. Does not bind or load a runtime.',
        'configuration_versions':'Read immutable versions of one configuration object, newest first.',
        'configuration_relations':'Read linked Sessions and configuration references. Omit version to include all versions of the logical object.',
        'session_configuration_binding':'Read the current Session binding and its revision for optimistic concurrency. Does not claim runtime adoption.',
        'session_bind_configuration':'Bind a fixed Bot reference using expected_revision. Preserves runtime references; does not reload processes. Repeated request_id returns the original receipt.',
        'session_export_runtime_configuration':'Export fixed per-group runtime snapshots from current chat and screening bindings. Checks every expected_revision. Does not start or reload processes; directory must be new.',
        'runtime_configuration_status':'Read consumer-written loading receipts for an exported runtime configuration. Missing evidence stays unknown; loading and model invocation are distinct.',
        'runtime_application_preview':'Preview fixed runtime application and previous loaded baseline. Returns affected consumers, native identity and binding preconditions; no writes.',
        'runtime_application_start':'Register the unchanged preview as one pending operation. Reuse request_id and identical arguments after a lost response. Does not reload.',
        'runtime_application_get':'Read application steps and fresh consumer loading receipts. Unknown or partial adoption is not success.',
        'runtime_application_execute':'Dispatch each consumer at most once through the private configured host adapter. Success requires matching fresh loading receipts. Repeated execution reconciles receipts and registration without redispatching. A live worker or host child stays running.',
        'runtime_application_rollback':'Restore original fixed bindings after a finished application with unchanged Session guards. Creates a new pending loading operation; execute it to verify runtime restoration.',
    }
    readonly = {'configuration_list','configuration_get','session_effective_configuration','session_runs',
                'configuration_schema','configuration_validate','configuration_versions',
                'configuration_relations','session_configuration_binding','runtime_configuration_status',
                'runtime_application_preview','runtime_application_get'}
    return [dict(name=n,description=descriptions[n],inputSchema={'type':'object','properties':p,'required':r,'additionalProperties':False},annotations={'readOnlyHint':n in readonly}) for n,p,r in specs]


def call(sessions,name,args,*,reload_consumer=None):
    p=ControlPlane(sessions)
    if name=='runtime_application_execute':
        return p.runtime_application_execute(**args,reload_consumer=reload_consumer)
    return {'configuration_schema':p.schema,'configuration_validate':p.validate_changes,
            'configuration_update':p.update,'configuration_versions':p.versions,
            'configuration_relations':p.relations,'session_configuration_binding':p.binding,
            'session_bind_configuration':p.bind_configuration,
            'session_export_runtime_configuration':p.export_runtime_configuration,
            'runtime_configuration_status':p.runtime_configuration_status,
            'runtime_application_preview':p.runtime_application_preview,
            'runtime_application_start':p.runtime_application_start,
            'runtime_application_get':p.runtime_application_get,
            'runtime_application_rollback':p.runtime_application_rollback,
            'configuration_list':p.list,'configuration_get':p.get,'configuration_put':p.put,
            'bot_inherit':p.inherit_bot,'session_bind':p.bind,'session_effective_configuration':p.effective,'session_runs':p.runs,'session_publish_runtime':p.publish_runtime,'session_rollback_publication':p.rollback_publication,'session_export_tools':p.export_tools}[name](**args)


def validate(schema,value):
    errors = configuration_schema.errors(value, schema)
    if errors:
        import json
        raise ValueError('invalid arguments: '+json.dumps(errors))
