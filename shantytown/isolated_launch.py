"""Privilege-drop boundary for the trusted operator's session introducer.

This prepares a process invocation, not an agent-controlled sudo path. The
controller must run outside every model process and is never made accessible
through a model's credential environment. Current sessions are not migrated.
"""
import os
import shlex
from .actor_identity import IdentityError

FORBIDDEN_ENV_PREFIXES=('SUDO_', 'SSH_', 'QUIPU_', 'SEEDS_', 'AWS_', 'INFISICAL_')

def isolated_invocation(command, *, uid, gid, home, principal, env=None):
    if os.geteuid()!=0:
        raise IdentityError('isolated session introduction requires a separate privileged controller')
    if (type(uid)is not int or type(gid)is not int or uid<10000 or gid<10000
            or not home.startswith('/var/lib/shantytown/agents/crew-')
            or not principal or not isinstance(command,list) or not command):
        raise IdentityError('invalid isolated session binding')
    safe={k:v for k,v in (env or {}).items() if not k.startswith(FORBIDDEN_ENV_PREFIXES)}
    # A positive allowlist avoids leaking controller credentials with an
    # unforeseen spelling. Provider logins must be enrolled under the child UID.
    safe={k:v for k,v in safe.items() if k in ('PATH','LANG','LC_ALL','TERM')}
    safe.update(HOME=home,USER='crew-'+principal,SHANTY_AGENT=principal)
    argv=['/usr/bin/setpriv','--reuid',str(uid),'--regid',str(gid),'--clear-groups',
          '--no-new-privs','--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all',
          '/usr/bin/env','-i',*[f'{k}={v}'for k,v in sorted(safe.items())],*command]
    return argv

def quoted_invocation(*args,**kwargs):
    return shlex.join(isolated_invocation(*args,**kwargs))


def wrap(card, launch):
    """Both harnesses use this same boundary; absent policy preserves migration mode."""
    from . import actor_identity
    row = actor_identity._policy(actor_identity.POLICY_PATH, for_principal=card.name)
    if row is None:
        return launch
    if os.geteuid() == row['uid']:
        # Already inside the correct OS boundary (also the native Mac path).
        return shlex.join(['/usr/bin/env','-i','PATH=/usr/local/bin:/usr/bin:/bin',
            'HOME='+row['home'],'SHANTY_AGENT='+row['principal'],
            '/bin/sh','-c',launch])
    if not __import__('sys').platform.startswith('linux'):
        raise IdentityError('introduce this session under its dedicated local user before launch')
    return quoted_invocation(['/bin/sh','-c',launch], uid=row['uid'],gid=row['uid'],
        home=row['home'],principal=row['principal'],env={'PATH':'/usr/local/bin:/usr/bin:/bin'})
