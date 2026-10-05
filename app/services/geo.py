"""Great-circle distance helpers, in Python and as SQL expressions (no PostGIS needed)."""

import math

from sqlalchemy import ColumnElement, Float, and_, cast, func

from app.models import Installer
from app.models.installer import MAX_COVERAGE_RADIUS_MILES

EARTH_RADIUS_MILES = 3958.8
_MILES_PER_DEGREE_LATITUDE = 69.0


def haversine_miles(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Distance in miles between two points given in decimal degrees."""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    half_dphi = (phi_b - phi_a) / 2
    half_dlambda = math.radians(lon_b - lon_a) / 2
    chord = (
        math.sin(half_dphi) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(half_dlambda) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(chord)))


def distance_miles(
    lat_a: ColumnElement[float] | float,
    lon_a: ColumnElement[float] | float,
    lat_b: ColumnElement[float] | float,
    lon_b: ColumnElement[float] | float,
) -> ColumnElement[float]:
    """SQL haversine distance in miles between two points (columns or literal degrees)."""
    half_dphi = (func.radians(lat_b) - func.radians(lat_a)) / 2
    half_dlambda = (func.radians(lon_b) - func.radians(lon_a)) / 2
    chord = func.power(func.sin(half_dphi), 2) + func.cos(func.radians(lat_a)) * func.cos(
        func.radians(lat_b)
    ) * func.power(func.sin(half_dlambda), 2)
    return cast(2 * EARTH_RADIUS_MILES * func.asin(func.least(1.0, func.sqrt(chord))), Float)


def installer_distance_to(latitude: float, longitude: float) -> ColumnElement[float]:
    """SQL distance in miles from each installer's base to a fixed point."""
    return distance_miles(Installer.latitude, Installer.longitude, latitude, longitude)


def installer_covers_point(latitude: float, longitude: float) -> ColumnElement[bool]:
    """SQL predicate: the point lies inside the installer's coverage circle.

    A bounding box sized for the largest allowed radius comes first so the
    `(latitude, longitude)` index can discard far-away installers before any trigonometry.
    """
    latitude_span = MAX_COVERAGE_RADIUS_MILES / _MILES_PER_DEGREE_LATITUDE
    longitude_span = latitude_span / max(math.cos(math.radians(latitude)), 0.01)
    return and_(
        Installer.latitude.between(latitude - latitude_span, latitude + latitude_span),
        Installer.longitude.between(longitude - longitude_span, longitude + longitude_span),
        installer_distance_to(latitude, longitude) <= Installer.coverage_radius_miles,
    )
