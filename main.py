"""
Firecrawl Home Information Service - Main Application

Optimized property search service with aggressive credit conservation,
intelligent caching, and quality-based fallback searches.
"""
import inspect
import json
import os
import time
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from firecrawl import FirecrawlApp

# Import our modular components
from config import (
    SERVICE_NAME, DEFAULT_PORT, SEARCH_QUERY_TEMPLATES, URL_VALIDATION_PATTERNS,
    get_firecrawl_api_key, Colors
)
from cache import (
    get_cached_result, cache_search_result, get_cache_stats, clear_cache as clear_search_cache,
    cleanup_expired_entries, get_cache_health_report
)
from credit_tracker import CreditTracker, global_monitor, estimate_monthly_usage
from property_extraction import (
    calculate_extraction_quality, meets_quality_threshold, extract_from_urls,
    validate_property_urls_optimized, analyze_extraction_gaps
)
from monitoring import (
    setup_tracing, setup_fastapi_instrumentation, setup_httpx_instrumentation,
    setup_fastapi_tracing, record_credits_used, record_extraction_quality,
    record_backup_search, record_cache_operation, update_cache_entries_count,
    get_credit_usage_from_metrics, RequestMonitor, get_comprehensive_metrics_report
)
from models import (
    HomeInfoRequest, HomeInfoResponse, PropertyInfo, PropertyUrlsResponse, 
    ExtractFromUrlsRequest, OASResponse
)

# Load environment variables
load_dotenv()

# Setup monitoring and tracing
tracer = setup_tracing()

# Initialize FastAPI app
app = FastAPI(title="Firecrawl Home Information Service")

# Setup instrumentation
setup_fastapi_tracing(app)
setup_httpx_instrumentation()
instrumentator = setup_fastapi_instrumentation(app)

# ==================================================================================
# SEARCH FUNCTIONS (KEPT IN MAIN.PY AS REQUESTED)
# ==================================================================================

def generate_search_urls(address: str, city: str = None, state: str = None, zip_code: str = None) -> List[str]:
    """Generate search URLs to find property detail pages."""
    full_address = address
    if city:
        full_address += f", {city}"
    if state:
        full_address += f", {state}"
    if zip_code:
        full_address += f" {zip_code}"
    
    # Encode address for URLs
    encoded_address = full_address.replace(" ", "+").replace(",", "%2C")
    
    # Try multiple URL formats to find property detail pages
    urls = []
    
    # Format 1: Try to construct direct homedetails URL
    address_clean = address.replace(" ", "-").replace(".", "")
    city_clean = city.replace(" ", "-") if city else ""
    if city and state and zip_code:
        potential_detail_url = f"https://www.zillow.com/homedetails/{address_clean}-{city_clean}-{state}-{zip_code}/"
        urls.append(potential_detail_url)
    
    # Format 2: Zillow search that often redirects to property page
    zillow_search = f"https://www.zillow.com/homes/{encoded_address}_rb/"
    urls.append(zillow_search)
    
    # Format 3: Redfin search 
    redfin_search = f"https://www.redfin.com/stingray/do/location-autocomplete?v=2&al=1&location={encoded_address}"
    urls.append(redfin_search)
    
    # Format 4: Realtor.com search
    realtor_search = f"https://www.realtor.com/search/street-view/{encoded_address}"
    urls.append(realtor_search)
    
    return urls

