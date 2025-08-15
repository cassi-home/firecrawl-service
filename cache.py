"""
Custom caching system for property search results.

This module provides a global, persistent cache with time-based expiry
that works across multiple API requests and users.
"""
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from config import CACHE_EXPIRY_HOURS, Colors

# ==================================================================================
# WHY CUSTOM CACHE INSTEAD OF @lru_cache?
# ==================================================================================
# 
# 1. PERSISTENT ACROSS REQUESTS: @lru_cache only caches within function scope.
#    Our global cache persists across multiple API requests, preventing duplicate
#    searches for the same property from different users/sessions.
#
# 2. TIME-BASED EXPIRY: @lru_cache has no time-based expiration. Our cache 
#    automatically expires entries after 24 hours to ensure data freshness while
#    still providing significant credit savings for repeated searches.
#
# 3. MEMORY CONTROL: @lru_cache grows indefinitely. Our cache can be manually
#    cleared via the /clear_cache endpoint and naturally expires old entries.
#
# 4. SHARED STATE: Works across async functions and multiple concurrent requests.
# ==================================================================================

# Global in-memory cache - stores search results to prevent duplicate API calls
# Structure: {cache_key: {'data': search_results, 'timestamp': datetime_created}}
SEARCH_CACHE: Dict[str, Dict[str, Any]] = {}

def get_cache_key(address: str, city: str = None, state: str = None, zip_code: str = None) -> str:
    """
    Generate a unique cache key for address search results.
    
    Creates an MD5 hash of the normalized address components to ensure:
    - Case-insensitive matching ("Main St" == "main st")  
    - Consistent key generation for same logical address
    - Compact key storage (32-char hash vs long address strings)
    
    Args:
        address: Street address (required)
        city: City name (optional)
        state: State abbreviation (optional) 
        zip_code: ZIP code (optional)
    
    Returns:
        32-character MD5 hash string
        
    Example:
        "123 Main St, Boston, MA 02101" -> "a1b2c3d4e5f6..."
    """
    address_parts = [address.lower().strip()]
    if city:
        address_parts.append(city.lower().strip())
    if state:
        address_parts.append(state.lower().strip())
    if zip_code:
        address_parts.append(zip_code.strip())
    
    cache_string = "|".join(address_parts)
    return hashlib.md5(cache_string.encode()).hexdigest()

def is_cache_valid(cache_entry: Dict[str, Any]) -> bool:
    """
    Check if cached search result is still fresh (within expiry time).
    
    Args:
        cache_entry: Cache entry dict with 'timestamp' key
        
    Returns:
        True if cache entry is valid, False if expired or malformed
        
    Note:
        Expired entries are automatically ignored, allowing fresh searches.
    """
    if 'timestamp' not in cache_entry:
        return False
    
    cache_time = cache_entry['timestamp']
    expiry_time = cache_time + timedelta(hours=CACHE_EXPIRY_HOURS)
    return datetime.now() < expiry_time

