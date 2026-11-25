"""Coverage radius up to 1,000 miles (nationwide businesses)."""

import math

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.installer import MAX_COVERAGE_RADIUS_MILES
from app.services.geo import EARTH_RADIUS_MILES, bounding_box_degrees, haversine_miles
from tests.helpers import auth_headers, create_installer

EDINBURGH = (55.9533, -3.1883)


def _destination(
    latitude: float, longitude: float, bearing_degrees: float, miles: float
) -> tuple[float, float]:
    """The point `miles` away from the start along a bearing (great circle)."""
    angle = miles / EARTH_RADIUS_MILES
    phi, bearing = math.radians(latitude), math.radians(bearing_degrees)
    phi_2 = math.asin(
        math.sin(phi) * math.cos(angle) + math.cos(phi) * math.sin(angle) * math.cos(bearing)
    )
    lambda_2 = math.radians(longitude) + math.atan2(
        math.sin(bearing) * math.sin(angle) * math.cos(phi),
        math.cos(angle) - math.sin(phi) * math.sin(phi_2),
    )
    return math.degrees(phi_2), math.degrees(lambda_2)


@pytest.mark.parametrize("latitude", [0.0, 35.0, 50.0, 55.0, 60.0, 70.0])
@pytest.mark.parametrize("miles", [15, 100, 500, 1000])
def test_the_bounding_box_never_cuts_a_point_inside_the_circle(latitude: float, miles: int):
    """The box is only a shortcut: every point the distance accepts must lie inside it."""
    latitude_span, longitude_span = bounding_box_degrees(latitude, miles)
    for bearing in range(0, 360, 5):
        point_lat, point_lon = _destination(latitude, 10.0, bearing, miles * 0.9999)
        assert haversine_miles(latitude, 10.0, point_lat, point_lon) <= miles
        assert abs(point_lat - latitude) <= latitude_span
        if longitude_span is not None:
            assert abs(point_lon - 10.0) <= longitude_span


def test_the_old_longitude_formula_would_have_cut_large_circles():
    """Guards the exact formula: `miles / cos(latitude)` is too narrow at 1,000 miles."""
    _, longitude_span = bounding_box_degrees(55.0, MAX_COVERAGE_RADIUS_MILES)
    naive = math.degrees(MAX_COVERAGE_RADIUS_MILES / EARTH_RADIUS_MILES) / math.cos(
        math.radians(55.0)
    )
    assert longitude_span is not None
    assert longitude_span > naive


async def test_an_installer_can_set_a_radius_of_1000_miles(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Nationwide Sparks")
    headers = auth_headers(installer.user)

    saved = await client.patch(
        "/api/v1/installers/me", headers=headers, json={"coverage_radius_miles": 1000}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["coverage"]["radius_miles"] == 1000
    public = (await client.get("/api/v1/installers/nationwide-sparks")).json()
    assert public["coverage"]["radius_miles"] == 1000

    for radius in (1001, 0, -5):
        refused = await client.patch(
            "/api/v1/installers/me", headers=headers, json={"coverage_radius_miles": radius}
        )
        assert refused.status_code == 422
        assert set(refused.json()["error"]["fields"]) == {"coverage_radius_miles"}


async def test_the_database_enforces_the_same_range(db: AsyncSession):
    await create_installer(db, "Exactly One Thousand", radius=1000)
    with pytest.raises(IntegrityError):
        await create_installer(db, "Too Wide", radius=1001)
    await db.rollback()


async def test_a_large_radius_reaches_far_towns_and_a_small_one_does_not(
    client: httpx.AsyncClient, db: AsyncSession
):
    """Edinburgh to London is about 332 miles; Edinburgh to Brighton about 376."""
    await create_installer(db, "Scotland Only", at=EDINBURGH, location="edinburgh", radius=100)
    await create_installer(db, "Reaches London", at=EDINBURGH, location="edinburgh", radius=350)
    await create_installer(db, "Whole UK", at=EDINBURGH, location="edinburgh", radius=1000)

    async def serving(town: str) -> set[str]:
        response = await client.get("/api/v1/installers", params={"location": town})
        assert response.status_code == 200
        return {item["slug"] for item in response.json()["items"]}

    assert await serving("edinburgh") == {"scotland-only", "reaches-london", "whole-uk"}
    assert await serving("london") == {"reaches-london", "whole-uk"}
    assert await serving("brighton") == {"whole-uk"}
