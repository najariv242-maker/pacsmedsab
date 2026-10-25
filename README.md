# ربات تلگرام جامع مدال پکس (Medal PACS v13.1) + Keep-Alive

این مخزن شامل **نسخه نهایی و دیباگ‌شده** افزونه مرورگر (`medal_pacs_v13.user.js`) و **ربات تلگرام چند بیمارستانی** (`bot.py`) برای استقرار روی **Render.com** به همراه **GitHub Actions Keep-Alive (پینگ هر ۵ دقیقه)** است.

## بیمارستان‌های تحت پوشش (لاگین خودکار `doc` / `doc`)
1. **بیمارستان حشمتیه (`hh-pacs.medsab.ac.ir`)**
2. **بیمارستان واسطی (`vh-pacs.medsab.ac.ir`)**
3. **بیمارستان امداد شهید بهشتی (`sbh-pacs.medsab.ac.ir`)**

---

## فایل‌های موجود در این پکیج گیت‌هاب
- `bot.py`: کد کامل ربات تلگرام + موتور فونتیک فارسی به فینگلیش + رندر ویدیو Cine با HUD پزشکی + تولید دایکام (`.dcm`) و عکس (`.jpg`) + وب‌سرور `/health` مخصوص Render.
- `medal_pacs_v13.user.js`: نسخه ۱۳.۱ دیباگ‌شده افزونه Tampermonkey برای مرورگر (شامل لاگین خودکار رفع‌باگ‌شده، اتصال دقیق به فیلدهای Dojo در `Default.aspx`، جستجوی تمام تاریخ‌ها با دکمه `All` و باز کردن مستقیم ویوئر از لینک‌های تلگرام).
- `requirements.txt`: کتابخانه‌های پایتون مورد نیاز روی Render.
- `render.yaml`: فایل تنظیمات خودکار Render.
- `.github/workflows/keep-alive.yml`: اکشن گیت‌هاب که هر ۵ دقیقه آدرس `/health` ربات را پینگ می‌کند تا همیشه بیدار بماند.

---

## راهنمای راه‌اندازی در ۳ دقیقه (GitHub + Render)

### گام ۱: آپلود در گیت‌هاب
تمام فایل‌های این پوشه (`bot.py`, `requirements.txt`, `render.yaml`, `medal_pacs_v13.user.js`, `.github/workflows/keep-alive.yml`) را در یک Repository در GitHub آپلود کنید.

### گام ۲: اتصال به Render.com
1. وارد سایت **Render.com** شوید و یک **New Web Service** بسازید و آن را به مخزن گیت‌هاب خود وصل کنید.
2. در بخش **Environment Variables** متغیرهای زیر را اضافه کنید:
   - `BOT_TOKEN`: توکن ربات تلگرام شما (از `@BotFather`)
   - `PACS_USERNAME`: `doc`
   - `PACS_PASSWORD`: `doc`
3. پس از استقرار، آدرس سرویس رندر شما (مثلاً `https://medal-pacs-telegram-bot.onrender.com`) آماده می‌شود.

### گام ۳: فعال‌سازی Keep-Alive هر ۵ دقیقه در GitHub
1. در مخزن گیت‌هاب خود وارد **Settings -> Secrets and variables -> Actions** شوید.
2. یک **New repository secret** با نام `RENDER_EXTERNAL_URL` بسازید و آدرس سرویس رندر خود را در آن قرار دهید.
3. از تب **Actions** ورکفلو `Keep Render Bot Awake` را فعال کنید تا هر ۵ دقیقه `/health` را پینگ کند.
