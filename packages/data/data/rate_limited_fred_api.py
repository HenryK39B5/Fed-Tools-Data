# Enhanced FRED API with Rate Limiting for FOMC Project

import os
import time
import requests
import pandas as pd
from typing import Dict, List, Optional
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

class RateLimitedFredAPI:
    """
    Enhanced FRED API client with rate limiting functionality
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        default_start_date: str = "2010-01-01",
    ):
        """
        Initialize the FRED API client with rate limiting
        
        Args:
            requests_per_minute: Maximum number of requests per minute (default: 60)
            default_start_date: Default observation start date when none is provided
        """
        self.api_key = os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError("FRED_API_KEY not found in environment variables")
        
        self.base_url = "https://api.stlouisfed.org/fred"
        
        # Rate limiting parameters
        self.requests_per_minute = requests_per_minute
        self.request_times = []  # Track request timestamps
        
        # Default date range (configurable start to latest)
        self.default_start_date = default_start_date
    
    def _check_rate_limit(self):
        """
        Check if we need to wait to respect rate limits
        """
        now = time.time()
        current_minute = now - 60  # 60 seconds ago
        
        # Remove old request timestamps (older than 1 minute)
        self.request_times = [t for t in self.request_times if t > current_minute]
        
        # If we've reached the limit, wait until we can make another request
        if len(self.request_times) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.request_times[0]) + 1  # Add 1 second buffer
            if sleep_time > 0:
                print(f"Rate limit reached. Waiting {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)
        
        # Record this request
        self.request_times.append(now)
    
    def get_series(self, series_id: str, 
                   observation_start: Optional[str] = None,
                   observation_end: Optional[str] = None,
                   frequency: Optional[str] = None,
                   units: Optional[str] = None) -> Dict:
        """
        Get economic data series from FRED with rate limiting
        
        Args:
            series_id: The FRED series ID
            observation_start: Start date (YYYY-MM-DD), defaults to 2018-01-01
            observation_end: End date (YYYY-MM-DD), defaults to latest
            frequency: Data frequency (daily, weekly, monthly, quarterly, annual)
            units: Units of measurement (lin, chg, ch1, pch, pc1, pca, cch, gpta, gpca)
            
        Returns:
            Dictionary with series information and data
        """
        # Check rate limit before making request
        self._check_rate_limit()
        
        # Use default dates if not provided
        if not observation_start:
            observation_start = self.default_start_date
        if not observation_end:
            observation_end = self._current_default_end_date()
            
        url = f"{self.base_url}/series/observations"
        
        params = {
            'series_id': series_id,
            'api_key': self.api_key,
            'file_type': 'json',
            'observation_start': observation_start,
            'observation_end': observation_end
        }
        
        if frequency:
            params['frequency'] = frequency
        if units:
            params['units'] = units
            
        print(f"Fetching data for {series_id} from {observation_start} to {observation_end}")
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching data for {series_id}: {response.status_code}")
            response.raise_for_status()
    
    def get_series_info(self, series_id: str) -> Dict:
        """
        Get metadata information about a series with rate limiting
        
        Args:
            series_id: The FRED series ID
            
        Returns:
            Dictionary with series metadata
        """
        # Check rate limit before making request
        self._check_rate_limit()
        
        url = f"{self.base_url}/series"
        
        params = {
            'series_id': series_id,
            'api_key': self.api_key,
            'file_type': 'json'
        }
        
        print(f"Fetching metadata for {series_id}")
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching metadata for {series_id}: {response.status_code}")
            response.raise_for_status()
    
    def search_series(self, search_text: str, limit: int = 30) -> Dict:
        """
        Search for economic series in FRED with rate limiting
        
        Args:
            search_text: Text to search for
            limit: Maximum number of results to return
            
        Returns:
            Dictionary with search results
        """
        # Check rate limit before making request
        self._check_rate_limit()
        
        url = f"{self.base_url}/series/search"
        
        params = {
            'search_text': search_text,
            'api_key': self.api_key,
            'file_type': 'json',
            'limit': limit
        }
        
        print(f"Searching for series with text: {search_text}")
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error searching for series: {response.status_code}")
            response.raise_for_status()
    
    def series_to_dataframe(self, series_data: Dict) -> pd.DataFrame:
        """
        Convert series data to pandas DataFrame
        
        Args:
            series_data: Series data from get_series method
            
        Returns:
            DataFrame with date and value columns
        """
        observations = series_data['observations']
        df = pd.DataFrame(observations)
        df['date'] = pd.to_datetime(df['date'])
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        return df[['date', 'value']].dropna()
    
    def get_multiple_series(self, series_ids: List[str], 
                           observation_start: Optional[str] = None,
                           observation_end: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Get multiple series data with rate limiting
        
        Args:
            series_ids: List of FRED series IDs
            observation_start: Start date (YYYY-MM-DD), defaults to 2018-01-01
            observation_end: End date (YYYY-MM-DD), defaults to latest
            
        Returns:
            Dictionary with series_id as key and DataFrame as value
        """
        results = {}
        
        for series_id in series_ids:
            try:
                series_data = self.get_series(series_id, observation_start, observation_end)
                df = self.series_to_dataframe(series_data)
                results[series_id] = df
                print(f"Successfully fetched {len(df)} data points for {series_id}")
            except Exception as e:
                print(f"Failed to fetch data for {series_id}: {str(e)}")
                results[series_id] = None
        
        return results

    @staticmethod
    def _current_default_end_date() -> str:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

# Example usage:
# fred = RateLimitedFredAPI(requests_per_minute=30)  # Limit to 30 requests per minute
# gdp_data = fred.get_series('GDP', observation_start='2020-01-01')
# gdp_df = fred.series_to_dataframe(gdp_data)
# 
# # Get multiple series at once
# series_ids = ['GDP', 'UNRATE', 'CPIAUCSL']
# all_data = fred.get_multiple_series(series_ids)
