"""Protocol tools are thin adapters over the same REST domain services."""
from pydantic import Field
from app.schemas.requests import StrictModel,MeetingCreate,MeetingQuery
from app.core.errors import MeetingError
from app.models import AgentGrant
from app.services.permission_service import live

class MeetingList(StrictModel):
    limit:int=Field(20,ge=1,le=100)
    cursor:str|None=Field(None,max_length=4096)
    query:str=Field('',max_length=200)
    connection_ref:str|None=Field(None,max_length=64)
class MeetingGet(StrictModel):
    meeting_id:str=Field(min_length=1,max_length=64)
class TranscriptRead(StrictModel):
    recording_id:str=Field(min_length=1,max_length=64)
    limit:int=Field(100,ge=1,le=500)
    cursor:str|None=Field(None,max_length=4096)
class MinutesRead(StrictModel):
    recording_id:str=Field(min_length=1,max_length=64)
class Download(StrictModel):
    asset_id:str=Field(min_length=1,max_length=64)
    purpose:str=Field(min_length=3,max_length=128)
class Create(MeetingCreate):
    idempotency_key:str=Field(min_length=1,max_length=128)
class Status(StrictModel):
    operation_id:str|None=Field(None,max_length=64)
    job_id:str|None=Field(None,max_length=64)
class SourceQuery(MeetingQuery):
    pass

TOOL_DEFINITIONS={
    'meeting_list':(MeetingList,{'meeting.read'},'查询当前授权范围内已同步的会议；不代表企业全量历史。',True),
    'meeting_get':(MeetingGet,{'meeting.read'},'查看一场有权限访问的会议元数据。',True),
    'meeting_transcript_read':(TranscriptRead,{'meeting.content.read'},'按已验证内容版本分页读取腾讯原生转写。',True),
    'meeting_minutes_read':(MinutesRead,{'meeting.content.read'},'读取腾讯原生纪要，保留原始模型和格式。',True),
    'meeting_download_request':(Download,{'meeting.content.download'},'申请绑定当前主体的原生资料下载许可；下载仍须同一主体认证。',False),
    'meeting_create_prepare':(Create,{'meeting.create.self'},'准备会议创建。可信员工客户端直接入队；其他客户端进入人工确认，确认由原业务系统的员工完成，智能体不能确认。',False),
    'meeting_operation_status':(Status,{'meeting.create.self','meeting.read'},'查看当前调用方自己的创建操作或查询作业。',True),
    'meeting_source_query':(SourceQuery,{'meeting.read'},'按会议 ID 或当前员工自己的时间窗向腾讯查询。不能查询其他员工，也不能改用企业密钥。',False),
}

class ToolService:
    def __init__(self,runtime):self.rt=runtime

    async def list(self,principal):
        async with self.rt.db.session() as s:
            actions=await self.rt.policy.action_ceiling(s,principal)
            if principal.actor_type=='AGENT':
                grant=await s.get(AgentGrant,principal.agent_grant_id)
                actions=actions&set(grant.actions) if live(grant) else set()
        tools=[]
        for name,(schema,required,description,read_only) in TOOL_DEFINITIONS.items():
            if not actions & required:continue
            if name=='meeting_create_prepare' and not self.rt.settings.meeting_create_enabled:continue
            tools.append({'name':name,'description':description,'inputSchema':schema.model_json_schema(),
                'outputSchema':{'type':'object','additionalProperties':True},
                'annotations':{'readOnlyHint':read_only,'destructiveHint':False,'openWorldHint':True,
                    'idempotentHint':name!='meeting_download_request'}})
        return tools

    async def call(self,principal,name,arguments):
        if name not in TOOL_DEFINITIONS:raise MeetingError('INVALID_REQUEST',422)
        schema=TOOL_DEFINITIONS[name][0]
        body=schema.model_validate(arguments)
        p=await self.rt.auth.revalidate(principal)
        if name=='meeting_list':return await self.rt.meetings.list(p,**body.model_dump())
        if name=='meeting_get':return await self.rt.meetings.get(p,body.meeting_id)
        if name=='meeting_transcript_read':return await self.rt.content.read(p,body.recording_id,'transcript',limit=body.limit,cursor=body.cursor)
        if name=='meeting_minutes_read':return await self.rt.content.read(p,body.recording_id,'minutes')
        if name=='meeting_download_request':return await self.rt.downloads.issue(p,body.asset_id,body.purpose)
        if name=='meeting_create_prepare':
            return await self.rt.operations.prepare(p,MeetingCreate.model_validate(body.model_dump(exclude={'idempotency_key'})),body.idempotency_key)
        if name=='meeting_source_query':
            return await self.rt.queries.submit(p,MeetingQuery.model_validate(body.model_dump()))
        if body.job_id:
            return await self.rt.jobs.get(p,body.job_id)
        return await self.rt.operations.get(p,body.operation_id)
