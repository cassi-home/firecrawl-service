import inspect
import json
import os
from typing import Any, Dict, Type, List
import re

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from pydantic import BaseModel
from firecrawl import FirecrawlApp

from models import HomeInfoRequest, HomeInfoResponse, PropertyInfo, PropertyUrlsResponse, ExtractFromUrlsRequest, OASResponse

RED = "\033[31m"
BLUE = "\033[34m"
GREEN = "\033[32m"
ENDC = "\033[0m"

load_dotenv()


def setup_tracing():
    """Setup OpenTelemetry tracing for the application."""
    resource = Resource(attributes={SERVICE_NAME: "firecrawl-service"})

    tracer_provider = TracerProvider(resource=resource)

    otlp_endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    )
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(tracer_provider)

    return trace.get_tracer(__name__)


tracer = setup_tracing()

app = FastAPI(title="Firecrawl Home Information Service")

FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics")

HTTPXClientInstrumentor().instrument()

# Metrics
FIRECRAWL_API_CALLS = Counter(
    "firecrawl_api_calls_total",
    "Total number of Firecrawl API calls",
    ["endpoint", "status"],
)

FIRECRAWL_API_DURATION = Histogram(
    "firecrawl_api_duration_seconds",
    "Duration of Firecrawl API calls",
    ["endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

FIRECRAWL_API_ERRORS = Counter(
    "firecrawl_api_errors_total",
    "Total number of Firecrawl API errors",
    ["endpoint", "error_type"],
)

JSON_PARSE_ERRORS = Counter(
    "json_parse_errors_total", "Total number of JSON parsing errors", ["endpoint"]
)

ACTIVE_REQUESTS = Gauge(
    "active_requests", "Number of requests currently being processed", ["endpoint"]
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "firecrawl-service"}


instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[".*admin.*", "/metrics"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)

instrumentator.add(
    metrics.latency(
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    )
)
instrumentator.add(metrics.request_size())
instrumentator.add(metrics.response_size())

instrumentator.instrument(app).expose(app, include_in_schema=False, should_gzip=True)


def get_model_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """Generate OpenAPI schema for a Pydantic model."""
    schema = model_class.model_json_schema()
    return {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
        "title": schema.get("title", model_class.__name__),
    }


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
                    f"http://localhost:{os.getenv('PORT', '8000')}",
                )
            }
        ],
        paths=paths,
        components={"schemas": schemas},
    )


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
    
    # Generate URLs using standard patterns
    # Removed hardcoded property mappings to avoid committing real addresses
    
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


async def find_property_urls_simple(app: FirecrawlApp, address: str, city: str = None, state: str = None, zip_code: str = None) -> Dict[str, List[str]]:
    """Step 1: Find property URLs using Firecrawl's search API to discover Zillow and Redfin listings."""
    
    # Build full address for search
    full_address = address
    if city:
        full_address += f", {city}"
    if state:
        full_address += f", {state}"
    if zip_code:
        full_address += f" {zip_code}"
    
    found_urls = {"zillow": [], "redfin": [], "errors": []}
    
    # Define search queries for each site
    search_queries = {
        "zillow": [
            f"{full_address} site:zillow.com",
            f"{address} {city} {state} zillow",
            f"zillow {full_address} property listing"
        ],
        "redfin": [
            f"{full_address} site:redfin.com", 
            f"{address} {city} {state} redfin",
            f"redfin {full_address} property listing"
        ]
    }
    
    print(f"{BLUE}Using Firecrawl search to find property URLs for: {full_address}{ENDC}")
    
    # Search each site using Firecrawl's search API
    for site, queries in search_queries.items():
        print(f"{BLUE}Searching for {site.title()} listings{ENDC}")
        
        for query in queries:
            try:
                print(f"{BLUE}  Query: {query}{ENDC}")
                
                # Use Firecrawl's search API
                search_result = app.search(query, limit=10)
                
                if hasattr(search_result, 'data') and search_result.data:
                    # Extract URLs from search results
                    candidate_urls = []
                    for result in search_result.data:
                        if hasattr(result, 'url'):
                            url = result.url
                        elif isinstance(result, dict) and 'url' in result:
                            url = result['url']
                        else:
                            continue
                            
                        # Filter for the target site domain
                        if site == "zillow" and "zillow.com" in url.lower():
                            candidate_urls.append(url)
                        elif site == "redfin" and "redfin.com" in url.lower():
                            candidate_urls.append(url)
                    
                    if candidate_urls:
                        print(f"{BLUE}  Found {len(candidate_urls)} {site} URLs to validate{ENDC}")
                        
                        # Validate URLs to ensure they match the exact address
                        validated_urls = validate_property_urls(candidate_urls, address, city, state, zip_code)
                        
                        if validated_urls:
                            # Add unique URLs (avoid duplicates)
                            for url in validated_urls:
                                if url not in found_urls[site]:
                                    found_urls[site].append(url)
                            
                            print(f"{GREEN}✓ Found {len(validated_urls)} validated {site} URLs{ENDC}")
                            
                            # Stop searching this site if we found good URLs
                            if len(found_urls[site]) >= 3:  # Limit to 3 URLs per site
                                break
                        else:
                            print(f"{BLUE}  No URLs matched exact address criteria{ENDC}")
                    else:
                        print(f"{BLUE}  No {site} URLs found in search results{ENDC}")
                else:
                    print(f"{BLUE}  No search results returned{ENDC}")
                    
            except Exception as e:
                error_msg = f"Error searching {site} with query '{query}': {str(e)}"
                found_urls["errors"].append(error_msg)
                print(f"{RED}  {error_msg}{ENDC}")
    
    # Summary
    total_found = len(found_urls["zillow"]) + len(found_urls["redfin"])
    if total_found > 0:
        print(f"{GREEN}Total property URLs found: {total_found} (Zillow: {len(found_urls['zillow'])}, Redfin: {len(found_urls['redfin'])}){ENDC}")
    else:
        print(f"{RED}No property URLs found for {full_address}{ENDC}")
    
    return found_urls


