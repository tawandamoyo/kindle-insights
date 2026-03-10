import logging
import random
from typing import Dict, Optional, List 
from sqlalchemy import or_
from sqlalchemy.sql import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import models 
from app.parsing.parser import parse_clippings_file

logger = logging.getLogger(__name__)

def get_or_create_book(db: Session, title: str, author: Optional[str]) -> models.Book:
    """
    Gets a book from DB based on title and author, or creates it if not found.
    Uses the author string directly as provided (assuming parser normalization).
    """
    book = db.query(models.Book).filter_by(title=title, author=author).first()
    if book:
        return book
    else:
        logger.info(f"Creating new book entry: Title='{title}', Author='{author}'")
        book = models.Book(title=title, author=author)
        db.add(book)
        try:
            db.flush()
            logger.info(f"Flushed new book: {book.title} (ID: {book.id})")
            return book
        except IntegrityError as e:
            db.rollback() 
            logger.warning(f"IntegrityError on flush for book: {title} ({author}). Attempting recovery lookup. Error: {e}")
            book = db.query(models.Book).filter_by(title=title, author=author).first()
            if book:
                 logger.info(f"Recovered book after IntegrityError: {book.title} (ID: {book.id})")
                 return book
            else:
                logger.error(f"Failed to get or create book after IntegrityError recovery attempt: {title} ({author})")
                raise ValueError(f"Failed to get or create book: {title} ({author}) after IntegrityError")
        except Exception as e:
             db.rollback()
             logger.error(f"Unexpected error during book flush for {title} ({author}): {e}", exc_info=True)
             raise 

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
    
    session_added_signatures = set()

    for idx, clipping_data in enumerate(parsed_data):
        try:
            book = get_or_create_book(db, clipping_data["book_title"], clipping_data["author"])

            if not book or not book.id:
                 logger.error(f"Skipping clipping #{idx+1} due to missing or invalid book ID for '{clipping_data['book_title']}'")
                 error_count += 1
                 continue
             
            signature = (
                book.id,
                clipping_data["clipping_type"],
                clipping_data["location"],
                clipping_data["content_hash"]
            )

            existing_clipping = db.query(models.Clipping.id).filter_by( 
                book_id=signature[0],
                clipping_type=signature[1],
                location=signature[2],
                content_hash=signature[3]
            ).first() 
            
            is_pending_dublicate = signature in session_added_signatures

            if existing_clipping or is_pending_dublicate:
                duplicate_count += 1
                continue 
            
            session_added_signatures.add(signature)

            try:
                new_clipping = models.Clipping(
                    book_id=book.id,
                    clipping_type=clipping_data["clipping_type"],
                    location=clipping_data["location"],
                    page=clipping_data["page"],
                    clipping_date=clipping_data["clipping_date"],
                    content=clipping_data["content"],
                    content_hash=clipping_data["content_hash"]
                )
                db.add(new_clipping)
                added_count += 1
            
            except KeyError as ke:
                logger.error(f"KeyError creating Clipping object: Missing key {ke}. Data: {clipping_data}", exc_info=False)
                raise 
        except Exception as e:
            err_loc = clipping_data.get('location', 'N/A')
            err_con_hash = clipping_data.get('content_hash', 'N/A')
            logger.error(f"Failed to process parsed clipping #{idx+1} ({clipping_data.get('book_title', 'N/A')} L:{err_loc} H:{err_con_hash}): {e}", exc_info=False)
            error_count += 1
            db.rollback()
            continue
        
    logger.debug(f"DEBUG: Processing clipping_data: {clipping_data}")
    logger.debug(f"DEBUG: Keys in clipping_data: {clipping_data.keys()}")
    

    try:
        logger.info(f"Attempting final commit for {added_count} new clippings...")
        db.commit()
        logger.info("Final commit successful.")
    except Exception as e:
        logger.error(f"Final commit failed after processing file {file_path}: {e}", exc_info=True)
        error_count += added_count 
        added_count = 0
        db.rollback()
        
        
    actual_duplicates = processed_count - added_count - error_count
    summary = {
        "processed": processed_count,
        "added": added_count,
        "duplicates": max(0, actual_duplicates), 
        "errors": error_count
    }
    summary["duplicates"] = max(0, summary["duplicates"])

    logger.info(f"Import finished for {file_path}. Summary: {summary}")
    return summary

def list_books(db: Session) -> List[models.Book]:
    """Lists all unique books."""
    logger.info("Fetching list of all books.")
    try:
        books = db.query(models.Book).order_by(models.Book.author, models.Book.title).all()
        return books
    except Exception as e:
        logger.error(f"Failed to fetch books: {e}", exc_info=True)
        return []

def find_book(db: Session, query: str) -> Optional[models.Book]:
    """Finds a book by ID, title, or author."""
    if query.isdigit():
        return db.query(models.Book).filter(models.Book.id == int(query)).first()
    
    search_query = f"%{query}%"
    return db.query(models.Book).filter(
        or_(
            models.Book.title.ilike(search_query),
            models.Book.author.ilike(search_query)
        )
    ).first()

def get_clippings_for_book(db: Session, book_id: int) -> List[models.Clipping]:
    """Gets all clippings for a specific book ID."""
    logger.info(f"Fetching clippings for book_id: {book_id}")
    return db.query(models.Clipping).filter(models.Clipping.book_id == book_id).order_by(models.Clipping.location).all()

def get_random_clippings(db: Session, book_id: Optional[int] = None, count: int = 1) -> List[models.Clipping]:
    """Gets a number of random clippings, optionally filtered by book ID."""
    logger.info(f"Fetching {count} random clipping(s). Book filter ID: {book_id}")
    query = db.query(models.Clipping)
    if book_id:
        query = query.filter(models.Clipping.book_id == book_id)

    return query.order_by(func.random()).limit(count).all()