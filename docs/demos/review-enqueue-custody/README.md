# Approved review custody across a controller exit

The input is an independently signed exact-head approval in an offline RDF
fixture. The controller retains it, suppresses a duplicate delivery, consumes
one attempt, then exits. After reopening, the attempt remains consumed and a
second attempt is refused. No forge or launcher is called.

Before base `f0250b2e936ee51cf0f89c26ace4745fb49a619b`, the
`shantytown.review_enqueue` storage contract is absent (checked with
`git cat-file -e BASE:shantytown/review_enqueue.py`). This is a new library:
the recording demonstrates its candidate behavior rather than a changed live
report flow. [Source hashes](source-sha256.json) identify the recorded code;
the PR identifies the corresponding commit.

On Linux, install the test extras, then reproduce from the repository root:

```sh
PYTHONPATH=.:tests python3 tests/demo_review_enqueue.py
```

The fixture models only mutable outer test-directory ancestors as immutable;
the created private directory/files, Ed25519 signatures, RDF verification,
locking, atomic replacement and fsync operations use the real code. It uses
synthetic keys and a modelled separate job UID. It does not prove host UID
isolation, native receipt compatibility, service ordering, or a remote enqueue.

[Output recording](output.log.gz) and [timing](timing.log) are retained here as a
small terminal demo. Download both to replay with util-linux `scriptreplay`:

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.log
```

The [readable transcript](transcript.txt) normalizes carriage-return/newline
pairs; the compressed recording preserves the original bytes and timing.
The recording is not an inline video. Its raw output has been inspected for
private data.
