"""Generate Shantytown's three documentation diagrams as SVG.

Usage: gen_diagrams.py OUTPUT_DIR
Style follows the Quipu README diagrams: dark card, gold and pink accents.
"""
import sys
from html import escape
from pathlib import Path

BG, CARD, EDGE = "#12121f", "#20203a", "#2e2e4d"
INK, BODY, GOLD, PINK, CORAL, DIM = "#ecebf5", "#a7a6c2", "#ffc24d", "#ff4fa0", "#ff8a70", "#6f6e8f"

STYLE = """
    .t{font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif}
    .m{font-family:JetBrains Mono,Menlo,Consolas,monospace}
    .card{fill:#20203a;stroke:#2e2e4d}
    .pipe{stroke:#ff8a70;stroke-width:2.5;fill:none;stroke-dasharray:6 6;opacity:.75;animation:flow 1.2s linear infinite}
    .up{stroke:#ffc24d;stroke-width:2;fill:none;stroke-dasharray:4 5;opacity:.8;animation:flow 1.6s linear infinite}
    .down{stroke:#ff4fa0;stroke-width:2;fill:none;stroke-dasharray:4 5;opacity:.8;animation:flow 1.6s linear infinite reverse}
    @keyframes flow{to{stroke-dashoffset:-24}}
    @media (prefers-reduced-motion: reduce){.pipe,.up,.down{animation:none}}
"""


def wrap(text, width, size, mono=False):
    per = size * (0.6 if mono else 0.53)
    limit = max(4, int(width / per))
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > limit:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


class Svg:
    def __init__(self, w, h, label):
        self.w, self.h, self.label, self.out = w, h, label, []

    def add(self, s):
        self.out.append(s)

    def text(self, x, y, s, size=13, fill=BODY, weight=None, cls="t", anchor=None, spacing=None, italic=False):
        attrs = f'class="{cls}" x="{x}" y="{y}" fill="{fill}" font-size="{size}"'
        if weight:
            attrs += f' font-weight="{weight}"'
        if anchor:
            attrs += f' text-anchor="{anchor}"'
        if spacing:
            attrs += f' letter-spacing="{spacing}"'
        if italic:
            attrs += ' font-style="italic"'
        self.add(f"  <text {attrs}>{escape(s)}</text>")

    def para(self, x, y, s, width, size=12.5, fill=BODY, lead=None, cls="t", weight=None, anchor=None):
        lead = lead or round(size * 1.38, 1)
        for n, line in enumerate(wrap(s, width, size, cls == "m")):
            self.text(x, round(y + n * lead, 1), line, size, fill, weight, cls, anchor)
        return y + len(wrap(s, width, size, cls == "m")) * lead

    def card(self, x, y, w, h, stroke=EDGE, fill=CARD, dash=None, rx=14, sw=1.2):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def path(self, d, cls):
        self.add(f'  <path class="{cls}" d="{d}"/>')

    def head(self, x, y, direction, fill):
        pts = {"right": f"{x},{y} {x-9},{y-5} {x-9},{y+5}", "left": f"{x},{y} {x+9},{y-5} {x+9},{y+5}",
               "up": f"{x},{y} {x-5},{y+9} {x+5},{y+9}", "down": f"{x},{y} {x-5},{y-9} {x+5},{y-9}"}[direction]
        self.add(f'  <polygon points="{pts}" fill="{fill}"/>')

    def render(self):
        body = "\n".join(self.out)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" role="img" '
                f'aria-label="{escape(self.label, quote=True)}">\n  <style>{STYLE}  </style>\n'
                f'  <rect width="{self.w}" height="{self.h}" rx="20" fill="{BG}"/>\n{body}\n</svg>\n')