def get_cached_result(address: str, city: str = None, state: str = None, zip_code: str = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached search result if available and valid.
    
    Args:
        address: Street address
        city: City name (optional)
        state: State abbreviation (optional)
        zip_code: ZIP code (optional)
        
    Returns:
        Cached search results dict if valid, None if not found or expired
    """
    cache_key = get_cache_key(address, city, state, zip_code)
    
    if cache_key in SEARCH_CACHE:
        cache_entry = SEARCH_CACHE[cache_key]
        if is_cache_valid(cache_entry):
            print(f"{Colors.GREEN}✓ Cache HIT for address (0 credits used){Colors.END}")
            return cache_entry['data']
        else:
            # Remove expired entry
            del SEARCH_CACHE[cache_key]
            print(f"{Colors.YELLOW}⚠ Cache entry expired, removed{Colors.END}")
    
    print(f"{Colors.BLUE}Cache MISS - will perform fresh search{Colors.END}")
    return None

def cache_search_result(
    search_results: Dict[str, Any], 
    address: str, 
    city: str = None, 
    state: str = None, 
    zip_code: str = None
) -> None:
    """
    Store search results in cache with current timestamp.
    
    Args:
        search_results: The search results to cache
        address: Street address
        city: City name (optional)
        state: State abbreviation (optional)
        zip_code: ZIP code (optional)
    """
    cache_key = get_cache_key(address, city, state, zip_code)
    
    SEARCH_CACHE[cache_key] = {
        'data': search_results,
        'timestamp': datetime.now()
    }
    
    print(f"{Colors.GREEN}✓ Cached search results for future requests{Colors.END}")

def get_cache_stats() -> Dict[str, Any]:
    """
    Get comprehensive cache statistics for monitoring.
    
    Returns:
        Dict with cache metrics including hit potential and expiry info
    """
    total_entries = len(SEARCH_CACHE)
    valid_entries = 0
    expired_entries = 0
    
    # Count valid vs expired entries
    for cache_entry in SEARCH_CACHE.values():
        if is_cache_valid(cache_entry):
            valid_entries += 1
        else:
            expired_entries += 1
    
    # Calculate cache hit potential
    cache_hit_potential = (valid_entries / max(1, total_entries)) * 100
    
    return {
        "total_entries": total_entries,
        "valid_entries": valid_entries, 
        "expired_entries": expired_entries,
        "cache_hit_potential": f"{cache_hit_potential:.1f}%",
        "expiry_hours": CACHE_EXPIRY_HOURS,
        "memory_usage_kb": len(str(SEARCH_CACHE)) / 1024 if SEARCH_CACHE else 0
    }

def clear_cache() -> Dict[str, Any]:
    """
    Clear all cached search results.
    
    Returns:
        Dict with information about cleared entries
    """
    global SEARCH_CACHE
    
    cache_count = len(SEARCH_CACHE)
    cache_stats = get_cache_stats()
    
    SEARCH_CACHE.clear()
    
    print(f"{Colors.CYAN}✓ Cleared {cache_count} cache entries{Colors.END}")
    
    return {
        "message": f"Cleared {cache_count} cache entries",
        "previous_stats": cache_stats,
        "cache_entries": 0
    }

def cleanup_expired_entries() -> int:
    """
    Remove expired cache entries to free memory.
    
    Returns:
        Number of expired entries removed
    """
    global SEARCH_CACHE
    
    expired_keys = []
    for cache_key, cache_entry in SEARCH_CACHE.items():
        if not is_cache_valid(cache_entry):
            expired_keys.append(cache_key)
    
    for key in expired_keys:
        del SEARCH_CACHE[key]
    
    if expired_keys:
        print(f"{Colors.YELLOW}🧹 Cleaned up {len(expired_keys)} expired cache entries{Colors.END}")
    
    return len(expired_keys)

def get_cache_entry_age(address: str, city: str = None, state: str = None, zip_code: str = None) -> Optional[timedelta]:
    """
    Get the age of a specific cache entry.
    
    Args:
        address: Street address
        city: City name (optional)
        state: State abbreviation (optional)
        zip_code: ZIP code (optional)
        
    Returns:
        timedelta representing age of cache entry, or None if not found
    """
    cache_key = get_cache_key(address, city, state, zip_code)
    
    if cache_key in SEARCH_CACHE:
        cache_entry = SEARCH_CACHE[cache_key]
        if 'timestamp' in cache_entry:
            return datetime.now() - cache_entry['timestamp']
    
    return None

# ==================================================================================
# CACHE MONITORING AND HEALTH FUNCTIONS
# ==================================================================================

def is_cache_healthy() -> bool:
    """Check if cache is functioning properly."""
    try:
        # Test basic cache operations
        test_key = "health_check_test"
        test_data = {"test": True, "timestamp": datetime.now()}
        
        # Store test entry
        SEARCH_CACHE[test_key] = test_data
        
        # Retrieve test entry
        retrieved = SEARCH_CACHE.get(test_key)
        
        # Clean up test entry
        if test_key in SEARCH_CACHE:
            del SEARCH_CACHE[test_key]
        
        return retrieved is not None and retrieved.get("test") is True
        
    except Exception:
        return False

def get_cache_health_report() -> Dict[str, Any]:
    """
    Get comprehensive cache health and performance report.
    
    Returns:
        Dict with health status, performance metrics, and recommendations
    """
    stats = get_cache_stats()
    is_healthy = is_cache_healthy()
    
    # Performance assessment
    hit_rate = float(stats["cache_hit_potential"].rstrip('%'))
    performance_rating = "excellent" if hit_rate >= 70 else "good" if hit_rate >= 50 else "poor"
    
    # Memory usage assessment
    memory_kb = stats["memory_usage_kb"]
    memory_status = "high" if memory_kb > 1024 else "normal" if memory_kb > 100 else "low"
    
    return {
        "health_status": "healthy" if is_healthy else "unhealthy",
        "performance_rating": performance_rating,
        "memory_status": memory_status,
        "statistics": stats,
        "recommendations": _get_cache_recommendations(stats, hit_rate, memory_kb)
    }

def _get_cache_recommendations(stats: Dict, hit_rate: float, memory_kb: float) -> list:
    """Generate cache optimization recommendations."""
    recommendations = []
    
    if hit_rate < 30:
        recommendations.append("Consider increasing cache expiry time to improve hit rate")
    
    if stats["expired_entries"] > stats["valid_entries"]:
        recommendations.append("Run cleanup_expired_entries() to free memory")
    
    if memory_kb > 2048:  # > 2MB
        recommendations.append("Cache memory usage is high, consider reducing expiry time")
    
    if stats["total_entries"] == 0:
        recommendations.append("Cache is empty - monitor for proper caching of search results")
    
    if not recommendations:
        recommendations.append("Cache is performing optimally")
    
    return recommendations
