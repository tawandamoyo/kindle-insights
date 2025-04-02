from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint, Index, Float, ForeignKey
from sqlalchemy.orm import relationship

# Import the Base class created in database.py
from .database import Base

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    # Allow null author, use parser's normalized version
    author = Column(String, index=True, nullable=True)

    # Define a unique constraint on title and author combination
    __table_args__ = (UniqueConstraint('title', 'author', name='_book_author_uc'),)

    # Relationship to clippings (one book has many clippings)
    # cascade="all, delete-orphan" can be useful if deleting a book should delete its clippings
    clippings = relationship("Clipping", back_populates="book") # cascade="all, delete-orphan"

    def __repr__(self):
        auth = self.author if self.author else "Unknown Author"
        return f"<Book(id={self.id}, title='{self.title[:30]}...', author='{auth}')>"

class Clipping(Base):
    __tablename__ = "clippings"

    id = Column(Integer, primary_key=True, index=True)
    # Foreign key linking to the books table
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    clipping_type = Column(String, index=True, nullable=False) # Highlight, Note, Bookmark
    location = Column(String, nullable=True, index=True) # Index location for sorting/lookup
    page = Column(String, nullable=True) # Page number if available
    clipping_date = Column(DateTime, index=True, nullable=False) # Naive datetime
    content = Column(Text, nullable=True) # Allow null for bookmarks or empty highlights/notes
    # SHA-256 hash for uniqueness check, including allowing null for bookmarks
    content_hash = Column(String(64), index=True, nullable=True)

    # Placeholder for future NLP features
    sentiment_score = Column(Float, nullable=True)

    # Define indexes and unique constraints
    __table_args__ = (
        # Index for sorting/querying clippings within a book by date or location
        Index('ix_clipping_book_date', 'book_id', 'clipping_date'),
        Index('ix_clipping_book_location', 'book_id', 'location'),
         # Unique constraint based on requirement (Book, Type, Location, ContentHash)
        UniqueConstraint('book_id', 'clipping_type', 'location', 'content_hash', name='_clipping_uniqueness_uc'),
    )

    # Relationship back to book (many clippings belong to one book)
    book = relationship("Book", back_populates="clippings")

    def __repr__(self):
        cont_prev = (self.content[:40] + '...') if self.content else 'N/A'
        return f"<Clipping(id={self.id}, book_id={self.book_id}, type='{self.clipping_type}', loc='{self.location}', date='{self.clipping_date.strftime('%Y-%m-%d')}', content='{cont_prev}')>"