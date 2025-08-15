"""
Credit tracking and management for Firecrawl API usage.

This module provides credit tracking, limits enforcement, and usage monitoring
to prevent exceeding monthly credit allowances.
"""
from typing import Dict, Any, Optional
from config import MAX_CREDITS_PER_REQUEST, Colors

class CreditTracker:
    """
    Tracks credit usage for a single request with limits enforcement.
    
    Provides real-time credit tracking, limit checking, and usage reporting
    to prevent exceeding per-request credit budgets.
    """
    
    def __init__(self, max_credits_per_request: int = MAX_CREDITS_PER_REQUEST):
        """
        Initialize credit tracker with specified limit.
        
        Args:
            max_credits_per_request: Maximum credits allowed for this request
        """
        self.credits_used = 0
        self.max_credits = max_credits_per_request
        self.phase_usage: Dict[str, int] = {
            "search": 0,
            "extract": 0,
            "validation": 0
        }
        
    def add_credits(self, count: int, phase: str = "unknown") -> bool:
        """
        Add credits to the usage counter.
        
        Args:
            count: Number of credits to add
            phase: Phase where credits were used (search, extract, validation)
            
        Returns:
            True if credits were added successfully, False if would exceed limit
        """
        if self.can_use_credits(count):
            self.credits_used += count
            if phase in self.phase_usage:
                self.phase_usage[phase] += count
            else:
                self.phase_usage[phase] = count
            
            print(f"{Colors.BLUE}Used {count} credits in {phase} phase (total: {self.credits_used}/{self.max_credits}){Colors.END}")
            return True
        else:
            print(f"{Colors.RED}⚠ Cannot use {count} credits - would exceed limit ({self.credits_used + count} > {self.max_credits}){Colors.END}")
            return False
        
    def can_use_credits(self, count: int) -> bool:
        """
        Check if specified number of credits can be used without exceeding limit.
        
        Args:
            count: Number of credits to check
            
        Returns:
            True if credits can be used, False if would exceed limit
        """
        return (self.credits_used + count) <= self.max_credits
        
    def get_remaining(self) -> int:
        """
        Get number of credits remaining in budget.
        
        Returns:
            Number of credits remaining (0 if at or over limit)
        """
        return max(0, self.max_credits - self.credits_used)
    
    def get_usage_percentage(self) -> float:
        """
        Get current usage as percentage of limit.
        
        Returns:
            Usage percentage (0-100+, can exceed 100 if over limit)
        """
        return (self.credits_used / self.max_credits) * 100 if self.max_credits > 0 else 0
    
    def is_near_limit(self, threshold: float = 80.0) -> bool:
        """
        Check if credit usage is near the limit.
        
        Args:
            threshold: Percentage threshold (default 80%)
            
        Returns:
            True if usage is at or above threshold
        """
        return self.get_usage_percentage() >= threshold
    
    def is_over_limit(self) -> bool:
        """
        Check if credit usage has exceeded the limit.
        
        Returns:
            True if over limit
        """
        return self.credits_used > self.max_credits
    
    def get_status_report(self) -> Dict[str, Any]:
        """
        Get comprehensive credit usage report.
        
        Returns:
            Dict with usage statistics, limits, and status indicators
        """
        percentage = self.get_usage_percentage()
        
        # Determine status
        if self.is_over_limit():
            status = "over_limit"
            status_color = Colors.RED
        elif self.is_near_limit():
            status = "near_limit" 
            status_color = Colors.YELLOW
        elif percentage > 50:
            status = "moderate_usage"
            status_color = Colors.BLUE
        else:
            status = "low_usage"
            status_color = Colors.GREEN
        
        return {
            "credits_used": self.credits_used,
            "credits_limit": self.max_credits,
            "credits_remaining": self.get_remaining(),
            "usage_percentage": round(percentage, 1),
            "status": status,
            "status_color": status_color,
            "phase_breakdown": self.phase_usage.copy(),
            "is_over_limit": self.is_over_limit(),
            "is_near_limit": self.is_near_limit()
        }
    
    def print_status(self) -> None:
        """Print colored status report to console."""
        report = self.get_status_report()
        color = report["status_color"]
        
        print(f"{color}📊 Credit Status: {report['credits_used']}/{report['credits_limit']} ({report['usage_percentage']}%){Colors.END}")
        print(f"{color}   Remaining: {report['credits_remaining']} credits{Colors.END}")
        
        if report["phase_breakdown"]:
            breakdown = ", ".join([f"{phase}: {count}" for phase, count in report["phase_breakdown"].items() if count > 0])
            print(f"{Colors.CYAN}   Breakdown: {breakdown}{Colors.END}")
    
    def enforce_limit(self, requested_credits: int) -> int:
        """
        Enforce credit limit by returning maximum allowable credits.
        
        Args:
            requested_credits: Number of credits requested
            
        Returns:
            Number of credits that can actually be used (may be less than requested)
        """
        remaining = self.get_remaining()
        allowed = min(requested_credits, remaining)
        
        if allowed < requested_credits:
            print(f"{Colors.YELLOW}⚠ Requested {requested_credits} credits, limiting to {allowed} to stay within budget{Colors.END}")
        
        return allowed

