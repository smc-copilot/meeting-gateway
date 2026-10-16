<script setup lang="ts">
import { computed } from 'vue'
import type { JsonSchema } from './types'
import { useMeetingText } from './locale'
const props = defineProps<{ name: string; schema: JsonSchema; root: JsonSchema; modelValue: any; required?: boolean }>()
const emit = defineEmits<{ (event:'update:modelValue', value:any): void }>()
const { field, tr } = useMeetingText()
const schema = computed<JsonSchema>(() => {
 let value = props.schema
 if (value.$ref) value = props.root.$defs?.[value.$ref.split('/').pop() || ''] || value
 if (value.anyOf) value = value.anyOf.find(x => x.type !== 'null') || value
 if (value.$ref) value = props.root.$defs?.[value.$ref.split('/').pop() || ''] || value
 return value
})
const secret = computed(() => /secret|encoding_key|webhook_token/.test(props.name))
const stringValue = computed(() => Array.isArray(props.modelValue) ? props.modelValue.join('\n') : props.modelValue ?? '')
const objectValue = computed(() => props.modelValue && typeof props.modelValue === 'object' ? props.modelValue : {})
function input(event: Event) {
 const value = (event.target as HTMLInputElement).value
 if (schema.value.type === 'array') emit('update:modelValue', value.split(/\n|,/).map(x=>x.trim()).filter(Boolean))
 else if (schema.value.type === 'integer' || schema.value.type === 'number') emit('update:modelValue', value === '' ? undefined : Number(value))
 else if (schema.value.format === 'date-time') emit('update:modelValue', value ? new Date(value).toISOString() : undefined)
 else emit('update:modelValue', value === '' && !props.required ? undefined : value)
}
const localDate = computed(() => {
 if (!props.modelValue) return ''
 const date=new Date(props.modelValue); if(Number.isNaN(date.getTime())) return ''
 return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)
})
</script>
<template>
 <fieldset v-if="schema.type === 'object' || schema.properties" class="field-object">
  <legend>{{ field(name) }}</legend>
  <SchemaField v-for="(child,key) in schema.properties" :key="key" :name="String(key)" :schema="child" :root="root"
   :required="schema.required?.includes(String(key))" :model-value="objectValue[key]"
   @update:model-value="emit('update:modelValue', {...objectValue,[key]:$event})" />
 </fieldset>
 <label v-else class="form-field">
  <span>{{ field(name) }} <small v-if="required">{{ tr('required') }}</small></span>
  <div v-if="schema.enum" class="choice-row">
   <button type="button" v-for="item in schema.enum" :key="String(item)"
    :aria-pressed="modelValue===item" @click="emit('update:modelValue', modelValue===item && !required ? undefined : item)">{{ field(String(item)) }}</button>
  </div>
  <input v-else-if="schema.type === 'boolean'" type="checkbox" :checked="Boolean(modelValue)" @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)" />
  <textarea v-else-if="schema.type === 'array'" :value="stringValue" rows="3" :required="required" @input="input" />
  <input v-else-if="schema.format === 'date-time'" type="datetime-local" :value="localDate" :required="required" @input="input" />
  <input v-else :type="secret ? 'password' : ['integer','number'].includes(schema.type || '') ? 'number' : 'text'"
    :value="stringValue" :required="required" :minlength="schema.minLength" :maxlength="schema.maxLength" :min="schema.minimum" :max="schema.maximum"
    :autocomplete="secret ? 'new-password' : 'off'" @input="input" />
  <small v-if="schema.description">{{ schema.description }}</small>
 </label>
</template>
