import {HttpError,json,boundedBody,bodyJSON,validateReport,signatureValid,jpegOK,admin} from './core.js';
import {db,identity,latest} from './services.js';
const reportPath=id=>'/rest/v1/reports?id=eq.'+encodeURIComponent(id);
async function ownedReport(id,user,env){
 if(!/^[0-9a-f-]{36}$/i.test(id))throw new HttpError(400,'รหัสรายงานไม่ถูกต้อง');
 const rows=await db(env,reportPath(id)+'&select=*');const row=rows[0];
 if(!row||row.owner_id!==user&&!admin(user,env))throw new HttpError(404,'ไม่พบรายงาน');return row;
}
async function webhook(request,env){
 const bytes=await boundedBody(request,262144);
 if(!await signatureValid(bytes,request.headers.get('x-line-signature'),env.LINE_CHANNEL_SECRET))throw new HttpError(401,'Invalid signature');
 let payload;try{payload=JSON.parse(new TextDecoder().decode(bytes));}catch{throw new HttpError(400,'Invalid JSON');}
 if(!Array.isArray(payload.events)||payload.events.length>20)throw new HttpError(400,'Invalid events');
 for(const event of payload.events){
  if(event.type!=='message'||event.message?.type!=='text'||!event.replyToken||!event.webhookEventId)continue;
  const text=event.message.text.trim();if(!['น้ำ','เมนู','แจ้งปัญหา','ช่วยเหลือ'].includes(text))continue;
  const claimed=await db(env,'/rest/v1/rpc/claim_line_event',{method:'POST',body:{p_id:event.webhookEventId}});if(!claimed)continue;
  const link='https://liff.line.me/'+env.LIFF_ID;
  const reply=text==='แจ้งปัญหา'?`แจ้งปัญหาและติดตามรายงานใน Water Fondue\n${link}\nกรณีฉุกเฉินโปรดติดต่อหน่วยงานในพื้นที่โดยตรง`:`เปิด Water Fondue เพื่อดูระดับน้ำและแจ้งปัญหา\n${link}\nข้อมูลจาก ThaiWater ไม่ใช่ประกาศเตือนภัยทางการ`;
  const r=await fetch('https://api.line.me/v2/bot/message/reply',{method:'POST',headers:{Authorization:'Bearer '+env.LINE_CHANNEL_ACCESS_TOKEN,'Content-Type':'application/json'},body:JSON.stringify({replyToken:event.replyToken,messages:[{type:'text',text:reply}]}),signal:AbortSignal.timeout(10000)});
  // At-most-once attempt: record failure for operators; never risk duplicate push.
  await db(env,'/rest/v1/line_events?id=eq.'+encodeURIComponent(event.webhookEventId),{method:'PATCH',body:{reply_status:r.ok?'sent':'failed'}});
 }
 return json({ok:true});
}
export default {async fetch(request,env,ctx){try{
 const u=new URL(request.url),p=u.pathname;
 if(p==='/webhook/line'&&request.method==='POST')return await webhook(request,env);
 if(p==='/api/config'&&request.method==='GET')return json({liffId:env.LIFF_ID,reportsEnabled:env.REPORTS_ENABLED==='true',contact:env.CONTACT_TEXT??'',maxPhotoBytes:102400});
 if(p==='/api/health'&&request.method==='GET')return json({ok:true,version:'3.0.0'});
 if(p==='/api/water'&&request.method==='GET'){
  const key=new Request(u.origin+'/api/water');const cache=globalThis.caches?.default;const hit=await cache?.match(key);if(hit)return hit;
  const response=json(await latest(env),200,{'Cache-Control':'public, max-age=300'});if(cache)ctx.waitUntil(cache.put(key,response.clone()));return response;
 }
 if(!p.startsWith('/api/'))return env.ASSETS.fetch(request);
 if(['POST','PATCH','DELETE','PUT'].includes(request.method)){
  const origin=request.headers.get('Origin');if(origin&&origin!==u.origin)throw new HttpError(403,'Origin denied');
 }
 const user=await identity(request,env);
 if(p==='/api/me'&&request.method==='GET')return json({userId:user,isAdmin:admin(user,env)});
 if(p==='/api/reports'&&request.method==='POST'){
  if(env.REPORTS_ENABLED!=='true')throw new HttpError(503,'ยังไม่เปิดรับรายงาน');
  const x=validateReport(await bodyJSON(request));
  const row=await db(env,'/rest/v1/rpc/create_water_report',{method:'POST',body:{p_id:x.id,p_owner:user,p_category:x.category,p_description:x.description,p_lat:x.latitude,p_lon:x.longitude}});
  return json(row,201);
 }
 if(p==='/api/reports'&&request.method==='GET'){
  const scope=u.searchParams.get('scope');if(scope==='all'&&!admin(user,env))throw new HttpError(403,'เฉพาะผู้ดูแล');
  const filter=scope==='all'?'':'&owner_id=eq.'+encodeURIComponent(user);
  return json(await db(env,'/rest/v1/reports?select=*&order=created_at.desc&limit=100'+filter));
 }
 const match=p.match(/^\/api\/reports\/([0-9a-f-]+)(\/photo)?$/i);
 if(match){
  const row=await ownedReport(match[1],user,env);
  if(match[2]&&request.method==='POST'){
   if(env.REPORTS_ENABLED!=='true')throw new HttpError(503,'ยังไม่เปิดรับรูป');
   if(row.owner_id!==user)throw new HttpError(403,'เฉพาะผู้ส่งรายงาน');
   if(row.photo_path)return json({ok:true,alreadyUploaded:true});
   if(request.headers.get('Content-Type')!=='image/jpeg')throw new HttpError(415,'รองรับ JPEG เท่านั้น');
   const bytes=await boundedBody(request,102400);if(!jpegOK(bytes))throw new HttpError(400,'JPEG ไม่ถูกต้องหรือใหญ่เกิน 100 KiB');
   const path=row.id+'.jpg';
   // Fixed key and size: concurrent retries overwrite at most this same small object.
   await db(env,'/storage/v1/object/report-photos/'+path,{method:'POST',body:bytes,headers:{'Content-Type':'image/jpeg','x-upsert':'true'}});
   await db(env,reportPath(row.id),{method:'PATCH',body:{photo_path:path}});return json({ok:true});
  }
  if(match[2]&&request.method==='GET'){
   if(!row.photo_path)throw new HttpError(404,'ไม่มีรูป');
   const signed=await db(env,'/storage/v1/object/sign/report-photos/'+encodeURIComponent(row.photo_path),{method:'POST',body:{expiresIn:60}});
   return json({url:env.SUPABASE_URL.replace(/\/$/,'')+'/storage/v1'+signed.signedURL});
  }
  if(!match[2]&&request.method==='PATCH'){
   if(!admin(user,env))throw new HttpError(403,'เฉพาะผู้ดูแล');const x=await bodyJSON(request);
   if(!['new','reviewing','resolved'].includes(x.status))throw new HttpError(400,'สถานะไม่ถูกต้อง');
   await db(env,reportPath(row.id),{method:'PATCH',body:{status:x.status}});return json({ok:true});
  }
 }
 throw new HttpError(404,'ไม่พบ API');
 }catch(e){return json({error:e instanceof HttpError?e.message:'ระบบขัดข้อง โปรดลองใหม่'},e instanceof HttpError?e.status:502);}}};
