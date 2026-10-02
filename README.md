# Water Fondue LINE — v3.0

ชุดนำร่องดูระดับน้ำและรับรายงานปัญหาใน LINE โดยใช้ Cloudflare Workers + Supabase + GitHub Actions + LINE OA/LIFF บนแผนฟรีภายในโควตา

เริ่มที่ **docs/Water_Fondue_LINE_v3_Guide_TH.docx** หรือ **docs/01_SETUP_TH.md** ทำตามลำดับตั้งแต่ขั้น 1 ใช้ชุดนี้แทน GitHub Pages v2.1 และอย่าเปิด collector สองชุดพร้อมกัน

## Modules
- `water_fondue/`: ดึง ThaiWater, แปลงข้อมูล, freshness, upsert, raw retention, backup, optional capped LINE push
- `worker/public/`: LIFF dashboard, รายงานพร้อมรูปและพิกัด, ติดตามเรื่อง, หน้าผู้ดูแล
- `worker/src/`: API, verify LINE ID token, HMAC webhook, private photo links
- `sql/`: schema, atomic report quotas, webhook deduplication, maintenance checks
- `.github/workflows/`: scheduled collector/cleanup และ offline tests
- `tools/backup_private.py`: สำรองรายงานและรูปไปเครื่องผู้ดูแล
- `docs/LINE_Rich_Menu.png`: ภาพเมนู LINE หนึ่งช่อง

## Test
```sh
python -m unittest discover -s tests -v
node --test worker/tests/*.test.mjs
cd worker
npm ci
npx wrangler deploy --dry-run
```

ค่าเริ่มต้นปิดรับรายงานและ push จนตั้งค่า LINE, ผู้ดูแล และคำชี้แจงข้อมูลครบ เพดานรายงาน 3 ต่อบัญชีต่อวัน / 100 รวมต่อเดือน รูป 100 KiB ต่อเรื่อง ไม่ต้องซื้อโดเมนหรือเปิด Paid plan

ยังไม่ได้ deploy เข้าบัญชีของคุณ ต้องทดสอบ LINE และ Storage จริงตาม checklist ในคู่มือก่อนเปิดให้ประชาชนใช้ ระบบไม่ใช่บริการเตือนภัยฉุกเฉิน และไม่รับรองใช้ฟรีไม่จำกัดหรือไม่มีวันเปลี่ยนโควตา

ดู `VALIDATION.md` สำหรับผลทดสอบและขอบเขตที่ยังต้องตรวจบนระบบจริง