# ==================================================================================
# GLOBAL CREDIT MONITORING
# ==================================================================================

class GlobalCreditMonitor:
    """
    Monitors credit usage across all requests for service-wide tracking.
    """
    
    def __init__(self):
        self.total_credits_used = 0
        self.request_count = 0
        self.phase_totals: Dict[str, int] = {
            "search": 0,
            "extract": 0,
            "validation": 0
        }
    
    def record_request_usage(self, tracker: CreditTracker) -> None:
        """
        Record credit usage from a completed request.
        
        Args:
            tracker: CreditTracker instance from completed request
        """
        self.total_credits_used += tracker.credits_used
        self.request_count += 1
        
        # Add to phase totals
        for phase, count in tracker.phase_usage.items():
            if phase in self.phase_totals:
                self.phase_totals[phase] += count
            else:
                self.phase_totals[phase] = count
    
    def get_average_credits_per_request(self) -> float:
        """Get average credits used per request."""
        return self.total_credits_used / max(1, self.request_count)
    
    def get_global_stats(self) -> Dict[str, Any]:
        """
        Get global credit usage statistics.
        
        Returns:
            Dict with service-wide credit usage metrics
        """
        avg_per_request = self.get_average_credits_per_request()
        
        return {
            "total_credits_used": self.total_credits_used,
            "total_requests": self.request_count,
            "average_credits_per_request": round(avg_per_request, 2),
            "phase_totals": self.phase_totals.copy(),
            "efficiency_rating": self._get_efficiency_rating(avg_per_request)
        }
    
    def _get_efficiency_rating(self, avg_credits: float) -> str:
        """Determine efficiency rating based on average credit usage."""
        if avg_credits <= 5:
            return "excellent"
        elif avg_credits <= 10:
            return "good"
        elif avg_credits <= 20:
            return "moderate"
        else:
            return "poor"
    
    def reset_stats(self) -> Dict[str, Any]:
        """Reset all global statistics."""
        old_stats = self.get_global_stats()
        
        self.total_credits_used = 0
        self.request_count = 0
        self.phase_totals = {"search": 0, "extract": 0, "validation": 0}
        
        return {
            "message": "Global credit statistics reset",
            "previous_stats": old_stats
        }

# Global monitor instance
global_monitor = GlobalCreditMonitor()

# ==================================================================================
# CREDIT BUDGET MANAGEMENT
# ==================================================================================

def estimate_monthly_usage(current_daily_credits: int, days_elapsed: int) -> Dict[str, Any]:
    """
    Estimate monthly credit usage based on current consumption.
    
    Args:
        current_daily_credits: Average credits used per day
        days_elapsed: Number of days into the month
        
    Returns:
        Dict with monthly usage projections and warnings
    """
    if days_elapsed <= 0:
        return {"error": "Invalid days_elapsed value"}
    
    # Project monthly usage
    daily_rate = current_daily_credits
    projected_monthly = daily_rate * 30
    
    # Determine warning level
    monthly_limit = 3000  # Standard Firecrawl limit
    
    if projected_monthly > monthly_limit:
        warning_level = "critical"
        overage = projected_monthly - monthly_limit
    elif projected_monthly > monthly_limit * 0.8:
        warning_level = "warning"
        overage = 0
    else:
        warning_level = "normal"
        overage = 0
    
    return {
        "current_daily_rate": daily_rate,
        "projected_monthly_usage": projected_monthly,
        "monthly_limit": monthly_limit,
        "projected_utilization_percent": round((projected_monthly / monthly_limit) * 100, 1),
        "warning_level": warning_level,
        "projected_overage": overage,
        "days_until_limit": (monthly_limit / daily_rate) if daily_rate > 0 else float('inf'),
        "recommendations": _get_usage_recommendations(warning_level, projected_monthly, monthly_limit)
    }

def _get_usage_recommendations(warning_level: str, projected: int, limit: int) -> list:
    """Generate usage recommendations based on projections."""
    recommendations = []
    
    if warning_level == "critical":
        recommendations.extend([
            "URGENT: Reduce credit usage immediately",
            "Enable aggressive caching",
            "Reduce search result limits",
            "Implement request rate limiting"
        ])
    elif warning_level == "warning":
        recommendations.extend([
            "Monitor usage closely",
            "Optimize search queries",
            "Consider implementing additional caching"
        ])
    else:
        recommendations.append("Usage is within normal limits")
    
    return recommendations
