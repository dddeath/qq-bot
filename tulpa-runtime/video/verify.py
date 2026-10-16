"""Run offline adapter tests into a new evidence directory on every invocation."""
import datetime, hashlib, json, os, pathlib, shutil, subprocess, sys, uuid, zipfile

here = pathlib.Path(__file__).resolve().parent
root = here.parents[1]
out = root / '.local' / ('video-verify-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex[:8])
out.mkdir(parents=True)
command = [shutil.which('node'), '--test', *[str(p) for p in sorted((here/'test').glob('*.test.mjs'))]]
result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
(out/'verification.json').write_text(json.dumps(dict(command=command, cwd=str(root), stdout=result.stdout, stderr=result.stderr, exit_status=result.returncode), ensure_ascii=False, indent=2), encoding='utf-8')
files = [p for p in here.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts]
files.append(root/'tulpa-runtime/skills/qq-background-work/SKILL.md')
with zipfile.ZipFile(out/'modified.zip','w') as archive:
    for p in files: archive.write(p,p.relative_to(root))
with zipfile.ZipFile(out/'modified.zip') as archive: assert archive.testzip() is None
diff=subprocess.run(['git','diff','HEAD','--','tulpa-runtime/video','tulpa-runtime/skills/qq-background-work/SKILL.md'],cwd=root,capture_output=True)
(out/'tracked.patch').write_bytes(diff.stdout)
# New integration sources are preserved in modified.zip, including their tests.
(out/'manifest.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2),encoding='utf-8')
assert json.loads((out/'verification.json').read_text(encoding='utf-8'))['exit_status']==result.returncode
print(out)
sys.exit(result.returncode)
