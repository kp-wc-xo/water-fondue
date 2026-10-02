const $=id=>document.getElementById(id);let cfg,me=null,water=null,requestId=null,photoBlob=null;
const fmt=t=>t?new Date(t).toLocaleString('th-TH',{timeZone:'Asia/Bangkok'}):'ไม่มี';
async function api(path,options={}){
 const headers={...options.headers};if(options.auth!==false){const token=window.liff?.getIDToken();if(!token)throw Error('โปรดเข้าสู่ระบบ LINE ก่อน');headers.Authorization='Bearer '+token;}
 const r=await fetch(path,{...options,headers});const d=await r.json();if(!r.ok)throw Error(d.error||'โหลดข้อมูลไม่สำเร็จ');return d;
}
function message(e){$('error').textContent=e.message??String(e);}
function tab(name){document.querySelectorAll('section').forEach(s=>s.hidden=s.id!==name);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));tab(['water','report','mine'].includes(location.hash.slice(1))?location.hash.slice(1):'water');
function renderWater(){if(!water)return;const age=(Date.now()-Date.parse(water.ingestion?.at))/60000;
 $('waterStatus').textContent=`ดึงสำเร็จ ${fmt(water.ingestion?.at)}${!Number.isFinite(age)||age>120||age< -15?' · โปรดตรวจสอบความสดของระบบ':''}`;
 $('waterRows').replaceChildren();let count=0;
 for(const r of water.rows){if(!$('search').value||String(r.name).includes($('search').value)){
 const tr=document.createElement('tr'),age=(Date.now()-Date.parse(r.observed_at))/60000;
 const stale=!Number.isFinite(age)||age>water.stale_minutes||age< -water.max_future_minutes;
 for(const v of [r.name,r.level_msl??'ไม่มีค่า',fmt(r.observed_at),stale?'เก่าหรือเวลาผิดปกติ':r.level_msl==null?'ไม่มีค่าระดับน้ำ':'อยู่ในช่วงความสด']){const td=document.createElement('td');td.textContent=v;tr.append(td);}if(stale)tr.className='stale';$('waterRows').append(tr);count++;
 }}$('waterCount').textContent=`แสดง ${count} สถานี`;}
async function loadWater(){try{water=await api('/api/water',{auth:false});renderWater();}catch(e){message(e);$('waterStatus').textContent='อ่านข้อมูลล่าสุดไม่สำเร็จ โปรดตรวจเวลาของข้อมูลที่ค้างอยู่';}}
$('refresh').onclick=loadWater;$('search').oninput=renderWater;setInterval(renderWater,30000);
$('login').onclick=()=>window.liff.login({redirectUri:location.origin+'/'});
$('locate').onclick=()=>{if(!navigator.geolocation)return message(Error('อุปกรณ์ไม่รองรับพิกัด'));navigator.geolocation.getCurrentPosition(p=>{$('latitude').value=p.coords.latitude;$('longitude').value=p.coords.longitude;},()=>message(Error('อ่านพิกัดไม่ได้ คุณกรอกเองหรือเว้นว่างได้')),{enableHighAccuracy:true,timeout:15000});};
async function compress(file){if(file.size>15*1024*1024)throw Error('โปรดเลือกรูปต้นฉบับไม่เกิน 15 MB');const url=URL.createObjectURL(file);try{const img=new Image();img.src=url;await img.decode();let width=Math.min(960,img.width);for(let attempt=0;attempt<4;attempt++){
 const c=document.createElement('canvas');c.width=width;c.height=Math.round(img.height*width/img.width);c.getContext('2d').drawImage(img,0,0,c.width,c.height);
 const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.65));if(blob&&blob.size<=102400)return blob;width=Math.round(width*.7);
 }throw Error('รูปยังใหญ่เกินกำหนด โปรดเลือกรูปอื่น');}finally{URL.revokeObjectURL(url);}}
