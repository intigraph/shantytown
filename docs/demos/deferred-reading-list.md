A deferred item untouched for40days with a future gate produced no reading list.
The same snapshot now produces a durable report with one old item. The future
gate remains quiet; the lapsed positive control still produces one finding.

Recording: [output](deferred-reading-list.log) and
[timing](deferred-reading-list.timing). Download both and replay with:
scriptreplay --log-out deferred-reading-list.log --log-timing deferred-reading-list.timing.
Repeat the source probe: python3 docs/demos/deferred-reading-list.py CHECKOUT.
BASE31605148230d and candidate source1ec73d07d0778f478975f9e2b91ab9698ae96b0b
use the same40-day future-gate fixture.
This is an isolated source observation, not installed scheduled acceptance.

No board query, pane wake or release is permitted by the probe. The report uses
tend's existing snapshot; malformed/missing/future touch timestamps and unreadable
snapshots remain UNKNOWN. Source age is a reading prompt, not a claim that the
work is wrong. Normal review, CI and one native scheduled observation are separate.
