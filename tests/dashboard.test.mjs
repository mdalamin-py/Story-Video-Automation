import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,cp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {createDashboard,ROOT} from '../server.mjs';

async function fixture(t,options={}){
 const root=await mkdtemp(path.join(tmpdir(),'story-studio-'));
 await cp(path.join(ROOT,'web'),path.join(root,'web'),{recursive:true});
 const server=createDashboard({root,...options});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(async()=>{await new Promise(r=>server.close(r));await rm(root,{recursive:true,force:true});});
 const base=`http://127.0.0.1:${server.address().port}`;
 const page=await fetch(base);const cookie=page.headers.get('set-cookie').split(';')[0];
 return {root,base,cookie,call:(url,options={})=>fetch(base+url,{...options,headers:{Cookie:cookie,...options.headers}})};
}
test('serves the Node dashboard and rejects cross-site requests and unauthenticated API access',async t=>{
 const f=await fixture(t);assert.match(await(await fetch(f.base)).text(),/Your creative space/);
 assert.equal((await fetch(f.base+'/local/jobs')).status,401);
 assert.equal((await f.call('/local/jobs',{headers:{Origin:'http://evil.example'}})).status,403);
 assert.equal((await f.call('/local/jobs',{headers:{'Sec-Fetch-Site':'cross-site'}})).status,403);
 assert.equal((await f.call('/package.json')).status,404);
 assert.equal((await f.call('/api/jobs')).status,503);
 assert.equal((await f.call('/local/jobs',{method:'POST',body:'{"prompt":""}'})).status,422);
});
test('proxies the existing API with server-side authentication and preserves method/body',async t=>{
 let seen;
 const upstream=http.createServer(async(req,res)=>{let body='';for await(const c of req)body+=c;seen={url:req.url,method:req.method,auth:req.headers.authorization,body};res.writeHead(201,{'Content-Type':'application/json'});res.end('{"id":"test-job"}');});
 await new Promise(r=>upstream.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>upstream.close(r)));
 const f=await fixture(t,{apiUrl:`http://127.0.0.1:${upstream.address().port}`,token:'private-server-token'});
 const response=await f.call('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"demo":true}'});
 assert.equal(response.status,201);assert.equal(seen.auth,'Bearer private-server-token');assert.equal(seen.body,'{"demo":true}');assert.equal(seen.method,'POST');
});
test('local submissions persist, complete, and support seekable MP4 downloads',async t=>{
 let release;const wait=new Promise(r=>release=r);
 const f=await fixture(t,{runJob:async(folder)=>{await wait;await mkdir(path.join(folder,'out'));await writeFile(path.join(folder,'out','final-bangla.mp4'),Buffer.from('0123456789'));}});
 const response=await f.call('/local/jobs',{method:'POST',body:JSON.stringify({prompt:'বাংলা গল্প; $(not a shell command)'})});assert.equal(response.status,201);const {id}=await response.json();
 assert.equal((await f.call('/local/jobs',{method:'POST',body:'{"prompt":"second"}'})).status,409);release();
 let row;for(let i=0;i<50;i++){[row]=await(await f.call('/local/jobs')).json();if(row.state==='READY_TO_PUBLISH')break;await new Promise(r=>setTimeout(r,10));}
 assert.equal(row.state,'READY_TO_PUBLISH');assert.match(row.prompt,/বাংলা/);
 const video=await f.call(`/local/jobs/${id}/video`,{headers:{Range:'bytes=2-5'}});assert.equal(video.status,206);assert.equal(await video.text(),'2345');
 assert.equal((await f.call(`/local/jobs/${id}/video`,{headers:{Range:'bytes=999-'}})).status,416);
});
test('serves the language list and finds films and subtitles under the neutral names',async t=>{
 const f=await fixture(t,{runJob:async folder=>{await mkdir(path.join(folder,'out'));await writeFile(path.join(folder,'out','final-video.mp4'),Buffer.from('film'));await writeFile(path.join(folder,'out','captions.srt'),'1\n00:00:00,000 --> 00:00:01,000\nचाय\n');}});
 for(const file of ['/','/app.js','/style.css','/languages.json'])assert.equal((await f.call(file)).headers.get('cache-control'),'no-cache');
 const languages=await(await f.call('/languages.json')).json();
 assert.ok(languages.some(l=>l.code==='hi-IN')&&languages.some(l=>l.code==='zh-CN')&&languages.some(l=>l.code==='ur-PK'));
 const {id}=await(await f.call('/local/jobs',{method:'POST',body:JSON.stringify({prompt:'चाय की कहानी',options:{language:'Hindi (हिन्दी)',voice:'hi-IN-SwaraNeural'}})})).json();
 let row;for(let i=0;i<50;i++){[row]=await(await f.call('/local/jobs')).json();if(row.state==='READY_TO_PUBLISH')break;await new Promise(r=>setTimeout(r,10));}
 assert.equal(row.state,'READY_TO_PUBLISH');
 assert.equal(await(await f.call(`/local/jobs/${id}/video`)).text(),'film');
 const srt=await f.call(`/local/jobs/${id}/subtitles`);assert.match(srt.headers.get('content-disposition'),/captions\.srt/);assert.match(await srt.text(),/चाय/);
});
test('failed local work stays failed and stale running records become interrupted',async t=>{
 const f=await fixture(t,{runJob:async()=>{throw Error('Speech service unavailable');}});
 await f.call('/local/jobs',{method:'POST',body:'{"prompt":"A story"}'});let row;
 for(let i=0;i<50;i++){[row]=await(await f.call('/local/jobs')).json();if(row.state==='FAILED')break;await new Promise(r=>setTimeout(r,10));}
 assert.equal(row.state,'FAILED');assert.match(row.error,/Speech service/);
 const folder=path.join(f.root,'runs/local/stale');await mkdir(folder);await writeFile(path.join(folder,'dashboard-job.json'),JSON.stringify({id:'stale',state:'RUNNING',created:new Date().toISOString()}));
 assert.equal((await(await f.call('/local/jobs')).json()).find(r=>r.id==='stale').state,'INTERRUPTED');
});

