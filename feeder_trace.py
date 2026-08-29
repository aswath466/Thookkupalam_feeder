"""
Traces electrical connectivity outward from each feeder's source node(s),
assigning a feeder id to every node/edge that is actually energised from
that source right now (given current switch_state values on edges).

Feeder 2 (Pambadumpara) has two physical entry points (node 108 and node
388 - see README, "apparent ring feeder"), so this traces from ALL of a
feeder's registered sources (feeder_sources table) simultaneously, rather
than a single source_node_id. That also means a node/edge fed from either
end of the ring gets colored correctly instead of only the first root
being honoured.

Traversal rule:
  - non-switch edges (is_switch = 0) are always passable
  - switch edges are passable only when switch_state == 'closed'
    (lowercase - matches the values stored in this schema)
  - traversal stops (without error) if it reaches another feeder's
    source node - that's a normal tie point, not a fault
"""
from db import query


def trace_feeders():
    nodes = query("SELECT id, type FROM nodes")
    edges = query("SELECT id, node_a_id, node_b_id, is_switch, switch_state FROM edges")
    feeders = query("SELECT id FROM feeders")
    feeder_sources = query("SELECT feeder_id, node_id FROM feeder_sources")

    source_ids = {n["id"] for n in nodes if n["type"] == "source"}

    sources_by_feeder = {}
    for fs in feeder_sources:
        sources_by_feeder.setdefault(fs["feeder_id"], []).append(fs["node_id"])

    adj = {}
    for e in edges:
        a, b = e["node_a_id"], e["node_b_id"]
        adj.setdefault(a, []).append(e)
        adj.setdefault(b, []).append(e)

    node_colors = {}
    edge_colors = {}

    for feeder in feeders:
        fid = feeder["id"]
        starts = sources_by_feeder.get(fid, [])
        if not starts:
            continue  # feeder has no trace root(s) configured yet

        seen_nodes = set()
        stack = []
        for start in starts:
            if start not in seen_nodes:
                seen_nodes.add(start)
                node_colors[start] = fid
                stack.append(start)

        while stack:
            cur = stack.pop()
            for e in adj.get(cur, []):
                other = e["node_b_id"] if e["node_a_id"] == cur else e["node_a_id"]

                if e["is_switch"] and e["switch_state"] != "closed":
                    continue  # open switch - do not propagate through it

                if other in seen_nodes:
                    # still color the connecting edge if it wasn't colored yet
                    edge_colors.setdefault(e["id"], fid)
                    continue

                # don't walk past another feeder's own source (unless it's
                # also one of this feeder's own start nodes, handled above)
                if other in source_ids and other not in starts:
                    edge_colors[e["id"]] = fid
                    continue

                seen_nodes.add(other)
                node_colors[other] = fid
                edge_colors[e["id"]] = fid
                stack.append(other)

    return node_colors, edge_colors


def trace_feeder_reach(nodes, edges, state_overrides=None):
    """Returns {node_id: set(feeder_id, ...)} - every feeder that can
    currently reach each node, given the current switch_state values
    (or, for a hypothetical "what if I close this switch" check, the
    optional per-edge state_overrides).

    This is the interlock building block: a node reachable from more
    than one feeder at once (see find_parallel_feed_conflicts below) is
    a parallel-feed hazard. Same idea as network_functions.py's
    trace_feeder_reach() on the Erattayar app, adapted for this schema's
    feeder_sources table (multiple roots per feeder) and lowercase
    'open'/'closed' state values.
    """
    state_overrides = state_overrides or {}
    feeders = query("SELECT id FROM feeders")
    feeder_sources = query("SELECT feeder_id, node_id FROM feeder_sources")
    source_ids = {n["id"] for n in nodes if n["type"] == "source"}

    sources_by_feeder = {}
    for fs in feeder_sources:
        sources_by_feeder.setdefault(fs["feeder_id"], []).append(fs["node_id"])

    adj = {}
    edge_state = {}
    for e in edges:
        state = state_overrides.get(e["id"], e["switch_state"])
        edge_state[e["id"]] = (e["is_switch"], state)
        a, b = e["node_a_id"], e["node_b_id"]
        adj.setdefault(a, []).append(e)
        adj.setdefault(b, []).append(e)

    node_feeders = {n["id"]: set() for n in nodes}

    for feeder in feeders:
        fid = feeder["id"]
        starts = sources_by_feeder.get(fid, [])
        if not starts:
            continue

        visited = set()
        stack = []
        for start in starts:
            if start not in visited:
                visited.add(start)
                node_feeders[start].add(fid)
                stack.append(start)

        while stack:
            cur = stack.pop()
            for e in adj.get(cur, []):
                other = e["node_b_id"] if e["node_a_id"] == cur else e["node_a_id"]
                is_switch, state = edge_state[e["id"]]

                if is_switch and state != "closed":
                    continue  # open switch - do not propagate through it

                if other in source_ids and other not in starts:
                    continue  # normal tie point - stop at another feeder's own source

                if other in visited:
                    continue

                visited.add(other)
                node_feeders[other].add(fid)
                stack.append(other)

    return node_feeders


def find_parallel_feed_conflicts(nodes, feeders, node_feeders):
    """Nodes reachable from more than one feeder at once - a real hazard
    to flag (it would put two live sources in parallel through
    whatever's sitting at that node)."""
    feeder_name_by_id = {f["id"]: f["name"] for f in feeders}
    conflicts = []
    for n in nodes:
        feeds = node_feeders.get(n["id"], set())
        if len(feeds) > 1:
            conflicts.append({
                "id": n["id"],
                "name": n["name"],
                "type": n["type"],
                "feeders": [feeder_name_by_id[fid] for fid in sorted(feeds)],
            })
    return conflicts
