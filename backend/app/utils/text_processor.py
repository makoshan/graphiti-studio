"""
Text processing utilities.
"""

import re
from typing import List

from ..services.file_parser import FileParser, split_text_into_chunks  # noqa: F401 — re-exported


class TextProcessor:
    """Text processor with extraction, splitting, and preprocessing."""

    @staticmethod
    def extract_from_files(file_paths: List[str]) -> str:
        """Extract text from multiple files."""
        return FileParser.extract_from_multiple(file_paths)

    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = 1000,
        overlap: int = 100,
    ) -> List[str]:
        """
        Split text into chunks.

        Args:
            text: Source text.
            chunk_size: Characters per chunk.
            overlap: Overlap characters between chunks.

        Returns:
            List of text chunks.
        """
        return split_text_into_chunks(text, chunk_size, overlap)

    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        Preprocess text:
        - Normalize line endings
        - Remove excessive blank lines
        - Strip leading/trailing whitespace per line

        Args:
            text: Raw text.

        Returns:
            Processed text.
        """
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Collapse runs of 3+ newlines down to 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Strip each line
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)

        return text.strip()

    @staticmethod
    def get_text_stats(text: str) -> dict:
        """Return basic statistics about the text."""
        return {
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "total_words": len(text.split()),
        }
