# Playwright — на каком мониторе открывать браузер

По умолчанию Hyperion открывает **все** headed Playwright-окна на **вашем дисплее №1 (правый)**.

## Нумерация (пользовательская)

| № | Значение | Как выбирается |
|---|----------|----------------|
| **1** | правый монитор | rightmost (`max X`) |
| **2** | основной / primary | `Screen.Primary` |
| **3** | верхний | topmost (`min Y`) |

Это **не** имя Windows `\\.\DISPLAY1` — у вас primary часто `DISPLAY1`, а правый — `DISPLAY3`.

## Где задано

| Место | Файл |
|-------|------|
| Код (default) | `scripts/playwright_display.py` → `PLAYWRIGHT_MONITOR=1` |
| Локальный env | `videoshorts.local.env` |
| Шаблоны | `videoshorts.local.env.example`, `videoshorts.env.example` |
| Клиенты | `tiktok_client`, `rutube_client`, `vk_client`, `dzen_client`, `instagram_client` |
| Login | `*_login_save.py` (TikTok / RuTube / VK / Dzen / Instagram) |
| Install | `install-plugin.ps1` дописывает/чинит env при установке |

## Env

```env
PLAYWRIGHT_MONITOR=1
PLAYWRIGHT_MONITOR_LAYOUT=1:right,2:primary,3:top
# optional override:
# PLAYWRIGHT_WINDOW_POSITION=3440,0
# PLAYWRIGHT_WINDOW_SIZE=2560,1440
```

Алиасы: `right` | `left` | `primary` | `top` | `bottom`.

## Смена монитора

В `videoshorts.local.env`:

```env
PLAYWRIGHT_MONITOR=2
```

или временно в PowerShell:

```powershell
$env:PLAYWRIGHT_MONITOR="2"
python scripts/tiktok_client.py --login-only
```