async def find_property_urls_single_optimized(
    app: FirecrawlApp, 
    address: str, 
    city: str = None, 
    state: str = None, 
    zip_code: str = None, 
    preferred_site: str = "zillow"
) -> Dict[str, List[str]]:
    """
    Find 1 valid URL with minimal credits, search second site only if needed.
    
    This function implements the conservative search strategy:
    1. Check cache first (0 credits if hit)
    2. Search preferred domain for 1 URL (1-3 credits, starting with 1)  
    3. Only search backup domain if extraction quality is poor
    
    Args:
        app: FirecrawlApp instance
        address: Street address
        city: City name (optional)
        state: State abbreviation (optional) 
        zip_code: ZIP code (optional)
        preferred_site: Preferred site to search first ("zillow" or "redfin")
        
    Returns:
        Dict with found URLs and metadata
    """
    
    # Check cache first
    cached_result = get_cached_result(address, city, state, zip_code)
    if cached_result is not None:
        record_cache_operation("hit")
        return cached_result
    
    record_cache_operation("miss")
    
    # Build full address for search
    full_address = address
    if city:
        full_address += f", {city}"
    if state:
        full_address += f", {state}"
    if zip_code:
        full_address += f" {zip_code}"
    
    found_urls = {"zillow": [], "redfin": [], "errors": [], "credits_used": 0}
    credit_tracker = CreditTracker(max_credits_per_request=10)  # Conservative per-request limit
    
    # Start with preferred site (usually Zillow for better data)
    search_order = [preferred_site, "redfin" if preferred_site == "zillow" else "zillow"]
    
    print(f"{Colors.BLUE}Optimized search for: {full_address} (max 10 credits, targeting 1 URL){Colors.END}")
    
    for site in search_order:
        # Skip if we already found a URL (only search second site if specifically requested)
        total_found = len(found_urls.get("zillow", [])) + len(found_urls.get("redfin", []))
        if total_found >= 1:
            print(f"{Colors.GREEN}✓ Found {total_found} URL, skipping {site} to conserve credits{Colors.END}")
            break
            
        # Check if we have enough credits for at least 1 search attempt
        if not credit_tracker.can_use_credits(1):
            print(f"{Colors.RED}⚠ Credit limit reached ({credit_tracker.credits_used}/{credit_tracker.max_credits}), stopping search{Colors.END}")
            break
            
        # Create targeted query for each site
        query = SEARCH_QUERY_TEMPLATES[site].format(full_address=full_address)
            
        try:
            print(f"{Colors.BLUE}  {site.title()} query ({credit_tracker.get_remaining()} credits left): {query}{Colors.END}")
            
            # Start with smallest possible search limit and increase if needed
            max_search_attempts = 3
            validated_urls = []
            
            for attempt in range(1, max_search_attempts + 1):
                # Check if we can afford this attempt size, otherwise use remaining credits
                actual_limit = attempt
                if not credit_tracker.can_use_credits(attempt):
                    remaining_credits = credit_tracker.get_remaining()
                    if remaining_credits > 0:
                        actual_limit = remaining_credits
                        print(f"{Colors.YELLOW}⚠ Cannot afford {attempt} credit search, using {actual_limit} remaining credits{Colors.END}")
                        # After using remaining credits, we'll have 0 left, so this will be our last attempt
                    else:
                        print(f"{Colors.YELLOW}⚠ Cannot afford {attempt} credit search, stopping{Colors.END}")
                        break
                    
                print(f"{Colors.BLUE}    Attempt {attempt}: searching with limit={actual_limit}{Colors.END}")
                search_result = app.search(query, limit=actual_limit)
                credit_tracker.add_credits(actual_limit, "search")
                
                if hasattr(search_result, 'data') and search_result.data:
                    # Extract and filter URLs from this attempt
                    candidate_urls = []
                    for result in search_result.data:
                        if hasattr(result, 'url'):
                            url = result.url
                        elif isinstance(result, dict) and 'url' in result:
                            url = result['url']
                        else:
                            continue
                            
                        # Strict domain filtering
                        if site == "zillow" and URL_VALIDATION_PATTERNS["zillow"] in url.lower():
                            candidate_urls.append(url)
                        elif site == "redfin" and URL_VALIDATION_PATTERNS["redfin_domain"] in url.lower() and URL_VALIDATION_PATTERNS["redfin_path"] in url.lower():
                            candidate_urls.append(url)
                    
                    if candidate_urls:
                        print(f"{Colors.BLUE}    Found {len(candidate_urls)} {site} URLs to validate{Colors.END}")
                        
                        # Validate URLs
                        validated_urls = validate_property_urls_optimized(candidate_urls, address, city, state, zip_code, max_urls=1)
                        
                        if validated_urls:
                            print(f"{Colors.GREEN}✓ Found valid URL with {actual_limit} credit search{Colors.END}")
                            break  # Success! Stop searching
                        else:
                            print(f"{Colors.BLUE}    No URLs matched address criteria, trying larger search{Colors.END}")
                    else:
                        print(f"{Colors.BLUE}    No {site} URLs found, trying larger search{Colors.END}")
                else:
                    print(f"{Colors.BLUE}    No results returned, trying larger search{Colors.END}")
                
                # If we used remaining credits, we're done with this site
                if actual_limit != attempt:
                    print(f"{Colors.BLUE}    Used all remaining credits, stopping search for {site}{Colors.END}")
                    break
            
            # Store results if found
            if validated_urls:
                found_urls[site] = validated_urls
                print(f"{Colors.GREEN}✓ Found 1 validated {site} URL, stopping search to conserve credits{Colors.END}")
                break  # Stop immediately after finding 1 valid URL
            else:
                print(f"{Colors.BLUE}  No valid {site} URLs found after {max_search_attempts} attempts{Colors.END}")
                
        except Exception as e:
            error_msg = f"Error searching {site}: {str(e)}"
            found_urls["errors"].append(error_msg)
            print(f"{Colors.RED}  {error_msg}{Colors.END}")
    
    # Track credits used
    found_urls["credits_used"] = credit_tracker.credits_used
    
    # Cache the results
    cache_search_result(found_urls, address, city, state, zip_code)
    
    # Update cache metrics
    update_cache_entries_count(get_cache_stats()["valid_entries"])
    
    # Record global usage
    global_monitor.record_request_usage(credit_tracker)
    
    # Summary
    total_found = len(found_urls.get("zillow", [])) + len(found_urls.get("redfin", []))
    print(f"{Colors.GREEN}Optimized search complete: {total_found} URLs found using {credit_tracker.credits_used} credits{Colors.END}")
    
    return found_urls

