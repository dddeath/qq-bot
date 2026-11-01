"""Execute one registered configuration application through a private host adapter."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from runtime_configuration import sha
from run_records import save
from sessions import Sessions
from control_plane import ControlPlane


class CommandReloader:
    def __init__(self, config):
        self.command=config.get('command')
        if not isinstance(self.command,list) or not self.command or not all(isinstance(x,str) and x for x in self.command):
            raise ValueError('runtime reload adapter command required')
        self.timeout=config.get('timeout_seconds',120)
        if not isinstance(self.timeout,(int,float)) or isinstance(self.timeout,bool) or self.timeout<=0:
            raise ValueError('positive reload adapter timeout required')

    def __call__(self,request):
        path=Path(request['config_path']).parent/('host-'+sha(request['conversation'].encode())+'-'+request['consumer']+'.json')
        record={'request':request,'command':self.command,'started_at':time.time(),
                'exit_status':None,'stdout':'','stderr':''}
        try:
            with subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,text=True,encoding='utf-8') as child:
                record['pid']=child.pid;save(path,record)
                try:
                    stdout,stderr=child.communicate(json.dumps(request),timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    child.kill();stdout,stderr=child.communicate()
                    record.update(exit_status=child.returncode,stdout=stdout,stderr=stderr,error='reload adapter timeout')
                    raise
                record.update(exit_status=child.returncode,stdout=stdout,stderr=stderr)
                if child.returncode:raise RuntimeError('reload adapter exited '+str(child.returncode))
        finally:
            record['finished_at']=time.time()
            save(path,record)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--operation-id',required=True)
    args=parser.parse_args();config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    adapter=CommandReloader(config.get('runtime_reload',{}))
    with Sessions(config['database']) as sessions:
        result=ControlPlane(sessions).runtime_application_execute(args.operation_id,reload_consumer=adapter)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='succeeded' else 1


if __name__=='__main__':raise SystemExit(main())