def validate_property_urls(urls: List[str], address: str, city: str = None, state: str = None, zip_code: str = None) -> List[str]:
    """Validate that URLs actually match the exact address using dynamic pattern matching."""
    validated_urls = []
    
    # Extract address components for validation
    street_number = address.split()[0] if address.split() else ""
    street_name = " ".join(address.split()[1:]) if len(address.split()) > 1 else ""
    
    # Handle common street type abbreviations dynamically
    street_abbreviations = {
        "street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
        "court": "ct", "place": "pl", "lane": "ln", "road": "rd", 
        "circle": "cir", "terrace": "ter", "way": "way"
    }
    
    print(f"{BLUE}Validating URLs for: {street_number} {street_name}{ENDC}")
    
    for url in urls:
        try:
            url_lower = url.lower()
            is_valid = False
            
            # For Zillow URLs - check if address components are in the URL path
            if "zillow.com/homedetails/" in url_lower:
                url_path = url_lower.split('/homedetails/')[-1] if '/homedetails/' in url_lower else ""
                
                # Check if street number is in the URL (exact match only)
                street_number_match = street_number and (
                    f"-{street_number.lower()}-" in url_path or 
                    url_path.startswith(f"{street_number.lower()}-") or
                    f"/{street_number.lower()}-" in url_path
                )
                
                # Additional check: make sure it's not a partial match of a longer number
                if street_number_match and street_number.isdigit():
                    # Verify the number appears as a complete word/segment, not part of a longer number
                    import re
                    pattern = rf"\b{re.escape(street_number.lower())}\b"
                    if not re.search(pattern, url_path.replace("-", " ").replace("/", " ")):
                        street_number_match = False
                        print(f"{RED}✗ Street number {street_number} appears to be part of longer number in URL{ENDC}: {url}")
                
                if street_number_match:
                    # Create variations of street name for matching
                    street_name_lower = street_name.lower()
                    street_name_variants = [street_name_lower]
                    
                    # Add abbreviation variants
                    for full_word, abbrev in street_abbreviations.items():
                        if full_word in street_name_lower:
                            street_name_variants.append(street_name_lower.replace(full_word, abbrev))
                        elif abbrev in street_name_lower:
                            street_name_variants.append(street_name_lower.replace(abbrev, full_word))
                    
                    # Check if any variant of the street name matches
                    street_match_found = False
                    for variant in street_name_variants:
                        street_name_parts = [part for part in variant.replace(" ", "-").split("-") if len(part) > 1]
                        street_matches = sum(1 for part in street_name_parts if part in url_path)
                        
                        # Require at least half of the street name parts to match
                        if len(street_name_parts) == 0 or street_matches >= max(1, len(street_name_parts) / 2):
                            street_match_found = True
                            break
                    
                    if street_match_found:
                        # Check city if provided (be more lenient)
                        city_match = not city or city.lower().replace(" ", "-") in url_path or city.lower() in url_path
                        
                        if city_match:
                            is_valid = True
                            print(f"{GREEN}✓ Valid Zillow URL{ENDC}: {url}")
                        else:
                            print(f"{RED}✗ Wrong city in Zillow URL{ENDC}: {url}")
                    else:
                        print(f"{RED}✗ Insufficient street match in Zillow URL{ENDC}: {url}")
                else:
                    print(f"{RED}✗ Wrong street number in Zillow URL{ENDC}: {url} (looking for {street_number})")
            
            # For Redfin URLs - format: /STATE/City/address-zip/home/ID
            elif "redfin.com" in url_lower and "/home/" in url_lower:
                url_parts = url_lower.split('/')
                
                # Find the address part (should be before /home/)
                address_part = ""
                for i, part in enumerate(url_parts):
                    if part == "home" and i > 0:
                        address_part = url_parts[i-1]  # Get the part before /home/
                        break
                
                print(f"{BLUE}Checking Redfin address part{ENDC}: {address_part}")
                
                # Check if street number is in the address part (exact match only)
                street_number_match = street_number and street_number.lower() in address_part
                
                # Additional check: make sure it's not a partial match of a longer number
                if street_number_match and street_number.isdigit():
                    # Verify the number appears as a complete word/segment, not part of a longer number
                    import re
                    pattern = rf"\b{re.escape(street_number.lower())}\b"
                    if not re.search(pattern, address_part.replace("-", " ")):
                        street_number_match = False
                        print(f"{RED}✗ Street number {street_number} appears to be part of longer number in Redfin URL{ENDC}: {url}")
                
                if street_number_match:
                    # Create variations of street name for matching (similar to Zillow)
                    street_name_lower = street_name.lower()
                    street_name_variants = [street_name_lower]
                    
                    # Add abbreviation variants
                    for full_word, abbrev in street_abbreviations.items():
                        if full_word in street_name_lower:
                            street_name_variants.append(street_name_lower.replace(full_word, abbrev))
                        elif abbrev in street_name_lower:
                            street_name_variants.append(street_name_lower.replace(abbrev, full_word))
                    
                    # Check if any variant of the street name matches
                    street_match_found = False
                    for variant in street_name_variants:
                        street_name_parts = [part for part in variant.replace(" ", "-").split("-") if len(part) > 1]
                        street_matches = sum(1 for part in street_name_parts if part in address_part)
                        
                        # Be more lenient with street matching for Redfin
                        if len(street_name_parts) == 0 or street_matches >= max(1, len(street_name_parts) / 2):
                            street_match_found = True
                            break
                    
                    if street_match_found:
                        # Check city and state in the full URL
                        city_match = not city or city.lower().replace(" ", "-") in url_lower
                        state_match = not state or f"/{state.lower()}/" in url_lower
                        
                        if city_match and state_match:
                            is_valid = True
                            print(f"{GREEN}✓ Valid Redfin URL{ENDC}: {url}")
                        else:
                            print(f"{RED}✗ Wrong city/state in Redfin URL{ENDC}: {url}")
                    else:
                        print(f"{RED}✗ Insufficient street match in Redfin URL{ENDC}: {url}")
                else:
                    print(f"{RED}✗ Wrong street number in Redfin URL{ENDC}: {url} (looking for {street_number})")
            
            else:
                print(f"{RED}✗ Unrecognized URL format{ENDC}: {url}")
            
            if is_valid:
                validated_urls.append(url)
                
        except Exception as e:
            print(f"{RED}Error validating URL {url}{ENDC}: {str(e)}")
    
    return validated_urls


