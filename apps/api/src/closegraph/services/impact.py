from dataclasses import dataclass

@dataclass(frozen=True)
class Impact:
    affected: frozenset[str]
    independent: frozenset[str]
    unverifiable: bool


def dependency_impact(changed, edges, outputs, *, coverage_complete):
    """Edges must already be scope-filtered, version-pinned and evidenced.

    A cycle anywhere in the potentially affected scope prevents independence claims.
    """
    graph = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
    visiting, visited = set(), set()
    def cyclic(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(cyclic(n) for n in graph.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False
    unknown = not coverage_complete or any(cyclic(n) for n in list(graph))
    affected, pending = set(changed), list(changed)
    while pending:
        for target in graph.get(pending.pop(), ()):
            if target not in affected:
                affected.add(target)
                pending.append(target)
    return Impact(frozenset(affected), frozenset() if unknown else frozenset(set(outputs)-affected), unknown)
