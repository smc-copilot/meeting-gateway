"""One independently deployable Worker process; PostgreSQL leases coordinate multiple processes."""
import argparse
import asyncio
import logging
import signal
import time
import uuid
from app.core.config import Settings
from app.core.errors import MeetingError
from app.core.types import Principal
from app.runtime import Runtime

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, runtime, worker_id=None):
        self.rt = runtime
        self.worker_id = worker_id or 'worker-' + str(uuid.uuid4())
        self.stopping = asyncio.Event()
        self.last_housekeeping = 0.0

    async def _heartbeat(self, job, execution):
        while True:
            await asyncio.sleep(max(5, self.rt.settings.worker_lease_seconds//3))
            if not await self.rt.jobs.heartbeat(job.id, job.lease_token):
                execution.cancel()
                return

    async def _dispatch(self, job):
        if job.kind == 'SYNC':
            await self.rt.sync.run(job, job.lease_token)
        elif job.kind == 'CONTENT':
            await self.rt.content.fetch(Principal.model_validate(job.principal_data), job.payload['recording_id'],
                job.payload['content_type'], job_id=job.id, lease_token=job.lease_token)
        elif job.kind == 'INGEST_CONTENT':
            await self.rt.content.fetch_ingestion(job, job.lease_token)
        elif job.kind == 'CREATE':
            await self.rt.operations.execute(job.id, job.lease_token)
        elif job.kind == 'SOURCE_QUERY':
            await self.rt.queries.run(job, job.lease_token)
        elif job.kind == 'INBOX':
            await self.rt.events.process_inbox(job, job.lease_token)
        elif job.kind == 'OUTBOX':
            await self.rt.events.deliver(job, job.lease_token)
        else:
            raise MeetingError('INVALID_REQUEST', 422)

    async def run_once(self):
        if not self.rt.settings.meeting_enabled:
            return False
        job = await self.rt.jobs.claim(self.worker_id)
        if job is None:
            return False
        execution = asyncio.create_task(self._dispatch(job))
        pulse = asyncio.create_task(self._heartbeat(job, execution))
        try:
            await execution
            await self.rt.jobs.finish(job.id, job.lease_token)
        except asyncio.CancelledError:
            # CREATE handles its own durable uncertainty journal. Others are safely reclaimable after lease expiry.
            if not self.stopping.is_set():
                logger.warning('worker.lease_lost job_id=%s', job.id)
            else:
                raise
        except Exception as exc:
            await self.rt.jobs.fail(job.id, job.lease_token, exc)
            logger.warning('worker.job_failed job_id=%s reason=%s', job.id,
                           exc.reason if isinstance(exc, MeetingError) else 'INTERNAL_ERROR')
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
        return True

    async def housekeeping(self):
        if not self.rt.settings.meeting_enabled:
            return
        from app.services.maintenance_service import MaintenanceService
        maintenance = MaintenanceService(self.rt)
        for function in (self.rt.sync.schedule_due, maintenance.tokens, maintenance.personal_sync,
                         self.rt.events.invalidate_delivery_access, self.rt.env_sts.refresh_due):
            try:
                await function()
            except Exception as exc:
                logger.warning('worker.housekeeping_failed type=%s reason=%s', function.__name__,
                               exc.reason if isinstance(exc, MeetingError) else 'INTERNAL_ERROR')
        if time.monotonic()-self.last_housekeeping >= self.rt.settings.maintenance_interval_seconds:
            await maintenance.expire()
            self.last_housekeeping = time.monotonic()

    async def run(self):
        last_cadence = 0.0
        while not self.stopping.is_set():
            try:
                if time.monotonic()-last_cadence >= 60:
                    await self.housekeeping()
                    last_cadence = time.monotonic()
                worked = await self.run_once()
            except asyncio.CancelledError:
                self.stopping.set()
                raise
            except Exception as exc:
                logger.warning('worker.loop_failed reason=%s', exc.reason if isinstance(exc, MeetingError) else 'INTERNAL_ERROR')
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=self.rt.settings.worker_poll_seconds)
                except TimeoutError:
                    pass


async def serve(once=False):
    runtime = Runtime(Settings())
    worker = Worker(runtime)
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: (worker.stopping.set(), task.cancel()))
        except NotImplementedError:
            pass
    try:
        if once:
            await worker.run_once()
        else:
            await worker.run()
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description='Meeting durable Worker')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(serve(args.once))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == '__main__':
    main()