# Backward compatibility functions
async def find_property_urls_optimized(app: FirecrawlApp, address: str, city: str = None, state: str = None, zip_code: str = None) -> Dict[str, List[str]]:
    """OPTIMIZED: Find property URLs with aggressive credit conservation."""
    return await find_property_urls_single_optimized(app, address, city, state, zip_code)

async def find_property_urls_simple(app: FirecrawlApp, address: str, city: str = None, state: str = None, zip_code: str = None) -> Dict[str, List[str]]:
    """DEPRECATED: Use find_property_urls_optimized instead to conserve credits."""
    print(f"{Colors.RED}⚠ WARNING: Using deprecated high-credit search function. Switch to find_property_urls_optimized(){Colors.END}")
    return await find_property_urls_optimized(app, address, city, state, zip_code)

# ==================================================================================
# ENHANCED EXTRACTION WITH QUALITY CHECKING
# ==================================================================================

async def extract_home_info_with_quality_check(request: HomeInfoRequest) -> PropertyInfo:
    """
    Extract home information with quality checking and smart backup search.
    
    Implements the optimized strategy:
    1. Search for 1 URL from preferred domain (1-3 credits, starting with 1)
    2. Extract and check quality (1 credit) 
    3. If quality < 25%, search backup domain (1-3 credits)
    4. Final extraction with both URLs if backup found (2 credits)
    
    Args:
        request: HomeInfoRequest with address details
        
    Returns:
        PropertyInfo with extracted data
    """
    endpoint = "home_info_extraction"
    
    with RequestMonitor(endpoint):
        try:
            # Initialize Firecrawl client
            firecrawl_api_key = get_firecrawl_api_key()
            app = FirecrawlApp(api_key=firecrawl_api_key)
            
            # STEP 1: Find initial URL
            found_urls = await find_property_urls_single_optimized(
                app, request.address, request.city, request.state, request.zip_code
            )
            
            # Get the first URL (prefer Zillow)
            initial_property_urls = []
            primary_site = None
            
            if found_urls.get("zillow"):
                initial_property_urls = found_urls["zillow"][:1]
                primary_site = "zillow"
            elif found_urls.get("redfin"):
                initial_property_urls = found_urls["redfin"][:1]
                primary_site = "redfin"
            else:
                print(f"{Colors.RED}No property detail URLs found - cannot extract data{Colors.END}")
                return PropertyInfo()
            
            # Record search credits
            search_credits_used = found_urls.get("credits_used", 0)
            record_credits_used(endpoint, "search", search_credits_used)
            
            print(f"{Colors.GREEN}Starting extraction with primary URL{Colors.END}: {initial_property_urls[0]}")
            
            # STEP 2: Initial extraction and quality check
            initial_property_info = extract_from_urls(app, initial_property_urls, request.address)
            record_credits_used(endpoint, "extract", 1)  # 1 URL = 1 credit
            
            # STEP 3: Check extraction quality
            extraction_quality = calculate_extraction_quality(initial_property_info)
            record_extraction_quality(endpoint, extraction_quality)
            
            # STEP 4: Backup search if quality is poor
            final_property_info = initial_property_info
            
            if not meets_quality_threshold(initial_property_info):
                print(f"{Colors.BLUE}Extraction quality below threshold, searching backup domain{Colors.END}")
                
                # Search for URL from the other domain
                backup_site = "redfin" if primary_site == "zillow" else "zillow"
                backup_urls = await find_property_urls_single_optimized(
                    app, request.address, request.city, request.state, request.zip_code,
                    preferred_site=backup_site
                )
                
                backup_search_credits = backup_urls.get("credits_used", 0)
                record_credits_used(endpoint, "search", backup_search_credits)
                record_backup_search(primary_site, backup_site)
                
                # Get backup URL
                backup_property_urls = []
                if backup_urls.get(backup_site):
                    backup_property_urls = backup_urls[backup_site][:1]
                    
                if backup_property_urls:
                    print(f"{Colors.GREEN}Found backup URL from {backup_site}{Colors.END}: {backup_property_urls[0]}")
                    
                    # Final extraction with both URLs
                    combined_urls = initial_property_urls + backup_property_urls
                    final_property_info = extract_from_urls(app, combined_urls, request.address)
                    record_credits_used(endpoint, "extract", 2)  # 2 URLs = 2 credits
                    
                    # Record improved quality
                    final_quality = calculate_extraction_quality(final_property_info)
                    record_extraction_quality(endpoint, final_quality)
                    
                    print(f"{Colors.GREEN}✓ Backup search improved quality from {extraction_quality:.1f}% to {final_quality:.1f}%{Colors.END}")
                else:
                    print(f"{Colors.RED}No backup URL found, using initial extraction{Colors.END}")
            
            return final_property_info
            
        except Exception as e:
            print(f"{Colors.RED}Error in extraction process: {str(e)}{Colors.END}")
            raise HTTPException(status_code=500, detail=f"Failed to extract home information: {str(e)}")

