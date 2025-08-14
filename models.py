from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class HomeInfoRequest(BaseModel):
    address: str = Field(..., description="Full home address to extract information for")
    city: Optional[str] = Field(None, description="City name")
    state: Optional[str] = Field(None, description="State abbreviation")
    zip_code: Optional[str] = Field(None, description="ZIP code")


class PropertyInfo(BaseModel):
    home_type: Optional[str] = Field(None, description="Property type: Single Family, Multi Family, Apartment, Townhouse, Condo, Duplex, Mobile/Manufactured, Land, or Other")
    heating_types: Optional[List[str]] = Field(None, description="Heating systems: Central, Forced Air, Baseboard, Radiant, Heat Pump, Gas, Electric, Oil, Solar, etc.")
    cooling_types: Optional[List[str]] = Field(None, description="Cooling systems: Central Air, Window Units, Evaporative, Heat Pump, None, etc.")
    interior_area_sqft: Optional[int] = Field(None, description="Total finished square footage of interior living space")
    lot_size_sqft: Optional[int] = Field(None, description="Lot size in square feet")
    bedrooms: Optional[int] = Field(None, description="Number of bedrooms")
    bathrooms: Optional[float] = Field(None, description="Number of bathrooms (can be fractional like 2.5)")
    parking_options: Optional[List[str]] = Field(None, description="Parking: Garage, Carport, Driveway, Off-street, On-street, Covered, Uncovered, etc.")
    year_built: Optional[int] = Field(None, description="Year the property was constructed")
    finished_basement: Optional[bool] = Field(None, description="Whether the basement is finished")
    has_patio: Optional[bool] = Field(None, description="Whether property has a patio, deck, or outdoor space")
    flooring_types: Optional[List[str]] = Field(None, description="Flooring materials: Hardwood, Carpet, Tile, Laminate, Vinyl, etc.")
    appliances_included: Optional[List[str]] = Field(None, description="Included appliances: Dishwasher, Refrigerator, Washer, Dryer, Microwave, etc.")
    hoa_fee: Optional[float] = Field(None, description="Monthly HOA fee amount")
    property_tax: Optional[float] = Field(None, description="Annual property tax amount")


class HomeInfoResponse(BaseModel):
    address: str
    property_info: PropertyInfo
    sources: List[str] = Field(default=[], description="List of websites used for extraction")
    success: bool = Field(True, description="Whether extraction was successful")
    error_message: Optional[str] = Field(None, description="Error message if extraction failed")


class PropertyUrlsResponse(BaseModel):
    address: str
    found_urls: Dict[str, List[str]] = Field(description="URLs found for each site (zillow, redfin)")
    success: bool = Field(True, description="Whether URL discovery was successful")
    error_message: Optional[str] = Field(None, description="Error message if discovery failed")


class ExtractFromUrlsRequest(BaseModel):
    property_urls: List[str] = Field(..., description="List of property detail URLs to extract data from")
    address: str = Field(..., description="Address for context and validation")


class OASResponse(BaseModel):
    openapi: str
    info: Dict[str, Any]
    servers: List[Dict[str, str]]
    paths: Dict[str, Any]
    components: Dict[str, Any]
