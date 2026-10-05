"""Billing request and response bodies."""

from typing import Literal

from pydantic import BaseModel

from app.core.enums import Plan


class CheckoutRequest(BaseModel):
    plan: Literal[Plan.PRO, Plan.PREMIUM]


class SessionUrl(BaseModel):
    url: str