$('photo').onchange=async()=>{photoBlob=null;try{if($('photo').files[0]){photoBlob=await compress($('photo').files[0]);$('photoStatus').textContent=`ย่อแล้ว ${Math.ceil(photoBlob.size/1024)} KiB และแปลงเป็น JPEG`;}}catch(e){$('photo').value='';$('photoStatus').textContent='';message(e);}};
$('reportForm').onsubmit=async e=>{e.preventDefault();$('error').textContent='';$('submitReport').disabled=true;try{
 if(!me)throw Error('โปรดเข้าสู่ระบบ LINE ก่อนส่ง');if(!cfg.reportsEnabled)throw Error('ยังไม่เปิดรับรายงาน');
 if($('photo').files.length&&!photoBlob)throw Error('โปรดรอรูปย่อเสร็จหรือเลือกรูปใหม่');
 requestId??=crypto.randomUUID();
 const body={id:requestId,category:$('category').value,description:$('description').value,latitude:$('latitude').value===''?null:Number($('latitude').value),longitude:$('longitude').value===''?null:Number($('longitude').value),consent:$('consent').checked};
 const report=await api('/api/reports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 $('receipt').textContent='บันทึกเรื่องแล้ว รหัส '+report.id;
 if(photoBlob){try{await api('/api/reports/'+report.id+'/photo',{method:'POST',headers:{'Content-Type':'image/jpeg'},body:photoBlob});}catch(err){$('receipt').textContent+=' แต่รูปยังส่งไม่สำเร็จ กดส่งอีกครั้งเพื่อแนบรูปกับรหัสเดิม';throw err;}}
 $('receipt').textContent+=' · ติดตามที่รายงานของฉัน';requestId=null;$('reportForm').reset();photoBlob=null;$('photoStatus').textContent='';
 }catch(err){message(err);}finally{$('submitReport').disabled=false;}};
async function reports(all){try{const rows=await api('/api/reports'+(all?'?scope=all':''));const target=$(all?'allReports':'myReports');target.replaceChildren();if(!rows.length)target.textContent='ยังไม่มีรายงาน';
 for(const r of rows){const card=document.createElement('article');card.className='card';
 for(const txt of [`${r.id} · ${fmt(r.created_at)}`,r.category+' · '+r.status,r.description,r.latitude==null?'ไม่ระบุพิกัด':`พิกัด ${r.latitude}, ${r.longitude}`]){const p=document.createElement('p');p.textContent=txt;card.append(p);}
 if(r.photo_path){const b=document.createElement('button');b.textContent='ดูรูป';b.onclick=async()=>{try{const x=await api('/api/reports/'+r.id+'/photo');const img=document.createElement('img');img.alt='รูปประกอบรายงาน';img.src=x.url;card.append(img);b.remove();}catch(e){message(e);}};card.append(b);}
 if(all){const sel=document.createElement('select');for(const [value,label] of [['new','รับเรื่องใหม่'],['reviewing','กำลังตรวจสอบ'],['resolved','ดำเนินการแล้ว']]){const opt=document.createElement('option');opt.value=value;opt.textContent=label;sel.append(opt);}sel.value=r.status;const save=document.createElement('button');save.textContent='บันทึกสถานะ';save.onclick=async()=>{try{await api('/api/reports/'+r.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:sel.value})});await reports(true);}catch(e){message(e);}};card.append(sel,save);}target.append(card);
 }}catch(e){message(e);}}
$('loadMine').onclick=()=>reports(false);$('loadAdmin').onclick=()=>reports(true);
async function start(){await loadWater();try{cfg=await api('/api/config',{auth:false});$('contact').textContent=cfg.contact;
 if(!cfg.reportsEnabled)$('receipt').textContent='ผู้ดูแลยังไม่เปิดรับรายงาน';
 if(!cfg.liffId||cfg.liffId.startsWith('REPLACE'))throw Error('ยังไม่ได้ตั้ง LIFF ID ดูข้อมูลน้ำได้ แต่การส่งรายงานต้องตั้ง LINE ก่อน');
 if(!window.liff)throw Error('โหลด LINE SDK ไม่สำเร็จ');await liff.init({liffId:cfg.liffId});
 if(!liff.isLoggedIn()){$('login').hidden=false;$('authStatus').textContent='ดูข้อมูลน้ำได้ทันที เข้าสู่ระบบ LINE เพื่อแจ้งปัญหา';return;}
 me=await api('/api/me');$('adminTab').hidden=!me.isAdmin;$('authStatus').textContent=`เข้าสู่ระบบแล้ว · รหัสบัญชีของคุณ ${me.userId}`;
 }catch(e){$('authStatus').textContent=e.message;}}
window.addEventListener('DOMContentLoaded',start);
