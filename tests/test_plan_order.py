"""Installer lists put Premium first, then Pro, then Free (website location pages and Dashboard)."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from tests.helpers import Plan, auth_headers, create_installer, create_user


async def _make(db: AsyncSession):
    # Created in the "wrong" order on purpose: free, premium, pro.
    await create_installer(db, "Free Sparks", plan=Plan.FREE)
    await create_installer(db, "Premium Sparks", plan=Plan.PREMIUM)
    await create_installer(db, "Pro Sparks", plan=Plan.PRO)


async def test_location_page_lists_premium_then_pro_then_free(
    client: httpx.AsyncClient, db: AsyncSession
):
    await _make(db)
    response = await client.get("/api/v1/installers", params={"location": "manchester"})
    names = [item["business_name"] for item in response.json()["items"]]
    assert names == ["Premium Sparks", "Pro Sparks", "Free Sparks"]


async def test_dashboard_installers_list_premium_then_pro_then_free(
    client: httpx.AsyncClient, db: AsyncSession
):
    await _make(db)
    admin = await create_user(db, role=Role.ADMIN)
    response = await client.get("/api/v1/admin/installers", headers=auth_headers(admin))
    names = [item["business_name"] for item in response.json()["items"]]
    assert names == ["Premium Sparks", "Pro Sparks", "Free Sparks"]
