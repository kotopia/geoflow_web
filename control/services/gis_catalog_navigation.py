"""Shared read-only category navigation for central GIS administration."""
from __future__ import annotations


def _dicts(cur):
    names = [column[0] for column in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def category_tree(cur):
    """Return active L1/L2 nodes and their existing parent relationship.

    L1 remains a derived navigation axis.  No GIS definition table stores it.
    """
    cur.execute("""SELECT id::text,code,name,level FROM catalog.category_node
        WHERE level IN (1,2) AND active ORDER BY level,ord,code""")
    nodes = _dicts(cur)
    cur.execute("""SELECT relation.parent_id::text,relation.child_id::text
        FROM catalog.category_parent relation
        JOIN catalog.category_node parent ON parent.id=relation.parent_id
          AND parent.level=1 AND parent.active
        JOIN catalog.category_node child ON child.id=relation.child_id
          AND child.level=2 AND child.active
        ORDER BY parent.ord,parent.code,child.ord,child.code""")
    return {"nodes": nodes, "parents": _dicts(cur)}
