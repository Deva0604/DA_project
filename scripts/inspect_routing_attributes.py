from pathlib import Path
import networkx as nx
from collections import Counter

path = Path("data/processed/saferoute_routing_graph_v3.graphml")

print("Loading routing graph with NetworkX...")
G = nx.read_graphml(
    path,
    node_type=int,
    force_multigraph=True,
)

print(f"\nNodes: {G.number_of_nodes():,}")
print(f"Edges: {G.number_of_edges():,}")

attribute_counts = Counter()
attribute_types = {}

for _, _, _, data in G.edges(keys=True, data=True):
    for name, value in data.items():
        attribute_counts[name] += 1
        attribute_types.setdefault(name, Counter())[type(value).__name__] += 1

print("\nEDGE ATTRIBUTES")
print("-" * 60)

for name, count in sorted(attribute_counts.items()):
    print(f"\n{name}: present on {count:,} edges")
    print("  Types:", dict(attribute_types[name]))

print("\nSAMPLE EDGE")
print("-" * 60)

for u, v, key, data in list(G.edges(keys=True, data=True))[:1]:
    print("From:", u)
    print("To:", v)
    print("Key:", key)

    for name, value in sorted(data.items()):
        print(f"  {name}: {value!r} ({type(value).__name__})")

print("\nInspection complete.")
