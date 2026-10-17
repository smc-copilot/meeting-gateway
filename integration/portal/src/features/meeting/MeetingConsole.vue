<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, downloadAsset, errorText, hasGatewaySession, loginAccount, clearGatewaySession } from './client'
import { useMeetingText } from './locale'
import type { Row, Page, JsonSchema } from './types'
import SchemaForm from './SchemaForm.vue'
import schemasJson from './form-schemas.json'
import './meeting.css'

const schemas=schemasJson as unknown as Record<string,JsonSchema>
const route=useRoute(); const router=useRouter(); const {tr,field}=useMeetingText()
const section=computed(()=>String(route.params.section || 'overview'))
const context=ref<Row>({actions:[],features:{}}), rows=ref<Row[]>([]), extra=ref<Row[]>([]), members=ref<Row[]>([])
const cursor=ref<string|null>(null), query=ref(''), busy=ref(false), error=ref(''), result=ref<any>(null)
const selected=ref<Row|null>(null), recordings=ref<Row[]>([]), content=ref<Row|null>(null), currentRecording=ref('')
const operation=ref<Row|null>(null), subtab=ref(''), modal=ref<{name:string;path:string;method?:string;business?:boolean;initial?:Row;title:string;key?:string}|null>(null)
const diagConnection=ref(''), diagProbe=ref('configuration'), diagRecording=ref(''), probeOpen=ref(false)
const probes=['configuration','oauth_user_info','upcoming','history','records','corp_records','record_detail','transcript','minutes']
const reason=ref(''), reconcileId=ref('')
const signedIn=ref(hasGatewaySession()), loginAccountValue=ref(''), loginPasswordValue=ref(''), localMemberId=ref('')
async function submitLogin(){
 const password=loginPasswordValue.value
 loginPasswordValue.value=''
 const data=await run(()=>loginAccount(loginAccountValue.value, password), false)
 if(data){ signedIn.value=true; await refresh() }
}
function signOut(){ clearGatewaySession(); signedIn.value=false; context.value={actions:[],features:{}} }
const minutesRemaining=computed(()=>{
 const deadline=operation.value?.confirm_deadline
 if(!deadline) return 0
 return Math.max(0, Math.ceil((new Date(String(deadline)).getTime()-Date.now())/60000))
})
const can=(action:string)=>context.value.actions.includes(action)
const menu=computed(()=>[
 ['overview',''],['applications','meeting.application.manage'],['connections',''],['meetings','meeting.read'],
 ['employees','meeting.acl.manage'],['clients','meeting.client.manage'],['agents',''],['operations',''],
 ['diagnostics','meeting.diagnostics.run'],['audit','meeting.audit.read'],
].filter(([,permission])=>!permission || can(permission)))
const visibleFields=computed(()=>{
 const map:Record<string,string[]>={applications:['name','application_type','environment','sdk_id','enabled'],connections:['name','kind','status','owner_member_id','last_synced_at'],
 meetings:['subject','start_at','end_at','host_member_id','state'],employees:['subject_type','subject_id','actions','scope_type','effect','expires_at'],
 clients:['name','client_type','allowed_scopes','enabled'],agents:['agent_id','actions','scope_type','expires_at','enabled'],operations:['state','created_at','confirm_deadline','last_reason'],
 diagnostics:['kind','state','attempts','last_reason','created_at'],audit:['created_at','subject_id','client_id','action','decision','reason','trace_id']}
 if(section.value==='employees' && subtab.value==='identity-bindings') return ['member_id','external_id','external_corp_id','enabled']
 if(section.value==='employees' && subtab.value==='resource-acl') return ['resource_id','subject_id','actions','effect']
 if(section.value==='diagnostics' && subtab.value==='events') return ['event_type','state','created_at','summary']
 if(section.value==='diagnostics' && subtab.value==='sync-policies') return ['connection_id','client_id','enabled','last_success_at']
 if(section.value==='clients' && subtab.value==='subscriptions') return ['client_id','destination','event_types','enabled']
 return map[section.value] || ['name','status']
})
const format=(v:any)=> v==null?'—':typeof v==='object'?JSON.stringify(v):String(v)
function open(name:string,path:string,title:string,options:{method?:string;business?:boolean;initial?:Row}={}) {
 result.value=null;error.value='';modal.value={name,path,title,...options,key:crypto.randomUUID()}
}
async function run(task:()=>Promise<any>, show=true){busy.value=true;error.value='';try{const data=await task();if(show)result.value=data;return data}catch(e){error.value=errorText(e);return null}finally{busy.value=false}}
async function refresh(next=false){
 if(!signedIn.value) return
 const captured=section.value
 await run(async()=>{
  const ctx=await api('/api/v1/portal/context'); context.value=ctx
  let path=''; let business=false
  if(captured==='overview') { rows.value=[];return }
  if(captured==='applications') path='/api/v1/admin/applications'
  if(captured==='connections') {path='/api/v1/portal/connections';extra.value=(await api('/api/v1/portal/applications')).items}
  if(captured==='meetings') {path='/api/v1/meetings?q='+encodeURIComponent(query.value);business=true}
  if(captured==='employees') path='/api/v1/admin/'+(subtab.value || 'grants')
  if(captured==='clients') path='/api/v1/admin/'+(subtab.value || 'clients')
  if(captured==='agents') path='/api/v1/portal/agent-grants'
  if(captured==='operations') path='/api/v1/portal/operations'
  if(captured==='diagnostics') path='/api/v1/admin/'+(subtab.value || 'jobs')
  if(captured==='audit') path='/api/v1/admin/audit'
  if(!path) {await router.replace('/meeting/overview');return}
  if(next && cursor.value) path+=(path.includes('?')?'&':'?')+'cursor='+encodeURIComponent(cursor.value)
  const data:Page=await api(path,{business})
  if(captured!==section.value) return
  rows.value=data.items || [];cursor.value=data.next_cursor || null
 },false)
}
async function submit(body:Row){if(!modal.value)return
 const form=modal.value
 const payload={...body}
 if(form.name==='ApplicationCreate'){
  const enterprise=payload.application_type==='ENTERPRISE_AKSK';payload.data_scope=enterprise?'enterprise':'user'
  if(enterprise) delete payload.oauth_secret;else{delete payload.secret_id;delete payload.secret_key}
 }
 const data=await run(()=>api(form.path,{method:form.method || 'POST',body:payload,business:form.business,idempotencyKey:form.key}))
 if(data){modal.value=null;if(form.name==='MeetingCreate'){operation.value=data;await router.push('/meeting/operations')};await refresh()}
}
async function setup(row:Row){await run(()=>api('/api/v1/admin/applications/'+row.id+'/setup'))}
function rotateApplication(row:Row){
 const initial:Row={};for(const key of Object.keys(schemas.ApplicationCreate.properties || {})) if(row[key]!==undefined)initial[key]=row[key]
 open('ApplicationCreate','/api/v1/admin/applications/'+row.id+'/credentials','edit',{method:'PUT',initial})
}
async function authorize(row:Row){const value=await run(()=>api('/api/v1/portal/applications/'+row.id+'/authorize',{method:'POST'}),false);if(value)window.location.assign(value.authorization_url)}
async function reasonAction(path:string){const why=window.prompt(tr('reason'));if(!why)return
 const data=await run(()=>api(path,{method:'POST',body:{reason:why}}));if(data)await refresh()
}
async function showMeeting(row:Row){await run(async()=>{selected.value=await api('/api/v1/meetings/'+row.id,{business:true});recordings.value=(await api('/api/v1/meetings/'+row.id+'/recordings',{business:true})).items;content.value=null},false)}
async function readContent(recording:Row,type:string,next=false){await run(async()=>{
 let path='/api/v1/recordings/'+recording.id+'/'+type
 if(next && content.value?.next_cursor) path+='?cursor='+encodeURIComponent(content.value.next_cursor)
 content.value=await api(path,{business:true});currentRecording.value=recording.id
},false)}
async function doDownload(asset:Row){const why=window.prompt(tr('reason'));if(why)await run(()=>downloadAsset(asset,why),false)}
function createMeeting(){open('MeetingCreate','/api/v1/meetings','newMeeting',{business:true,initial:{host_member_id:context.value.member?.member_id,invitee_member_ids:[]}})}
async function showOperation(row:Row){const data=await run(()=>api('/api/v1/portal/operations/'+row.id),false);if(data)operation.value=data}
async function confirmOperation(){if(!operation.value)return;const op=operation.value
 if(!window.confirm(tr('approvalNote')))return
 const data=await run(()=>api('/api/v1/portal/operations/'+op.id+'/confirm',{method:'POST',body:{request_hash:op.request_hash}}),false)
 if(data){operation.value=data;await refresh()}
}
async function rejectOperation(){if(!operation.value)return;await reasonAction('/api/v1/portal/operations/'+operation.value.id+'/reject');await showOperation(operation.value)}
async function reconcile(link:boolean){if(!operation.value)return
 const data=await run(()=>api('/api/v1/portal/operations/'+operation.value!.id+'/reconcile',{method:'POST',body:{
 action:link?'LINK_VERIFIED_MEETING':'CLOSE_UNRESOLVED',meeting_id:link?reconcileId.value:null,reason:reason.value}}),false)
 if(data){operation.value=data;await refresh()}
}
async function diagnostics(){await run(()=>api('/api/v1/admin/connections/'+encodeURIComponent(diagConnection.value)+'/diagnostics',{
 method:'POST',body:{probe:diagProbe.value,recording_id:diagRecording.value || null}}))}
