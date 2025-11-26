# Basic Data Visualization for FOMC Project

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from typing import List, Optional
import numpy as np

class DataVisualizer:
    """
    Class to handle basic data visualization for economic data
    """
    
    def __init__(self):
        """
        Initialize the data visualizer with default styles
        """
        # Set default style
        plt.style.use('seaborn-v0_8')
        sns.set_palette("husl")
        
        # Set default figure size
        plt.rcParams['figure.figsize'] = (12, 6)
    
    def plot_time_series(self, df: pd.DataFrame,
                        date_column: str = 'date',
                        value_column: str = 'value',
                        title: str = 'Time Series Plot',
                        xlabel: str = 'Date',
                        ylabel: str = 'Value',
                        save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot a time series
        
        Args:
            df: DataFrame with time series data
            date_column: Name of the date column
            value_column: Name of the value column
            title: Plot title
            xlabel: X-axis label
            ylabel: Y-axis label
            save_path: Path to save the plot (optional)
            
        Returns:
            Matplotlib figure object
        """
        fig, ax = plt.subplots(figsize=(12, 6))
        
        ax.plot(df[date_column], df[value_column], linewidth=1.5)
        ax.set_title(title, fontsize=16, pad=20)
        ax.set_xlabel(xlabel, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)
        
        # Rotate x-axis labels for better readability
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            
        return fig
    
    def plot_multiple_series(self, series_list: List[pd.DataFrame],
                           labels: List[str],
                           date_column: str = 'date',
                           value_column: str = 'value',
                           title: str = 'Multiple Time Series Comparison',
                           xlabel: str = 'Date',
                           ylabel: str = 'Value',
                           save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot multiple time series on the same chart
        
        Args:
            series_list: List of DataFrames with time series data
            labels: List of labels for each series
            date_column: Name of the date column
            value_column: Name of the value column
            title: Plot title
            xlabel: X-axis label
            ylabel: Y-axis label
            save_path: Path to save the plot (optional)
            
        Returns:
            Matplotlib figure object
        """
        fig, ax = plt.subplots(figsize=(12, 6))
        
        for i, series in enumerate(series_list):
            ax.plot(series[date_column], series[value_column], 
                   linewidth=1.5, label=labels[i])
        
        ax.set_title(title, fontsize=16, pad=20)
        ax.set_xlabel(xlabel, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Rotate x-axis labels for better readability
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            
        return fig
    
    def plot_distribution(self, df: pd.DataFrame,
                         value_column: str = 'value',
                         title: str = 'Distribution Plot',
                         xlabel: str = 'Value',
                         ylabel: str = 'Frequency',
                         bins: int = 30,
                         save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot the distribution of a series
        
        Args:
            df: DataFrame with data
            value_column: Name of the value column
            title: Plot title
            xlabel: X-axis label
            ylabel: Y-axis label
            bins: Number of histogram bins
            save_path: Path to save the plot (optional)
            
        Returns:
            Matplotlib figure object
        """
        fig, ax = plt.subplots(figsize=(10, 6))
        
        ax.hist(df[value_column], bins=bins, alpha=0.7, edgecolor='black')
        ax.set_title(title, fontsize=16, pad=20)
        ax.set_xlabel(xlabel, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            
        return fig
    
    def plot_correlation_heatmap(self, df: pd.DataFrame,
                               columns: List[str],
                               title: str = 'Correlation Heatmap',
                               save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot a correlation heatmap for selected columns
        
        Args:
            df: DataFrame with data
            columns: List of column names to include in correlation analysis
            title: Plot title
            save_path: Path to save the plot (optional)
            
        Returns:
            Matplotlib figure object
        """
        # Select only the specified columns
        df_selected = df[columns]
        
        # Calculate correlation matrix
        corr_matrix = df_selected.corr()
        
        # Create heatmap
        fig, ax = plt.subplots(figsize=(10, 8))
        sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0,
                   square=True, linewidths=0.5, cbar_kws={"shrink": .8})
        
        ax.set_title(title, fontsize=16, pad=20)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            
        return fig

# Example usage:
# visualizer = DataVisualizer()
# fig = visualizer.plot_time_series(data, title='GDP Growth Over Time')
# plt.show()