# Old live mail stays visible

The trigger is one unread message in a live window dated January 2000. This
library demonstration executes the actual inbox implementations at baseline
`39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076` and candidate
`d9370924febd29e77c5e41b912e21f969ba88ecd`, with an explicitly synthetic,
age-aware backend. Before, unread is zero and marking the old message refuses.
After, unread is one, marking succeeds, and unread becomes zero. The recorded
scope calls show that the candidate requests all live windows throughout.

Run from the repository root with its Python dependencies:

```sh
PYTHONPATH=. python3 docs/demos/all-live-windows/demo.py
```

The [output](output.txt) is a readable transcript, not a timing recording. No
recording was made; replay timing is unavailable. This small artifact and its
caption are retained in the repository for review. The backend is mocked: the
separate Seeds native CLI control proves real list/count/show/read across old
registered windows. This does not claim a deployed adapter, expiry, a production
config flip or the later 24-hour acceptance check.