async function requestSTS(){await run(()=>api('/api/v1/admin/connections/'+encodeURIComponent(diagConnection.value)+'/sts',{method:'POST',body:{valid_hours:6}}))}
async function findMembers(){await run(async()=>{members.value=(await api('/api/v1/portal/members?q='+encodeURIComponent(query.value))).items},false)}
async function changeMember(enable:boolean){
 const why=window.prompt(tr('reason')); if(!why || !localMemberId.value) return
 const action=enable?'enable':'disable'
 await run(()=>api('/api/v1/admin/members/'+encodeURIComponent(localMemberId.value)+'/'+action,{method:'POST',body:{reason:why}}))
}
async function switchTab(value:string){subtab.value=value;cursor.value=null;await refresh()}
watch(section,()=>{subtab.value='';cursor.value=null;rows.value=[];result.value=null;selected.value=null;content.value=null;modal.value=null;error.value='';void refresh()})
onMounted(()=>{ if(signedIn.value) void refresh() })
</script>
<template>
 <main class="meeting-console">
  <h1>{{tr('title')}}</h1>
  <form v-if="!signedIn" class="panel" @submit.prevent="submitLogin">
   <h2>{{tr('loginTitle')}}</h2>
   <p>{{tr('loginHint')}}</p>
   <label>{{tr('loginAccount')}}<input v-model="loginAccountValue" autocomplete="username" /></label>
   <label>{{tr('loginPassword')}}<input v-model="loginPasswordValue" type="password" autocomplete="current-password" /></label>
   <button type="submit" :disabled="busy">{{tr('loginSubmit')}}</button>
  </form>
  <div v-else class="toolbar"><button type="button" @click="signOut">{{tr('close')}}</button></div>
  <nav aria-label="Meeting navigation"><RouterLink v-for="item in menu" :key="item[0]" :to="'/meeting/'+item[0]">{{tr(item[0])}}</RouterLink></nav>
  <p class="notice">{{tr('securityNote')}}</p>
  <p v-if="error" class="error" role="alert">{{error}}</p>
  <div class="toolbar"><h2>{{tr(section)}}</h2><button :disabled="busy" @click="refresh()">{{tr('refresh')}}</button><span v-if="busy" aria-live="polite">{{tr('preparing')}}</span></div>

  <template v-if="section==='overview'">
   <button v-if="context.can_bootstrap" :disabled="busy" @click="run(()=>api('/api/v1/admin/bootstrap',{method:'POST'})).then(()=>refresh())">{{tr('bootstrap')}}</button>
   <div class="panel"><h2>{{tr('currentUser')}}</h2><pre>{{JSON.stringify(context.member,null,2)}}</pre>
    <h2>{{tr('permission')}}</h2><pre>{{JSON.stringify(context.actions,null,2)}}</pre><h2>{{tr('features')}}</h2><pre>{{JSON.stringify(context.features,null,2)}}</pre></div>
  </template>

  <template v-if="section==='applications'">
   <p>{{tr('officialNote')}}</p><p>{{tr('credentialsNote')}}</p>
   <div class="toolbar"><button @click="open('ApplicationCreate','/api/v1/admin/applications','application')">{{tr('application')}}</button>
    <button @click="open('EnterpriseConnectionCreate','/api/v1/admin/connections/enterprise','enterprise')">{{tr('enterprise')}}</button>
    <button @click="open('IdentityBind','/api/v1/admin/identity-bindings','bindIdentity')">{{tr('bindIdentity')}}</button></div>
  </template>
  <div v-if="section==='connections'" class="panel"><h2>{{tr('authorize')}}</h2>
   <div v-for="app in extra" :key="app.id" class="toolbar"><span>{{app.name}}</span><button :disabled="busy" @click="authorize(app)">{{tr('authorize')}}</button></div>
   <button v-if="can('meeting.sync.manage')" @click="open('SyncRequest','/api/v1/sync-jobs','newSync',{business:true})">{{tr('newSync')}}</button>
  </div>
  <div v-if="section==='meetings'" class="toolbar">
   <input v-model="query" :aria-label="tr('query')" @keyup.enter="refresh()" /><button @click="refresh()">{{tr('query')}}</button>
   <button v-if="can('meeting.create.self') && context.features.create" @click="createMeeting">{{tr('newMeeting')}}</button>
   <button v-if="can('meeting.sync.manage')" @click="open('SyncRequest','/api/v1/sync-jobs','newSync',{business:true})">{{tr('newSync')}}</button>
  </div>
  <template v-if="section==='employees'">
   <p>{{tr('membersLocal')}}</p>
   <p>{{tr('lastAdmin')}}</p>
   <div class="toolbar"><label>{{tr('id')}}<input v-model="localMemberId" /></label>
    <button type="button" :disabled="busy || !localMemberId" @click="changeMember(false)">{{tr('memberDisable')}}</button>
    <button type="button" :disabled="busy || !localMemberId" @click="changeMember(true)">{{tr('memberEnable')}}</button></div>
   <div class="toolbar"><button @click="switchTab('grants')">{{tr('grants')}}</button><button @click="switchTab('resource-acl')">{{tr('permission')}}</button><button @click="switchTab('identity-bindings')">{{tr('identities')}}</button></div>
   <div class="toolbar"><button @click="open('GrantCreate','/api/v1/admin/grants','addGrant')">{{tr('addGrant')}}</button>
    <button @click="open('ACLCreate','/api/v1/admin/resource-acl','addACL')">{{tr('addACL')}}</button>
    <button @click="open('Retention','/api/v1/admin/retention-policy','retention')">{{tr('retention')}}</button>
    <button v-if="can('meeting.application.manage')" @click="open('IdentityBind','/api/v1/admin/identity-bindings','bindIdentity')">{{tr('bindIdentity')}}</button></div>
   <label>{{tr('memberSearch')}}<input v-model="query" @keyup.enter="findMembers" /></label><button @click="findMembers">{{tr('query')}}</button>
   <pre v-if="members.length">{{JSON.stringify(members,null,2)}}</pre>
  </template>
  <div v-if="section==='clients'" class="toolbar">
   <button @click="switchTab('clients')">{{tr('clients')}}</button><button @click="switchTab('subscriptions')">{{tr('newSubscription')}}</button>
   <button @click="open('ClientCreate','/api/v1/admin/clients','newClient')">{{tr('newClient')}}</button>
   <button @click="open('SubscriptionCreate','/api/v1/admin/subscriptions','newSubscription')">{{tr('newSubscription')}}</button>
  </div>
  <div v-if="section==='agents'" class="toolbar"><button @click="open('AgentGrantCreate','/api/v1/portal/agent-grants','newAgent')">{{tr('newAgent')}}</button>
   <button @click="run(()=>api('/api/v1/portal/agent-clients'))">{{tr('clients')}}</button></div>
  <template v-if="section==='diagnostics'">
   <div class="panel form-grid">
    <label class="form-field">{{tr('connectionRef')}}<input v-model="diagConnection" /></label>
    <label class="form-field probe-field">{{tr('probe')}}
     <button type="button" @click="probeOpen=!probeOpen">{{tr(diagProbe)}}</button>
     <div v-if="probeOpen" class="probe-menu">
      <button type="button" v-for="value in probes" :key="value" @click="diagProbe=value;probeOpen=false">{{tr(value)}}</button>
     </div>
    </label>
    <label class="form-field">{{tr('recordingId')}}<input v-model="diagRecording" /></label>
    <div class="toolbar"><button :disabled="busy || !diagConnection" @click="diagnostics">{{tr('diagnosticsRun')}}</button>
     <button v-if="can('meeting.application.manage')" :disabled="busy || !diagConnection" @click="requestSTS">{{tr('sts')}}</button></div>
    <p v-if="result && result.probe">{{tr('status'+result.status)}}<span v-if="result.reason"> · {{result.reason}}</span><span v-if="result.upstream_code"> · {{result.upstream_code}}</span></p>
    <p v-if="result && result.chain">{{result.chain.map(item=>tr(item.probe)+' '+tr('status'+item.status)).join(' / ')}}</p>
   </div>
   <div v-if="can('meeting.sync.manage')" class="toolbar"><button @click="switchTab('jobs')">{{tr('jobs')}}</button><button @click="switchTab('sync-policies')">{{tr('policies')}}</button>
    <button @click="open('AdminSync','/api/v1/admin/sync-jobs','newSync')">{{tr('newSync')}}</button><button @click="open('PolicyCreate','/api/v1/admin/sync-policies','newPolicy')">{{tr('newPolicy')}}</button></div>
   <button @click="switchTab('events')">{{tr('events')}}</button>
  </template>

  <p v-if="section==='meetings'" class="notice">{{tr('catalogNote')}}</p>
  <div v-if="section!=='overview'" class="table-wrap"><table><thead><tr><th>{{tr('id')}}</th><th v-for="key in visibleFields" :key="key">{{field(key)}}</th><th>{{tr('actions')}}</th></tr></thead>
   <tbody><tr v-for="row in rows" :key="row.id"><td>{{row.id}}</td><td v-for="key in visibleFields" :key="key">{{format(row[key])}}</td><td><div class="toolbar">
    <button @click="result=row">{{tr('details')}}</button>
    <template v-if="section==='applications'"><button @click="setup(row)">{{tr('setup')}}</button><button @click="rotateApplication(row)">{{tr('edit')}}</button><button @click="reasonAction('/api/v1/admin/applications/'+row.id+'/disable')">{{tr('disable')}}</button></template>
    <template v-if="section==='connections' && row.kind==='THIRD_PARTY_OAUTH'">
     <button v-if="row.status==='PENDING_CONFIRMATION'" @click="run(()=>api('/api/v1/portal/connections/'+row.id+'/confirm',{method:'POST'})).then(()=>refresh())">{{tr('confirmConnection')}}</button>
     <button @click="reasonAction('/api/v1/portal/connections/'+row.id+'/revoke')">{{tr('revoke')}}</button>
    </template>
    <button v-if="section==='meetings'" @click="showMeeting(row)">{{tr('assets')}}</button>
    <button v-if="section==='operations'" @click="showOperation(row)">{{tr('details')}} / {{tr('confirm')}}</button>
    <button v-if="section==='agents' && row.enabled" @click="reasonAction('/api/v1/portal/agent-grants/'+row.id+'/revoke')">{{tr('revoke')}}</button>
    <button v-if="section==='employees'" @click="reasonAction('/api/v1/admin/'+(subtab || 'grants')+'/'+row.id+'/disable')">{{tr('disable')}}</button>
    <template v-if="section==='clients'"><button @click="reasonAction('/api/v1/admin/'+(subtab || 'clients')+'/'+row.id+'/disable')">{{tr('disable')}}</button>
     <button v-if="(!subtab || subtab==='clients') && row.client_type==='CONFIDENTIAL'" @click="reasonAction('/api/v1/admin/clients/'+row.id+'/rotate-secret')">{{tr('refreshSecret')}}</button></template>
    <button v-if="section==='diagnostics' && (!subtab || subtab==='jobs') && row.state==='FAILED'" @click="reasonAction('/api/v1/admin/jobs/'+row.id+'/retry')">{{tr('retry')}}</button>
    <button v-if="section==='diagnostics' && subtab==='sync-policies'" @click="reasonAction('/api/v1/admin/sync-policies/'+row.id+'/disable')">{{tr('disable')}}</button>
   </div></td></tr><tr v-if="!rows.length"><td :colspan="visibleFields.length+2">{{section==='meetings'?tr('emptyMeetings'):tr('empty')}}</td></tr></tbody></table></div>
  <button v-if="cursor" :disabled="busy" @click="refresh(true)">{{tr('next')}}</button>

  <section v-if="selected && section==='meetings'" class="panel"><h2>{{selected.subject}}</h2><p>{{tr('nativeExportNote')}}</p>
   <div v-for="rec in recordings" :key="rec.id" class="panel"><p>{{tr('recordingId')}}: {{rec.id}} — {{rec.state}}</p>
    <div class="toolbar"><button v-if="can('meeting.content.read')" @click="readContent(rec,'transcript')">{{tr('transcript')}}</button>
     <button v-if="can('meeting.content.read')" @click="readContent(rec,'minutes')">{{tr('minutes')}}</button>
     <button v-if="can('meeting.sync.manage')" @click="open('SyncRequest','/api/v1/sync-jobs','newSync',{business:true,initial:{kind:'CONTENT',connection_ref:selected!.connection_ref,recording_id:rec.id,content_type:'transcript'}})">{{tr('sync')}}</button>
     <template v-if="can('meeting.content.download')"><button v-for="asset in rec.assets" :key="asset.id" :disabled="busy" @click="doDownload(asset)">{{tr('download')}} {{tr(asset.asset_type)}}</button></template>
    </div></div>
   <template v-if="content"><p>{{tr('noRawHtml')}}</p><pre>{{JSON.stringify(content,null,2)}}</pre><button v-if="content.next_cursor" @click="readContent({id:currentRecording},'transcript',true)">{{tr('next')}}</button></template>
  </section>
  <section v-if="operation && section==='operations'" class="panel"><h2>{{tr('requestId')}}: {{operation.id}}</h2><p>{{tr('approvalNote')}}</p>
   <p>{{tr('autoRecord')}}: {{operation.request?.auto_record_type==='CLOUD'?tr('cloud'):tr('autoRecordOff')}}</p>
   <pre>{{JSON.stringify(operation,null,2)}}</pre>
   <div v-if="operation.state==='AWAITING_CONFIRMATION'" class="toolbar">
    <p>{{tr('confirmElsewhere')}} · {{tr('minutesLeft').replace('{count}', String(minutesRemaining))}}</p>
    <button disabled>{{tr('confirmInBusiness')}}</button>
    <button :disabled="busy" @click="rejectOperation">{{tr('reject')}}</button>
   </div>
   <p v-if="operation.state==='OPERATION_EXPIRED'">{{tr('confirmExpired')}}</p>
   <button :disabled="busy" @click="showOperation(operation)">{{tr('refresh')}}</button>
   <div v-if="operation.state==='OUTCOME_UNKNOWN'"><p>{{tr('unknownNote')}}</p><label class="form-field">{{tr('localMeetingId')}}<input v-model="reconcileId" /></label>
    <label class="form-field">{{tr('reason')}}<textarea v-model="reason" /></label><div class="toolbar"><button :disabled="busy || !reconcileId || reason.length<3" @click="reconcile(true)">{{tr('linkVerified')}}</button><button :disabled="busy || reason.length<3" @click="reconcile(false)">{{tr('closeUnresolved')}}</button></div></div>
  </section>
  <section v-if="result" class="panel"><div class="toolbar"><h2>{{tr('result')}}</h2><button @click="result=null">{{tr('close')}}</button></div><p v-if="result.client_secret || result.signing_secret" class="notice">{{tr('onceSecret')}}</p><pre>{{JSON.stringify(result,null,2)}}</pre></section>

  <div v-if="modal" class="modal-shade" @click.self="modal=null"><section class="modal" role="dialog" aria-modal="true" :aria-label="tr(modal.title)">
   <header><h2>{{tr(modal.title)}}</h2><button @click="modal=null">{{tr('close')}}</button></header>
   <p v-if="modal.name==='ApplicationCreate'">{{tr('credentialsNote')}}</p><p v-if="error" class="error" role="alert">{{error}}</p>
   <SchemaForm :schema="schemas[modal.name]" :initial="modal.initial" :busy="busy" @submit="submit" @cancel="modal=null" />
  </section></div>
 </main>
</template>
