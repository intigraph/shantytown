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

## Updates that turn delivery into work

An assigned alarm or inbox record can become real work through a title or label
edit. Admission checks the proposed record against the current record, including
clearing a future deferral. It preserves labels from the same backend item read.
At capacity, an owned conversion refuses without changing the record; it does
not silently reassign it. New unassigned work still follows the pool/lead path.

The paired [recording](conversion-output.log) and [timing](conversion-timing.log)
execute both actual wrappers against private temporary stores and HOME:

| Conversion through either wrapper | Before | After |
| --- | --- | --- |
| Owner has nine work items | Ten, one write | Ten, one write |
| Owner has ten work items | Eleven, one write | Ten, zero writes; record preserved |

The source SHA-256 in each result identifies the module exercised. To repeat,
set `CAPACITY_BASE_SOURCE` and `CAPACITY_HEAD_SOURCE` to the source directories
and run `python3 docs/demos/real-work-capacity/conversion-record.py`.
Use `scriptreplay --log-out conversion-output.log --log-timing conversion-timing.log`
to replay. This is source behavior, not installed scheduler acceptance. Tests
also cover native SDK label-only conversion, parallel admissions and a response
lost after a conversion commit. Label operations whose order is ambiguous to
the companion refuse before writing.