# ==================================================================================
# API ENDPOINTS
# ==================================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": SERVICE_NAME}

@app.get("/credit_usage")
async def get_credit_usage():
    """Get current credit usage statistics with comprehensive monitoring."""
    try:
        # Get credit usage from metrics
        credit_metrics = get_credit_usage_from_metrics()
        
        # Get cache statistics
        cache_stats = get_cache_stats()
        
        # Get global monitoring stats
        global_stats = global_monitor.get_global_stats()
        
        return {
            "total_credits_used": credit_metrics["total_credits"],
            "search_credits": credit_metrics["search_credits"],
            "extract_credits": credit_metrics["extract_credits"],
            "cache_stats": cache_stats,
            "global_stats": global_stats,
            "optimization_status": "optimized",
            "strategy": "single_url_with_quality_check",
            "max_credits_per_request": 10,
            "quality_threshold": "25%"
        }
    except Exception as e:
        cache_stats = get_cache_stats()
        return {
            "error": f"Could not retrieve credit usage: {str(e)}",
            "cache_stats": cache_stats,
            "optimization_status": "optimized"
        }

@app.post("/clear_cache")
async def clear_cache():
    """Clear the search result cache (admin endpoint)."""
    result = clear_search_cache()
    record_cache_operation("clear")
    update_cache_entries_count(0)
    return result

