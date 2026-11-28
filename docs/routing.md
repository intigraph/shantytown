# 📮 Routing: there is nothing in the middle

**A live `st inbox` *is* `tmux send-keys`.** That's not an implementation detail — it's the product.

```
st inbox ada "go read st-1"
   │
   ├─ registry.get("ada")        → identity: role, reports_to, pane
   ├─ pane = "crew-ada"          → the address IS the pane
   ├─ panes.exists(pane)?        → NO  → exit 2 "could not tell". nothing sent.
   └─ tmux send-keys -t <pane>   → the message. that's the delivery.
```

**No message bus and no broker. A live send has no delivery guarantee — because there's nothing to
guarantee.** The pane is either there or it isn't, and you're told which.

| routing outcome | exit | what it means |
|---|---|---|
| delivered | **0** | the keys went into a live pane |
| no such agent / no pane | **1** | refused. nothing sent. |
| pane named but gone | **2** | *could not tell* — never a cheerful success |

## Messages that must arrive

For the messages that must survive a dead recipient — a handoff, a protocol step — `-d`
(`--durable`) stores the message in the recipient's inbox **first** and only then attempts the live
send. The inbox is an item in the tracker by default, or a message window in its own graph when
`[inbox] store = "message-graph"` is set ([message graph](message-graph.md)).

| the recipient wants to | runs |
|---|---|
| list unread messages | `st inbox` |
| count them, marking nothing read | `st inbox --count` |
| mark them read | `st inbox --read`, or `st inbox --read-id ID` for one |

A session that starts with unread messages is shown them at launch. `--routine` marks a durable
message as batchable progress, so the administrator can be told at the next tend pass instead of
being interrupted now.

A message to an agent on another host is relayed through that host's own `st` over ssh, using the
peer declared in `[host.peers.<name>]`. With no peer declared it is refused by name.

**Identity resolves through the registry, not through a config file you hand-edit.** With the
`quipu` registry the graph is the truth and the agent card is a projection of it: writes go to the
graph, reads may come from the card, never the reverse — so an agent's address can't quietly drift
from reality. With the default `files` registry the generated cards are the store
([agent card](agent-card.md)).
