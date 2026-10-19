"""Private management API schemas and dispatch; never registered with a chat bot."""
from control_plane import ControlPlane


def tools():
    string={'type':'string'}
    ref={'type':'object','properties':{'kind':string,'id':string,'version':{'type':'integer'}},'required':['kind','id','version'],'additionalProperties':False}
    specs=[
        ('configuration_list',{'kind':string},[]),
        ('configuration_get',{'kind':string,'id':string,'version':{'type':'integer'}},['kind','id']),
        ('configuration_put',{'kind':string,'id':string,'body':{'type':'object'},'expected_version':{'type':'integer'}},['kind','id','body']),
        ('bot_inherit',{'id':string,'source_bot_ref':ref,'account_id':string,'bindings':{'type':'object'},'disabled_tools':{'type':'object'},'persona_ref':string},['id','source_bot_ref','account_id','bindings']),
        ('session_bind',{'session_id':string,'purpose':string,'bot_ref':ref,'runtime_refs':{'type':'object'}},['session_id','purpose']),
        ('session_effective_configuration',{'session_id':string},['session_id']),
        ('session_publish_runtime',{'session_id':string,'release':string,'run_path':string,'tool_snapshot':string},['session_id','release','run_path']),
        ('session_rollback_publication',{'receipt':{'type':'object'}},['receipt']),
        ('session_runs',{'session_id':string},['session_id']),
        ('session_export_tools',{'session_id':string,'directory':string,'python':string,'proxy':string},['session_id','directory','python','proxy']),
    ]
    return [dict(name=n,description=n.replace('_',' '),inputSchema={'type':'object','properties':p,'required':r,'additionalProperties':False},annotations={'readOnlyHint':n in ('configuration_list','configuration_get','session_effective_configuration','session_runs')}) for n,p,r in specs]


def call(sessions,name,args):
    p=ControlPlane(sessions)
    return {'configuration_list':p.list,'configuration_get':p.get,'configuration_put':p.put,
            'bot_inherit':p.inherit_bot,'session_bind':p.bind,'session_effective_configuration':p.effective,'session_runs':p.runs,'session_publish_runtime':p.publish_runtime,'session_rollback_publication':p.rollback_publication,'session_export_tools':p.export_tools}[name](**args)


def validate(schema,value):
    types={'string':str,'object':dict,'array':list,'integer':int}
    if schema.get('type') in types and (not isinstance(value,types[schema['type']]) or schema['type']=='integer' and isinstance(value,bool)):
        raise ValueError('invalid argument type')
    if 'enum' in schema and value not in schema['enum']:raise ValueError('invalid argument value')
    if isinstance(value,dict):
        if set(schema.get('required',[]))-set(value):raise ValueError('missing arguments')
        if schema.get('additionalProperties') is False and set(value)-set(schema.get('properties',{})):raise ValueError('unknown arguments')
        for key,spec in schema.get('properties',{}).items():
            if key in value:validate(spec,value[key])
