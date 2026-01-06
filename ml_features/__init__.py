"""
ML Features Package
Contains expense prediction and buying suggestions
"""

from .ml_service import MLService
from .routes import ml_bp

__all__ = ['MLService', 'ml_bp']