test('cinematic stages require the correct approval and expose review artifacts',async t=>{
 const states={prepare:'AWAITING_SCRIPT',preview:'AWAITING_LOOK',draft:'AWAITING_DRAFT',finish:'READY_TO_PUBLISH'};
 const f=await fixture(t,{runJob:async(folder,row,action)=>{
  await writeFile(path.join(folder,'pipeline.json'),JSON.stringify({status:states[action],stage:action,completed:[action]}));
  await writeFile(path.join(folder,'beats.md'),'# Review this script');
 }});
 assert.equal((await f.call('/local/jobs',{method:'POST',body:JSON.stringify({prompt:'My film',options:{look:'not-a-look'}})})).status,422);
 const submitted=await f.call('/local/jobs',{method:'POST',body:JSON.stringify({prompt:'My film',options:{look:'wall',review:true}})});
 const {id}=await submitted.json();
 async function waitFor(state){for(let i=0;i<50;i++){const rows=await(await f.call('/local/jobs')).json();if(rows.find(r=>r.id===id)?.state===state)return;await new Promise(r=>setTimeout(r,10));}assert.fail('Expected '+state);}
 await waitFor('AWAITING_SCRIPT');
 assert.equal((await f.call(`/local/jobs/${id}/action`,{method:'POST',body:'{"action":"finish"}'})).status,409);
 const manifest=await(await f.call(`/local/jobs/${id}/manifest`)).json();
 assert.equal(manifest.files['beats.md'],'# Review this script');
 assert.equal((await f.call(`/local/jobs/${id}/artifact?file=../../.env`)).status,403);
 assert.equal((await f.call(`/local/jobs/${id}/artifact?file=beats.md`)).status,200);
 for(const action of ['preview','draft','finish']){
  assert.equal((await f.call(`/local/jobs/${id}/action`,{method:'POST',body:JSON.stringify({action})})).status,202);
  await waitFor(states[action]);
 }
});
