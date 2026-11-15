"""Explicit publish lineage; uncertain writes never trigger another create."""
import re


class LineageError(ValueError):
    pass


TRAILER = re.compile(r"^(Supersedes|Split-from|Folds|Stacked-on):\s*#([1-9][0-9]*)\s*$")


def declarations(body):
    result = []
    seen = set()
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = TRAILER.fullmatch(line)
        if not match:
            if re.match(r"^(Supersedes|Split-from|Folds|Stacked-on):", line):
                raise LineageError("lineage trailer must name one same-repository PR as #N")
            continue
        relation, number = match.group(1), int(match.group(2))
        if number in seen:
            raise LineageError("duplicate or conflicting predecessor declaration")
        seen.add(number)
        result.append({"relation": relation, "number": number})
    return result


def snapshot(api, repo, declaration, bead, candidate):
    number = declaration["number"]
    old = api(f"repos/{repo}/pulls/{number}")
    head = old.get("head") if isinstance(old, dict) else None
    if (not isinstance(head, dict) or not isinstance(head.get("sha"), str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head["sha"])
            or type(old.get("number")) is not int or old["number"] != number
            or old.get("state") not in {"open", "closed"}
            or old.get("html_url") != f"https://github.com/{repo}/pull/{number}"):
        raise LineageError("predecessor identity/state is unverified")
    body = old.get("body") or ""
    if not isinstance(body, str):
        raise LineageError("predecessor body is unverified")
    primary = re.findall(r"^Bead:\s*(\S+)\s*$", body, re.M)
    if primary != [bead]:
        raise LineageError("predecessor must declare the same primary work item")
    if head["sha"] == candidate["head"] or head.get("ref") == candidate["head_ref"]:
        raise LineageError("candidate cannot name itself as predecessor")
    if declaration["relation"] == "Stacked-on":
        if old["state"] != "open" or candidate["base"] != head["sha"]:
            raise LineageError("stack must target the open predecessor exact head")
    return {**declaration, "head": head["sha"], "state": old["state"],
            "body": old.get("body") or ""}


def prepare(api, repo, body, bead, candidate):
    return [snapshot(api, repo, d, bead, candidate) for d in declarations(body)]


def retire(api, patch, repo, plan, successor, bead, candidate):
    """Called only after the successor create response passed identity checks.

    GitHub has no conditional close. Recheck before and after, report a raced
    head as uncertain, and keep branches. Caller must preserve successor ID.
    """
    receipts = []
    for old in plan:
        if snapshot(api, repo, old, bead, candidate) != old:
            raise LineageError("predecessor changed after publish; reconcile existing successor")
        if old["relation"] == "Stacked-on":
            receipts.append({"number": old["number"], "action": "kept-open-stack"})
            continue
        if old["state"] == "closed":
            receipts.append({"number": old["number"], "action": "already-closed"})
            continue
        number = old["number"]
        api(f"repos/{repo}/issues/{number}/comments", {
            "body": f"{old['relation']} successor: {successor['html_url']}\n\n"
                    f"Work item: {bead}. Predecessor head: {old['head']}. Branch retained."})
        if snapshot(api, repo, old, bead, candidate) != old:
            raise LineageError("predecessor changed after pointer; reconcile before close")
        patch(f"repos/{repo}/pulls/{number}", {"state": "closed"})
        after = snapshot(api, repo, old, bead, candidate)
        if after != {**old, "state": "closed"}:
            raise LineageError("predecessor close/head outcome unverified")
        receipts.append({"number": number, "head": old["head"], "action": "closed"})
    return receipts
