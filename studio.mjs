import {spawn} from 'node:child_process';
import net from 'node:net';
import {readFile} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';
import path from 'node:path';
import {ROOT,pythonFor} from './server.mjs';

try{for(const line of (await readFile(path.join(ROOT,'.env'),'utf8')).split(/\r?\n/)){const m=/^\s*([A-Z_][A-Z_0-9]*)\s*=\s*(.*?)\s*$/.exec(line);if(m&&!Object.hasOwn(process.env,m[1]))process.env[m[1]]=m[2].replace(/^(['"])(.*)\1$/,'$2');}}catch(e){if(e.code!=='ENOENT')throw e;}
function port(preferred){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',e=>{if(['EADDRINUSE','EACCES'].includes(e.code))port(0).then(resolve,reject);else reject(e);});s.listen(preferred,'127.0.0.1',()=>{const n=s.address().port;s.close(()=>resolve(n));});});}
const python=pythonFor(ROOT),children=[];let stopping=false;
function child(command,args,env){const p=spawn(command,args,{cwd:ROOT,env,stdio:'inherit',windowsHide:true});p.on('error',e=>{console.error(e.message);stop(1);});p.on('exit',code=>{if(!stopping){console.error('A studio service stopped.');stop(code||1);}});children.push(p);return p;}
function stop(code=0){if(stopping)return;stopping=true;process.exitCode=code;for(const p of children)p.kill();setTimeout(()=>process.exit(code),700).unref();}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
async function ready(url){for(let i=0;i<90;i++){if(stopping)throw Error('Service startup failed');try{const response=await fetch(url,{signal:AbortSignal.timeout(1000)});if(response.ok)return;}catch{}await new Promise(r=>setTimeout(r,500));}throw Error(`Startup timed out: ${url}`);}
try{
 const apiPort=await port(Number(process.env.STUDIO_API_PORT||8765));let webPort=await port(Number(process.env.STUDIO_PORT||3000));if(webPort===apiPort)webPort=await port(0);
 const env={...process.env,PYTHONUTF8:'1',STUDIO_API_URL:`http://127.0.0.1:${apiPort}`,STUDIO_PORT:String(webPort),STUDIO_ADMIN_TOKEN:process.env.STUDIO_ADMIN_TOKEN||randomBytes(32).toString('hex')};
 if(env.STUDIO_ADMIN_TOKEN.length<24)throw Error('STUDIO_ADMIN_TOKEN must have at least 24 characters.');
 child(python,['-m','uvicorn','backend.api:app','--host','127.0.0.1','--port',String(apiPort)],env);await ready(env.STUDIO_API_URL+'/health');
 child(python,['-m','backend.worker'],env);child(process.execPath,[path.join(ROOT,'server.mjs')],env);const url=`http://127.0.0.1:${webPort}`;await ready(url+'/health');
 console.log(`\nStory Studio is ready: ${url}\nKeep this window open. Press Ctrl+C to stop.\n`);
 if(process.env.STUDIO_NO_BROWSER!=='1'){
  const opener=process.platform==='win32'?spawn('rundll32.exe',['url.dll,FileProtocolHandler',url],{windowsHide:true,stdio:'ignore'}):spawn(process.platform==='darwin'?'open':'xdg-open',[url],{stdio:'ignore'});opener.on('error',()=>console.log('Open the studio URL above in your browser.'));
 }
}catch(e){console.error('Studio startup failed:',e.message,'\nInstall Python dependencies with: python -m pip install -r requirements.txt');stop(1);}
