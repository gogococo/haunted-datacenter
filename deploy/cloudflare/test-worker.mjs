import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createProxy} from './worker.mjs';
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
