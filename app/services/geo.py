"""
Great-circle distance helpers, in Python and as SQL expressions (no PostGIS needed).
"""

import math

from sqlalchemy import ColumnElement, Float, and_, cast, func

from app.models import Installer
from app.models.installer import MAX_COVERAGE_RADIUS_MILES

EARTH_RADIUS_MILES = 3958.8
# Room for rounding, so a point exactly on the edge is never cut by the box.
_BOX_MARGIN_DEGREES = 0.001


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


def bounding_box_degrees(latitude: float, miles: float) -> tuple[float, float | None]:
    """How far, in degrees, a circle of `miles` around `latitude` can reach north-south
    and east-west. The east-west reach is `None` when the circle takes in a pole.

    Exact on a sphere, so it stays safe for very large circles: the east-west reach is
    wider than `miles / cos(latitude)` once the circle is hundreds of miles across.
    """
    angle = miles / EARTH_RADIUS_MILES
    latitude_span = math.degrees(angle) + _BOX_MARGIN_DEGREES
    ratio = math.sin(angle) / max(math.cos(math.radians(latitude)), 1e-9)
    if angle >= math.pi / 2 or ratio >= 1:
        return latitude_span, None
    return latitude_span, math.degrees(math.asin(ratio)) + _BOX_MARGIN_DEGREES


def installer_covers_point(latitude: float, longitude: float) -> ColumnElement[bool]:
    """SQL predicate: the point lies inside the installer's coverage circle.

    A bounding box sized for the largest allowed radius is a cheap first test; the exact
    distance decides. The box must never exclude a point the distance accepts (see
    `bounding_box_degrees`).
    """
    latitude_span, longitude_span = bounding_box_degrees(latitude, MAX_COVERAGE_RADIUS_MILES)
    box = [Installer.latitude.between(latitude - latitude_span, latitude + latitude_span)]
    if longitude_span is not None:
        box.append(
            Installer.longitude.between(longitude - longitude_span, longitude + longitude_span)
        )
    return and_(
        *box,
        installer_distance_to(latitude, longitude) <= Installer.coverage_radius_miles,
    )