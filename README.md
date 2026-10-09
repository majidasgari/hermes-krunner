# هرمس در KRunner (Alt+F2)

سؤالت را **مستقیم از خود هرمس** بپرس و جواب را همان‌جا در پنجرهٔ KRunner ببین؛ با اینتر، مستقیم
داخل هرمس می‌روی.
پلاگین بومی نیست: یک سرویس D-Bus پایتونی است که KRunner خودش با اولین پرسش بالا می‌آوردش (بدون autostart).

```
Alt+F2  →  پایتخت استرالیا کجاست؟        ← جواب همان‌جا می‌آید
Alt+F2  →  ? رنگ آسمان چیست            ← نشانه‌دار
Alt+F2  →  قوانین سه‌گانه رباتیک         ← اینتر: پرسیدن و رفتن داخل هرمس
```

## قاعدهٔ اصلی: حین تایپ هیچ درخواستی به مدل نمی‌رود

سؤال فقط وقتی فرستاده می‌شود که **خودت علامت بدهی**:

| علامت | رفتار |
|---|---|
| **Enter** روی ردیف «از هرمس بپرس: …» | سؤال ثبت می‌شود و پنجرهٔ هرمس جلو می‌آید |
| **علامت سؤال** در متن (`?` یا `؟` هر جا) | بعد از تمام‌شدن تایپ، خودش می‌پرسد و جواب را در KRunner نشان می‌دهد |
| **نشانهٔ پرسش** (`?`، `هرمس`، `hermes`، `کتی`، `آنا` …) | همان بالا |

هیچ درخواستی برای پیشوندهای تایپ‌شده فرستاده نمی‌شود: اگر «شماره کارت من چی بود» را بنویسی و بعد
«؟» را بزنی، فقط یک پرسش (متن کامل) می‌رود. برای متن‌های بدون علامت هم یک ردیف پیشنهاد نشان داده
می‌شود که تا اینتر نزنی هیچ هزینه‌ای ندارد.

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

| کار | نتیجه |
|---|---|
| Enter روی نتیجه | پنجرهٔ اپ هرمس جلو می‌آید و سؤال به‌عنوان پیام در چت `⚡ پرسش سریع` می‌نشیند |
| Enter روی ردیف پیشنهاد (متن بدون علامت) | اول می‌پرسد، بعد پنجرهٔ هرمس را جلو می‌آورد |
| اکشن «دوباره بپرس» | همین سؤال با دور زدن کش از مدل پرسیده می‌شود |
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

KRunner برای هر کوئری جدید یک بار `Match` صدا می‌زند؛ پلاگین تا `inline_wait_s` (پیش‌فرض ۱۸
ثانیه، سقف D-Bus کرانر ۲۵ ثانیه) پاسخ را نگه می‌دارد تا جواب همان‌جا ظاهر شود؛ اگر دیر شود، یک
نتیجهٔ «در حال پرسیدن…» برمی‌گرداند و جواب از راه نوتیفیکیشن و کش (تایپ بعدی) می‌رسد.
پاسخ‌های خطا (مثل «No reply / cancelled») هرگز به‌عنوان پاسخ کش یا نوتیفای نمی‌شوند.

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
| `inline_answer_chars` | `1500` | چقدر از پاسخ در KRunner دیده شود |
| `auto_ask` | `true` | اگر `false` شود، هیچ‌وقت خودش نمی‌پرسد (فقط Enter) |
| `auto_ask_on_question_mark` | `true` | علامت سؤال در متن یعنی همین حالا بپرس |
| `debounce_ms` | `700` | تا این مدت تایپ ثابت بماند، پرسشی فرستاده نمی‌شود |
| `min_question_chars` | `3` | کوتاه‌تر از این، پرسش حساب نمی‌شود |
| `suggest_untriggered` | `true` | برای متن ساده ردیف «از هرمس بپرس» نشان داده شود |
| `min_suggest_chars` | `3` | حداقل طول متن برای پیشنهاد |
| `suggest_relevance` / `suggest_category_relevance` | `0.5` / `50` | میزان بالا آمدن ردیف پیشنهاد در فهرست |
| `show_hint_when_empty` | `true` | وقتی فقط نشانه تایپ شده، راهنما نشان داده شود |
| `notify` / `notify_inline_answers` | `true` / `false` | نوتیفیکیشن پاسخ؛ و آیا وقتی پاسخ در KRunner آمد هم بدهد |
| `app_window_class` | `["com.nousresearch.hermes"]` | کلاس پنجرهٔ اپ برای جلو آوردنش |
| `idle_exit_minutes` | `20` | سرویس بعد از این مدت بی‌کاری خودش می‌بندد |
| `cli_extra_args` | `["--oneshot","-Q","--source","krunner"]` | آرگومان‌های موتور CLI |

### جلو آوردن پنجرهٔ اپ

`focus_app` یک اسکریپت کوچک KWin را از راه D-Bus بارگذاری و اجرا می‌کند که پنجرهٔ اپ را
raise و فعال می‌کند (روش قبلی — اجرای دوبارهٔ اپ برای گرفتن قفل single-instance — پنجره را
واقعاً جلو نمی‌آورد). اگر کلاس پنجره‌ات فرق دارد، `app_window_class` را عوض کن.

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
/usr/bin/python3 -m unittest discover -s tests        # تست‌های واحد (۳۱ تست)
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
| پنجرهٔ اپ جلو نمی‌آید | `app_window_class` را با کلاس واقعی پنجره عوض کن (اسکریپت KWin در `~/.cache/hermes-krunner/focus-window.js`) |
| کد را عوض کردم | `$P $S --stop` (سرویس با پرسش بعدی خودش با کد تازه بالا می‌آید) |

## حذف

```bash
bash /data/Codes/hermes-krunner/uninstall.sh
```
