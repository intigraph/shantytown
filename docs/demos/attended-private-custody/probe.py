"""Actual local directory admission only; no forge or native process calls."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from shantytown import review_enqueue
# Require an existing private, clean-ancestry parent chosen by the operator.
with tempfile.TemporaryDirectory(prefix='attended-contract-demo-',dir=sys.argv[2]) as temp:
    base=Path(temp)
    for name in ('intents','bindings'): (base/name).mkdir(mode=0o700)
    policy=SimpleNamespace(review_enqueue_attended_uid=os.geteuid(),review_enqueue_attended_dir=str(base))
    if not hasattr(review_enqueue,'attended_directory'):
        print('BEFORE: no separately configured attended custody admission')
    else:
        review_enqueue.attended_directory(policy)
        print('AFTER: explicit current UID + private 0700 state admitted')
        policy.review_enqueue_attended_uid+=1
        try: review_enqueue.attended_directory(policy)
        except Exception as error: print('WRONG UID: refused ('+type(error).__name__+')')
        else: raise AssertionError('wrong UID admitted')
        policy.review_enqueue_attended_uid=os.geteuid()
        (base/'intents').chmod(0o770)
        try: review_enqueue.attended_directory(policy)
        except Exception as error: print('MUTABLE STATE: refused ('+type(error).__name__+')')
        else: raise AssertionError('mutable state admitted')
