import typer
import logging
from typing_extensions import Annotated, Optional # Use typing_extensions for older Python versions if needed, otherwise use typing
from sqlalchemy.orm import Session
from pathlib import Path 

from rich.console import Console
from rich.table import Table

from app.database.database import SessionLocal, init_db, engine # Import engine if needed directly
from app.services import clipping_service # Import the service module

# Configure logging level (optional, can be configured elsewhere)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the Typer application
cli_app = typer.Typer(help="Kindle Insights CLI - Manage your Kindle clippings.")

# Database Dependency (Context Manager) for CLI commands
# Ensures the session is closed even if errors occur
def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@cli_app.command()
def init():
    """
    Initialize the db schema. Run once, initially
    """
    typer.echo("Initializing database")
    try:
        init_db() # Call the function from database.py
        typer.secho("Database initialized successfully.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Database initialization failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

@cli_app.command()
def ingest(
    filepath: Annotated[
        Path,
        typer.Argument(..., help="Path to the MyClippings.txt file.")
    ]
):
    """
    Import clippings from a MyClippings.txt file into the database.
    """
    typer.echo(f"Starting ingestion process for: {filepath}")
    db_session: Session = next(get_db_session())  # Get a DB session

    try:
        summary = clipping_service.import_clippings(db=db_session, file_path=str(filepath))  # Call service function
        typer.echo("\n--- Import Summary ---")
        typer.echo(f"Processed Entries: {summary['processed']}")
        typer.secho(f"Added New:        {summary['added']}", fg=typer.colors.GREEN if summary['added'] > 0 else None)
        typer.secho(f"Duplicates Found: {summary['duplicates']}", fg=typer.colors.YELLOW if summary['duplicates'] > 0 else None)
        typer.secho(f"Errors Encountered:{summary['errors']}", fg=typer.colors.RED if summary['errors'] > 0 else None)
    except Exception as e:
        logger.error(f"An unexpected error occurred during ingestion: {e}", exc_info=True)
        typer.secho(f"An unexpected error occurred during ingestion: {e}", fg=typer.colors.RED)
    finally:
        if db_session:
            db_session.close()


@cli_app.command()
def list_books():
    """Lists all unique books in the library."""
    typer.echo("Listing books...")
    db: Session = next(get_db_session())
    books : List[models.Book] = [] 
    
    try:
        books = clipping_service.list_books(db=db)
        
        if not books:
            console.print("No books found in the library. Use 'ingest' to add clippings.")
            raise typer.Exit(code=0)
        
        # Make nice table using Rich
        table = Table(title="Your Kindle Library", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="dim", width=6, justify="right")
        table.add_column("Title", style="cyan", no_wrap=False)
        table.add_column("Author", style="green", no_wrap=False)
        
        for book in books:
            author_display = book.author if book.author else "Unknown"
            table.add_row(str(book.id), book.title, author_display)
            
        console.print(table)
        
    except Exception as e:
        logger.error(f"An unexpected error occurred while listing books: {e}", exc_info=True)
        console.print(f"[bold red]An unexpected error occurred while listing books: {e}[/]", style="red")
    finally:
        db.close()

@cli_app.command()
def show_highlights(book_query: str = typer.Argument(..., help="ID, Title, or Author query for the book.")):
    """Shows highlights for a specific book."""
    typer.echo(f"Showing highlights for '{book_query}'... (Not Implemented Yet)")
    # TODO: Implement book lookup and call to clipping_service.get_clippings_for_book

@cli_app.command(name="random") # Use 'random' as the command name instead of 'random_quote'
def random_quote(book_query: Optional[str] = typer.Option(None, "--book", "-b", help="Filter by book ID, Title, or Author.")):
    """Displays a random highlight/note, optionally filtered by book."""
    typer.echo(f"Getting random quote (Filter: {book_query})... (Not Implemented Yet)")
     # TODO: Implement book lookup (if filter) and call to clipping_service.get_random_clipping


if __name__ == "__main__":
    cli_app()