@app.get("/cache_health")
async def get_cache_health():
    """Get comprehensive cache health and performance report."""
    return get_cache_health_report()

@app.post("/cleanup_cache")
async def cleanup_cache():
    """Remove expired cache entries to free memory."""
    expired_count = cleanup_expired_entries()
    cache_stats = get_cache_stats()
    update_cache_entries_count(cache_stats["valid_entries"])
    
    return {
        "message": f"Cleaned up {expired_count} expired entries",
        "cache_stats": cache_stats
    }

@app.get("/metrics_report")
async def get_metrics_report():
    """Get comprehensive service metrics report."""
    return get_comprehensive_metrics_report()

@app.get("/get_oas", tags=["Documentation"], response_model=OASResponse)
async def get_oas():
    """Get OpenAPI Schema for all available models and tools."""
    model_classes = {
        name: cls
        for name, cls in inspect.getmembers(
            inspect.getmodule(HomeInfoRequest),
            lambda x: inspect.isclass(x)
            and issubclass(x, BaseModel)
            and x != BaseModel,
        )
        if name != "get_oas"
    }

    schemas = {name: get_model_schema(cls) for name, cls in model_classes.items()}

    routes = []
    for route in app.routes:
        if route.path == "/get_oas":
            continue
        if hasattr(route, "response_model"):
            response_model_name = None
            if (
                hasattr(route, "response_model")
                and route.response_model is not None
                and hasattr(route.response_model, "__name__")
            ):
                response_model_name = route.response_model.__name__
            route_info = {
                "path": route.path,
                "method": route.methods,
                "summary": route.endpoint.__doc__ or f"Endpoint for {route.path}",
                "request_model": None,
                "response_model": response_model_name,
            }

            if hasattr(route, "body_field") and route.body_field is not None:
                try:
                    route_info["request_model"] = route.body_field.type_.__name__
                except (AttributeError, TypeError):
                    pass

            routes.append(route_info)

    paths = {
        route["path"]: {
            method.lower(): {
                "summary": route["summary"],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": f"#/components/schemas/{route['request_model']}"
                            }
                        }
                    }
                }
                if route["request_model"]
                else None,
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": f"#/components/schemas/{route['response_model']}"
                                }
                            }
                        },
                    }
                },
            }
            for method in route["method"]
        }
        for route in routes
    }

    return OASResponse(
        openapi="3.0.0",
        info={
            "title": "Firecrawl Home Information Service",
            "version": "1.0.0",
            "description": "API for extracting comprehensive home information from real estate websites using Firecrawl.",
        },
        servers=[
            {
                "url": os.getenv(
                    "RAILWAY_PRIVATE_DOMAIN",
                    f"http://localhost:{os.getenv('PORT', str(DEFAULT_PORT))}",
                )
            }
        ],
        paths=paths,
        components={"schemas": schemas},
    )

@app.post("/find_property_urls", response_model=PropertyUrlsResponse)
async def find_property_urls(request: HomeInfoRequest):
    """
    Step 1: Find property detail URLs from Zillow and Redfin for a given address.
    
    This endpoint searches real estate websites to find the actual property detail page URLs
    that can then be used for comprehensive data extraction.
    """
    endpoint = "find_property_urls"
    
    with RequestMonitor(endpoint):
        try:
            firecrawl_api_key = get_firecrawl_api_key()
            app = FirecrawlApp(api_key=firecrawl_api_key)
            
            # Find property URLs using optimized search
            found_urls = await find_property_urls_single_optimized(
                app, request.address, request.city, request.state, request.zip_code
            )
            
            # Record credits used
            credits_used = found_urls.get("credits_used", 0)
            record_credits_used(endpoint, "search", credits_used)
            
            # Build full address for response
            full_address = request.address
            if request.city:
                full_address += f", {request.city}"
            if request.state:
                full_address += f", {request.state}"
            if request.zip_code:
                full_address += f" {request.zip_code}"
            
            # Check if we found any URLs
            total_urls = len(found_urls.get("zillow", [])) + len(found_urls.get("redfin", []))
            
            # Filter out non-URL fields for the response model
            filtered_urls = {
                "zillow": found_urls.get("zillow", []),
                "redfin": found_urls.get("redfin", [])
            }
            
            return PropertyUrlsResponse(
                address=full_address,
                found_urls=filtered_urls,
                success=total_urls > 0,
                error_message="; ".join(found_urls.get("errors", [])) if found_urls.get("errors") else None
            )
            
        except Exception as e:
            return PropertyUrlsResponse(
                address=request.address,
                found_urls={"zillow": [], "redfin": []},
                success=False,
                error_message=str(e)
            )

