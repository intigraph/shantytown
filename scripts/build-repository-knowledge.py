#!/usr/bin/env python3
"""Render reviewed summaries onto existing indexed pointers, never new identities."""

import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

A = "http://aegis.gastown.local/ontology/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
PROV = "http://www.w3.org/ns/prov#"
XSD = "http://www.w3.org/2001/XMLSchema#"
KINDS = {"idea", "interface", "decision", "start-here"}
PROPERTIES = {"interfaceKind", "publicName", "status", "supersessionStatus", "startHereOrder", "glossaryTerm"}


# This exception is an explicit reviewed contract for one high-churn interface,
# not permission to silently rebind any other record's source witness.
CLI_SOURCE = "shantytown/cli.py"
CLI_SUBJECT = A + "code/shantytown/shantytown%2Fcli.py"
CLI_SUMMARY = "docs/knowledge/cli-summary.md"


def witness_bytes(source, path):
    if not isinstance(path, str):
        raise ValueError("source witness path must be explicit")
    witness = source / path
    if (Path(path).is_absolute() or ".." in Path(path).parts
            or not witness.resolve().is_relative_to(source.resolve())):
        raise ValueError("source witness escaped: " + path)
    return witness.read_bytes()


def record_content(source, record):
    content = witness_bytes(source, record["source"])
    digest = hashlib.sha256(content).hexdigest()
    if "source_hash_mode" not in record:
        if "summary_source" in record or "summary_sha256" in record:
            raise ValueError("summary witness requires explicit source hash mode")
        if digest != record.get("source_sha256"):
            raise ValueError("source witness changed: " + record["source"])
        return digest, record["summary"]
    if record["source_hash_mode"] != "release-bytes":
        raise ValueError("unknown source hash mode")
    if "source_sha256" in record or "summary" in record:
        raise ValueError("mixed source or summary witness modes")
    if (record["source"] != CLI_SOURCE or record.get("subject") != CLI_SUBJECT
            or record.get("kind") != "interface"):
        raise ValueError("release-byte source is not the approved CLI interface")
    if record.get("summary_source") != CLI_SUMMARY:
        raise ValueError("summary source is not the approved stable anchor")
    summary = witness_bytes(source, record["summary_source"])
    if hashlib.sha256(summary).hexdigest() != record.get("summary_sha256"):
        raise ValueError("summary witness changed")
    # sourceHash identifies published bytes. Summary review is separately bound
    # to the strict anchor; neither witness renews the review date.
    return digest, summary.decode("utf-8").strip()


def render(source, revision, lookup):
    source = Path(source)
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("release revision must be explicit")
    registry = json.loads((source / "docs/knowledge/repository-knowledge.json").read_text())
    reviewed = datetime.datetime.fromisoformat(registry["reviewed_at"].replace("Z", "+00:00"))
    age = registry["max_age_seconds"]
    if reviewed.tzinfo is None or type(age) is not int or age <= 0:
        raise ValueError("freshness requires an explicit UTC review time and positive seconds")
    after = (reviewed + datetime.timedelta(seconds=age)).isoformat().replace("+00:00", "Z")
    records = registry["records"]
    if {record["kind"] for record in records} != KINDS:
        raise ValueError("ideas/interfaces/decisions/start-here inventory incomplete")
    lines, seen = [], set()

    def fact(subject, predicate, obj, iri=False, datatype=None):
        if iri:
            if not re.fullmatch(r'[^\s<>"{}|\\^`]+:[^\s<>"{}|\\^`]*', obj):
                raise ValueError("invalid referenced IRI")
            value = "<" + obj + ">"
        else:
            value = json.dumps(str(obj), ensure_ascii=False)
            if datatype:
                value += "^^<" + datatype + ">"
        lines.append("<" + subject + "> <" + predicate + "> " + value + " .")

    for record in records:
        path = record["source"]
        digest, summary = record_content(source, record)
        subject = record["subject"]
        bases = (A + "doc/shantytown/" + quote(path, safe=""), A + "code/shantytown/" + quote(path, safe=""))
        if not any(subject == base or subject.startswith(base + "#") for base in bases):
            raise ValueError("subject is not the source-backed indexed pointer")
        # lookup must use the actual index: a deterministic-looking guessed IRI
        # is not an identity proof. Never mint another node when it is absent.
        label = lookup(subject)
        if not isinstance(label, str) or not label:
            raise ValueError("source pointer absent or ambiguous in actual index: " + subject)
        if (subject, record["kind"]) in seen:
            raise ValueError("duplicate knowledge record")
        seen.add((subject, record["kind"]))
        if record.get("type") not in ("Concept", "DecisionRecord", None):
            raise ValueError("unsupported knowledge type")
        fact(subject, RDFS + "label", label)
        fact(subject, A + "filePath", path)
        if record.get("type"):
            fact(subject, RDF + "type", A + record["type"], iri=True)
        if (
            not summary.strip()
            or len(summary) > 1000
            or re.search(r"\b[\w-]+\.(?:svc|lan)\b|/home/|\baegis-[A-Za-z0-9]", summary)
        ):
            raise ValueError("unreviewed or private summary")
        fact(subject, RDFS + "comment", summary)
        fact(subject, A + "knowledgeKind", record["kind"])
        fact(subject, A + "sourceHash", digest)
        fact(subject, A + "reviewAfter", after, datatype=XSD + "dateTime")
        fact(subject, A + "maxAge", age, datatype=XSD + "integer")
        fact(subject, "http://purl.org/dc/terms/modified", registry["reviewed_at"], datatype=XSD + "dateTime")
        fact(
            subject,
            PROV + "wasDerivedFrom",
            "https://github.com/scbrown/shantytown/blob/" + revision + "/" + path,
            iri=True,
        )
        for key, value in record.get("properties", {}).items():
            if key not in PROPERTIES:
                raise ValueError("unknown content property")
            if key == "startHereOrder":
                if not str(value).isdigit() or int(value) <= 0:
                    raise ValueError("start-here order must be a positive integer")
                fact(subject, A + key, int(value), datatype=XSD + "integer")
            else:
                fact(subject, A + key, value, iri=(key == "glossaryTerm"))
        for dependency in record.get("depends_on", []):
            fact(subject, A + "depends_on", dependency, iri=True)
        for term in record.get("see_also", []):
            fact(subject, RDFS + "seeAlso", term, iri=True)
    return "\n".join(sorted(set(lines))) + "\n"
