"""Main runs retain their identities; supersession is confined to one PR."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ('ci.yml', 'install.yml', 'identity-isolation.yml')


def render(value, **context):
    def expression(match):
        code = match[1].strip().replace('&&', ' and ').replace('||', ' or ')
        return str(eval(code, {'__builtins__': {}}, {'github': SimpleNamespace(**context)}))
    return re.sub(r'\$\{\{(.*?)\}\}', expression, value)


@pytest.mark.parametrize('workflow', WORKFLOWS)
def test_three_main_arrivals_have_distinct_groups(workflow):
    concurrency = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())['concurrency']
    groups = [render(concurrency['group'], workflow=workflow, event_name='push',
                     ref='refs/heads/main', run_id=run) for run in (101, 102, 103)]
    # A running and B pending cannot collide with C, even though pending replacement
    # is independent of cancel-in-progress in GitHub's single-pending scheduler.
    assert len(set(groups)) == 3
    assert render(concurrency['cancel-in-progress'], event_name='push') == 'False'


@pytest.mark.parametrize('workflow', WORKFLOWS)
def test_pr_heads_share_group_but_other_pr_does_not(workflow):
    concurrency = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())['concurrency']
    def group(pr, run):
        return render(concurrency['group'], workflow=workflow, event_name='pull_request',
                      ref=f'refs/pull/{pr}/merge', run_id=run)
    assert group(17, 201) == group(17, 202)
    assert group(17, 201) != group(18, 203)
    assert render(concurrency['cancel-in-progress'], event_name='pull_request') == 'True'
