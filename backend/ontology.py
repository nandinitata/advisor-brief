"""A small financial knowledge graph.

It is deliberately shallow but real: it connects a client to what they hold, a
holding to its sector and the macro factors it reacts to, and each factor to the
FRED series that measures it. The retriever walks these edges so a question like
"what should I flag to the Patels about rates" can reach the right filings and
the right macro readings without the model guessing the connections.

    client --holds--> ticker --in_sector--> sector
                         |--sensitive_to--> factor --measured_by--> series

Bonds are a synthetic holding tied straight to rates and inflation, since the
demo portfolios carry a bond sleeve.
"""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from clients import CLIENTS
from universe import SERIES_TO_FACTOR, UNIVERSE

GRAPH_PATH = Path(__file__).parent / "data" / "ontology.json"

# the bond sleeve: not a filing-bearing ticker, just factor exposure
BONDS_FACTORS = ["rates", "inflation"]


def build() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    for ticker, (name, sector, factors) in UNIVERSE.items():
        g.add_node(ticker, kind="ticker", name=name)
        g.add_node(sector, kind="sector")
        g.add_edge(ticker, sector, rel="in_sector")
        for factor in factors:
            g.add_node(factor, kind="factor")
            g.add_edge(ticker, factor, rel="sensitive_to")

    g.add_node("BONDS", kind="ticker", name="Bond sleeve")
    for factor in BONDS_FACTORS:
        g.add_node(factor, kind="factor")
        g.add_edge("BONDS", factor, rel="sensitive_to")

    for series_id, factor in SERIES_TO_FACTOR.items():
        g.add_node(series_id, kind="series")
        g.add_node(factor, kind="factor")
        g.add_edge(factor, series_id, rel="measured_by")

    for cid, client in CLIENTS.items():
        g.add_node(cid, kind="client", name=client["name"])
        for h in client["holdings"]:
            g.add_edge(cid, h["ticker"], rel="holds", weight=h["weight"])

    return g


def save(g: nx.MultiDiGraph) -> None:
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_PATH.write_text(json.dumps(nx.node_link_data(g, edges="links")))


def load() -> nx.MultiDiGraph:
    data = json.loads(GRAPH_PATH.read_text())
    return nx.node_link_graph(data, multigraph=True, directed=True, edges="links")


# ---- query helpers used by the retriever ----

def tickers_for_client(g: nx.MultiDiGraph, client_id: str) -> list[str]:
    return [v for _, v, d in g.out_edges(client_id, data=True) if d.get("rel") == "holds"]


def factors_for_client(g: nx.MultiDiGraph, client_id: str) -> list[str]:
    factors: set[str] = set()
    for ticker in tickers_for_client(g, client_id):
        for _, v, d in g.out_edges(ticker, data=True):
            if d.get("rel") == "sensitive_to":
                factors.add(v)
    return sorted(factors)


def series_for_factors(g: nx.MultiDiGraph, factors: list[str]) -> list[str]:
    series: list[str] = []
    for factor in factors:
        for _, v, d in g.out_edges(factor, data=True):
            if d.get("rel") == "measured_by":
                series.append(v)
    return sorted(set(series))


def tickers_for_factor(g: nx.MultiDiGraph, factor: str, within: list[str]) -> list[str]:
    """Which of the client's holdings react to this factor."""
    hits = []
    for ticker in within:
        for _, v, d in g.out_edges(ticker, data=True):
            if d.get("rel") == "sensitive_to" and v == factor:
                hits.append(ticker)
    return hits
