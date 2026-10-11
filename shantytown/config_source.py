"""Opt-in, read-only deployment configuration with source-bound last-good data.

Bootstrap selectors stay local: a graph document cannot redirect its own reader.
The document is validated before it can replace the cache or a rendered file.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import warnings

from .quipu import QuipuRegistry

ENTITY_KEY = "SHANTY_CONFIG_ENTITY"
SERVER_KEY = "SHANTY_CONFIG_SERVER"
FRAGMENT_CLASS_KEY = "SHANTY_CONFIG_FRAGMENT_CLASS"
VALUE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#value"
IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^<>\s\"{}|^`\\]+")
MAX_BYTES = 1024 * 1024
_snapshot = ContextVar("st_config_source_snapshot", default=None)


def start_snapshot():
    return _snapshot.set({})


def end_snapshot(token):
    _snapshot.reset(token)


class SourceError(ValueError):
    """Configuration source could not be validated; never include response bodies."""


@dataclass(frozen=True)
class Projection:
    data: dict
    document: dict | None
    origins: dict[str, str]
    warning: str | None = None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("duplicate configuration key")
        result[key] = value
    return result


def parse(text):
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise SourceError("configuration exceeds the document budget")
    try:
        doc = json.loads(text, object_pairs_hook=_object)
    except (ValueError, TypeError):
        raise SourceError("configuration is not a unique-key JSON object") from None
    if (not isinstance(doc, dict) or set(doc) != {"version", "settings", "fragments"}
            or type(doc["version"]) is not int or doc["version"] != 1
            or not isinstance(doc["settings"], dict)
            or not isinstance(doc["fragments"], list)):
        raise SourceError("configuration requires version 1, settings and fragments")
    env = doc["settings"].get("env", {})
    if not isinstance(env, dict):
        raise SourceError("configuration env must be an object")
    for key in env:
        if (key in (ENTITY_KEY, SERVER_KEY, FRAGMENT_CLASS_KEY)
                or re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY", key, re.I)):
            raise SourceError("configuration cannot carry credentials or bootstrap selectors")
    if ("SHANTY_BACKEND" in env
            and env["SHANTY_BACKEND"] not in ("files", "beads", "br", "seeds", "forgejo")):
        raise SourceError("configuration declares an unknown tracker backend")
    ids = set()
    for fragment in doc["fragments"]:
        if (not isinstance(fragment, dict)
                or set(fragment) != {"id", "scope", "selector", "text"}
                or not all(isinstance(v, str) for v in fragment.values())
                or not IRI.fullmatch(fragment["id"])
                or fragment["id"] in ids
                or fragment["scope"] not in ("fleet", "role", "agent", "harness")
                or (fragment["scope"] == "fleet") != (fragment["selector"] == "")
                or "\x00" in fragment["text"]):
            raise SourceError("configuration contains an invalid instruction fragment")
        ids.add(fragment["id"])
    return doc


def merge(base, override, origins, source, prefix=""):
    """Local declarations override graph settings, recursively and per key."""
    result = dict(base)
    for key, value in override.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            previous = result.get(key, {})
            result[key] = merge(previous if isinstance(previous, dict) else {},
                                value, origins, source, path)
        else:
            result[key] = value
            origins[path] = source
    return result


def _fetch(server, entity, fragment_class=None):
    # No deployment root: using the normal root resolver here would recursively
    # load this very configuration. Both selectors were already resolved locally.
    client = QuipuRegistry(server=server, onto="urn:st:config:", timeout=1.0,
                           client_label="shantytown-config")
    rows = client._query_answer(
        f"SELECT ?value WHERE {{ <{entity}> <{VALUE}> ?value }}").exact()
    if len(rows) != 1 or not isinstance(rows[0].get("value"), str):
        raise SourceError("configuration source must have exactly one value")
    try:
        doc = json.loads(rows[0]["value"], object_pairs_hook=_object)
        refs = doc["fragments"]
    except (ValueError, TypeError, KeyError):
        raise SourceError("configuration is not a fragment-reference document") from None
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 128
            or not all(isinstance(ref, str) and IRI.fullmatch(ref) for ref in refs)
            or len(set(refs)) != len(refs)
            or not isinstance(fragment_class, str) or not IRI.fullmatch(fragment_class)):
        raise SourceError("configuration requires bounded refs and a governed fragment class")
    separator = "#" if "#" in fragment_class else "/" if "/" in fragment_class else ":"
    namespace = fragment_class.rsplit(separator, 1)[0] + separator
    values = " ".join(f"<{ref}>" for ref in refs)
    fragments = client._query_answer(
        f"SELECT ?id ?scope ?selector ?text WHERE {{ VALUES ?id {{ {values} }} "
        f"?id a <{fragment_class}> ; <{namespace}instructionScope> ?scope ; "
        f"<{namespace}instructionSelector> ?selector ; <{VALUE}> ?text }}").exact()
    by_id = {}
    for row in fragments:
        identity = row.get("id")
        if identity not in refs or identity in by_id:
            raise SourceError("fragment identity or cardinality mismatch")
        by_id[identity] = {"id": identity, "scope": row.get("scope"),
                           "selector": row.get("selector"), "text": row.get("text")}
    if set(by_id) != set(refs):
        raise SourceError("typed fragment read is incomplete")
    doc["fragments"] = [by_id[ref] for ref in refs]
    return json.dumps(doc)


def _store(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".last-good-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def project(root, local, validate, *, fetch=None):
    key = (str(root), json.dumps(local, sort_keys=True))
    memo = _snapshot.get()
    if memo is not None and key in memo:
        return memo[key]
    env = local.get("env", {})
    entity = env.get(ENTITY_KEY) or os.environ.get(ENTITY_KEY)
    origins = {}
    if not entity:
        return Projection(merge({}, local, origins, "toml"), None, origins)
    server = env.get(SERVER_KEY) or os.environ.get(SERVER_KEY)
    if not isinstance(entity, str) or not IRI.fullmatch(entity) or not server:
        raise SourceError("configuration source requires explicit server and entity")
    fragment_class = env.get(FRAGMENT_CLASS_KEY) or os.environ.get(FRAGMENT_CLASS_KEY)
    identity = hashlib.sha256(json.dumps([server, entity, fragment_class]).encode()).hexdigest()
    cache = Path(root) / "config-source" / f"{identity}.json"
    warning = None
    fresh = False
    try:
        text = (fetch or _fetch)(server, entity, fragment_class)
        document = parse(text)
        validate(document["settings"])
        fresh = True
    except Exception:  # A failed graph read must not prevent an existing launch.
        try:
            document = parse(cache.read_text())
            validate(document["settings"])
            warning = "Quipu config unavailable or invalid; using source-bound last-good"
        except Exception:
            document = None
            warning = "Quipu config unavailable or invalid; keeping local configuration/instructions"
    data = merge({}, document["settings"] if document else {}, origins,
                 "quipu" if fresh else "quipu:last-good")
    data = merge(data, local, origins, "toml")
    validate(data)
    if fresh:
        try:
            _store(cache, text)
        except OSError:
            warning = "Quipu config loaded but last-good cache could not be saved"
    if warning:
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
    result = Projection(data, document, origins, warning)
    if memo is not None:
        memo[key] = result
    return result


def render(document, agent, role, harness):
    """Stable scope order, exact fragment bytes; identity stays in local files."""
    selectors = {"fleet": "", "role": role, "agent": agent, "harness": harness}
    fragments = document["fragments"]
    return "".join(f["text"] for scope in selectors for f in fragments
                   if f["scope"] == scope and f["selector"] == selectors[scope])