def lifecycle():
    s = Svg(960, 640, (
        "How a work item moves through a crew. Five stages run left to right. Ask: you, a schedule or an event "
        "creates a work item with st task. Dispatch: the administrator sends it with st go, and it is admitted only "
        "if the agent is free and the account has room. Work: the worker reads who it is and what it owns with st "
        "anchor, then works in its own pane. Stop: one verdict decides whether the worker takes its next item, "
        "reports to its lead or rests; taking the next item loops back to Work. Deliver: st repo pr opens a pull "
        "request, a short-lived reviewer agent reviews it, and the item is closed. Under each stage is the part of "
        "the Quipu stack that serves it. Chaski and Shuttle trigger an item. Seeds and Quipu say who owns what. "
        "Bobbin and Yupana inform and constrain the work. Camayoc and Desire Path account for it and learn from it. "
        "Quipu remembers the outcome. Between turns a host timer runs st fleet tend. Every stack tool is optional."))
    s.text(40, 52, "How a work item moves through a crew", 24, INK, 700)
    s.text(40, 78, "Shantytown moves the item. The Quipu stack tells each agent what it owns, what to read and what it may change.", 14)

    xs, w, top, h = [30, 214, 398, 582, 766], 164, 128, 158
    stages = [
        ("YOU OR A TRIGGER", "Ask", "st task", "A work item with an owner, a priority and a due date."),
        ("ADMINISTRATOR", "Dispatch", "st go ITEM AGENT", "Admitted only if the agent is free and its account has room."),
        ("WORKER", "Work", "st anchor", "Reads who it is and what it owns, then works in its own pane."),
        ("WORKER", "Stop", "stop hook", "One verdict: take the next item, report to the lead, or rest."),
        ("WORKER AND REVIEWER", "Deliver", "st repo pr", "A short-lived agent can review. The change merges and the item closes."),
    ]
    for x, (role, title, cmd, cap) in zip(xs, stages):
        s.card(x, top, w, h, stroke=PINK if title == "Work" else EDGE, sw=1.6 if title == "Work" else 1.2)
        s.text(x + 14, top + 24, role, 9.5, GOLD, 700, spacing="0.8")
        s.text(x + 14, top + 52, title, 19, INK, 700)
        s.text(x + 14, top + 75, cmd, 12.5, PINK, cls="m")
        s.para(x + 14, top + 98, cap, w - 26, 12.5)
    for x in xs[:-1]:
        s.path(f"M{x + w + 2} {top + 46} H{x + w + 12}", "pipe")
        s.head(x + w + 19, top + 46, "right", CORAL)
    # Stop loops back to Work.
    a, b = xs[3] + w / 2, xs[2] + w / 2
    s.path(f"M{a} {top - 2} C{a} {top - 30} {b} {top - 30} {b} {top - 12}", "pipe")
    s.head(b, top - 3, "down", CORAL)
    s.text((a + b) / 2, top - 30, "next item on its plate", 12, CORAL, anchor="middle")

    stack_top, sh = 368, 132
    stack = [
        ("Chaski · Shuttle", "trigger", "up", "An event or a signed workflow can open the item."),
        ("Seeds · Quipu", "who owns what", "up", "The item, its owner and due date. The crew and who leads whom."),
        ("Bobbin · Yupana", "inform, constrain", "up", "The code this item touches. The impact of each edit, and your policies."),
        ("Camayoc · Desire Path", "account, learn", "down", "Tokens spent on the item. Tool calls that failed."),
        ("Quipu", "remember", "down", "Rulings and handoffs on the item, for the next session to query."),
    ]
    for x, (name, verb, way, cap) in zip(xs, stack):
        cx = x + 34
        y1, y2 = top + h + 4, stack_top - 4
        if way == "up":
            s.path(f"M{cx} {y2} V{y1 + 8}", "up")
            s.head(cx, y1, "up", GOLD)
        else:
            s.path(f"M{cx} {y1} V{y2 - 8}", "down")
            s.head(cx, y2, "down", PINK)
        s.text(cx + 12, (y1 + y2) / 2 + 4, verb, 12.5, GOLD if way == "up" else PINK, 600)
        s.card(x, stack_top, w, sh)
        s.text(x + 14, stack_top + 28, name, 13, GOLD, 700)
        s.para(x + 14, stack_top + 52, cap, w - 26, 12.5)

    fy = 522
    s.card(30, fy, 440, 92)
    s.text(48, fy + 28, "Between turns", 15, INK, 700)
    s.text(160, fy + 28, "st fleet tend", 12.5, PINK, cls="m")
    s.para(48, fy + 50, "A host timer runs it every few minutes. It restarts an agent that died, enforces deadlines and feeds an idle agent its next item.", 410, 12.5)
    s.card(490, fy, 440, 92)
    s.text(508, fy + 28, "The Quipu stack is optional", 15, INK, 700)
    s.para(508, fy + 50, "With no stack tool installed, the same stages run on local files. Gold arrows guide the agent. Pink arrows record what it did.", 410, 12.5)
    return s.render()


