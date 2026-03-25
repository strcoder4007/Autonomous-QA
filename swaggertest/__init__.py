"""Swagger API Test Tool — discover, test, and validate OpenAPI endpoints."""

__version__ = "1.0.0"

from swaggertest.parser import SpecParser
from swaggertest.runner import Runner
from swaggertest.reporter import Report

__all__ = ["SpecParser", "Runner", "Report", "__version__"]
