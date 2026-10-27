// Public routing configuration only. Provider keys remain in Nebius SecretStash.
export const APP_ORIGIN='https://halloween.curiousjaxx.dev';
export const UPSTREAM_ORIGIN='https://port8080-pk7n9wmwcegkaah.tunnel.applications.eu-north1.nebius.cloud';

export function createProxy({appOrigin=APP_ORIGIN,upstreamOrigin=UPSTREAM_ORIGIN,fetcher=fetch,assets={}}={}){
 const app=new URL(appOrigin),upstream=new URL(upstreamOrigin);
 return async request=>{
  const incoming=new URL(request.url);
  if(incoming.host!==app.host)return new Response('Not found',{status:404});
  if(incoming.protocol!==app.protocol)return Response.redirect(app.origin+incoming.pathname+incoming.search,308);
  const origin=request.headers.get('Origin');
  // Translate only the exact app origin for the backend's existing same-origin
  // check. Foreign browser origins are rejected before any inference can start.
  if(origin&&origin!==app.origin)return new Response('Origin rejected.',{status:403});
  const asset=assets[incoming.pathname];
  if(asset&&['GET','HEAD'].includes(request.method))return new Response(request.method==='HEAD'?null:asset.body,{headers:{'Content-Type':asset.type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  const target=new URL(upstream.origin);target.pathname=incoming.pathname;target.search=incoming.search;
  const headers=new Headers(request.headers);headers.set('Host',upstream.host);
  headers.delete('Forwarded');headers.delete('X-Forwarded-Host');
  if(origin)headers.set('Origin',upstream.origin);
  const init={method:request.method,headers,redirect:'manual',signal:request.signal};
  if(!['GET','HEAD'].includes(request.method)){init.body=request.body;init.duplex='half';}
  let response;
  try{response=await fetcher(new Request(target,init),{cf:{cacheEverything:false,cacheTtl:0}});}
  catch{return new Response('The demo is temporarily unavailable. Please try again shortly.',{status:502,headers:{'Cache-Control':'no-store'}});}
  const output=new Headers(response.headers);output.set('Cache-Control','no-store');
  output.set('X-Content-Type-Options','nosniff');output.set('Referrer-Policy','no-referrer');
  if(output.has('Access-Control-Allow-Origin')){
   if(origin)output.set('Access-Control-Allow-Origin',app.origin);else output.delete('Access-Control-Allow-Origin');
  }
  const location=output.get('Location');
  if(location){try{const next=new URL(location,target);if(next.origin===upstream.origin){next.host=app.host;next.protocol=app.protocol;output.set('Location',next.href);}}catch{}}
  // Pass the original response stream through without buffering SSE events.
  return new Response(response.body,{status:response.status,statusText:response.statusText,headers:output});
 };
}
const proxy=createProxy();
export default {fetch:request=>proxy(request)};
