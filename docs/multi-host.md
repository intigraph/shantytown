# A crew across hosts

One crew can run on more than one machine. Each host has its own store, its
own panes and its own timer, and launches only the agents placed on it. The
hosts name each other as peers, and a command for an agent on another host
runs that host's own `st` over SSH.

![One crew on two hosts. Each host has its own store, panes and timer running st fleet tend. The hosts declare each other as peers and reach each other over SSH, which carries st go, st inbox and the st crew census. Both hosts read the same Quipu registry of members and the same board of work items. st ops doctor --deploy and --relay check the setup from both directions.](diagrams/two-hosts.svg)

## What is shared and what stays local

| | where it lives |
|---|---|
| Members, roles and the host each member runs on | the Quipu registry, read by every host |
| Work items and their owners | one tracker, declared in every host's `shantytown.toml` |
| Cards, settings and `shantytown.toml` | each host's own store |
| Panes and agent sessions | the host the member is placed on |
| The timer that runs `st fleet tend` | each host, for its own agents |

## Set it up

Do these in order. Each step links to the page with the full commands.

1. **Install the same `st` on each host.** Check with `st --version`.
   See the [installation reference](installation-reference.md).
2. **Scaffold each host with a distinct name and the other host as a peer.**

   ```sh
   st --root /opt/second/store fleet init -y \
     --host second --admin second-admin --crew second-worker \
     --peer first=operator@first.example,/opt/first/store \
     --quipu-server https://graph.example \
     --ontology-namespace https://fleet.example/ontology/
   ```

   A host that already has a configuration gets a `[host.peers.<name>]` table
   added by hand. See [New-host setup](new-host.md#scaffold-each-host).
3. **Register each host and place each member in the registry.**
   See [Register the Host identity](new-host.md#register-the-host-identity).
4. **Project the cards.** Preview first, then write:

   ```sh
   st --root /opt/second/store fleet roles sync --require-host-sync 1 --dry-run
   st --root /opt/second/store fleet roles sync --require-host-sync 1
   ```

   The preview lists this host's members and names the ones it skips. See
   [Place members and inspect projection](second-host.md#place-members-and-inspect-projection).
5. **Point every host at one board.**
   See [Use one board on every host](second-host.md#use-one-board-on-every-host).
6. **Prove it from both hosts.** Run each check over non-interactive SSH, in
   both directions:

   ```sh
   ssh -o BatchMode=yes operator@first.example \
     'st --root /opt/first/store ops doctor --deploy'
   ssh -o BatchMode=yes operator@first.example \
     'st --root /opt/first/store ops doctor --relay'
   ```

   Then send one durable message to an agent on the other host and read it
   there. See [Prove messaging across the boundary](second-host.md#prove-messaging-across-the-boundary).

## What crosses the boundary

| command | across hosts |
|---|---|
| `st go ITEM AGENT` | finds the agent's host and runs `st go` there. The receiving host does its own admission, pane check and tracker read-back. |
| `st inbox AGENT MESSAGE` | relays through the declared peer. Add `-d` when the message must survive. |
| `st crew` | reads each peer and shows its agents with a `HOST` column. See [Fleet view across hosts](cli-crew.md#fleet-view-across-hosts). |
| `st crew --governor` | uses account observations from every host. See [Account governors across hosts](cli-supervision.md#account-governors-across-hosts). |
| `st fleet tend` | supervises local agents only. With `[host] admission_owner` set, launches serialize on one host while it is up. |

## Limits

- A host that cannot be reached is reported as unknown. It is never treated as
  an empty crew.
- An SSH failure or timeout during `st go` means delivery is unconfirmed.
  Inspect the destination and the board before you retry.
- A cross-host `st go --repo` is refused, because a local store path has no
  meaning on another host.
- A durable inbox on the `files` backend persists on the receiving host only.
  Use a shared board when a message must be visible fleet-wide.
