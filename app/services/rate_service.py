"""PostgreSQL-coordinated fixed-spacing limiter; no replica-local quota multiplication.

Short waits sleep outside the database lock. Longer gaps are deferred without
being treated as a failed attempt by the caller.
"""
import asyncio
import math
from datetime import timedelta
from sqlalchemy import select
from app.core.types import utcnow
from app.core.security import digest
from app.core.errors import MeetingError
from app.models import RateLimit

SHORT_WAIT_SECONDS = 2


class RateService:
    def __init__(self,runtime):self.rt=runtime

    async def acquire(self,bucket:str,interval:float,*,heartbeat=None):
        if interval<=0:return
        key=digest(bucket)
        while True:
            async with self.rt.db.lock('rate:'+key),self.rt.db.transaction() as s:
                row=await s.scalar(select(RateLimit).where(RateLimit.bucket==key).with_for_update())
                now=utcnow()
                if row and row.next_allowed_at>now:
                    wait=(row.next_allowed_at-now).total_seconds()
                else:
                    if row is None:
                        row=RateLimit(bucket=key,next_allowed_at=now+timedelta(seconds=interval));s.add(row)
                    else:row.next_allowed_at=now+timedelta(seconds=interval)
                    return
            if wait>SHORT_WAIT_SECONDS:
                raise MeetingError('RATE_LIMITED',429,retry_after=max(1,math.ceil(wait)),budgeted=False)
            if heartbeat:await heartbeat()
            await asyncio.sleep(wait)
