from types import SimpleNamespace
import pytest
from app.services.download_service import PreparedDownload
from app.core.errors import MeetingError

class Response:
    status=200
    headers={'Content-Length':'6'}
    def __init__(self): self.content=self; self.closed=False
    async def iter_chunked(self,size):
        yield b'abc'; yield b'def'
    def close(self): self.closed=True

class Session:
    closed=False
    async def close(self): self.closed=True

class Service:
    def __init__(self):
        self.rt=SimpleNamespace(settings=SimpleNamespace(max_download_bytes=100,download_bytes_per_second=10**9))
        self.charged=0;self.released=[];self.reject=False
    async def charge(self,p,size):
        if self.reject:raise MeetingError('RATE_LIMITED',429)
        self.charged+=size
    async def release(self,p,ticket,sent):self.released.append(sent)

async def test_stream_is_bounded_charges_before_return_and_closes():
    service=Service();response=Response();session=Session()
    stream=PreparedDownload(service,None,'private-ticket','asset',session,response,'txt',6)
    chunks=[]
    async for chunk in stream.iterate():
        assert service.charged>=sum(map(len,chunks))+len(chunk)
        chunks.append(chunk)
    assert b''.join(chunks)==b'abcdef' and service.released==[6]
    assert response.closed and session.closed
    await stream.close();assert service.released==[6]

async def test_quota_failure_never_yields_bytes_and_always_releases():
    service=Service();service.reject=True;response=Response();session=Session()
    stream=PreparedDownload(service,None,'private-ticket','asset',session,response,'txt',6)
    with pytest.raises(MeetingError):
        await anext(stream.iterate())
    assert stream.sent==0 and response.closed and session.closed and service.released==[0]

async def test_truncated_upstream_is_not_a_successful_download():
    service=Service();response=Response();session=Session()
    stream=PreparedDownload(service,None,'private-ticket','asset',session,response,'txt',9)
    with pytest.raises(MeetingError):
        _=[chunk async for chunk in stream.iterate()]
    assert response.closed and session.closed
