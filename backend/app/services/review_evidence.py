"""Bind a human review to the product evidence actually presented to the reviewer."""
import hashlib
import json


def product_fingerprint(product) -> str:
    def ingredient(ing, seen):
        identity = ing.id if ing.id is not None else id(ing)
        if identity in seen:
            return {"cycle": identity}
        return {"id": ing.id, "name": ing.name, "tags": ing.tags, "ambiguous": ing.ambiguous,
                "components": [ingredient(c, seen | {identity}) for c in sorted(ing.components, key=lambda c: c.id or 0)]}
    evidence = {"id": product.id, "name": product.name, "tags": product.tags,
                "may_contain": product.may_contain, "data_complete": product.data_complete,
                "ingredients": [ingredient(i, set()) for i in sorted(product.ingredients, key=lambda i: i.id or 0)]}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
