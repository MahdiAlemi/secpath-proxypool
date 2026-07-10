import statistics
from datetime import datetime, timezone


def compute_cost(alive_hits, fail_hits, speed_ms, speed_history, last_alive, last_fail, consecutive_fails=0, status='untested', current_cost=None):
    """
    Cost: 0.0 to 1.0 (LOWER IS BETTER)
    
    Returns: (cost, is_cooling, latency_score, reliability, jitter_score, recency_score, previous_cost)
    
    Only alive proxies get calculated cost. All other statuses get cost = 1.0 (worst).
    previous_cost preserves the last calculated cost for historical analysis.
    
    Weights (for alive only):
    - Latency: 40%
    - Reliability: 40%
    - Jitter: 15%
    - Recency: 5%
    """
    
    # Only alive proxies have meaningful cost
    if status != 'alive':
        # For non-alive, return 1.0 but preserve previous_cost for historical analysis
        return 1.0, 0, 0.0, 0.0, 0.0, 0.0, current_cost
    
    # 1. Reliability (40%) - success rate
    total = (alive_hits or 0) + (fail_hits or 0)
    reliability = (alive_hits or 0) / total if total > 0 else 0
    failure_rate = 1 - reliability
    
    # 2. Latency (40%) - normalized (5000ms = max penalty)
    latency_score = min((speed_ms or 5000) / 5000, 1.0)
    
    # 3. Jitter (15%) - consistency/variance
    jitter_score = calculate_jitter(speed_history, speed_ms)
    
    # 4. Recency (5%) - time decay (24h = max penalty)
    recency_score = calculate_recency(last_alive)
    
    # Weighted sum
    cost = (latency_score * 0.40) + \
           (failure_rate * 0.40) + \
           (jitter_score * 0.15) + \
           (recency_score * 0.05)
    
    # For alive proxies, previous_cost equals current calculated cost
    return round(cost, 4), 0, round(latency_score, 4), round(reliability, 4), round(jitter_score, 4), round(recency_score, 4), round(cost, 4)


def calculate_jitter(speed_history, current_speed):
    """
    Calculate jitter from speed history.
    Uses hybrid approach: builds accuracy over time.
    """
    all_speeds = list(speed_history or [])
    if current_speed:
        all_speeds.append(current_speed)
    
    if len(all_speeds) >= 2:
        # Calculate standard deviation, normalize (500ms = max)
        return min(statistics.stdev(all_speeds) / 500, 1.0)
    
    # Default middle ground when no history
    return 0.5


def calculate_recency(last_alive):
    """
    Calculate recency penalty.
    More time since last successful check = higher penalty.
    """
    if not last_alive:
        return 1.0  # Max penalty if never alive
    
    try:
        if isinstance(last_alive, str):
            last_alive = datetime.fromisoformat(last_alive.replace('Z', '+00:00'))
        
        hours = (datetime.now(timezone.utc) - last_alive).total_seconds() / 3600
        # 24 hours = max penalty
        return min(hours / 24, 1.0)
    except Exception:
        return 1.0


def runtime_health_rank(row, max_total_checks=1) -> float:
    """Legacy function for shuffle bias during monitoring"""
    alive = row.get("alive_hits") or 0
    fails = row.get("fail_hits") or 0
    total = alive + fails
    
    if total == 0:
        return 0.1
    
    alive_ratio = alive / max(total, 1)
    fail_ratio = fails / max(total, 1)
    
    health = alive_ratio * 1.0 - fail_ratio * 2.0
    
    speed = row.get("speed_ms")
    if speed and speed < 1000:
        health += 0.5
    elif speed and speed > 5000:
        health -= 0.5
    
    return max(0.01, health + 1.0)
