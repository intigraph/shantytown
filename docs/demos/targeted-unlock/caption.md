# Finite unlock notification seam

Replay with `scriptreplay --log-out output.log --log-timing timing.log`.
Readable fallback: [output.log](output.log). No inline player is promised.

Source-library comparison: base `00aeb887d5ec2f8575283bd1c8eca5bbf09aa795`
rejects the targeted reader argument; candidate `9d3d195` supports it. The
reproducer uses isolated tracker, registry and inbox adapters; it invokes the
actual shared notifier and reads its retained local receipt ledger. It does not
create a real notification or run an installed Chaski reaction.

Watch one fixture delivery, then a committed ACK whose response is lost. Replay
confirms the retained receipt without another send or ACK write. All native
calls use the selected seed. Run `python3 docs/demos/targeted-unlock/demo.py`
from the source checkout. Small sanitized output/timing artifacts are retained
with this change. Runtime binding and foreign-node acceptance remain open.
