import random
from typing import List, Callable, Dict, Any


def weighted_shuffle(rows: List[Dict[str, Any]], weight_fn: Callable, bias_factor: float = 1.0) -> List[Dict[str, Any]]:
    if not rows or bias_factor <= 0:
        random.shuffle(rows)
        return rows
    
    weights = [weight_fn(r) for r in rows]
    total = sum(weights)
    if total == 0:
        random.shuffle(rows)
        return rows
    
    probs = [w / total for w in weights]
    
    n = len(rows)
    result = []
    available = list(range(n))
    
    for _ in range(n):
        if not available:
            break
        
        selected = random.choices(available, weights=[probs[i] for i in available], k=1)[0]
        result.append(rows[selected])
        available.remove(selected)
    
    return result
