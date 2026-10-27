import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createProxy} from './worker.mjs';
import {execFileSync} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
const app='https://halloween.example',upstream='https://upstream.example';
test('forwards host cookie and translates exact origin without caching',async()=>{
 let received;
 const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,fetcher:async(r,opts)=>{received=r;assert.equal(opts.cf.cacheTtl,0);return new Response('{"ok":true}',{headers:{'Set-Cookie':'haunted_host=session; HttpOnly; Secure; SameSite=Strict'}})}});
 const response=await proxy(new Request(app+'/api/start',{method:'POST',headers:{Cookie:'haunted_host=session',Origin:app,'X-Game-Token':'game','X-Forwarded-Host':'evil.example'},body:'{}'}));
 assert.equal(received.url,upstream+'/api/start');assert.equal(received.headers.get('Cookie'),'haunted_host=session');assert.equal(received.headers.get('Origin'),upstream);assert.equal(received.headers.get('X-Forwarded-Host'),null);assert.equal(received.redirect,'manual');assert.match(response.headers.get('Set-Cookie'),/HttpOnly/);assert.equal(response.headers.get('Cache-Control'),'no-store');
});
test('rejects foreign hosts and origins without contacting the backend',async()=>{
 let called=false;const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,fetcher:()=>{called=true}});
 assert.equal((await proxy(new Request('https://elsewhere.example/'))).status,404);
 assert.equal((await proxy(new Request(app+'/api/start',{method:'POST',headers:{Origin:'https://evil.example'}}))).status,403);assert.equal(called,false);
});
test('rewrites only upstream redirects and never follows them',async()=>{
 const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,fetcher:async()=>new Response(null,{status:302,headers:{Location:upstream+'/next'}})});
 assert.equal((await proxy(new Request(app+'/'))).headers.get('Location'),app+'/next');
});
test('returns a safe error if upstream is unavailable',async()=>{
 const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,fetcher:async()=>{throw Error('private diagnostic')}});
 const r=await proxy(new Request(app+'/'));assert.equal(r.status,502);assert.doesNotMatch(await r.text(),/private diagnostic/);
});
test('serves generated UI assets for GET and HEAD while APIs still use the backend',async()=>{
 let calls=0;const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,assets:{'/app.js':{body:'export const test=true;',type:'text/javascript; charset=utf-8'}},fetcher:async()=>{calls++;return new Response('backend')}});
 const response=await proxy(new Request(app+'/app.js?v=2'));
 assert.equal(await response.text(),'export const test=true;');assert.match(response.headers.get('Content-Type'),/javascript/);assert.equal(response.headers.get('Cache-Control'),'no-store');
 const head=await proxy(new Request(app+'/app.js',{method:'HEAD'}));assert.equal(await head.text(),'');assert.match(head.headers.get('Content-Type'),/javascript/);
 assert.equal(await (await proxy(new Request(app+'/api/state?run=one'))).text(),'backend');assert.equal(calls,1);
});
test('UI assets retain host and origin protection',async()=>{
 const proxy=createProxy({appOrigin:app,upstreamOrigin:upstream,assets:{'/app.js':{body:'code',type:'text/javascript'}}});
 assert.equal((await proxy(new Request('https://elsewhere.example/app.js'))).status,404);
 assert.equal((await proxy(new Request(app+'/app.js',{headers:{Origin:'https://evil.example'}}))).status,403);
});
test('release bundle includes the current scripts for every room',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'haunted-edge-'));
 try{
  const output=join(directory,'worker.mjs');
  execFileSync(process.execPath,[fileURLToPath(new URL('./build-worker.mjs',import.meta.url)),output]);
  const bundle=await import(pathToFileURL(output));
  for(const name of ['app.js','room.js','noc.js','plant.js','style.css']){
   const response=await bundle.default.fetch(new Request(bundle.APP_ORIGIN+'/'+name));
   assert.equal(await response.text(),await readFile(new URL('../../web/'+name,import.meta.url),'utf8'));
   assert.equal(response.headers.get('Cache-Control'),'no-store');
  }
 }finally{await rm(directory,{recursive:true,force:true});}
});
