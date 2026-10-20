# Real work capacity

Run `python3 docs/demos/real-work-capacity/probe.py` from the checkout.
The source fixture feeds the same 17 records (two implementation tasks, eight
alarm records and seven inbox messages) to base `1434b3df1c80` and the candidate.
Watch the capacity count change from ten to two. The positive control then fills
ten real slots: the automatic producer retains overflow in the unassigned pool
and invokes one lead notice, while alarm and inbox delivery continue.

Download [the recording](output.log) and [timing](timing.log), then play them with
`scriptreplay --log-out output.log --log-timing timing.log`. This is a terminal
recording; download and terminal replay are required. The recording identifies
the candidate module by SHA256; the pull request identifies its source revision.
The artifacts are small and retained with this demo.

This uses a temporary file store and HOME. It proves source behavior, not a
running fleet repair. The separate native SDK fixture covers the deployment
producer adapter's actual create/readback and lead-message route; uncertainty
and concurrent admission controls live in the tests.

Installation order for scheduled SDK producers is Shantytown first, then the
neutral producer adapter. Until the installed Shantytown interpreter has the
companion module, the neutral adapter refuses an assignment rather than writing
without admission. The host lock serializes cooperating writers on one host;
it does not claim a cross-host backend transaction or police direct SDK calls.
