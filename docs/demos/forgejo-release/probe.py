"""Offline source reproducer; the only transport is an in-memory JSON fixture."""
import importlib.util
import io
import json
import sys

spec = importlib.util.spec_from_file_location('resume_probe', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
arg = 'forgejo:forge.example/team/project@v1.2.3'
print('condition: release:' + arg)
try:
    m.validate('release', arg)
except ValueError as exc:
    print('write refused:', exc)
    assert not hasattr(m, 'forgejo_release')
    raise SystemExit(0)

body = dict(tag_name='v1.2.3', draft=False,
            html_url='https://forge.example/team/project/releases/tag/v1.2.3',
            published_at='2026-10-29T12:00:00Z')
class Reply(io.BytesIO):
    def geturl(self):
        return 'https://forge.example/api/v1/repos/team/project/releases/tags/v1.2.3'
class Reader:
    def open(self, request, timeout):
        print('fixture read:', request.full_url)
        return Reply(json.dumps(body).encode())
env = {'SHANTY_FORGEJO_URL': 'https://forge.example'}
result = m.forgejo_release(arg, env=env, opener=Reader())
print('published:', result)
assert result[0] is True
body['draft'] = True
result = m.forgejo_release(arg, env=env, opener=Reader())
print('draft control:', result)
assert result[0] is False
env['SHANTY_FORGEJO_URL'] = 'https://other.example'
result = m.forgejo_release(arg, env=env, opener=Reader())
print('wrong-host control:', result)
assert result[0] is None
