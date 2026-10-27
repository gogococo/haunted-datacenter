import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({document:{addEventListener(){}},setInterval(){}});
vm.runInContext(readFileSync(new URL('./web/noc.js',import.meta.url),'utf8'),context);
const reason=(output,checks={})=>context.reportReason({output,checks:{complete:true,structured:false,correct:false,consistent:true,...checks}});
test('valid JSON with nested equipment is a schema problem, not Markdown',()=>{
 const output=JSON.stringify({action:'maintain',equipment:{cooling_fans:{status:'normal operating'},rack:{cooling:'activated and ambient temperature maintained'},status_lights:[{name:'GPU Cooling Fan',status:'green'}]}});
 assert.match(reason(output),/valid JSON.*equipment.*text label/);
 assert.doesNotMatch(reason(output),/Markdown|not valid JSON/);
});
test('Markdown fences and malformed JSON get their own explanations',()=>{
 assert.match(reason('```json\n{"action":"leave_alone","equipment":"gpu_rack"}\n```'),/wrapped.*Markdown/);
 for(const output of ['Sure! {"action":"leave_alone"}','{"action":'])assert.match(reason(output),/not valid JSON/);
});
test('wrong top-level JSON, field names and value types explain the contract',()=>{
 assert.match(reason('[]'),/one object/);
 assert.match(reason('null'),/one object/);
 assert.match(reason('{"action":"leave_alone"}'),/exactly the two fields/);
 assert.match(reason('{"action":"leave_alone","equipment":"gpu_rack","comment":"ok"}'),/exactly the two fields/);
 assert.match(reason('{"action":null,"equipment":"gpu_rack"}'),/both be text labels/);
});
test('command, truncation and consistency feedback stays distinct',()=>{
 assert.match(reason('{"action":"maintain","equipment":"gpu_rack"}',{structured:true}),/does not match the evidence/);
 assert.match(reason('{}',{complete:false}),/cut short/);
 assert.match(reason('{}',{structured:true,correct:true,consistent:false}),/different decisions/);
 assert.equal(reason('{}',{structured:true,correct:true,consistent:true}),'Correct command.');
});
