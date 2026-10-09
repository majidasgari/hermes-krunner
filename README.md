# هرمس در KRunner (Alt+F2)

پلاگین KRunner که اجازه می‌دهد سؤالت را **مستقیم از خود هرمس** بپرسی و جواب را همان‌جا در پنجرهٔ KRunner ببینی.
پلاگین بومی نیست: یک سرویس D-Bus پایتونی است که KRunner خودش با اولین پرسش بالا می‌آوردش (بدون autostart).

```
Alt+F2  →  ? پایتخت استرالیا کجاست؟
```

## نصب

```bash
cd /data/Codes/hermes-krunner
bash install.sh            # یا: bash install.sh --no-restart
```

پیش‌نیاز پایتون (روی این سیستم هست): `python3-dbus`، `python3-gi`، `python3-websockets`.
اسکریپت نصب خودش پایتونی را انتخاب می‌کند که این سه ماژول را داشته باشد (`/usr/bin/python3`).

نصب این‌ها را می‌نویسد:

| مسیر | نقش |
|---|---|
| `~/.local/share/krunner/dbusplugins/hermes-krunner.desktop` | معرفی رانر به KRunner |
| `~/.local/share/dbus-1/services/org.maxv.hermeskrunner.service` | فعال‌سازی خودکار سرویس با اولین پرسش |
| `~/.config/hermes-krunner/config.json` | تنظیمات (اگر نباشد از `config.example.json` ساخته می‌شود) |
| `~/.cache/hermes-krunner/` | کش پاسخ‌ها، لاگ، pid سرویس |

## استفاده

نشانه‌ها (قابل تغییر در کانفیگ): `?`، `؟`، `هرمس`، `hermes`، `آنا`، `ana`، `کتی`، `kattie` — با یا بدون فاصله بعدش.
نشانه لازم است تا KRunner برای هر کوئری دیگری از ما نپرسد.

| کار | نتیجه |
|---|---|
| Enter روی نتیجه | پاسخ در کلیپ‌بورد کپی می‌شود (+ نوتیفیکیشن) |
| اکشن «دوباره بپرس» | همین سؤال از مدل پرسیده می‌شود، کش دور زده می‌شود |
| اکشن «باز کردن برنامه هرمس» | پنجرهٔ اپ هرمس جلو می‌آید |
| اکشن «در گفتگوی تازه بپرس» | یک چت تازه در اپ ساخته می‌شود |
| تایپ دوبارهٔ همان سؤال | پاسخ از کش فوری می‌آید (۰ ثانیه) |

## پرسش چطور به هرمس می‌رسد

1. **اپ دسکتاپ هرمس** (اگر بالا باشد — حالت معمول): سؤال به‌عنوان یک پیام واقعی در چت
   `⚡ پرسش سریع` ثبت می‌شود، همان جا استریم می‌شود، و پاسخ موازی در KRunner برمی‌گردد.
   اگر آن چت از `session_rotate_after_messages` بگذرد، خودکار چت تازه ساخته می‌شود.
2. **اگر اپ پایین باشد**: پلاگین خودش اپ را بالا می‌آورد (background، بدون قفل‌شدن KRunner)
   و همان لحظه سؤال را با موتور خط فرمان (`hermes chat -q --oneshot -Q --source krunner`)
   جواب می‌دهد تا جواب در KRunner گم نشود.
3. اگر هیچ‌کدام نشد، خطا در subtext همان نتیجه نشان داده می‌شود.

KRunner برای هر کوئری جدید یک بار `Match` صدا می‌زند؛ پلاگین تا
`inline_wait_s` (پیش‌فرض ۱۸ ثانیه، سقف D-Bus کرانر ۲۵ ثانیه) پاسخ را نگه می‌دارد تا جواب
همان‌جا ظاهر شود؛ اگر دیر شود، یک نتیجهٔ «در حال پرسیدن…» برمی‌گرداند و جواب از راه
نوتیفیکیشن + کلیپ‌بورد + کش (تایپ بعدی) می‌رسد.

## کانفیگ — `~/.config/hermes-krunner/config.json`

| کلید | پیش‌فرض | معنی |
|---|---|---|
| `triggers` | `["?","؟","hermes","هرمس","ana","آنا","kattie","کتی"]` | نشانه‌های حالت پرسش |
| `session_title` | `⚡ پرسش سریع` | نام چتی که سؤال‌ها در اپ می‌نشینند |
| `engine` | `auto` | `auto` = اپ، در نبودش CLI · `app` = فقط اپ (با انتظار) · `cli` = فقط خط فرمان |
| `launch_app_if_down` | `true` | اپ پایین بود، بالا بیاید |
| `inline_wait_s` | `18` | چند ثانیه پاسخ را در KRunner نگه داریم |
| `answer_timeout_s` | `240` | سقف کل یک پرسش |
| `session_rotate_after_messages` | `60` | بعد از این تعداد پیام، چت تازه |
| `cache_size` | `120` | تعداد پاسخ‌های کش‌شده روی دیسک |
| `inline_answer_chars` | `1500` | چقدر از پاسخ در KRunner دیده شود (کپی همیشه کامل است) |
| `copy_to_clipboard` / `notify` | `true` | کپی/نوتیفای |
| `notify_inline_answers` | `false` | اگر پاسخ همان‌جا در KRunner آمد، باز هم نوتیفیکیشن بدهد؟ |
| `idle_exit_minutes` | `20` | سرویس بعد از این مدت بی‌کاری خودش می‌بندد |
| `cli_extra_args` | `["--oneshot","-Q","--source","krunner"]` | آرگومان‌های موتور CLI |

## دستورها

```bash
P=/usr/bin/python3; S=/data/Codes/hermes-krunner/hermes-krunner.py
$P $S --status                     # وضعیت بک‌اند اپ/پلاگین
$P $S --ask "سلام"                 # پرسش یک‌باره از ترمینال (همان موتور/کش)
$P $S --match "? رنگ آسمان"        # همان چیزی که KRunner می‌بیند (JSON)
$P $S --clear-cache                # پاک کردن کش پاسخ‌ها
$P $S --stop                       # بستن سرویس (برای بارگذاری کد تازه)
```

لاگ: `~/.cache/hermes-krunner/hermes-krunner.log` (کم‌حجم، فقط رویدادهای معنادار).

## تست

```bash
cd /data/Codes/hermes-krunner
/usr/bin/python3 -m unittest discover -s tests        # تست‌های واحد (~۲۰)
/usr/bin/python3 tests/dbus_client.py "? رنگ آسمان"    # همان کاری که KRunner می‌کند
/usr/bin/python3 tests/dbus_client.py --actions --config
HERMES_KRUNNER_LIVE=1 /usr/bin/python3 -m unittest tests.test_unit.TestLiveBackend
```

## عیب‌یابی

| نشانه | کار |
|---|---|
| در KRunner هیچ نتیجه‌ای نیست | `hermes-krunnerEnabled=true` در `~/.config/krunnerrc`، بعد `kquitapp6 krunner` و یک `dbus-send --session --dest=org.kde.krunner / org.freedesktop.DBus.Peer.Ping` |
| `--status` می‌گوید `app_running: false` | اپ هرمس بسته است؛ با اولین پرسش خودش بالا می‌آید یا `hermes desktop` |
| جواب نمی‌آید | `tail ~/.cache/hermes-krunner/hermes-krunner.log` — خط `ask done engine=…` |
| کد را عوض کردم | `$P $S --stop` (سرویس با پرسش بعدی خودش با کد تازه بالا می‌آید) |

## حذف

```bash
bash /data/Codes/hermes-krunner/uninstall.sh
```
