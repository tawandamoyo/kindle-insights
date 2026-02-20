import typer
import logging
from typing import List
from typing_extensions import Annotated, Optional 
from sqlalchemy.orm import Session
from pathlib import Path 

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from app.database.database import SessionLocal, init_db, engine 
from app.services import clipping_service 
from app.database import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

cli_app = typer.Typer(help="Kindle Insights CLI - Manage your Kindle clippings.")
console = Console()

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
        init_db() 
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
    db_session: Session = next(get_db_session())

    try:
        summary = clipping_service.import_clippings(db=db_session, file_path=str(filepath))
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

def _display_clipping(clipping: models.Clipping):
    """Helper to display a single clipping in a formatted panel."""
    if not clipping:
        return
    
    author_str = clipping.book.author or "Unknown Author"
    title_str = f"[bold cyan]{clipping.book.title}[/bold cyan] by [green]{author_str}[/green]"
    
    meta_parts = [
        f"Type: {clipping.clipping_type}",
        f"Date: {clipping.clipping_date.strftime('%Y-%m-%d')}"
    ]
    if clipping.page:
        meta_parts.append(f"Page: {clipping.page}")
    if clipping.location:
        meta_parts.append(f"Location: {clipping.location}")
        
    meta_str = " | ".join(meta_parts)
    
    content = clipping.content if clipping.content else "[italic]No content for this clipping.[/italic]"
    
    console.print(Panel(
        content,
        title=title_str,
        subtitle=meta_str,
        border_style="blue"
    ))

@cli_app.command()
def show_highlights(book_query: str = typer.Argument(..., help="ID, Title, or Author query for the book.")):
    """Shows highlights for a specific book."""
    db: Session = next(get_db_session())
    try:
        book = clipping_service.find_book(db, book_query)
        if not book:
            typer.secho(f"Book not found for query: '{book_query}'", fg=typer.colors.RED)
            raise typer.Exit(1)
        
        clippings = clipping_service.get_clippings_for_book(db, book.id)
        if not clippings:
            typer.echo(f"No highlights found for '{book.title}'.")
            raise typer.Exit()
            
        typer.echo(f"Showing {len(clippings)} highlights for '{book.title}':")
        for clip in clippings:
            _display_clipping(clip)

    finally:
        db.close()

@cli_app.command(name="random")
def random_quote(book_query: Optional[str] = typer.Option(None, "--book", "-b", help="Filter by book ID, Title, or Author.")):
    """Displays a random highlight/note, optionally filtered by book."""
    db: Session = next(get_db_session())
    book_id = None
    try:
        if book_query:
            book = clipping_service.find_book(db, book_query)
            if not book:
                typer.secho(f"Book not found for query: '{book_query}'", fg=typer.colors.RED)
                raise typer.Exit(1)
            book_id = book.id
        
        clipping = clipping_service.get_random_clipping(db, book_id=book_id)
        
        if not clipping:
            msg = "No clippings found"
            if book_query:
                msg += f" for '{book_query}'"
            typer.echo(msg + ".")
            raise typer.Exit()
            
        _display_clipping(clipping)

    finally:
        db.close()


if __name__ == "__main__":
    cli_app()

