"""atlas: a knowledge graph built from your notes."""

VERSION = "1.1.0"

from .graph import Graph
from .extract import extract_document, extract_triples, extract_entities

__all__ = ["Graph", "VERSION", "extract_document", "extract_triples",
           "extract_entities"]
