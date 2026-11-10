"""atlas: a knowledge graph built from your notes."""

VERSION = "1.3.0"

from .graph import Graph
from .extract import (extract_cooccurrences, extract_document,
                      extract_triples, extract_entities)

__all__ = ["Graph", "VERSION", "extract_document", "extract_triples",
           "extract_entities", "extract_cooccurrences"]
