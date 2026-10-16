// Actual TypeScript syntax check only. This is NOT a substitute for vue-tsc or a Vite build.
const ts=require('typescript');const fs=require('fs');const path=require('path');
const root=path.join(__dirname,'../integration/portal/src/features/meeting');let count=0;let errors=0;
for(const name of fs.readdirSync(root)){
 const file=path.join(root,name);let source=fs.readFileSync(file,'utf8');
 if(name.endsWith('.vue')){
  const match=source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/);
  if(!match)continue;source=match[1];
 }else if(!name.endsWith('.ts'))continue;
 const parsed=ts.createSourceFile(name.replace('.vue','.ts'),source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
 for(const d of parsed.parseDiagnostics){console.error(name,ts.flattenDiagnosticMessageText(d.messageText,'\n'));errors++}
 count++;
}
console.log(JSON.stringify({typescript_blocks:count,syntax_errors:errors,vue_template_typecheck:'NOT_RUN',vite_build:'NOT_RUN'}));
process.exitCode=errors?1:0;
