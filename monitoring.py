"""
Monitoring, metrics, and observability setup for the Firecrawl service.

This module configures OpenTelemetry tracing, Prometheus metrics, and provides
monitoring utilities for tracking API performance and credit usage.
"""
import os
from typing import Dict, Any
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from config import SERVICE_NAME as CONFIG_SERVICE_NAME, METRICS_CONFIG, EXCLUDED_MONITORING_ENDPOINTS, get_otel_endpoint

# ==================================================================================
# OPENTELEMETRY TRACING SETUP
# ==================================================================================

def setup_tracing():
    """
    Setup OpenTelemetry tracing for the application.
    
    Configures distributed tracing with OTLP export to collect and analyze
    request traces across the service.
    
    Returns:
        Tracer instance for creating spans
    """
    resource = Resource(attributes={SERVICE_NAME: CONFIG_SERVICE_NAME})
    
    tracer_provider = TracerProvider(resource=resource)
    
    otlp_endpoint = get_otel_endpoint()
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)
    
    trace.set_tracer_provider(tracer_provider)
    
    return trace.get_tracer(__name__)

# ==================================================================================
# PROMETHEUS METRICS DEFINITIONS
# ==================================================================================

# API call metrics
FIRECRAWL_API_CALLS = Counter(
    "firecrawl_api_calls_total",
    "Total number of Firecrawl API calls",
    ["endpoint", "status"],
)

FIRECRAWL_API_DURATION = Histogram(
    "firecrawl_api_duration_seconds",
    "Duration of Firecrawl API calls",
    ["endpoint"],
    buckets=METRICS_CONFIG["latency_buckets"],
)

FIRECRAWL_API_ERRORS = Counter(
    "firecrawl_api_errors_total",
    "Total number of Firecrawl API errors",
    ["endpoint", "error_type"],
)

# Credit usage metrics
FIRECRAWL_CREDITS_USED = Counter(
    "firecrawl_credits_used_total",
    "Total number of Firecrawl API credits consumed",
    ["endpoint", "phase"]
)

# Extraction quality metrics
EXTRACTION_QUALITY_SCORE = Histogram(
    "extraction_quality_score",
    "Quality score of property data extraction (percentage)",
    ["endpoint"],
    buckets=[0, 10, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100]
)

BACKUP_SEARCH_TRIGGERED = Counter(
    "backup_search_triggered_total",
    "Number of times backup domain search was triggered due to poor quality",
    ["primary_domain", "backup_domain"]
)

# Cache metrics
CACHE_OPERATIONS = Counter(
    "cache_operations_total",
    "Cache operations (hit, miss, clear)",
    ["operation"]
)

CACHE_ENTRIES = Gauge(
    "cache_entries_current",
    "Current number of entries in search cache"
)

# Error and parsing metrics
JSON_PARSE_ERRORS = Counter(
    "json_parse_errors_total", 
    "Total number of JSON parsing errors", 
    ["endpoint"]
)

ACTIVE_REQUESTS = Gauge(
    "active_requests", 
    "Number of requests currently being processed", 
    ["endpoint"]
)

# ==================================================================================
# FASTAPI INSTRUMENTATION SETUP
# ==================================================================================

def setup_fastapi_instrumentation(app):
    """
    Setup FastAPI instrumentation with Prometheus metrics.
    
    Args:
        app: FastAPI application instance
        
    Returns:
        Configured instrumentator instance
    """
    # Configure instrumentator
    instrumentator = Instrumentator(
        should_group_status_codes=METRICS_CONFIG["should_group_status_codes"],
        should_ignore_untemplated=METRICS_CONFIG["should_ignore_untemplated"],
        should_respect_env_var=METRICS_CONFIG["should_respect_env_var"],
        should_instrument_requests_inprogress=METRICS_CONFIG["should_instrument_requests_inprogress"],
        excluded_handlers=EXCLUDED_MONITORING_ENDPOINTS,
        inprogress_name=METRICS_CONFIG["inprogress_name"],
        inprogress_labels=METRICS_CONFIG["inprogress_labels"],
    )
    
    # Add standard metrics
    instrumentator.add(
        metrics.latency(
            buckets=METRICS_CONFIG["latency_buckets"],
        )
    )
    instrumentator.add(metrics.request_size())
    instrumentator.add(metrics.response_size())
    
    # Instrument the app and expose metrics endpoint
    instrumentator.instrument(app).expose(app, include_in_schema=False, should_gzip=True)
    
    return instrumentator

def setup_httpx_instrumentation():
    """Setup HTTPX client instrumentation for external API calls."""
    HTTPXClientInstrumentor().instrument()

