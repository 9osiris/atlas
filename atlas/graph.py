"""the graph itself: nodes, typed edges, save/load, queries."""

import json
from collections import Counter, deque

from .extract import norm


class Graph:
    def __init__(self):
        # key -> {"name", "kind", "count", "sources"}
        self.nodes = {}
        # list of {"src", "rel", "dst", "weight", "sources"}
        self.edges = []

    def add_entity(self, name, kind="entity", source=None, count=True):
        key = norm(name)
        node = self.nodes.get(key)
        if node is None:
            node = {"name": name, "kind": kind, "count": 0, "sources": set()}
            self.nodes[key] = node
        if count:
            node["count"] += 1
        if source:
            node["sources"].add(source)
        return key

    def add_triple(self, subj, rel, obj, source=None):
        # triple endpoints were already counted as mentions by the
        # extractor, so they do not bump the count again here
        skey = self.add_entity(subj, source=source, count=False)
        okey = self.add_entity(obj, kind="concept" if rel == "is_a" else "entity",
                               source=source, count=False)
        for edge in self.edges:
            if edge["src"] == skey and edge["rel"] == rel and edge["dst"] == okey:
                edge["weight"] += 1
                if source:
                    edge["sources"].add(source)
                return edge
        edge = {"src": skey, "rel": rel, "dst": okey, "weight": 1,
                "sources": {source} if source else set()}
        self.edges.append(edge)
        return edge

    def find(self, name):
        """exact key match, else first name containing the query."""
        key = norm(name)
        if key in self.nodes:
            return key
        for k, node in self.nodes.items():
            if key in k:
                return k
        return None

    def neighbors(self, name, rel=None):
        """(relation, other name, weight, incoming) for each edge touching
        the node. incoming means the edge points at this node, so the
        printed direction is other --rel--> this."""
        key = self.find(name)
        if key is None:
            return []
        out = []
        for edge in self.edges:
            if edge["src"] == key and (rel is None or edge["rel"] == rel):
                out.append((edge["rel"], self.nodes[edge["dst"]]["name"],
                            edge["weight"], False))
            elif edge["dst"] == key and (rel is None or edge["rel"] == rel):
                out.append((edge["rel"], self.nodes[edge["src"]]["name"],
                            edge["weight"], True))
        out.sort(key=lambda t: (-t[2], t[0], t[1].lower()))
        return out

    def degree(self, name):
        return len(self.neighbors(name))

    def path(self, start, end):
        """shortest path as a list of (from, rel, to) steps, or None."""
        skey, ekey = self.find(start), self.find(end)
        if skey is None or ekey is None:
            return None
        if skey == ekey:
            return []
        prev = {skey: None}
        queue = deque([skey])
        while queue:
            cur = queue.popleft()
            for edge in self.edges:
                nxt, rel, flipped = None, None, False
                if edge["src"] == cur:
                    nxt, rel = edge["dst"], edge["rel"]
                elif edge["dst"] == cur:
                    nxt, rel, flipped = edge["src"], edge["rel"], True
                if nxt is None or nxt in prev:
                    continue
                prev[nxt] = (cur, rel, flipped)
                if nxt == ekey:
                    steps = []
                    node = ekey
                    while prev[node] is not None:
                        parent, rel, flipped = prev[node]
                        if flipped:
                            steps.append((self.nodes[node]["name"], rel,
                                          self.nodes[parent]["name"]))
                        else:
                            steps.append((self.nodes[parent]["name"], rel,
                                          self.nodes[node]["name"]))
                        node = parent
                    steps.reverse()
                    return steps
                queue.append(nxt)
        return None

    def top_nodes(self, n=10):
        ranked = sorted(self.nodes.items(),
                        key=lambda kv: (-kv[1]["count"], kv[1]["name"].lower()))
        return [(node["name"], node["count"]) for _, node in ranked[:n]]

    def stats(self):
        rels = Counter(e["rel"] for e in self.edges)
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "relations": dict(rels),
            "top": self.top_nodes(5),
        }

    def merge(self, other):
        for key, node in other.nodes.items():
            mine = self.nodes.get(key)
            if mine is None:
                self.nodes[key] = {"name": node["name"], "kind": node["kind"],
                                   "count": node["count"],
                                   "sources": set(node["sources"])}
            else:
                mine["count"] += node["count"]
                mine["sources"] |= set(node["sources"])
        for edge in other.edges:
            for mine in self.edges:
                if (mine["src"] == edge["src"] and mine["rel"] == edge["rel"]
                        and mine["dst"] == edge["dst"]):
                    mine["weight"] += edge["weight"]
                    mine["sources"] |= set(edge["sources"])
                    break
            else:
                self.edges.append({"src": edge["src"], "rel": edge["rel"],
                                   "dst": edge["dst"],
                                   "weight": edge["weight"],
                                   "sources": set(edge["sources"])})

    def to_dict(self):
        return {
            "version": 1,
            "nodes": {k: {"name": v["name"], "kind": v["kind"],
                          "count": v["count"],
                          "sources": sorted(v["sources"])}
                      for k, v in self.nodes.items()},
            "edges": [{"src": e["src"], "rel": e["rel"], "dst": e["dst"],
                       "weight": e["weight"], "sources": sorted(e["sources"])}
                      for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data):
        graph = cls()
        for key, node in data.get("nodes", {}).items():
            graph.nodes[key] = {"name": node["name"], "kind": node["kind"],
                                "count": node["count"],
                                "sources": set(node.get("sources", []))}
        for edge in data.get("edges", []):
            graph.edges.append({"src": edge["src"], "rel": edge["rel"],
                                "dst": edge["dst"], "weight": edge["weight"],
                                "sources": set(edge.get("sources", []))})
        return graph

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