def hooks():
    s = Svg(960, 628, (
        "What reaches an agent during a session. A stack tool registers a hook bundle with st ops hooks register. "
        "Shantytown writes one settings file per role, holding its own hooks and every registered one, for the "
        "agent program: Claude Code, Codex, OpenCode or Antigravity. The hooks run at four fixed points of a "
        "session. At session start, Shantytown runs st anchor to give identity, plate and lead, and Yupana briefs "
        "the agent on its work item. At each prompt, Shantytown recalls earlier incidents and Bobbin adds the code "
        "that matches the prompt. At each tool call, Shantytown captures tools run, files touched and tokens "
        "spent, Yupana checks an edit against your policies and reports its impact, and Desire Path records a call "
        "that failed. At stop, Shantytown decides between the next item, a report to the lead and rest, and Quipu "
        "asks the agent to record what it learned."))
    s.text(40, 52, "What reaches an agent during a session", 24, INK, 700)
    s.text(40, 78, "Shantytown writes one settings file per role. It holds Shantytown's own hooks and every hook a stack tool has registered.", 14)

    s.card(30, 104, 250, 74)
    s.text(46, 130, "A stack tool registers", 15, INK, 700)
    s.text(46, 152, "st ops hooks register", 12.5, PINK, cls="m")
    s.path("M284 141 H336", "pipe")
    s.head(344, 141, "right", CORAL)
    s.card(348, 104, 250, 74, stroke=PINK, sw=1.6)
    s.text(364, 130, "Shantytown renders", 15, INK, 700)
    s.text(364, 152, "one settings file per role", 12.5, BODY)
    s.path("M602 141 H654", "pipe")
    s.head(662, 141, "right", CORAL)
    s.card(666, 104, 264, 74)
    s.text(682, 130, "The agent program runs", 15, INK, 700)
    s.text(682, 152, "Claude Code, Codex, OpenCode, Antigravity", 11.5, BODY)

    xs, w = [30, 260, 490, 720], 210
    line_y = 252
    s.text(40, 208, "ONE SESSION, FOUR HOOK POINTS", 10.5, DIM, 700, spacing="1.2")
    s.path(f"M{xs[0] + 20} {line_y} H{xs[-1] + w - 22}", "pipe")
    s.head(xs[-1] + w - 12, line_y, "right", CORAL)
    points = [
        ("Session start", "st anchor", "Identity, plate, lead and standing directives.",
         "Yupana", "Briefs the agent on its work item."),
        ("Each prompt", "incident recall", "Earlier incidents that match what is being asked.",
         "Bobbin", "Adds the code that matches the prompt."),
        ("Each tool call", "capture", "Tools run, files touched and tokens spent.",
         "Yupana · Desire Path", "Checks an edit against your policies and reports its impact. Records a failed call."),
        ("Stop", "stop decision", "Take the next item, report to the lead, or rest.",
         "Quipu", "Asks the agent to record what it learned."),
    ]
    st_top, st_h, tool_top, tool_h = 282, 112, 424, 142
    for x, (name, cmd, cap, tool, tcap) in zip(xs, points):
        cx = x + w / 2
        s.add(f'  <path d="M{cx} {line_y + 8} V{st_top}" stroke="{EDGE}" stroke-width="1.5"/>')
        s.add(f'  <circle cx="{cx}" cy="{line_y}" r="7" fill="{BG}" stroke="{GOLD}" stroke-width="2.5"/>')
        s.text(cx, line_y - 16, name, 13.5, INK, 700, anchor="middle")
        s.card(x, st_top, w, st_h, stroke=PINK, sw=1.2)
        s.text(x + 16, st_top + 24, "SHANTYTOWN", 9.5, PINK, 700, spacing="0.8")
        s.text(x + 16, st_top + 47, cmd, 13, INK, cls="m")
        s.para(x + 16, st_top + 70, cap, w - 30, 12.5)
        s.add(f'  <path d="M{cx} {st_top + st_h} V{tool_top}" stroke="{EDGE}" stroke-width="1.5"/>')
        s.card(x, tool_top, w, tool_h)
        s.text(x + 16, tool_top + 24, "STACK", 9.5, GOLD, 700, spacing="0.8")
        s.text(x + 16, tool_top + 47, tool, 14.5, GOLD, 700)
        s.para(x + 16, tool_top + 70, tcap, w - 30, 12.5)
    s.text(40, 598, "A registered hook survives every regeneration of the settings. With no stack tool registered, only the Shantytown row runs.", 12.5)
    return s.render()


