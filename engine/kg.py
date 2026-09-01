"""Knowledge-graph load, entity matching, traversal and fact generation.

Used at query time: detect which entities a question mentions, expand to their
graph neighbourhood, and emit human-readable facts (deterministic, no
hallucination) that get injected into the LLM context alongside retrieved text.
"""
from __future__ import annotations

import json
import re
import warnings
from functools import lru_cache
from typing import Dict, List, Set

import networkx as nx

from engine import config

# Friendly phrasing for each edge relation: (subject rel object).
_REL_PHRASE = {
    "owns": "{s} owns {o}",
    "team_owns": "{s} owns {o}",
    "member_of": "{s} is a member of {o}",
    "about": "{s} is about {o}",
    "affects": "{s} affects {o}",
    "assigned": "{s} is assigned to {o}",
    "blocks": "{s} blocks {o}",
    "relates_to": "{s} relates to {o}",
    "in_release": "{s} is part of {o}",
    "depends_on": "{s} depends on {o}",
}


@lru_cache(maxsize=1)
def load_graph() -> nx.DiGraph:
    if not config.GRAPH_FILE.exists():
        return nx.DiGraph()
    data = json.loads(config.GRAPH_FILE.read_text(encoding="utf-8"))
    # Accept either serialization key across networkx versions.
    if "edges" in data and "links" not in data:
        data = {**data, "links": data["edges"]}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return nx.node_link_graph(data, directed=True)


@lru_cache(maxsize=1)
def entity_vocab() -> Dict[str, str]:
    """Map a lowercased searchable token -> canonical node id."""
    g = load_graph()
    vocab: Dict[str, str] = {}
    for nid, attrs in g.nodes(data=True):
        vocab[nid.lower()] = nid
        label = str(attrs.get("label", "")).strip()
        if label:
            vocab[label.lower()] = nid
    # Common synonyms for releases (e.g. "v2.1" -> "REL-v2.1").
    for nid, attrs in g.nodes(data=True):
        if attrs.get("type") == "release":
            vocab[str(attrs.get("label", "")).lower()] = nid
    return vocab


def match_entities(question: str) -> List[str]:
    """Find graph entities referenced in the question via word-boundary matching."""
    q = question.lower()
    found: Set[str] = set()
    for token, nid in entity_vocab().items():
        if not token:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", q):
            found.add(nid)
    return sorted(found)


def expand(entities: List[str], hops: int = 2) -> Set[str]:
    """Return the entity set within `hops` of any seed (undirected reachability)."""
    g = load_graph()
    seen: Set[str] = set()
    frontier = {e for e in entities if e in g}
    seen |= frontier
    for _ in range(hops):
        nxt: Set[str] = set()
        for node in frontier:
            nxt |= set(g.successors(node)) | set(g.predecessors(node))
        frontier = nxt - seen
        seen |= frontier
    return seen


def facts_for(entities: List[str], hops: int = 1) -> List[str]:
    """Human-readable facts about the seed entities and their close neighbours."""
    g = load_graph()
    relevant = expand(entities, hops=hops) | {e for e in entities if e in g}
    facts: List[str] = []
    emitted: Set[str] = set()
    for u, v, attrs in g.edges(data=True):
        if u in relevant or v in relevant:
            rel = attrs.get("rel", "related_to")
            phrase = _REL_PHRASE.get(rel, "{s} " + rel + " {o}")
            sentence = phrase.format(s=u, o=v) + "."
            if sentence not in emitted:
                emitted.add(sentence)
                facts.append(sentence)
    return facts


def source_ids_for(entities: List[str], chunk_metas: List[dict], hops: int = 2) -> Set[str]:
    """Chunks whose entity_ids intersect the expanded entity neighbourhood."""
    relevant = expand(entities, hops=hops) | set(entities)
    ids: Set[str] = set()
    for meta in chunk_metas:
        if relevant.intersection(meta.get("entity_ids", [])):
            ids.add(meta["source_id"])
    return ids
