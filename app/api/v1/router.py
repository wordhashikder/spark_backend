"""The `/api/v1` router."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    auth,
    billing,
    blog,
    contact,
    content,
    conversation_links,
    health,
    installers,
    locations,
    quotes,
    reviews,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    installers,
    locations,
    quotes,
    reviews,
    contact,
    content,
    conversation_links,
    blog,
    billing,
    admin,
):
    api_router.include_router(module.router)