def hosts():
    s = Svg(960, 600, (
        "One crew on two hosts. Each host has its own store, its own panes and its own timer running st fleet "
        "tend, and launches only the agents placed on it. The two hosts declare each other as peers in "
        "shantytown.toml and reach each other over SSH. A command for an agent on the other host, such as st go, "
        "st inbox or the st crew census, runs that host's own st over the SSH link. Both hosts read the same Quipu "
        "registry, which holds the members and the host each runs on, and the same board of work items. "
        "st ops doctor --deploy and st ops doctor --relay check the setup from both directions."))
    s.text(40, 52, "One crew on two hosts", 24, INK, 700)
    s.text(40, 78, "Each host runs only its own agents. A command for an agent on the other host runs that host's own st, over SSH.", 14)

    # Shared layer.
    s.card(190, 100, 580, 112, stroke=GOLD, fill="none", dash="5 6", rx=16)
    s.text(480, 122, "SHARED BY BOTH HOSTS", 10, GOLD, 700, anchor="middle", spacing="1.2")
    s.card(206, 132, 266, 68)
    s.text(222, 158, "Quipu registry", 15, GOLD, 700)
    s.text(222, 180, "Members, and the host each runs on.", 12, BODY)
    s.card(488, 132, 266, 68)
    s.text(504, 158, "One board", 15, GOLD, 700)
    s.text(504, 180, "One tracker, so an item has one owner.", 12, BODY)

    def host(x, name, agents, timer_note):
        s.card(x, 252, 330, 250, stroke=PINK, sw=1.4)
        s.text(x + 18, 280, "HOST", 9.5, PINK, 700, spacing="0.8")
        s.text(x + 60, 281, name, 13, INK, cls="m")
        s.card(x + 18, 296, 140, 84, fill="#1a1a2e")
        s.text(x + 30, 320, "Store", 14, INK, 700)
        s.para(x + 30, 340, "Cards, settings and its own shantytown.toml", 120, 11.5)
        s.card(x + 172, 296, 140, 84, fill="#1a1a2e")
        s.text(x + 184, 320, "Panes", 14, INK, 700)
        for n, a in enumerate(agents):
            s.text(x + 184, 340 + n * 16, a, 11.5, BODY, cls="m")
        s.card(x + 18, 394, 294, 92, fill="#1a1a2e")
        s.text(x + 30, 418, "Timer", 14, INK, 700)
        s.text(x + 84, 418, "st fleet tend", 12, PINK, cls="m")
        s.para(x + 30, 440, timer_note, 270, 11.5)

    host(30, "first", ["st-admin", "st-worker-a"], "Supervises the agents placed on this host and skips the rest.")
    host(600, "second", ["st-second-admin", "st-worker-b"], "Admits a launch against the other host's last census when it is down.")

    # Hosts read the shared layer.
    s.path("M150 248 V160 H178", "up")
    s.head(187, 160, "right", GOLD)
    s.path("M810 248 V160 H782", "up")
    s.head(773, 160, "left", GOLD)
    s.text(140, 150, "reads, writes", 12, GOLD, anchor="end")
    s.text(820, 150, "reads, writes", 12, GOLD)

    # SSH link.
    s.path("M372 350 H588", "pipe")
    s.head(596, 350, "right", CORAL)
    s.path("M588 392 H372", "pipe")
    s.head(364, 392, "left", CORAL)
    s.text(480, 318, "SSH", 16, INK, 700, anchor="middle")
    s.text(480, 338, "[host.peers.second]", 11.5, PINK, cls="m", anchor="middle")
    s.text(480, 380, "[host.peers.first]", 11.5, PINK, cls="m", anchor="middle")
    s.para(480, 424, "st go, st inbox and the st crew census cross here", 190, 12, BODY, anchor="middle")

    s.card(30, 522, 900, 56)
    s.text(48, 546, "Prove it from both hosts", 14, INK, 700)
    s.text(230, 546, "st ops doctor --deploy", 12, PINK, cls="m")
    s.text(410, 546, "st ops doctor --relay", 12, PINK, cls="m")
    s.text(584, 546, "st fleet roles sync --require-host-sync 1", 12, PINK, cls="m")
    s.text(48, 566, "An unreachable host is reported as unknown, never as an empty crew.", 12)
    return s.render()


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, fn in (("work-item-lifecycle", lifecycle), ("session-hooks", hooks), ("two-hosts", hosts)):
    (out / f"{name}.svg").write_text(fn())
    print("wrote", out / f"{name}.svg")
