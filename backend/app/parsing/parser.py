import re
import hashlib
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dateutil.parser import parse as parse_date
from fuzzywuzzy import fuzz, process 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# regex patterns

# Line 1: Book title and author
# Handles titles with or without parentheses, captures author if present
LINE1_PATTERN = re.compile(r"^(.*?)(?:\s+\(([^)]+)\))?$")

# Line 2: Metadata (Type, Page, Location, Date)
# Revised LINE2_PATTERN (Place this in backend/app/parsing/parser.py)
LINE2_PATTERN = re.compile(
    r"^\-\s+Your\s+"
    r"(Highlight|Note|Bookmark)" # Clipping Type (Group 1)
    r"\s+" # Space after type is mandatory
    # EITHER 'on page P [| Location L]' OR just 'on Location L'
    r"(?:" # Start non-capturing group for metadata options
      # Option 1: Page is present (Location is optional after page)
      r"(?:on\s+page\s+(\d+[\-\d]*))" # Page (Group 2)
      r"(?:\s*\|\s*Location\s+([\d\-]+))?" # Optional Location following Page (Group 3)
    r"|" # OR
      # Option 2: Only Location is present
      r"(?:on\s+Location\s+([\d\-]+))" # Just Location (Group 4) - MUST have 'on' here based on samples
    r")" # End non-capturing group for metadata options
    r"\s*\|\s*Added\s+on\s+(.*?)$" # Separator '|', 'Added on', and Date string (Group 5)
)

DELIMITER = "=========="

def normalize_author(author_string: Optional[str], existing_authors: Optional[List[str]] = None) -> Optional[str]:
    """
    Normalizes author names and attempts to match them against known authors
    Simple initial implementation: lowercase and strip whitespace
    TODO: Enhance with fuzzy matching or other techniques 
    """
    if not author_string:
        return None
    
    normalized = author_string.strip().lower()
    
    # Implement basic normalization now, use more advanced in service layer
    
    normalized = re.sub(r'[.,]', '', normalized)  # Remove periods and commas
    
    parts = normalized.split()
    if len(parts) > 1 and len(parts[-1]) > 1:
        # check if "Lastname, Firstname" format
        if ',' in parts[0]:
            last_name = parts[0].replace(',', '').strip()
            first_names = " ".join(parts[1:]).strip()
            normalized = f"{first_names} {last_name}".strip()
    
    return normalized.title()

def generate_content_hash(content: Optional[str]) -> Optional[str]:
    """
    Generates a hash for the content to ensure uniqueness
    """
    if content:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    return None

def parse_clippings_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses the clippings file and returns a list of dictionaries each representing a clipping
    """
    parsed_clippings = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except FileNotFoundError:
        logger.error(f"File not found at: {file_path}")
        return []
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return []
    
    current_clipping_lines = []
    entry_count = 0
    processed_count = 0
    skipped_count = 0
    
    for line_num, line in enumerate(lines):
        line = line.strip()
        if line == DELIMITER:
            entry_count += 1
            if len(current_clipping_lines) >= 2:
                try:
                    parsed_data = parse_entry(current_clipping_lines)
                    if parsed_data:
                        parsed_clippings.append(parsed_data)
                        processed_count += 1
                    else:
                        skipped_count += 1
                        logger.warning(f"Skipped entry ending near line {line_num + 1}")
                except Exception as e:
                    skipped_count += 1
                    logger.error(f"Error processing entry ending near line {line_num + 1}: {e}\nEntry lines: {current_clipping_lines}", exc_info=False)
            elif current_clipping_lines:
                skipped_count += 1
                logger.warning(f"Skipped potentially incomplete entry ending near line {line_num + 1}: {current_clipping_lines}")
                
            current_clipping_lines = []
        elif line:
            current_clipping_lines.append(line)
            
    logger.info(f"Parsing complete for {file_path}")
    logger.info(f"Total entries: {entry_count}, Processed: {processed_count}, Skipped: {skipped_count}")
    
    return parsed_clippings

def parse_entry(entry_lines: List[str]) -> Optional[Dict[str, Any]]:
    """
    Parses a single entry from the clippings file
    """
    if len(entry_lines) < 2:
        return None
    
    # Line 1: Book title and author
    line1_match = LINE1_PATTERN.match(entry_lines[0])
    if not line1_match:
        logger.warning(f"Line 1 format error: {entry_lines[0]}")
        return None
    book_title = line1_match.group(1).strip()
    raw_author = line1_match.group(2).strip() if line1_match.group(2) else None
    normalized_author = normalize_author(raw_author)
    
    # Line 2: Metadata
    line2_match = LINE2_PATTERN.match(entry_lines[1])
    if not line2_match:
        logger.warning(f"Line 2 format error: {entry_lines[1]}")
        return None
    clipping_type = line2_match.group(1).strip()
    page = line2_match.group(2).strip() if line2_match.group(2) else None
    location = line2_match.group(3).strip() if line2_match.group(3) else None
    location2 = line2_match.group(4).strip() if line2_match.group(4) else None
    date_str = line2_match.group(5).strip()
    
    location= location if page else location2
    
    # Parse date -> naive date 
    try:
        clipping_date = parse_date(date_str)
    except Exception as e:
        logger.warning(f"Date parsing error: {date_str} - {e}")
        return None
    
    content = None
    if clipping_type in ["Highlight", "Note"] and len(entry_lines) > 2:
        content = "\n".join(entry_lines[2:]).strip()
        if not content:
            content = None
            
    # Generate content hash
    content_hash = generate_content_hash(content)
    
    return {
        "book_title": book_title,
        "author": normalized_author,
        "clipping_type": clipping_type,
        "page": page,
        "location": location,
        "clipping_date": clipping_date,
        "content": content,
        "content_hash": content_hash
    }
    
    
# Example usage (for testing purposes)
if __name__ == "__main__":
    # Create a dummy MyClippings.txt for testing
    dummy_file_content = """Book Title One (Author A)
- Your Highlight on page 10 | Location 100-105 | Added on Sunday, March 30, 2025 10:00:00 AM

This is the first highlight text.
It spans multiple lines.
==========
Book Title One (Author A)
- Your Note on page 15 | Location 150 | Added on Sunday, March 30, 2025 10:05:00 AM

This is a note associated with a highlight.
==========
Book Title Two (Tolkien, J. R. R.)
- Your Highlight on page 20 | Location 200-210 | Added on Monday, 31 March 2025 11:15:30 PM

Highlight text from the second book.
==========
Book Title Three ()
- Your Bookmark on Location 300 | Added on Tuesday, 1 April 2025 01:20:45 PM
==========
Malformed Entry
Just one line.
==========
Another Book (Some Author)
- Invalid Metadata Line here Added on Tuesday, 1 April 2025 01:30:00 PM

Content for malformed metadata.
==========
"""
    dummy_file_path = "dummy_clippings.txt"
    with open(dummy_file_path, "w", encoding="utf-8") as f:
        f.write(dummy_file_content)

    print(f"Parsing dummy file: {dummy_file_path}")
    parsed_results = parse_clippings_file(dummy_file_path)

    print("\n--- Parsed Results ---")
    if parsed_results:
        for i, clipping in enumerate(parsed_results):
            print(f"\nClipping {i+1}:")
            for key, value in clipping.items():
                 # Format datetime for printing
                if isinstance(value, datetime):
                    print(f"  {key}: {value.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    print(f"  {key}: {value}")
    else:
        print("No clippings parsed.")

    # Clean up the dummy file
    import os
    os.remove(dummy_file_path)




