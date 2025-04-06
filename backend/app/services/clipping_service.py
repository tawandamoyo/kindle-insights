import logging
from typing import Dict, Optional, List # Added List import
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

# Import database models, session management, and parser function
# Assuming Session is properly imported or managed by the caller (e.g., FastAPI dependency)
from app.database import models # Use 'app' as the root package name
from app.parsing.parser import parse_clippings_file

logger = logging.getLogger(__name__)

def get_or_create_book(db: Session, title: str, author: Optional[str]) -> models.Book:
    """
    Gets a book from DB based on title and author, or creates it if not found.
    Uses the author string directly as provided (assuming parser normalization).
    TODO: Implement more advanced author consolidation/matching if needed later.
    """
    book = db.query(models.Book).filter_by(title=title, author=author).first()
    if book:
        return book
    else:
        logger.info(f"Creating new book entry: Title='{title}', Author='{author}'")
        book = models.Book(title=title, author=author)
        db.add(book)
        try:
            # Flush to get the book.id assigned by the database, needed for foreign key relationships
            db.flush()
            logger.info(f"Flushed new book: {book.title} (ID: {book.id})")
            return book
        except IntegrityError as e:
            # This might happen in concurrent scenarios or if normalization fails to catch an existing author variation
            db.rollback() # Rollback the failed flush
            logger.warning(f"IntegrityError on flush for book: {title} ({author}). Attempting recovery lookup. Error: {e}")
            # Retry the query to get the potentially concurrently created or existing book
            book = db.query(models.Book).filter_by(title=title, author=author).first()
            if book:
                 logger.info(f"Recovered book after IntegrityError: {book.title} (ID: {book.id})")
                 return book
            else:
                # If still not found, re-raise or handle as critical failure
                logger.error(f"Failed to get or create book after IntegrityError recovery attempt: {title} ({author})")
                # Raise a specific exception or return None, depending on desired handling
                raise ValueError(f"Failed to get or create book: {title} ({author}) after IntegrityError")
        except Exception as e:
             db.rollback()
             logger.error(f"Unexpected error during book flush for {title} ({author}): {e}", exc_info=True)
             raise # Re-raise unexpected errors

