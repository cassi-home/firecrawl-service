"""
Property data extraction and quality assessment utilities.

This module handles property data extraction from URLs, quality assessment,
and validation of extracted property information.
"""
from typing import List, Dict, Any, Union
from models import PropertyInfo
from config import PROPERTY_EXTRACTION_SCHEMA, EXTRACTION_PROMPT_TEMPLATE, EXTRACTION_QUALITY_THRESHOLD, Colors

def calculate_extraction_quality(property_info: PropertyInfo) -> float:
    """
    Calculate the percentage of PropertyInfo fields that are filled (non-null).
    
    Analyzes all fields in the PropertyInfo model to determine data completeness.
    Used to decide whether backup domain search is needed.
    
    Args:
        property_info: PropertyInfo instance to analyze
        
    Returns:
        Float percentage (0-100) of fields that contain useful data
        
    Example:
        If 4 out of 16 fields are filled: returns 25.0
    """
    total_fields = 0
    filled_fields = 0
    
    # Get all PropertyInfo fields from the model
    for field_name, field_info in property_info.__fields__.items():
        total_fields += 1
        field_value = getattr(property_info, field_name)
        
        # Check if field is filled (not None and not empty)
        if field_value is not None:
            if isinstance(field_value, list):
                # For lists, check if they have content
                if len(field_value) > 0:
                    filled_fields += 1
            elif isinstance(field_value, str):
                # For strings, check if they're not empty
                if field_value.strip():
                    filled_fields += 1
            else:
                # For numbers, booleans, etc., count as filled if not None
                filled_fields += 1
    
    quality_percentage = (filled_fields / total_fields) * 100 if total_fields > 0 else 0
    
    # Color-coded logging based on quality
    if quality_percentage >= EXTRACTION_QUALITY_THRESHOLD:
        color = Colors.GREEN
        status = "✓ GOOD"
    elif quality_percentage >= 15:
        color = Colors.YELLOW  
        status = "⚠ POOR"
    else:
        color = Colors.RED
        status = "✗ VERY POOR"
    
    print(f"{color}{status} Extraction quality: {filled_fields}/{total_fields} fields filled ({quality_percentage:.1f}%){Colors.END}")
    
    return quality_percentage

def meets_quality_threshold(property_info: PropertyInfo) -> bool:
    """
    Check if extracted property info meets the minimum quality threshold.
    
    Args:
        property_info: PropertyInfo instance to check
        
    Returns:
        True if quality meets threshold, False if backup search needed
    """
    quality = calculate_extraction_quality(property_info)
    meets_threshold = quality >= EXTRACTION_QUALITY_THRESHOLD
    
    if meets_threshold:
        print(f"{Colors.GREEN}✓ Quality threshold met - no backup search needed{Colors.END}")
    else:
        print(f"{Colors.YELLOW}⚠ Below {EXTRACTION_QUALITY_THRESHOLD}% threshold - backup search recommended{Colors.END}")
    
    return meets_threshold

def process_extraction_response(extracted_data: Any) -> PropertyInfo:
    """
    Process raw extraction response from Firecrawl API into PropertyInfo object.
    
    Handles various response formats from the Firecrawl API and extracts the
    relevant property data into a standardized PropertyInfo instance.
    
    Args:
        extracted_data: Raw response from Firecrawl extract API
        
    Returns:
        PropertyInfo instance with extracted data
    """
    if not extracted_data:
        print(f"{Colors.RED}No extraction data received{Colors.END}")
        return PropertyInfo()
    
    combined_info = {}
    
    # Handle both list and dict responses
    data_to_process = extracted_data if isinstance(extracted_data, list) else [extracted_data]
    
    for result in data_to_process:
        extract_data = _extract_data_from_result(result)
        
        if extract_data:
            # Handle both dict and list of dicts
            if isinstance(extract_data, list) and len(extract_data) > 0:
                extract_data = extract_data[0]
                
            if isinstance(extract_data, dict):
                _merge_extraction_data(combined_info, extract_data)
    
    try:
        property_info = PropertyInfo(**combined_info)
        print(f"{Colors.BLUE}Successfully processed extraction data{Colors.END}")
        return property_info
    except Exception as e:
        print(f"{Colors.RED}Error creating PropertyInfo from extracted data: {str(e)}{Colors.END}")
        return PropertyInfo()

def _extract_data_from_result(result: Any) -> Union[Dict[str, Any], None]:
    """Extract data from individual result object."""
    extract_data = None
    
    # Try different possible response structures
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
    
    return extract_data

def _merge_extraction_data(combined_info: Dict[str, Any], extract_data: Dict[str, Any]) -> None:
    """Merge extraction data into combined info, avoiding overwrites of valid data."""
    for key, value in extract_data.items():
        if value is not None and key in PROPERTY_EXTRACTION_SCHEMA['properties']:
            # Only update if we don't already have this field or current value is None
            if key not in combined_info or combined_info[key] is None:
                combined_info[key] = value

