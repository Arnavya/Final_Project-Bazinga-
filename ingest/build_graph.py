"""Build the knowledge graph (entities + relationships) with networkx.

Nodes carry a `type` (service/person/team/release/incident/ticket/commit) and a
`label`. Edges carry a `rel`. Persisted as node-link JSON. The graph answers
relational/multi-hop questions (who owns, what blocks, what caused) deterministically.
"""
from __future__ import annotations

import json

import networkx as nx

from engine import config


def _load(name: str):
    return json.loads((config.SOURCES_DIR / name).read_text(encoding="utf-8"))


def build_graph() -> nx.DiGraph:
    g = nx.DiGraph()

    def node(nid: str, ntype: str, label: str = "") -> None:
        if not nid:
            return
        if nid in g.nodes:
            # Upgrade a placeholder label, but never clobber a real one.
            if label and g.nodes[nid].get("label", nid) == nid:
                g.nodes[nid]["label"] = label
            return
        g.add_node(nid, type=ntype, label=label or nid)

    services = _load("services.json")
    for s in services:
        node(s["name"], "service", s["name"])
        node(s["team"], "team", s["team"])
        node(s["owner"], "person", s["owner"])
        g.add_edge(s["owner"], s["name"], rel="owns")
        g.add_edge(s["owner"], s["team"], rel="member_of")
        g.add_edge(s["team"], s["name"], rel="team_owns")
        for dep in s.get("depends_on", []):
            node(dep, "service")
            g.add_edge(s["name"], dep, rel="depends_on")

    for r in _load("releases.json"):
        node(r["id"], "release", r["name"])
    for i in _load("incidents.json"):
        node(i["id"], "incident", i["title"])
        node(i["service"], "service", i["service"])
        g.add_edge(i["id"], i["service"], rel="affects")

    for t in _load("tickets.json"):
        node(t["id"], "ticket", t["title"])
        node(t["service"], "service", t["service"])
        node(t["owner"], "person", t["owner"])
        g.add_edge(t["id"], t["service"], rel="about")
        g.add_edge(t["owner"], t["id"], rel="assigned")
        for rel_release in t.get("blocks", []):
            node(rel_release, "release")
            g.add_edge(t["id"], rel_release, rel="blocks")
        for inc in t.get("relates", []):
            node(inc, "incident")
            g.add_edge(t["id"], inc, rel="relates_to")

    for c in _load("commits.json"):
        node(c["id"], "commit", c["id"])
        node(c["service"], "service", c["service"])
        g.add_edge(c["id"], c["service"], rel="about")
        if c.get("release"):
            node(c["release"], "release")
            g.add_edge(c["id"], c["release"], rel="in_release")

    return g


def main() -> None:
    config.ensure_dirs()
    g = build_graph()
    # Call without the `edges=` kwarg for compatibility across networkx versions;
    # the reader (engine/kg.py) accepts either the "links" or "edges" key.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = nx.node_link_data(g)
    config.GRAPH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[build_graph] {g.number_of_nodes()} nodes, {g.number_of_edges()} edges "
          f"-> {config.GRAPH_FILE.name}")


if __name__ == "__main__":
    main()
