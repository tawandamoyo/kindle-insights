import os
import logging # Added logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

logger = logging.getLogger(__name__) # Added logger

# Define the path for the SQLite database file
# Store it in the user's home directory for better cross-platform compatibility
USER_HOME = os.path.expanduser("~")
# Use a hidden directory for application data
DATABASE_DIR = os.path.join(USER_HOME, ".kindle_insights_data") # Changed folder name slightly
DATABASE_URL = f"sqlite:///{os.path.join(DATABASE_DIR, 'kindle_insights.db')}"

# Ensure the database directory exists
try:
    os.makedirs(DATABASE_DIR, exist_ok=True)
except OSError as e:
    logger.error(f"Failed to create database directory {DATABASE_DIR}: {e}", exc_info=True)
    # Depending on requirements, you might want to exit or raise here
    raise

# Create the SQLAlchemy engine
# connect_args is needed for SQLite to enforce foreign key constraints and allow multi-threading access (FastAPI/Typer use)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False # Set echo=True to see SQL queries (useful for debugging)
)

# Create a SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a Base class for declarative models
Base = declarative_base()

# Dependency for getting a database session (useful for FastAPI/CLI later)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Function to create all tables defined in models that inherit from Base
def init_db():
    try:
        logger.info(f"Initializing database schema at {DATABASE_URL}")
        # Import all models here before calling create_all
        # This ensures they are registered with the Base metadata
        from . import models # Relative import works here
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
        raise # Re-raise the exception so the caller knows it failed

logger.info(f"Database setup configured. Using database at: {DATABASE_URL}")