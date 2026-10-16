<script setup lang="ts">
import { ref, watch } from 'vue'
import SchemaField from './SchemaField.vue'
import type { JsonSchema, Row } from './types'
import { useMeetingText } from './locale'
const props=defineProps<{schema:JsonSchema; initial?:Row; busy?:boolean}>()
const emit=defineEmits<{(event:'submit',value:Row):void;(event:'cancel'):void}>()
const {tr}=useMeetingText()
const value=ref<Row>({})
watch(()=>[props.schema,props.initial],()=>{
 const defaults:Row={}
 for(const [key,schema] of Object.entries(props.schema.properties || {})) if(schema.default !== undefined) defaults[key]=schema.default
 value.value={...defaults,...props.initial}
},{immediate:true})
</script>
<template><form @submit.prevent="emit('submit',value)">
 <p>{{tr('formHelp')}}</p>
 <SchemaField v-for="(child,key) in schema.properties" :key="key" :name="String(key)" :schema="child" :root="schema"
  :required="schema.required?.includes(String(key))" :model-value="value[key]" @update:model-value="value[key]=$event" />
 <div class="toolbar"><button type="submit" :disabled="busy">{{tr('save')}}</button><button type="button" @click="emit('cancel')">{{tr('cancel')}}</button></div>
 </form></template>