async def extract_property_data_from_urls(app: FirecrawlApp, property_urls: List[str], address: str) -> PropertyInfo:
    """Step 2: Extract comprehensive property data from specific URLs."""
    
    # Define extraction schema for structured data
    extraction_schema = {
        "type": "object",
        "properties": {
            "home_type": {
                "type": ["string", "null"],
                "description": "Property type: Single Family, Multi Family, Apartment, Townhouse, Condo, Duplex, Mobile/Manufactured, Land, or Other"
            },
            "heating_types": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Heating systems: Central, Forced Air, Baseboard, Radiant, Heat Pump, Gas, Electric, Oil, Solar, etc."
            },
            "cooling_types": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Cooling systems: Central Air, Window Units, Evaporative, Heat Pump, None, etc."
            },
            "interior_area_sqft": {
                "type": ["integer", "null"],
                "description": "Total finished square footage of interior living space"
            },
            "lot_size_sqft": {
                "type": ["integer", "null"],
                "description": "Lot size in square feet"
            },
            "bedrooms": {
                "type": ["integer", "null"],
                "description": "Number of bedrooms"
            },
            "bathrooms": {
                "type": ["number", "null"],
                "description": "Number of bathrooms (can be fractional like 2.5)"
            },
            "parking_options": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Parking: Garage, Carport, Driveway, Off-street, On-street, Covered, Uncovered, etc."
            },
            "year_built": {
                "type": ["integer", "null"],
                "description": "Year the property was constructed"
            },
            "finished_basement": {
                "type": ["boolean", "null"],
                "description": "Whether the basement is finished"
            },
            "has_patio": {
                "type": ["boolean", "null"],
                "description": "Whether property has a patio, deck, or outdoor space"
            },
            "flooring_types": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Flooring materials: Hardwood, Carpet, Tile, Laminate, Vinyl, etc."
            },
            "appliances_included": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "Included appliances: Dishwasher, Refrigerator, Washer, Dryer, Microwave, etc."
            },
            "hoa_fee": {
                "type": ["number", "null"],
                "description": "Monthly HOA fee amount"
            },
            "property_tax": {
                "type": ["number", "null"],
                "description": "Annual property tax amount"
            }
        }
    }
    
    # Natural language prompt for extraction
    extraction_prompt = f"""
    You are extracting comprehensive property information for: {address}
    
    Look for information in these specific sections commonly found on real estate websites:

    **PROPERTY OVERVIEW & BASICS:**
    - Property type: Look for "Property Type", "Home Type", or similar - extract Single Family, Condo, Townhouse, Apartment, etc.
    - Bedrooms: Look for "Beds", "Bedrooms", or "BR" - extract the number
    - Bathrooms: Look for "Baths", "Bathrooms", or "BA" - extract the number (including decimals like 2.5)
    - Square footage: Look for "Sq Ft", "Square Feet", "Interior Area", "Living Area" - extract the number
    - Lot size: Look for "Lot Size", "Land Area" - extract square footage
    - Year built: Look for "Year Built", "Built in", "Construction Date"

    **PROPERTY DETAILS & FEATURES:**
    - Heating: Look in "Property Details", "Home Features", "Interior Features" for heating system info
    - Cooling: Look for air conditioning, central air, cooling system details
    - Flooring: Look for hardwood, carpet, tile, laminate, vinyl flooring types
    - Appliances: Look for included appliances like dishwasher, refrigerator, washer/dryer
    - Basement: Look for "Finished Basement", "Basement Features", or basement details
    - Outdoor space: Look for patio, deck, balcony, outdoor features

    **PARKING & UTILITIES:**
    - Parking: Look for garage spaces, carport, driveway, parking details
    - HOA fee: Look for "HOA", "Association Fee", "Monthly Fee"
    - Property tax: Look for "Property Tax", "Annual Tax", "Tax Amount"

    **SEARCH STRATEGY:**
    1. First scan for property overview sections that show bed/bath/sqft
    2. Look for detailed property information tables or lists
    3. Check "Property Details", "Home Facts", "Features & Amenities" sections
    4. Look for tax and fee information in financial sections
    5. Scan listing descriptions for additional details

    **DATA EXTRACTION RULES:**
    - Extract exact numbers (don't round or estimate)
    - For arrays, extract all applicable items found
    - Use standard terminology (e.g., "Central Air" not "A/C")
    - If multiple values exist, include all of them
    - Return null only if information is truly not available
    - Focus on factual data from structured sections, not subjective descriptions

    These are property detail pages from real estate websites.
    """
    
    import time
    start_time = time.time()
    
    try:
        extracted_data = app.extract(
            urls=property_urls,
            schema=extraction_schema,
            prompt=extraction_prompt
        )
        
        duration = time.time() - start_time
        print(f"{GREEN}Extraction completed in {duration:.2f}s{ENDC}")
        
        try:
            print(f"{BLUE}Extracted Data{ENDC}: {json.dumps(extracted_data, indent=2, default=str)}")
        except (TypeError, ValueError):
            print(f"{BLUE}Extracted Data (non-serializable){ENDC}: {str(extracted_data)}")
        
        # Process the extracted data - handle different response formats
        if extracted_data:
            combined_info = {}
            
            # Handle both list and dict responses
            data_to_process = extracted_data if isinstance(extracted_data, list) else [extracted_data]
            
            for result in data_to_process:
                # Handle different response structures
                extract_data = None
                if hasattr(result, 'data') and result.data:
                    extract_data = result.data
                elif hasattr(result, 'extract') and result.extract:
                    extract_data = result.extract
                elif isinstance(result, dict) and 'extract' in result:
                    extract_data = result['extract']
                elif isinstance(result, dict) and 'data' in result:
                    extract_data = result['data']
                elif isinstance(result, dict):
                    extract_data = result
                    
                if extract_data:
                    # Handle both dict and list of dicts
                    if isinstance(extract_data, list) and len(extract_data) > 0:
                        extract_data = extract_data[0]
                        
                    if isinstance(extract_data, dict):
                        for key, value in extract_data.items():
                            if value is not None and key in extraction_schema['properties']:
                                if key not in combined_info or combined_info[key] is None:
                                    combined_info[key] = value
            
            return PropertyInfo(**combined_info)
        else:
            print(f"{RED}No data extracted from URLs{ENDC}")
            return PropertyInfo()
            
    except Exception as e:
        print(f"{RED}Extraction error{ENDC}: {str(e)}")
        raise


