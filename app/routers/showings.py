from fastapi import APIRouter
from pydantic import BaseModel

from app.services import routing

router = APIRouter()


class RouteRequest(BaseModel):
    home: str
    addresses: list[str]
    start: str = "17:00"
    showing_minutes: int = 30
    buffer_minutes: int = 5
    traffic: str = "auto"
    break_after: int = 0
    break_minutes: int = 15


@router.post("/showings/route")
async def plan_route(req: RouteRequest):
    return routing.plan(
        home=req.home,
        addresses=req.addresses,
        start=req.start,
        showing_minutes=req.showing_minutes,
        buffer_minutes=req.buffer_minutes,
        traffic=req.traffic,
        break_after=req.break_after,
        break_minutes=req.break_minutes,
    )
