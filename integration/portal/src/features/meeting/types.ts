export type Row = Record<string, any>
export interface JsonSchema { type?: string; title?: string; description?: string; format?: string; enum?: any[]; default?: any;
  properties?: Record<string, JsonSchema>; required?: string[]; items?: JsonSchema; anyOf?: JsonSchema[];
  $ref?: string; $defs?: Record<string, JsonSchema>; minLength?: number; maxLength?: number; minimum?: number; maximum?: number }
export interface Page { items: Row[]; next_cursor?: string | null; [key: string]: unknown }