async def extract_home_info(request: HomeInfoRequest) -> PropertyInfo:
    """Extract home information using Firecrawl API."""
    firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
    if not firecrawl_api_key:
        raise HTTPException(status_code=500, detail="Firecrawl API key not configured")

    endpoint = "home_info_extraction"
    ACTIVE_REQUESTS.labels(endpoint=endpoint).inc()

    try:
        # Initialize Firecrawl client
        app = FirecrawlApp(api_key=firecrawl_api_key)
        
        # Generate URLs to search
        search_urls = generate_search_urls(
            request.address, 
            request.city, 
            request.state, 
            request.zip_code
        )
        
        print(f"{GREEN}Searching URLs{ENDC}: {search_urls}")
        
        # Try to find actual property detail URLs from the search results
        found_urls = await find_property_urls_simple(
            app, 
            request.address, 
            request.city, 
            request.state, 
            request.zip_code
        )
        
        # Extract URLs from the found_urls dict, limit to 10 URLs total (Firecrawl API limit)
        property_urls = []
        if found_urls.get("zillow"):
            property_urls.extend(found_urls["zillow"][:5])  # Max 5 Zillow URLs
        if found_urls.get("redfin"):
            remaining_slots = 10 - len(property_urls)
            property_urls.extend(found_urls["redfin"][:remaining_slots])  # Fill remaining slots with Redfin URLs
        
        if property_urls:
            print(f"{GREEN}Found property detail URLs{ENDC}: {property_urls}")
            extraction_urls = property_urls
        else:
            print(f"{BLUE}No property detail URLs found, using limited search URLs{ENDC}")
            # Fallback to search URLs but limit to 10
            extraction_urls = search_urls[:10]
        
        # Define extraction schema for structured data
        extraction_schema = {
            "type": "object",
            "properties": {
                "home_type": {
                    "type": ["string", "null"],
                    "description": "Property type: Single Family, Multi Family, Apartment, Townhouse, Condo, Duplex, Mobile/Manufactured, Land, or Other"
                },
                "heating_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Heating systems: Central, Forced Air, Baseboard, Radiant, Heat Pump, Gas, Electric, Oil, Solar, etc."
                },
                "cooling_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Cooling systems: Central Air, Window Units, Evaporative, Heat Pump, None, etc."
                },
                "interior_area_sqft": {
                    "type": ["integer", "null"],
                    "description": "Total finished square footage of interior living space"
                },
                "lot_size_sqft": {
                    "type": ["integer", "null"],
                    "description": "Lot size in square feet"
                },
                "bedrooms": {
                    "type": ["integer", "null"],
                    "description": "Number of bedrooms"
                },
                "bathrooms": {
                    "type": ["number", "null"],
                    "description": "Number of bathrooms (can be fractional like 2.5)"
                },
                "parking_options": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Parking: Garage, Carport, Driveway, Off-street, On-street, Covered, Uncovered, etc."
                },
                "year_built": {
                    "type": ["integer", "null"],
                    "description": "Year the property was constructed"
                },
                "finished_basement": {
                    "type": ["boolean", "null"],
                    "description": "Whether the basement is finished"
                },
                "has_patio": {
                    "type": ["boolean", "null"],
                    "description": "Whether property has a patio, deck, or outdoor space"
                },
                "flooring_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Flooring materials: Hardwood, Carpet, Tile, Laminate, Vinyl, etc."
                },
                "appliances_included": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Included appliances: Dishwasher, Refrigerator, Washer, Dryer, Microwave, etc."
                },
                "hoa_fee": {
                    "type": ["number", "null"],
                    "description": "Monthly HOA fee amount"
                },
                "property_tax": {
                    "type": ["number", "null"],
                    "description": "Annual property tax amount"
                }
            }
        }
        
        # Natural language prompt for extraction
        extraction_prompt = f"""
        You are extracting comprehensive property information for: {request.address}
        
        Look for information in these specific sections commonly found on real estate websites:

        **PROPERTY OVERVIEW & BASICS:**
        - Property type: Look for "Property Type", "Home Type", or similar - extract Single Family, Condo, Townhouse, Apartment, etc.
        - Bedrooms: Look for "Beds", "Bedrooms", or "BR" - extract the number
        - Bathrooms: Look for "Baths", "Bathrooms", or "BA" - extract the number (including decimals like 2.5)
        - Square footage: Look for "Sq Ft", "Square Feet", "Interior Area", "Living Area" - extract the number
        - Lot size: Look for "Lot Size", "Land Area" - extract square footage
        - Year built: Look for "Year Built", "Built in", "Construction Date"

        **PROPERTY DETAILS & FEATURES:**
        - Heating: Look in "Property Details", "Home Features", "Interior Features" for heating system info
        - Cooling: Look for air conditioning, central air, cooling system details
        - Flooring: Look for hardwood, carpet, tile, laminate, vinyl flooring types
        - Appliances: Look for included appliances like dishwasher, refrigerator, washer/dryer
        - Basement: Look for "Finished Basement", "Basement Features", or basement details
        - Outdoor space: Look for patio, deck, balcony, outdoor features

        **PARKING & UTILITIES:**
        - Parking: Look for garage spaces, carport, driveway, parking details
        - HOA fee: Look for "HOA", "Association Fee", "Monthly Fee"
        - Property tax: Look for "Property Tax", "Annual Tax", "Tax Amount"

        **SEARCH STRATEGY:**
        1. First scan for property overview sections that show bed/bath/sqft
        2. Look for detailed property information tables or lists
        3. Check "Property Details", "Home Facts", "Features & Amenities" sections
        4. Look for tax and fee information in financial sections
        5. Scan listing descriptions for additional details

        **DATA EXTRACTION RULES:**
        - Extract exact numbers (don't round or estimate)
        - For arrays, extract all applicable items found
        - Use standard terminology (e.g., "Central Air" not "A/C")
        - If multiple values exist, include all of them
        - Return null only if information is truly not available
        - Focus on factual data from structured sections, not subjective descriptions

        Target websites: Zillow, Redfin, Realtor.com property pages and search results.
        """
        
        import time
        start_time = time.time()
        
        # Extract data from the URLs
        try:
            extracted_data = app.extract(
                urls=extraction_urls,
                schema=extraction_schema,
                prompt=extraction_prompt
            )
            
            duration = time.time() - start_time
            FIRECRAWL_API_DURATION.labels(endpoint=endpoint).observe(duration)
            
            try:
                print(f"{BLUE}Extracted Data{ENDC}: {json.dumps(extracted_data, indent=2, default=str)}")
            except (TypeError, ValueError):
                print(f"{BLUE}Extracted Data (non-serializable){ENDC}: {str(extracted_data)}")
            
            # Process the extracted data - handle different response formats
            if extracted_data:
                combined_info = {}
                
                # Handle both list and dict responses
                data_to_process = extracted_data if isinstance(extracted_data, list) else [extracted_data]
                
                for result in data_to_process:
                    # Handle different response structures
                    extract_data = None
                    if hasattr(result, 'data') and result.data:
                        extract_data = result.data
                    elif hasattr(result, 'extract') and result.extract:
                        extract_data = result.extract
                    elif isinstance(result, dict) and 'extract' in result:
                        extract_data = result['extract']
                    elif isinstance(result, dict) and 'data' in result:
                        extract_data = result['data']
                    elif isinstance(result, dict):
                        extract_data = result
                        
                    if extract_data:
                        # Handle both dict and list of dicts
                        if isinstance(extract_data, list) and len(extract_data) > 0:
                            extract_data = extract_data[0]
                            
                        if isinstance(extract_data, dict):
                            for key, value in extract_data.items():
                                if value is not None and key in extraction_schema['properties']:
                                    if key not in combined_info or combined_info[key] is None:
                                        combined_info[key] = value
                
                FIRECRAWL_API_CALLS.labels(endpoint=endpoint, status="success").inc()
                
                return PropertyInfo(**combined_info)
            else:
                print(f"{RED}No data extracted from sources{ENDC}")
                FIRECRAWL_API_CALLS.labels(endpoint=endpoint, status="no_data").inc()
                return PropertyInfo()
                
        except Exception as e:
            FIRECRAWL_API_ERRORS.labels(endpoint=endpoint, error_type="extraction_error").inc()
            FIRECRAWL_API_CALLS.labels(endpoint=endpoint, status="error").inc()
            print(f"{RED}Firecrawl extraction error{ENDC}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to extract home information: {str(e)}")

    except Exception as e:
        FIRECRAWL_API_ERRORS.labels(endpoint=endpoint, error_type="unexpected_error").inc()
        FIRECRAWL_API_CALLS.labels(endpoint=endpoint, status="error").inc()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    finally:
        ACTIVE_REQUESTS.labels(endpoint=endpoint).dec()


