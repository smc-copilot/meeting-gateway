<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api,errorText } from './client'
import { useMeetingText } from './locale'
import type { Row } from './types'
import './meeting.css'
const route=useRoute();const {tr}=useMeetingText();const data=ref<Row>();const error=ref('');const grant=ref('');const busy=ref(false)
const id=String(route.query.transaction_id || '')
onMounted(async()=>{try{data.value=await api('/api/v1/portal/authorization/'+encodeURIComponent(id))}catch(e){error.value=errorText(e)}})
async function decide(allow:boolean){busy.value=true;try{
 const value=await api('/api/v1/portal/authorization/'+encodeURIComponent(id)+(allow?'/approve':'/deny'),{method:'POST',body:allow?(grant.value?{agent_grant_id:grant.value}:{}):undefined})
 if(allow) window.location.assign(value.redirect_uri);else window.location.assign('/meeting/overview')
}catch(e){error.value=errorText(e)}finally{busy.value=false}}
</script>
<template><main class="meeting-console consent"><h1>{{tr('requestConsent')}}</h1><p>{{tr('consentNote')}}</p>
 <p v-if="error" role="alert" class="error">{{error}}</p><pre v-if="data">{{JSON.stringify(data,null,2)}}</pre>
 <label class="form-field">{{tr('agentGrant')}}<input v-model="grant" autocomplete="off" /></label>
 <div class="toolbar"><button :disabled="busy || !data" @click="decide(true)">{{tr('allow')}}</button><button :disabled="busy" @click="decide(false)">{{tr('deny')}}</button></div>
 </main></template>