def import_clippings(db: Session, file_path: str) -> Dict[str, int]:
    """
    Parses a MyClippings file, checks for duplicates, and imports new clippings.
    Returns a dictionary with counts of processed, added, duplicate, and error clippings.
    """
    logger.info(f"Starting import process for file: {file_path}")
    try:
        parsed_data = parse_clippings_file(file_path)
    except Exception as e:
        logger.error(f"Failed during parsing phase for file {file_path}: {e}", exc_info=True)
        return {"processed": 0, "added": 0, "duplicates": 0, "errors": 0}


    if not parsed_data:
        logger.warning("No clippings parsed from file.")
        return {"processed": 0, "added": 0, "duplicates": 0, "errors": 0}

    added_count = 0
    duplicate_count = 0
    error_count = 0
    processed_count = len(parsed_data)
    
    # Track items added in this session to avoid duplicate processing
    session_added_signatures = set()

    # Keep track of books processed in this session to potentially reduce queries, although get_or_create handles caching via Session
    # book_cache = {} # Optional optimization

    for idx, clipping_data in enumerate(parsed_data):
        try:
            # 1. Get or Create Book record
            book = get_or_create_book(db, clipping_data["book_title"], clipping_data["author"])

            if not book or not book.id: # Should not happen if get_or_create_book raises on critical failure
                 logger.error(f"Skipping clipping #{idx+1} due to missing or invalid book ID for '{clipping_data['book_title']}'")
                 error_count += 1
                 continue
             
            # Create a unique signature for the clipping to track in this session
            signature = (
                book.id,
                clipping_data["clipping_type"],
                clipping_data["location"],
                clipping_data["content_hash"] # None for bookmarks
            )

            # 2. Check for Duplicate Clipping using the unique constraint criteria
            # (book_id, clipping_type, location, content_hash)
            existing_clipping = db.query(models.Clipping.id).filter_by( # Only query for ID for efficiency
                book_id=signature[0],
                clipping_type=signature[1],
                location=signature[2],
                content_hash=signature[3]
            ).first() 
            
            is_pending_dublicate = signature in session_added_signatures

            if existing_clipping or is_pending_dublicate:
                duplicate_count += 1
                continue # Skip adding this duplicate
            
            # Add signature to session tracker BEFORE adding the object
            session_added_signatures.add(signature)

            # 3. Create and Add New Clipping record
            try:
                new_clipping = models.Clipping(
                    book_id=book.id,
                    clipping_type=clipping_data["clipping_type"],
                    location=clipping_data["location"],
                    page=clipping_data["page"],
                    clipping_date=clipping_data["clipping_date"],
                    content=clipping_data["content"],
                    content_hash=clipping_data["content_hash"]
                    # sentiment_score is null initially
                )
                db.add(new_clipping)
                added_count += 1
            
            except KeyError as ke:
                logger.error(f"KeyError creating Clipping object: Missing key {ke}. Data: {clipping_data}", exc_info=False)
                # Propagate the error count from the outer loop's except block or handle here
                # Let the outer loop handle rollback and error counting for simplicity now.
                raise # Re-raise to be caught by the outer loop's generic Exception handler
                # except Exception as creation_e: # Catch other potential creation errors
                #      logger.error(f"Error creating Clipping object: {creation_e}. Data: {clipping_data}", exc_info=True)
                #      raise # Re-raise

            # Optional: Flush periodically for large files? Maybe not needed for typical MyClippings sizes.
            # if added_count % 500 == 0:
            #     logger.info(f"Flushing session after {added_count} additions...")
            #     db.flush()

        except Exception as e:
            # Log specific clipping data that caused the error for easier debugging
            err_loc = clipping_data.get('location', 'N/A')
            err_con_hash = clipping_data.get('content_hash', 'N/A')
            logger.error(f"Failed to process parsed clipping #{idx+1} ({clipping_data.get('book_title', 'N/A')} L:{err_loc} H:{err_con_hash}): {e}", exc_info=False) # Set exc_info=True for full traceback
            error_count += 1
            # Important: Rollback changes potentially added in this iteration's try block
            db.rollback()
            continue
        
    # Debugging: print dict and its keys before access
    logger.debug(f"DEBUG: Processing clipping_data: {clipping_data}")
    logger.debug(f"DEBUG: Keys in clipping_data: {clipping_data.keys()}")
    

    # Final commit for all additions in this import run
    try:
        logger.info(f"Attempting final commit for {added_count} new clippings...")
        db.commit()
        logger.info("Final commit successful.")
    except Exception as e:
        logger.error(f"Final commit failed after processing file {file_path}: {e}", exc_info=True)
        # If commit fails, none of the clippings were actually saved
        error_count += added_count # Count previously 'added' items as errors now
        added_count = 0
        db.rollback()
        
        
    actual_duplicates = processed_count - added_count - error_count
    summary = {
        "processed": processed_count,
        "added": added_count,
        "duplicates": max(0, actual_duplicates), # Ensure non-negative
        "errors": error_count
    }
     # Ensure calculated duplicates isn't negative if errors caused discrepancies
    summary["duplicates"] = max(0, summary["duplicates"])

    logger.info(f"Import finished for {file_path}. Summary: {summary}")
    return summary

# --- Placeholder for other service functions ---

def list_books(db: Session) -> List[models.Book]:
    """Lists all unique books."""
    logger.info("Fetching list of all books.")
    try:
        # Query all books, order them for consistency
        books = db.query(models.Book).order_by(models.Book.author, models.Book.title).all()
        return books
    except Exception as e:
        logger.error(f"Failed to fetch books: {e}", exc_info=True)
        return []
    
def get_clippings_for_book(db: Session, book_id: int) -> List[models.Clipping]:
    """Gets all clippings for a specific book ID."""
    logger.info(f"Fetching clippings for book_id: {book_id}")
    # TODO: Implement query
    # return db.query(models.Clipping).filter(models.Clipping.book_id == book_id).order_by(models.Clipping.clipping_date).all() # Or order by location
    pass # Placeholder

def get_random_clipping(db: Session, book_id: Optional[int] = None) -> Optional[models.Clipping]:
    """Gets a random clipping, optionally filtered by book ID."""
    logger.info(f"Fetching random clipping. Book filter ID: {book_id}")
    # TODO: Implement query (Random selection in SQL can be tricky/DB specific)
    # import random
    # query = db.query(models.Clipping)
    # if book_id:
    #     query = query.filter(models.Clipping.book_id == book_id)
    # count = query.count()
    # if count > 0:
    #     return query.offset(random.randint(0, count - 1)).first()
    # return None
    pass # Placeholder