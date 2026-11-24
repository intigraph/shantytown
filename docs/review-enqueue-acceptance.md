# Review enqueue acceptance

An approval record, an enqueue request and a merged pull request are separate
observations. Verify each step against the exact reviewed commit.

Before a proof window, record the installed version, current configuration,
rollback command and a small pull request owned by the operator. Keep the
pull request head fixed while its checks finish. A pending or cancelled check
does not establish success.

Use the same attended or protected launch path that production reviews use.
An attended job cannot establish a protected Unix identity boundary. A
protected runtime needs its own launch, turn and teardown evidence.

For the negative case, submit an approval with a head that differs from the
pull request head, or without its required binding. Retain the refusal and
verify that the forge has no queue entry for that request. A refused launch
alone does not test approval admission.

For the positive case, let the review job report approval for the fixed head.
Retain the verdict and enqueue receipts, then read the queue state from the
forge. Confirm that no merge agent was spawned. Let the normal merge queue
perform the merge and verify the resulting commit independently.

Enable review enqueue only when its configured adapter and the selected
report path are available. Turning on a configuration flag does not add a
missing report hook. If either proof fails, restore the previous flag value
and retain the failure evidence before attempting a repair.
