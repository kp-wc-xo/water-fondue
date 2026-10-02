export class HttpError extends Error { constructor(status,message){super(message);this.status=status;} }
export function json(data,status=200,extra={}){return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...extra}});}
export async function boundedBody(request,max){
 const reader=request.body?.getReader();if(!reader)return new Uint8Array();
 let size=0,parts=[];
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>max){await reader.cancel();throw new HttpError(413,'ข้อมูลใหญ่เกินกำหนด');}parts.push(value);}
 const out=new Uint8Array(size);let offset=0;for(const p of parts){out.set(p,offset);offset+=p.length;}return out;
}
export async function bodyJSON(request,max=8192){try{return JSON.parse(new TextDecoder().decode(await boundedBody(request,max)));}catch(e){if(e instanceof HttpError)throw e;throw new HttpError(400,'JSON ไม่ถูกต้อง');}}
export function validateReport(x){
 if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(x.id??''))throw new HttpError(400,'รหัสคำขอไม่ถูกต้อง');
 if(!['flood','blocked_canal','gate','other'].includes(x.category))throw new HttpError(400,'ประเภทไม่ถูกต้อง');
 const description=typeof x.description==='string'?x.description.trim():'';
 if(description.length<10||description.length>1000)throw new HttpError(400,'รายละเอียดต้องมี 10–1000 ตัวอักษร');
 const lat=x.latitude??null,lon=x.longitude??null;
 if((lat===null)!==(lon===null)||lat!==null&&(!Number.isFinite(lat)||!Number.isFinite(lon)||lat< -90||lat>90||lon< -180||lon>180))throw new HttpError(400,'พิกัดไม่ถูกต้อง');
 if(x.consent!==true)throw new HttpError(400,'โปรดยอมรับการใช้ข้อมูลเพื่อจัดการรายงาน');
 return {id:x.id,category:x.category,description,latitude:lat,longitude:lon};
}
export async function signatureValid(bytes,signature,secret){
 if(!secret||!signature)return false;
 try{const raw=Uint8Array.from(atob(signature),c=>c.charCodeAt(0));const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);return await crypto.subtle.verify('HMAC',key,raw,bytes);}catch{return false;}
}
export function jpegOK(bytes){return bytes.length>=4&&bytes.length<=102400&&bytes[0]===255&&bytes[1]===216&&bytes[bytes.length-2]===255&&bytes[bytes.length-1]===217;}
export function admin(user,env){return (env.ADMIN_LINE_USER_IDS??'').split(',').map(x=>x.trim()).filter(Boolean).includes(user);}