def validate_property_urls_optimized(urls: List[str], address: str, city: str = None, state: str = None, zip_code: str = None, max_urls: int = 1) -> List[str]:
    """
    OPTIMIZED: Validate URLs with early stopping to save processing time.
    
    Validates property URLs to ensure they match the target address using
    quick validation checks. Stops early once maximum URLs are found.
    
    Args:
        urls: List of URLs to validate
        address: Target street address
        city: Target city (optional)
        state: Target state (optional)
        zip_code: Target ZIP code (optional)
        max_urls: Maximum URLs to return (default 1 for credit conservation)
        
    Returns:
        List of validated URLs that match the address
    """
    validated_urls = []
    
    # Extract address components for validation
    street_number = address.split()[0] if address.split() else ""
    street_name = " ".join(address.split()[1:]) if len(address.split()) > 1 else ""
    
    print(f"{Colors.BLUE}OPTIMIZED validation for: {street_number} {street_name} (max {max_urls} URLs){Colors.END}")
    
    for i, url in enumerate(urls):
        # Stop early if we have enough validated URLs
        if len(validated_urls) >= max_urls:
            print(f"{Colors.GREEN}✓ Found {max_urls} validated URLs, stopping validation early{Colors.END}")
            break
            
        try:
            url_lower = url.lower()
            is_valid = False
            
            # Quick validation for Zillow homedetails URLs
            if "zillow.com/homedetails/" in url_lower and street_number:
                # Simple check: street number should be in the URL path
                if street_number.lower() in url_lower:
                    is_valid = True
                    print(f"{Colors.GREEN}✓ Quick validated Zillow URL{Colors.END}: {url}")
            
            # Quick validation for Redfin URLs
            elif "redfin.com" in url_lower and "/home/" in url_lower and street_number:
                # Simple check: street number should be in the URL
                if street_number.lower() in url_lower:
                    is_valid = True
                    print(f"{Colors.GREEN}✓ Quick validated Redfin URL{Colors.END}: {url}")
            
            if is_valid:
                validated_urls.append(url)
                
        except Exception as e:
            print(f"{Colors.RED}Error validating URL {url}{Colors.END}: {str(e)}")
    
    return validated_urls

def get_extraction_prompt(address: str) -> str:
    """
    Generate extraction prompt for specific address.
    
    Args:
        address: Target address for extraction
        
    Returns:
        Formatted extraction prompt string
    """
    return EXTRACTION_PROMPT_TEMPLATE.format(address=address)

def analyze_extraction_gaps(property_info: PropertyInfo) -> Dict[str, Any]:
    """
    Analyze which fields are missing from extracted property info.
    
    Useful for understanding extraction quality and identifying areas
    where backup domain searches might help.
    
    Args:
        property_info: PropertyInfo instance to analyze
        
    Returns:
        Dict with analysis of missing fields and suggestions
    """
    filled_fields = []
    empty_fields = []
    
    for field_name, field_info in property_info.__fields__.items():
        field_value = getattr(property_info, field_name)
        
        if field_value is not None:
            if isinstance(field_value, list):
                if len(field_value) > 0:
                    filled_fields.append(field_name)
                else:
                    empty_fields.append(field_name)
            elif isinstance(field_value, str):
                if field_value.strip():
                    filled_fields.append(field_name)
                else:
                    empty_fields.append(field_name)
            else:
                filled_fields.append(field_name)
        else:
            empty_fields.append(field_name)
    
    # Categorize missing fields by importance
    critical_fields = ["bedrooms", "bathrooms", "interior_area_sqft", "home_type"]
    important_fields = ["year_built", "lot_size_sqft", "heating_types", "cooling_types"]
    
    missing_critical = [f for f in critical_fields if f in empty_fields]
    missing_important = [f for f in important_fields if f in empty_fields]
    
    return {
        "filled_fields": filled_fields,
        "empty_fields": empty_fields,
        "missing_critical": missing_critical,
        "missing_important": missing_important,
        "quality_score": len(filled_fields) / len(property_info.__fields__) * 100,
        "backup_search_recommended": len(missing_critical) > 2 or len(filled_fields) < 4,
        "summary": f"{len(filled_fields)} of {len(property_info.__fields__)} fields filled"
    }

def log_extraction_summary(property_info: PropertyInfo, credits_used: int = 0) -> None:
    """
    Log a summary of extraction results with quality assessment.
    
    Args:
        property_info: Extracted property information
        credits_used: Number of credits used for extraction
    """
    quality = calculate_extraction_quality(property_info)
    gap_analysis = analyze_extraction_gaps(property_info)
    
    print(f"\n{Colors.CYAN}{'='*60}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*60}{Colors.END}")
    print(f"{Colors.BLUE}Quality Score: {quality:.1f}%{Colors.END}")
    print(f"{Colors.BLUE}Credits Used: {credits_used}{Colors.END}")
    print(f"{Colors.BLUE}Fields Summary: {gap_analysis['summary']}{Colors.END}")
    
    if gap_analysis['missing_critical']:
        print(f"{Colors.RED}Missing Critical: {', '.join(gap_analysis['missing_critical'])}{Colors.END}")
    
    if gap_analysis['backup_search_recommended']:
        print(f"{Colors.YELLOW}⚠ Backup domain search recommended{Colors.END}")
    else:
        print(f"{Colors.GREEN}✓ Extraction quality sufficient{Colors.END}")
    
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")

def extract_from_urls(app, urls: List[str], address: str) -> PropertyInfo:
    """
    Extract property data from URLs using Firecrawl API.
    
    Args:
        app: Firecrawl application instance
        urls: List of URLs to extract from
        address: Target address for context
        
    Returns:
        PropertyInfo instance with extracted data
    """
    if not urls:
        print(f"{Colors.RED}No URLs provided for extraction{Colors.END}")
        return PropertyInfo()
    
    try:
        print(f"{Colors.BLUE}Extracting from {len(urls)} URLs...{Colors.END}")
        
        extraction_schema = PROPERTY_EXTRACTION_SCHEMA
        extraction_prompt = get_extraction_prompt(address)
        
        extracted_data = app.extract(
            urls=urls,
            schema=extraction_schema,
            prompt=extraction_prompt
        )
        
        # Process the raw extraction response
        property_info = process_extraction_response(extracted_data)
        
        # Log summary
        log_extraction_summary(property_info, len(urls))
        
        return property_info
        
    except Exception as e:
        print(f"{Colors.RED}Extraction error: {str(e)}{Colors.END}")
        return PropertyInfo()
