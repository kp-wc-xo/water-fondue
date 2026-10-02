import {HttpError} from './core.js';
export async function db(env,path,{method='GET',body,headers={}}={}){
 if(!env.SUPABASE_URL?.startsWith('https://')||!env.SUPABASE_SECRET_KEY?.startsWith('sb_secret_'))throw new HttpError(503,'ผู้ดูแลยังตั้งค่าฐานข้อมูลไม่ครบ');
 const response=await fetch(env.SUPABASE_URL.replace(/\/$/,'')+path,{method,headers:{apikey:env.SUPABASE_SECRET_KEY,...(body instanceof Uint8Array?{}:{'Content-Type':'application/json'}),...headers},body:body===undefined?undefined:body instanceof Uint8Array?body:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
 if(!response.ok){
  // Only translate known validation failures; never expose DB messages or credentials.
  if(response.status===400){const x=await response.json().catch(()=>({}));if(x.message==='REPORT_LIMIT')throw new HttpError(429,'ถึงเพดานรายงานนำร่องแล้ว ลองใหม่ภายหลังหรือติดต่อผู้ดูแล');}
  throw new HttpError(502,'บริการฐานข้อมูลขัดข้อง โปรดลองใหม่');
 }
 const text=await response.text();return text?JSON.parse(text):null;
}
export async function identity(request,env){
 const token=request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1];
 if(!token||token.length>8192)throw new HttpError(401,'โปรดเข้าสู่ระบบผ่าน LINE');
 if(!/^\d+$/.test(env.LINE_LOGIN_CHANNEL_ID??''))throw new HttpError(503,'ยังไม่ได้ตั้ง LINE Login channel');
 const r=await fetch('https://api.line.me/oauth2/v2.1/verify',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({id_token:token,client_id:env.LINE_LOGIN_CHANNEL_ID}),signal:AbortSignal.timeout(10000)});
 if(!r.ok)throw new HttpError(r.status>=500?502:401,'ยืนยันบัญชี LINE ไม่สำเร็จ โปรดเข้าสู่ระบบใหม่');
 const p=await r.json();
 if(p.iss!=='https://access.line.me'||String(p.aud)!==env.LINE_LOGIN_CHANNEL_ID||!Number.isFinite(p.exp)||p.exp<=Date.now()/1000||!/^U[0-9a-f]{32}$/.test(p.sub??''))throw new HttpError(401,'ข้อมูลยืนยันบัญชี LINE ไม่ถูกต้อง');
 return p.sub;
}
export async function latest(env){
 const [rows,state]=await Promise.all([db(env,'/rest/v1/latest_water?select=*&order=station_key&limit=100'),db(env,'/rest/v1/state?key=eq.last_success&select=value')]);
 return {rows,ingestion:state[0]?.value??null,stale_minutes:Number(env.STALE_MINUTES)||120,max_future_minutes:Number(env.MAX_FUTURE_MINUTES)||15};
}