def setup_fastapi_tracing(app):
    """Setup FastAPI tracing instrumentation."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics")

# ==================================================================================
# METRIC RECORDING UTILITIES
# ==================================================================================

def record_api_call(endpoint: str, status: str):
    """Record a Firecrawl API call."""
    FIRECRAWL_API_CALLS.labels(endpoint=endpoint, status=status).inc()

def record_api_duration(endpoint: str, duration: float):
    """Record API call duration."""
    FIRECRAWL_API_DURATION.labels(endpoint=endpoint).observe(duration)

def record_api_error(endpoint: str, error_type: str):
    """Record an API error."""
    FIRECRAWL_API_ERRORS.labels(endpoint=endpoint, error_type=error_type).inc()

def record_credits_used(endpoint: str, phase: str, credits: int):
    """Record credit usage."""
    FIRECRAWL_CREDITS_USED.labels(endpoint=endpoint, phase=phase).inc(credits)

def record_extraction_quality(endpoint: str, quality_score: float):
    """Record extraction quality score."""
    EXTRACTION_QUALITY_SCORE.labels(endpoint=endpoint).observe(quality_score)

def record_backup_search(primary_domain: str, backup_domain: str):
    """Record when backup search is triggered."""
    BACKUP_SEARCH_TRIGGERED.labels(primary_domain=primary_domain, backup_domain=backup_domain).inc()

def record_cache_operation(operation: str):
    """Record cache operation (hit, miss, clear)."""
    CACHE_OPERATIONS.labels(operation=operation).inc()

def update_cache_entries_count(count: int):
    """Update current cache entries gauge."""
    CACHE_ENTRIES.set(count)

def increment_active_requests(endpoint: str):
    """Increment active requests counter."""
    ACTIVE_REQUESTS.labels(endpoint=endpoint).inc()

def decrement_active_requests(endpoint: str):
    """Decrement active requests counter."""
    ACTIVE_REQUESTS.labels(endpoint=endpoint).dec()

# ==================================================================================
# METRICS COLLECTION AND REPORTING
# ==================================================================================

def get_credit_usage_from_metrics() -> Dict[str, float]:
    """
    Extract credit usage statistics from Prometheus metrics.
    
    Returns:
        Dict with credit usage breakdown by phase
    """
    search_credits = 0
    extract_credits = 0
    
    try:
        for metric in REGISTRY.collect():
            if metric.name == "firecrawl_credits_used_total":
                for sample in metric.samples:
                    if 'phase' in sample.labels:
                        if sample.labels['phase'] == 'search':
                            search_credits += sample.value
                        elif sample.labels['phase'] == 'extract':
                            extract_credits += sample.value
        
        return {
            "search_credits": search_credits,
            "extract_credits": extract_credits,
            "total_credits": search_credits + extract_credits
        }
    except Exception as e:
        return {
            "error": f"Could not retrieve credit metrics: {str(e)}",
            "search_credits": 0,
            "extract_credits": 0,
            "total_credits": 0
        }

def get_cache_metrics() -> Dict[str, Any]:
    """
    Extract cache-related metrics from Prometheus.
    
    Returns:
        Dict with cache performance statistics
    """
    cache_hits = 0
    cache_misses = 0
    cache_clears = 0
    
    try:
        for metric in REGISTRY.collect():
            if metric.name == "cache_operations_total":
                for sample in metric.samples:
                    if 'operation' in sample.labels:
                        operation = sample.labels['operation']
                        if operation == 'hit':
                            cache_hits += sample.value
                        elif operation == 'miss':
                            cache_misses += sample.value
                        elif operation == 'clear':
                            cache_clears += sample.value
        
        total_operations = cache_hits + cache_misses
        hit_rate = (cache_hits / total_operations * 100) if total_operations > 0 else 0
        
        return {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_clears": cache_clears,
            "hit_rate_percent": round(hit_rate, 1),
            "total_operations": total_operations
        }
    except Exception as e:
        return {
            "error": f"Could not retrieve cache metrics: {str(e)}",
            "cache_hits": 0,
            "cache_misses": 0,
            "hit_rate_percent": 0
        }

def get_extraction_quality_metrics() -> Dict[str, Any]:
    """
    Extract quality-related metrics from Prometheus.
    
    Returns:
        Dict with extraction quality statistics
    """
    try:
        quality_scores = []
        backup_searches = 0
        
        for metric in REGISTRY.collect():
            if metric.name == "extraction_quality_score":
                for sample in metric.samples:
                    if sample.name.endswith('_bucket'):
                        continue  # Skip histogram buckets
                    quality_scores.append(sample.value)
            elif metric.name == "backup_search_triggered_total":
                for sample in metric.samples:
                    backup_searches += sample.value
        
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        return {
            "average_quality_score": round(avg_quality, 1),
            "total_extractions": len(quality_scores),
            "backup_searches_triggered": backup_searches,
            "backup_search_rate": round((backup_searches / len(quality_scores) * 100), 1) if quality_scores else 0
        }
    except Exception as e:
        return {
            "error": f"Could not retrieve quality metrics: {str(e)}",
            "average_quality_score": 0,
            "backup_searches_triggered": 0
        }

def get_comprehensive_metrics_report() -> Dict[str, Any]:
    """
    Generate comprehensive metrics report combining all monitoring data.
    
    Returns:
        Dict with complete service metrics and performance indicators
    """
    credit_metrics = get_credit_usage_from_metrics()
    cache_metrics = get_cache_metrics()
    quality_metrics = get_extraction_quality_metrics()
    
    return {
        "service": CONFIG_SERVICE_NAME,
        "timestamp": os.environ.get('TIMESTAMP', 'unknown'),
        "credit_usage": credit_metrics,
        "cache_performance": cache_metrics,
        "extraction_quality": quality_metrics,
        "optimization_status": "optimized",
        "strategy": "single_url_with_quality_check"
    }

# ==================================================================================
# MONITORING CONTEXT MANAGERS
# ==================================================================================

class RequestMonitor:
    """Context manager for monitoring individual requests."""
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.start_time = None
    
    def __enter__(self):
        increment_active_requests(self.endpoint)
        self.start_time = __import__('time').time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        decrement_active_requests(self.endpoint)
        
        if self.start_time:
            duration = __import__('time').time() - self.start_time
            record_api_duration(self.endpoint, duration)
        
        if exc_type:
            error_type = exc_type.__name__ if exc_type else "unknown"
            record_api_error(self.endpoint, error_type)
            record_api_call(self.endpoint, "error")
        else:
            record_api_call(self.endpoint, "success")