@app.post("/find_property_urls", response_model=PropertyUrlsResponse)
async def find_property_urls(request: HomeInfoRequest):
    """
    Step 1: Find property detail URLs from Zillow and Redfin for a given address.
    
    This endpoint searches real estate websites to find the actual property detail page URLs
    that can then be used for comprehensive data extraction.
    """
    try:
        firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        if not firecrawl_api_key:
            raise HTTPException(status_code=500, detail="Firecrawl API key not configured")

        app = FirecrawlApp(api_key=firecrawl_api_key)
        
        # Find property URLs
        found_urls = await find_property_urls_simple(
            app, 
            request.address, 
            request.city, 
            request.state, 
            request.zip_code
        )
        
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
        
        return PropertyUrlsResponse(
            address=full_address,
            found_urls=found_urls,
            success=total_urls > 0,
            error_message="; ".join(found_urls.get("errors", [])) if found_urls.get("errors") else None
        )
        
    except Exception as e:
        return PropertyUrlsResponse(
            address=request.address,
            found_urls={"zillow": [], "redfin": [], "errors": [str(e)]},
            success=False,
            error_message=str(e)
        )


@app.post("/extract_from_urls", response_model=HomeInfoResponse)
async def extract_from_property_urls(request: ExtractFromUrlsRequest):
    """
    Step 2: Extract comprehensive property data from specific property URLs.
    
    Takes the URLs found from step 1 and performs detailed data extraction.
    """
    try:
        firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        if not firecrawl_api_key:
            raise HTTPException(status_code=500, detail="Firecrawl API key not configured")

        app = FirecrawlApp(api_key=firecrawl_api_key)
        
        if not request.property_urls:
            raise HTTPException(status_code=400, detail="No property URLs provided")
        
        print(f"{GREEN}Extracting from URLs{ENDC}: {request.property_urls}")
        
        # Use the comprehensive extraction schema and prompt we already have
        property_info = await extract_property_data_from_urls(app, request.property_urls, request.address)
        
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
    
    This endpoint will search Zillow, Redfin, and Realtor.com for detailed property information
    including value estimates, property characteristics, financial data, and neighborhood details.
    """
    try:
        # Extract property information
        property_info = await extract_home_info(request)
        
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
            sources=["zillow.com", "redfin.com", "realtor.com"],
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


if __name__ == "__main__":
    import logging
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting Firecrawl Service on port {port}")

    uvicorn.run(app, host="::", port=port, log_level="info")
