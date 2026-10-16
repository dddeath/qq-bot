"""Offline native-tool/gallery regression; unique evidence per invocation."""
import datetime,difflib,json,subprocess,uuid,zipfile
from pathlib import Path
b=Path('/home/ubuntu/tulpa-test');s=b/'self-qq-stage';r=b/'evidence'/('native-tools-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6]);r.mkdir()
cmd=[str(b/'venv/bin/python'),'-m','unittest','test_community_media','test_self_qq','test_poke_ingress','test_message_schema'];z=subprocess.run(cmd,cwd=s,capture_output=True,text=True)
(r/'verification.json').write_text(json.dumps(dict(command=cmd,cwd=str(s),exit_status=z.returncode,stdout=z.stdout,stderr=z.stderr),indent=2));assert z.returncode==0,z.stderr
old=Path((b/'native-tools-build.txt').read_text())/'mcp_chat_media.py.before';new=s/'chatlocal/mcp_chat_media.py';(r/'generated-gallery.patch').write_text(''.join(difflib.unified_diff(old.read_text().splitlines(True),new.read_text().splitlines(True),fromfile='a/chatlocal/mcp_chat_media.py',tofile='b/chatlocal/mcp_chat_media.py')))
with zipfile.ZipFile(r/'modified.zip','w') as a:
 for f in [new,s/'runner.py',s/'qq_tools.md']:a.write(f,f.name)
with zipfile.ZipFile(r/'modified.zip') as a:assert a.testzip() is None
print(r)
