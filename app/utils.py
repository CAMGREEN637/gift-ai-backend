def validate_gifts(gifts):
    required = {"name", "price", "reason", "category"}
    return [
        g for g in gifts
        if isinstance(g, dict) and required.issubset(g.keys())
    ]