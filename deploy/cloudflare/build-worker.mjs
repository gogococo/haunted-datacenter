// Publish UI-only updates without restarting the stateful game or model workers.
import {readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
const root=fileURLToPath(new URL('../../',import.meta.url));
const assets={};
for(const [name,type] of [['app.js','text/javascript; charset=utf-8'],['room.js','text/javascript; charset=utf-8'],['noc.js','text/javascript; charset=utf-8'],['plant.js','text/javascript; charset=utf-8'],['style.css','text/css; charset=utf-8']]){
 assets['/'+name]={type,body:await readFile(resolve(root,'web',name),'utf8')};
}
const source=await readFile(new URL('./worker.mjs',import.meta.url),'utf8');
const bundle=source.replace('const proxy=createProxy();','const proxy=createProxy({assets:'+JSON.stringify(assets)+'});');
if(bundle===source)throw Error('Worker entry point was not found.');
const output=process.argv[2];
if(!output)throw Error('Pass an output filename for the generated deployment bundle.');
await writeFile(output,bundle);
console.log('UI worker bundle written: '+Buffer.byteLength(bundle)+' bytes');
