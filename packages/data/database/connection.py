# Database connection management for FOMC project

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .base import Base

# Use SQLite database
# The database file will be created in the project root directory
DATABASE_URL = "sqlite:///./fomc_data.db"

# Create engine and session
# For SQLite, we need to set check_same_thread to False for use with FastAPI
try:
    engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    print(f"Error creating database engine: {e}")
    sys.exit(1)

def get_db():
    """
    Dependency to get DB session
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        print(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """
    Initialize database tables
    """
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False