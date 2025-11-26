# Data Preprocessing Pipeline for FOMC Project

import pandas as pd
import numpy as np
from typing import List, Tuple
from datetime import datetime

class DataPreprocessor:
    """
    Class to handle data preprocessing tasks for economic data
    """
    
    def __init__(self):
        """
        Initialize the data preprocessor
        """
        pass
    
    def clean_series(self, df: pd.DataFrame, 
                     date_column: str = 'date',
                     value_column: str = 'value') -> pd.DataFrame:
        """
        Clean a time series dataframe by removing invalid values and duplicates
        
        Args:
            df: DataFrame with time series data
            date_column: Name of the date column
            value_column: Name of the value column
            
        Returns:
            Cleaned DataFrame
        """
        # Remove rows with missing values
        df_clean = df.dropna(subset=[date_column, value_column])
        
        # Convert date column to datetime if it isn't already
        df_clean[date_column] = pd.to_datetime(df_clean[date_column])
        
        # Convert value column to numeric
        df_clean[value_column] = pd.to_numeric(df_clean[value_column], errors='coerce')
        
        # Remove rows with NaN values after conversion
        df_clean = df_clean.dropna(subset=[value_column])
        
        # Remove duplicates based on date, keeping the last entry
        df_clean = df_clean.drop_duplicates(subset=[date_column], keep='last')
        
        # Sort by date
        df_clean = df_clean.sort_values(by=date_column)
        
        # Reset index
        df_clean = df_clean.reset_index(drop=True)
        
        return df_clean
    
    def fill_missing_values(self, df: pd.DataFrame,
                           date_column: str = 'date',
                           value_column: str = 'value',
                           method: str = 'forward_fill') -> pd.DataFrame:
        """
        Fill missing values in a time series
        
        Args:
            df: DataFrame with time series data
            date_column: Name of the date column
            value_column: Name of the value column
            method: Method to use for filling ('forward_fill', 'backward_fill', 'linear_interpolation')
            
        Returns:
            DataFrame with filled values
        """
        df_filled = df.copy()
        
        if method == 'forward_fill':
            df_filled[value_column] = df_filled[value_column].fillna(method='ffill')
        elif method == 'backward_fill':
            df_filled[value_column] = df_filled[value_column].fillna(method='bfill')
        elif method == 'linear_interpolation':
            df_filled[value_column] = df_filled[value_column].interpolate(method='linear')
            
        return df_filled
    
    def resample_series(self, df: pd.DataFrame,
                       date_column: str = 'date',
                       value_column: str = 'value',
                       frequency: str = 'M') -> pd.DataFrame:
        """
        Resample time series to a different frequency
        
        Args:
            df: DataFrame with time series data
            date_column: Name of the date column
            value_column: Name of the value column
            frequency: Target frequency ('D'=daily, 'W'=weekly, 'M'=monthly, 'Q'=quarterly, 'Y'=yearly)
            
        Returns:
            Resampled DataFrame
        """
        # Set date as index
        df_resampled = df.set_index(date_column)
        
        # Resample
        df_resampled = df_resampled.resample(frequency).mean()
        
        # Reset index
        df_resampled = df_resampled.reset_index()
        
        return df_resampled
    
    def calculate_returns(self, df: pd.DataFrame,
                         date_column: str = 'date',
                         value_column: str = 'value',
                         period: int = 1) -> pd.DataFrame:
        """
        Calculate returns for a time series
        
        Args:
            df: DataFrame with time series data
            date_column: Name of the date column
            value_column: Name of the value column
            period: Number of periods to calculate returns for
            
        Returns:
            DataFrame with returns column
        """
        df_returns = df.copy()
        df_returns['returns'] = df_returns[value_column].pct_change(periods=period)
        return df_returns
    
    def normalize_series(self, df: pd.DataFrame,
                        value_column: str = 'value') -> pd.DataFrame:
        """
        Normalize a series to be between 0 and 1
        
        Args:
            df: DataFrame with time series data
            value_column: Name of the value column
            
        Returns:
            DataFrame with normalized values
        """
        df_normalized = df.copy()
        min_val = df_normalized[value_column].min()
        max_val = df_normalized[value_column].max()
        df_normalized[f'{value_column}_normalized'] = (df_normalized[value_column] - min_val) / (max_val - min_val)
        return df_normalized

# Example usage:
# preprocessor = DataPreprocessor()
# cleaned_data = preprocessor.clean_series(raw_data)
# filled_data = preprocessor.fill_missing_values(cleaned_data, method='linear_interpolation')