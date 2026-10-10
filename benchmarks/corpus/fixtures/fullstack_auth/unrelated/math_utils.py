"""
Unrelated numerical calculations with zero authentication or network code.
"""

def calculate_compound_interest(principal: float, rate: float, periods: int) -> float:
    """Calculates compounded growth strictly using mathematical formula."""
    return principal * ((1.0 + rate) ** periods)

def calculate_vector_norm(x: float, y: float, z: float) -> float:
    """Computes Euclidean norm in 3D space."""
    return (x**2 + y**2 + z**2) ** 0.5
