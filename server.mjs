import http from 'node:http';
import {readFile,stat,mkdir,readdir,writeFile,rm,rename} from 'node:fs/promises';
import {createReadStream,existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {randomUUID,randomBytes} from 'node:crypto';
import {spawn} from 'node:child_process';
import {Readable,pipeline} from 'node:stream';

export const ROOT=path.dirname(fileURLToPath(import.meta.url));
// The Python runtime this PC was first set up with; a project .venv or STUDIO_PYTHON takes priority.
const SHARED=process.env.STUDIO_RUNTIME||String.raw`C:\Users\HP\Documents\Codex\2026-11-22\d-video-maker-cinematic-skill\work`;
export function pythonFor(root){return process.env.STUDIO_PYTHON || [path.join(root,'.venv','Scripts','python.exe'),path.join(SHARED,'cinematic-venv','Scripts','python.exe')].find(existsSync) || 'python';}
// Finished films and subtitles have neutral names; projects from before multi-language support keep theirs.
const finalVideo=folder=>[path.join(folder,'out','final-video.mp4'),path.join(folder,'out','final-bangla.mp4')].find(existsSync)||path.join(folder,'out','final-video.mp4');
const subtitleFile=folder=>[path.join(folder,'out','captions.srt'),path.join(folder,'out','captions.bn.srt')].find(existsSync)||path.join(folder,'out','captions.srt');
// A project's name is the start of the story, without the settings the dashboard appends to the prompt.
const cleanTitle=text=>String(text||'').split(/\s*Director notes:/)[0].replace(/\s+/g,' ').trim().slice(0,90)||'Untitled film';
const json=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
async function body(req){const chunks=[];let size=0;for await(const c of req){size+=c.length;if(size>160000)throw Object.assign(Error('Request is too large'),{status:413});chunks.push(c);}try{return JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw Object.assign(Error('Invalid JSON'),{status:400});}}
async function media(req,res,file){
 const info=await stat(file);const range=req.headers.range;
 let start=0,end=info.size-1,status=200;
 if(range){const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||(!m[1]&&!m[2])){res.writeHead(416,{'Content-Range':`bytes */${info.size}`});return res.end();}
  if(!m[1])start=Math.max(0,info.size-Number(m[2]));else start=Number(m[1]);
  if(m[1]&&m[2])end=Math.min(end,Number(m[2]));
  if(start>end||start>=info.size){res.writeHead(416,{'Content-Range':`bytes */${info.size}`});return res.end();}status=206;}
 res.writeHead(status,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Length':end-start+1,...(status===206?{'Content-Range':`bytes ${start}-${end}/${info.size}`}:{})});
 if(req.method==='HEAD')return res.end();pipeline(createReadStream(file,{start,end}),res,()=>{});
}
export function createDashboard({root=ROOT,apiUrl=process.env.STUDIO_API_URL,token=process.env.STUDIO_ADMIN_TOKEN,runJob}={}){
 const session=randomBytes(32).toString('hex'),running=new Map();const jobsRoot=path.join(root,'runs','local');
 const readJSON=async(file,fallback={})=>{try{return JSON.parse(await readFile(file,'utf8'));}catch{return fallback;}};
 // Write then rename, so the library never reads a half-written status file. Windows refuses the
 // rename for a moment while a reader has the file open, so it is retried briefly.
 async function saveRow(folder,row){
  const file=path.join(folder,'dashboard-job.json'),temporary=file+'.'+randomUUID().slice(0,8)+'.tmp';
  await writeFile(temporary,JSON.stringify(row,null,2));
  for(let attempt=0;;attempt++){try{return await rename(temporary,file);}catch(e){if(attempt>=20||!['EPERM','EACCES','EBUSY'].includes(e.code)){await rm(temporary,{force:true});throw e;}await new Promise(r=>setTimeout(r,25));}}
 }
 async function launchStage(id,folder,row,action='prepare'){
  running.set(id,true);row.state='RUNNING';row.error=null;await saveRow(folder,row);
  const finish=async(code,error)=>{
   const pipeline=await readJSON(path.join(folder,'pipeline.json'));
   row.state=code===0?(pipeline.status||(existsSync(finalVideo(folder))?'READY_TO_PUBLISH':'FAILED')):'FAILED';
   row.error=error||pipeline.error||(row.state==='FAILED'?'Production stopped. Read the production log.':null);
   row.stage=pipeline.stage;running.delete(id);await saveRow(folder,row);
  };
  if(runJob){Promise.resolve().then(()=>runJob(folder,row,action)).then(()=>finish(0),e=>finish(1,e.message))
   .catch(e=>{console.error('Could not save production status:',e.message);running.delete(id);});return;}
  const child=spawn(pythonFor(root),['-X','utf8',path.join(root,'tools','dashboard_job.py'),folder,action],{cwd:root,env:{...process.env,PYTHONUTF8:'1'},windowsHide:true,stdio:['ignore','pipe','pipe']});
  running.set(id,child);let logs='';const append=c=>{logs=(logs+c.toString()).slice(-160000);};child.stdout.on('data',append);child.stderr.on('data',append);child.on('error',e=>{logs+=e.message;});
  child.on('close',async code=>{try{await writeFile(path.join(folder,'dashboard.log'),logs);await finish(code);}catch(e){console.error('Could not save production status:',e.message);running.delete(id);}});
 }
 function validateOptions(config){
  if(!config||typeof config!=='object'||Array.isArray(config))throw Object.assign(Error('Invalid cinematic settings'),{status:422});
  const allowed=['review','look','size','voice','audio','captions','caption_style','sfx','archive','maps','duration','language','voice_source','music'];
  if(Object.keys(config).some(k=>!allowed.includes(k)))throw Object.assign(Error('Unknown cinematic setting'),{status:422});
  for(const k of ['review','audio','captions','sfx','archive','maps'])if(k in config&&typeof config[k]!=='boolean')throw Object.assign(Error(k+' must be true or false'),{status:422});
  const enums={voice_source:['edge','takes','lines'],look:['studio','wall','slate','charcoal','blueprint','paper','night'],size:['640x360','1280x720','1920x1080','360x640','720x1280','1080x1920','2560x1440','3840x2160','1440x2560','2160x3840'],caption_style:['clean','highlighter','paper','redbar']};
  for(const [k,values] of Object.entries(enums))if(k in config&&!values.includes(config[k]))throw Object.assign(Error('Unsupported '+k),{status:422});
  if('duration' in config&&(!Number.isInteger(config.duration)||config.duration<5||config.duration>180))throw Object.assign(Error('Duration must be 5–180 seconds'),{status:422});
  if('music' in config&&config.music!==null&&config.music!=='audio/music.mp3')throw Object.assign(Error('Use audio/music.mp3 for the licensed score'),{status:422});
  for(const k of ['voice','language'])if(k in config&&(typeof config[k]!=='string'||!config[k].trim()||config[k].length>100))throw Object.assign(Error('Invalid '+k),{status:422});
 }
 async function thumbnail(folder){try{const names=(await readdir(path.join(folder,'out','probe'))).filter(n=>/^[a-zA-Z0-9_.-]+\.(png|jpg)$/.test(n)).sort();const still=names.find(n=>n.endsWith('.png'))||names[0];return still?'out/probe/'+still:null;}catch{return null;}}
 async function localJobs(){await mkdir(jobsRoot,{recursive:true});const rows=[];for(const name of await readdir(jobsRoot)){
  if(!/^[a-zA-Z0-9_-]+$/.test(name))continue;
  const options=await readJSON(path.join(jobsRoot,name,'cinematic-options.json'),{});const facts={...(typeof options.language==='string'?{language:options.language}:{}),...(Number.isInteger(options.duration)?{duration:options.duration}:{})};
  try{const row={...JSON.parse(await readFile(path.join(jobsRoot,name,'dashboard-job.json'),'utf8')),...facts};row.title=cleanTitle(row.title);const pipeline=await readJSON(path.join(jobsRoot,name,'pipeline.json'));if(pipeline.status){if(!running.has(name))row.state=pipeline.status;row.stage=pipeline.stage;row.error=pipeline.error;row.pipeline=pipeline;}if(['RUNNING','QUEUED'].includes(row.state)&&!running.has(name)){row.state='INTERRUPTED';row.error='The studio stopped before this job finished. Inspect the run before retrying.';}row.thumb=await thumbnail(path.join(jobsRoot,name));rows.push(row);}catch{
   const final=finalVideo(path.join(jobsRoot,name));
   if(existsSync(final)){
    const info=await stat(final);let title='Local cinematic film';
    try{title=JSON.parse(await readFile(path.join(jobsRoot,name,'script.json'),'utf8')).title||title;}catch{}
    rows.push({id:name,title,state:'READY_TO_PUBLISH',created:info.mtime.toISOString(),mode:'local',...facts,thumb:await thumbnail(path.join(jobsRoot,name))});
   }
  }
 }return rows.sort((a,b)=>b.created.localeCompare(a.created));}
 const server=http.createServer(async(req,res)=>{
  try{
   const host=req.headers.host||'';if(!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host))return json(res,403,{detail:'Local access only'});
   const url=new URL(req.url,'http://'+host);const protectedRoute=url.pathname.startsWith('/api/')||url.pathname.startsWith('/local/');
   if(req.headers['sec-fetch-site']==='cross-site'||(req.headers.origin&&req.headers.origin!=='http://'+host))return json(res,403,{detail:'Cross-site request blocked'});
   if(url.pathname==='/health')return json(res,200,{status:'ok',dashboard:'nodejs'});
   if(protectedRoute&&!(req.headers.cookie||'').split(';').some(c=>c.trim()===`studio=${session}`))return json(res,401,{detail:'Open the dashboard first'});
   if(url.pathname==='/local/jobs'&&req.method==='GET')return json(res,200,await localJobs());
   if(url.pathname==='/local/jobs'&&req.method==='POST'){
    const data=await body(req);if(typeof data.prompt!=='string'||!data.prompt.trim()||data.prompt.length>36000)return json(res,422,{detail:'Enter a story between 1 and 36,000 characters.'});
    if(running.size)return json(res,409,{detail:'A local film is already running. Wait for it to finish.'});
    validateOptions(data.options||{});
    // Claim the single production slot before any await, so a double click cannot start two films.
    const id=Date.now()+'-'+randomUUID().slice(0,8),folder=path.join(jobsRoot,id);running.set(id,true);
    try{
     await mkdir(folder,{recursive:true});
     const row={id,title:cleanTitle(data.prompt),prompt:data.prompt.trim(),state:'RUNNING',created:new Date().toISOString(),mode:'local'};
     await writeFile(path.join(folder,'user-prompt.txt'),row.prompt);
     await writeFile(path.join(folder,'cinematic-options.json'),JSON.stringify(data.options||{},null,2));
     await launchStage(id,folder,row);
    }catch(error){running.delete(id);throw error;}
    return json(res,201,{id});
   }
   const project=/^\/local\/jobs\/([a-zA-Z0-9_-]+)$/.exec(url.pathname);
   if(project){
    if(req.method!=='DELETE')return json(res,405,{detail:'Method not allowed'});
    const folder=path.join(jobsRoot,project[1]);
    if(!existsSync(folder))return json(res,404,{detail:'Project not found'});
    if(running.has(project[1]))return json(res,409,{detail:'This project is still running. Wait for the stage to finish, then delete it.'});
    await rm(folder,{recursive:true,force:true,maxRetries:5,retryDelay:200});return json(res,200,{deleted:true});
   }
   const stageRoute=/^\/local\/jobs\/([a-zA-Z0-9_-]+)\/(action|manifest|artifact|folder)$/.exec(url.pathname);
   if(stageRoute){
    const id=stageRoute[1],folder=path.join(jobsRoot,id);
    if(!existsSync(folder))return json(res,404,{detail:'Project not found'});
    if(stageRoute[2]==='folder'&&req.method==='POST'){
     if(process.platform!=='win32')return json(res,501,{detail:'Open the project folder manually on this operating system'});
     const explorer=spawn('explorer.exe',[folder],{windowsHide:true,stdio:'ignore'});explorer.on('error',()=>{});return json(res,200,{opened:true});
    }
    if(stageRoute[2]==='action'&&req.method==='POST'){
     if(running.size)return json(res,409,{detail:'Wait for the current production stage to finish.'});
     running.set(id,true);let launched=false;   // claimed before any await; released below unless the stage starts
     try{
     const data=await body(req);const pipeline=await readJSON(path.join(folder,'pipeline.json'));
     const expected={AWAITING_SCRIPT:'preview',AWAITING_LOOK:'draft',AWAITING_DRAFT:'finish',FAILED:'retry'};
     if(expected[pipeline.status]!==data.action&&!(data.action==='prepare'&&['AWAITING_SCRIPT','FAILED'].includes(pipeline.status))&&!(data.action==='revise'&&['AWAITING_SCRIPT','AWAITING_LOOK','AWAITING_DRAFT','FAILED'].includes(pipeline.status)))return json(res,409,{detail:'That production action is not available at this stage.'});
     if(data.action==='revise'){if(typeof data.notes!=='string'||!data.notes.trim()||data.notes.length>6000)return json(res,422,{detail:'Add revision notes (up to 6,000 characters)'});const previous=await readFile(path.join(folder,'user-prompt.txt'),'utf8');if(previous.length+data.notes.length>50000)return json(res,422,{detail:'Start a new project for more revisions'});await writeFile(path.join(folder,'user-prompt.txt'),previous+'\nRevision requested by user: '+data.notes);}
     const row=await readJSON(path.join(folder,'dashboard-job.json'),{id,title:id,created:new Date().toISOString(),mode:'local'});
     await launchStage(id,folder,row,data.action);launched=true;return json(res,202,{id,state:'RUNNING'});
     }finally{if(!launched&&running.get(id)===true)running.delete(id);}
    }
    if(stageRoute[2]==='manifest'&&req.method==='GET'){
     const files={};for(const name of ['beats.md','credits.md','script.json','story-plan.json'])try{files[name]=(await readFile(path.join(folder,name),'utf8')).slice(0,100000);}catch{}
     let previews=[];try{previews=(await readdir(path.join(folder,'out','probe'))).filter(n=>/^[a-zA-Z0-9_.-]+\.(png|jpg)$/.test(n)).map(n=>'out/probe/'+n);}catch{}
     const pipeline=await readJSON(path.join(folder,'pipeline.json'));
     return json(res,200,{pipeline,files,previews,options:await readJSON(path.join(folder,'cinematic-options.json'))});
    }
    if(stageRoute[2]==='artifact'&&['GET','HEAD'].includes(req.method)){
     const name=url.searchParams.get('file')||'';
     if(!/^(out\/probe\/[a-zA-Z0-9_.-]+\.(png|jpg)|out\/(draft|final)\.mp4|beats\.md|credits\.md|script\.json|out\/verification\.json)$/.test(name))return json(res,403,{detail:'Artifact not available'});
     const file=path.join(folder,name);
     if(name.endsWith('.mp4'))return await media(req,res,file);
     const data=await readFile(file);res.writeHead(200,{'Content-Type':name.endsWith('.png')?'image/png':name.endsWith('.jpg')?'image/jpeg':'text/plain; charset=utf-8','X-Content-Type-Options':'nosniff'});return res.end(data);
    }
    return json(res,405,{detail:'Method not allowed'});
   }
   const local=/^\/local\/jobs\/([a-zA-Z0-9_-]+)\/(video|log|subtitles)$/.exec(url.pathname);
   if(local){const folder=path.join(jobsRoot,local[1]);if(local[2]==='video')return await media(req,res,finalVideo(folder));
    if(local[2]==='subtitles'){const data=await readFile(subtitleFile(folder));res.writeHead(200,{'Content-Type':'text/plain; charset=utf-8','Content-Disposition':'attachment; filename="captions.srt"'});return res.end(data);}
    let text='';for(const file of ['run.log','production.log','dashboard.log','result.txt'])try{text+='\n'+await readFile(path.join(folder,file),'utf8');}catch{}
    return json(res,200,{log:text.slice(-60000)||'Starting the local video agent…'});
   }
   if(url.pathname.startsWith('/api/')){
    if(!apiUrl)return json(res,503,{detail:'The render API is not connected. Restart with studio.cmd.'});
    const headers={'Authorization':'Bearer '+token};if(req.headers['content-type'])headers['Content-Type']=req.headers['content-type'];if(req.headers.range)headers.Range=req.headers.range;
    // The timeout covers only the wait for the API's answer; a long video preview must keep streaming.
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),120000);
    const init={method:req.method,headers,redirect:'manual',signal:abort.signal};
    if(!['GET','HEAD'].includes(req.method)){init.body=req;init.duplex='half';}
    let upstream;try{upstream=await fetch(new URL(url.pathname+url.search,apiUrl),init);}catch{return json(res,503,{detail:'The studio API is not running. Close the studio window and start studio.cmd again.'});}finally{clearTimeout(timer);}
    const resultHeaders={};for(const name of ['content-type','content-length','content-range','accept-ranges','location','content-disposition'])if(upstream.headers.has(name))resultHeaders[name]=upstream.headers.get(name);
    res.writeHead(upstream.status,resultHeaders);
    // pipeline() handles stream errors and cancels the upstream when the viewer closes the tab.
    if(upstream.body)pipeline(Readable.fromWeb(upstream.body),res,()=>{});else res.end();return;
   }
   const files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/languages.json':'languages.json'};const file=files[url.pathname];
   if(!file)return json(res,404,{detail:'Not found'});
   if(!['GET','HEAD'].includes(req.method))return json(res,405,{detail:'Method not allowed'});
   const mime=file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':file.endsWith('.json')?'application/json':'text/html';
   res.writeHead(200,{'Content-Type':mime+'; charset=utf-8','Cache-Control':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; media-src 'self' blob: https:; img-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none'",...(file==='index.html'?{'Set-Cookie':`studio=${session}; HttpOnly; SameSite=Strict; Path=/`}:{})});
   res.end(req.method==='HEAD'?undefined:await readFile(path.join(root,'web',file)));
  }catch(error){if(res.headersSent){res.destroy();return;}json(res,error.code==='ENOENT'?404:error.status||500,{detail:error.code==='ENOENT'?'File not available':error.message});}
 });
 server.on('close',()=>{for(const child of running.values())if(child&&typeof child.kill==='function')child.kill();});return server;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){const server=createDashboard();server.listen(Number(process.env.STUDIO_PORT||3000),'127.0.0.1',()=>console.log(`Story Studio · http://127.0.0.1:${server.address().port}`));}
