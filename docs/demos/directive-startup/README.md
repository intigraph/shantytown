# Directive startup reminder

[Recorded output](output.log) compares an unchanged baseline checkout with this
candidate using inert plate and memory readers. No agent is launched and no
registry or graph write is made. Both normal startup and a simultaneous unreadable
plate/primer now tell the agent to check governing Directives and record new
operator directives verbatim. This is a source demonstration, not installed
session acceptance.

From the candidate repository root, with a separate unchanged baseline checkout:

```sh
python3 docs/demos/directive-startup/probe.py --baseline /path/to/baseline
```
