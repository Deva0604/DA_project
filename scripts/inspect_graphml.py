from pathlib import Path
import xml.etree.ElementTree as ET

path = Path("data/processed/saferoute_routing_graph_v3.graphml")

if not path.exists():
    print("ERROR: GraphML file not found:", path)
    raise SystemExit(1)

print("GraphML file:", path)
print("Size MB:", round(path.stat().st_size / (1024 * 1024), 2))

root = ET.parse(path).getroot()
ns = {"g": "http://graphml.graphdrawing.org/xmlns"}

definitions = {}

for item in root.findall("g:key", ns):
    definitions[item.attrib["id"]] = {
        "name": item.attrib.get("attr.name"),
        "type": item.attrib.get("attr.type"),
    }

print("\nAttribute definitions:")
for key_id, definition in definitions.items():
    print(key_id, definition)

print("\nSelected edge attributes:")
wanted = {
    "travel_time",
    "length",
    "dynamic_risk",
    "risk_source",
    "road_closure",
}
count = 0

for edge in root.findall(".//g:edge", ns):
    for item in edge.findall("g:data", ns):
        key_id = item.attrib.get("key")
        definition = definitions.get(key_id, {})
        name = definition.get("name", key_id)

        if name in wanted:
            print(
                "name =", name,
                "| declared type =", definition.get("type"),
                "| value =", repr(item.text)
            )
            count += 1

            if count >= 20:
                break

    if count >= 20:
        break

print("\nInspection complete.")