@app.post("/extract_from_urls", response_model=HomeInfoResponse)
async def extract_from_property_urls(request: ExtractFromUrlsRequest):
    """
    Step 2: Extract comprehensive property data from specific property URLs.
    
    Takes the URLs found from step 1 and performs detailed data extraction.
    """
    endpoint = "extract_from_urls"
    
    with RequestMonitor(endpoint):
        try:
            firecrawl_api_key = get_firecrawl_api_key()
            app = FirecrawlApp(api_key=firecrawl_api_key)
            
            if not request.property_urls:
                raise HTTPException(status_code=400, detail="No property URLs provided")
            
            print(f"{Colors.GREEN}Extracting from URLs{Colors.END}: {request.property_urls}")
            
            # Extract property data
            property_info = extract_from_urls(app, request.property_urls, request.address)
            
            # Record metrics
            credits_used = len(request.property_urls)
            record_credits_used(endpoint, "extract", credits_used)
            
            quality = calculate_extraction_quality(property_info)
            record_extraction_quality(endpoint, quality)
            
            return HomeInfoResponse(
                address=request.address,
                property_info=property_info,
                sources=[url.split('/')[2] for url in request.property_urls],  # Extract domain names
                success=True
            )
            
        except Exception as e:
            return HomeInfoResponse(
                address=request.address,
                property_info=PropertyInfo(),
                sources=[],
                success=False,
                error_message=str(e)
            )

@app.post("/extract_home_info", response_model=HomeInfoResponse)
async def extract_home_information(request: HomeInfoRequest):
    """
    Extract comprehensive home information from real estate websites using Firecrawl.
    
    This endpoint uses the optimized strategy:
    1. Find 1 URL from preferred domain (1-3 credits, starts with 1)
    2. Extract and check quality (1 credit)
    3. If quality < 25%, search backup domain and re-extract (3-5 additional credits)
    4. Average usage: 2-9 credits per property (vs 60+ before optimization)
    """
    try:
        # Extract property information using quality-checked approach
        property_info = await extract_home_info_with_quality_check(request)
        
        # Build full address for response
        full_address = request.address
        if request.city:
            full_address += f", {request.city}"
        if request.state:
            full_address += f", {request.state}"
        if request.zip_code:
            full_address += f" {request.zip_code}"
        
        return HomeInfoResponse(
            address=full_address,
            property_info=property_info,
            sources=["zillow.com", "redfin.com"],
            success=True
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Handle any other unexpected errors
        return HomeInfoResponse(
            address=request.address,
            property_info=PropertyInfo(),
            sources=[],
            success=False,
            error_message=str(e)
        )

# ==================================================================================
# UTILITY FUNCTIONS
# ==================================================================================

def get_model_schema(model_class) -> Dict[str, Any]:
    """Generate OpenAPI schema for a Pydantic model."""
    schema = model_class.model_json_schema()
    return {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
        "title": schema.get("title", model_class.__name__),
    }

# ==================================================================================
# APPLICATION STARTUP
# ==================================================================================

if __name__ == "__main__":
    import logging
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    logger.info(f"Starting {SERVICE_NAME} on port {port}")
    logger.info(f"Optimization status: Optimized")
    logger.info(f"Strategy: single_url_with_quality_check")
    logger.info(f"Expected credit usage: 2-9 credits per property (vs 60+ before)")

    uvicorn.run(app, host="::", port=port, log_level="info")
