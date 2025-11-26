#!/usr/bin/env python3
# Script to initialize the database for the FOMC project

import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.connection import Base, engine

def main():
    """Initialize the database tables"""
    print("Initializing database tables...")
    
    try:
        # Create tables directly using Base metadata
        Base.metadata.create_all(bind=engine)
        print("Database initialized successfully!")
        return 0
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())