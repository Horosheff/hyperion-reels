#!/usr/bin/env python3
"""Inject multi-platform publish API + Results UI into Hyperion."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_SERVER = ROOT / "scripts" / "ui_server.py"
RESULTS = ROOT / "ui" / "videoshorts-results.html"

API_BLOCK = r'''
        if path in {
            "/api/publish-vk",
            "/api/publish-rutube",
            "/api/publish-tiktok",
            "/api/publish-platforms",
        }:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                clips_dir = Path(str(payload.get("clips_dir") or "")).expanduser()
                index = payload.get("index")
                draft = bool(payload.get("draft"))
                if not clips_dir.is_dir():
                    json_response(self, {"ok": False, "error": f"clips_dir not found: {clips_dir}"}, status=400)
                    return
                resolved = clips_dir.resolve()
                try:
                    resolved.relative_to(PLUGIN_ROOT.resolve())
                except ValueError:
                    json_response(self, {"ok": False, "error": "clips_dir outside project"}, status=400)
                    return
                try:
                    index = int(index)
                except (TypeError, ValueError):
                    json_response(self, {"ok": False, "error": "index required"}, status=400)
                    return

                script_by_platform = {
                    "zen": "publish_dzen.py",
                    "dzen": "publish_dzen.py",
                    "vk": "publish_vk.py",
                    "rutube": "publish_rutube.py",
                    "tiktok": "publish_tiktok.py",
                }
                log_by_platform = {
                    "zen": "dzen-publish-log.json",
                    "dzen": "dzen-publish-log.json",
                    "vk": "vk-publish-log.json",
                    "rutube": "rutube-publish-log.json",
                    "tiktok": "tiktok-publish-log.json",
                }

                if path == "/api/publish-platforms":
                    raw_platforms = payload.get("platforms") or []
                    if isinstance(raw_platforms, str):
                        raw_platforms = [p.strip() for p in raw_platforms.replace(";", ",").split(",")]
                    platforms = []
                    for p in raw_platforms:
                        key = str(p).strip().lower()
                        if key == "dzen":
                            key = "zen"
                        if key in script_by_platform and key not in platforms:
                            platforms.append(key)
                    platforms = [p for p in platforms if p in {"zen", "vk", "rutube", "tiktok"}]
                else:
                    platforms = [{
                        "/api/publish-vk": "vk",
                        "/api/publish-rutube": "rutube",
                        "/api/publish-tiktok": "tiktok",
                    }[path]]

                if not platforms:
                    json_response(
                        self,
                        {"ok": False, "error": "Нет отмеченных платформ (Дзен / VK / RuTube / TikTok)"},
                        status=400,
                    )
                    return

                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _run_one(platform: str) -> dict:
                    script = SCRIPTS_DIR / script_by_platform[platform]
                    if not script.is_file():
                        return {
                            "platform": platform,
                            "ok": False,
                            "error": f"script missing: {script.name}",
                        }
                    cmd = [
                        sys.executable,
                        str(script),
                        str(resolved),
                        "--index",
                        str(index),
                    ]
                    if draft and platform in {"zen", "tiktok"}:
                        cmd.append("--draft")
                    proc = subprocess.run(
                        cmd,
                        cwd=str(SCRIPTS_DIR),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    log_path = resolved / log_by_platform[platform]
                    log_data = {}
                    if log_path.is_file():
                        try:
                            log_data = json.loads(log_path.read_text(encoding="utf-8-sig"))
                        except Exception:
                            log_data = {}
                    ok = proc.returncode == 0
                    return {
                        "platform": platform,
                        "ok": ok,
                        "returncode": proc.returncode,
                        "log": log_data,
                        "stdout": (proc.stdout or "")[-4000:],
                        "stderr": (proc.stderr or "")[-4000:],
                        "error": None if ok else (proc.stderr or proc.stdout or f"{platform} publish failed"),
                    }

                results_by_platform: dict = {}
                workers = max(1, min(len(platforms), 4))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_run_one, p): p for p in platforms}
                    for fut in as_completed(futures):
                        platform = futures[fut]
                        try:
                            results_by_platform[platform] = fut.result()
                        except Exception as exc:
                            results_by_platform[platform] = {
                                "platform": platform,
                                "ok": False,
                                "error": str(exc),
                            }

                results = [results_by_platform[p] for p in platforms]
                all_ok = all(bool(r.get("ok")) for r in results)

                try:
                    from videoshorts_core import write_latest_results
                    if all_ok:
                        write_latest_results(resolved, status="PASS")
                except Exception:
                    pass

                json_response(
                    self,
                    {
                        "ok": all_ok,
                        "index": index,
                        "draft": draft,
                        "platforms": platforms,
                        "parallel": True,
                        "results": results,
                        "error": None if all_ok else "; ".join(
                            f"{r['platform']}: {r.get('error')}" for r in results if not r.get("ok")
                        ),
                    },
                    status=200 if all_ok else 500,
                )
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
'''

STATUS_BLOCK = r'''
        if path in {"/api/vk-status", "/api/rutube-status", "/api/tiktok-status"}:
            query = parse_qs(parsed.query)
            raw_path = query.get("clips_dir", [""])[0]
            clips_dir = None
            if raw_path:
                clips_dir = Path(raw_path).expanduser()
                if clips_dir.is_dir():
                    try:
                        clips_dir.resolve().relative_to(PLUGIN_ROOT.resolve())
                    except ValueError:
                        json_response(self, {"ok": False, "error": "clips_dir outside project"}, status=400)
                        return
                else:
                    clips_dir = None
            if str(SCRIPTS_DIR) not in sys.path:
                sys.path.insert(0, str(SCRIPTS_DIR))
            try:
                if path == "/api/vk-status":
                    from publish_vk import status_payload as _status
                    json_response(self, _status(clips_dir))
                elif path == "/api/rutube-status":
                    from publish_rutube import status_payload as _status
                    json_response(self, _status(clips_dir))
                else:
                    from publish_tiktok import resolve_config as _tt_cfg
                    cfg = _tt_cfg()
                    json_response(self, {
                        "ok": True,
                        "has_cookies": bool(cfg.get("has_cookies")),
                        "client_ok": bool(cfg.get("client_ok")),
                        "storage": str(cfg.get("storage") or ""),
                        "visibility": cfg.get("visibility") or "Everyone",
                    })
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
'''


def patch_ui_server() -> None:
    text = UI_SERVER.read_text(encoding="utf-8")
    if "publish-platforms" not in text:
        anchor = '                    "error": None if proc.returncode == 0 else (proc.stderr or proc.stdout or "dzen publish failed"),\n                }, status=200 if proc.returncode == 0 else 500)\n            except Exception as exc:\n                json_response(self, {"ok": False, "error": str(exc)}, status=500)\n            return\n        if path == "/api/dependencies":'
        if anchor not in text:
            raise SystemExit("publish-dzen anchor not found")
        text = text.replace(
            anchor,
            '                    "error": None if proc.returncode == 0 else (proc.stderr or proc.stdout or "dzen publish failed"),\n                }, status=200 if proc.returncode == 0 else 500)\n            except Exception as exc:\n                json_response(self, {"ok": False, "error": str(exc)}, status=500)\n            return\n'
            + API_BLOCK
            + '        if path == "/api/dependencies":',
            1,
        )
        print("API publish-platforms inserted")
    if "/api/vk-status" not in text:
        anchor2 = '                json_response(self, status_payload(clips_dir))\n            except Exception as exc:\n                json_response(self, {"ok": False, "error": str(exc)}, status=500)\n            return\n        if path == "/api/media":'
        if anchor2 not in text:
            raise SystemExit("dzen-status anchor not found")
        text = text.replace(
            anchor2,
            '                json_response(self, status_payload(clips_dir))\n            except Exception as exc:\n                json_response(self, {"ok": False, "error": str(exc)}, status=500)\n            return\n'
            + STATUS_BLOCK
            + '        if path == "/api/media":',
            1,
        )
        print("status endpoints inserted")
    UI_SERVER.write_text(text, encoding="utf-8")
    print("patched ui_server.py ok=", "publish-platforms" in text and "vk-status" in text)


def patch_results() -> None:
    text = RESULTS.read_text(encoding="utf-8")
    # platforms checkboxes
    old_platforms = '''              <div class="platforms" data-platforms-for="${esc(idx)}">
                <label><input type="checkbox" value="youtube" checked> YouTube</label>
                <label><input type="checkbox" value="instagram" checked> Instagram</label>
                <label><input type="checkbox" value="tiktok" checked> TikTok</label>
                <label><input type="checkbox" value="telegram"> Telegram</label>
                <label><input type="checkbox" value="vk"> VK</label>
                <label><input type="checkbox" value="zen" checked> Дзен</label>
              </div>'''
    new_platforms = '''              <div class="platforms" data-platforms-for="${esc(idx)}">
                <label><input type="checkbox" value="instagram" checked> Instagram</label>
                <label><input type="checkbox" value="tiktok" checked> TikTok</label>
                <label><input type="checkbox" value="vk" checked> VK</label>
                <label><input type="checkbox" value="rutube" checked> RuTube</label>
                <label><input type="checkbox" value="zen" checked> Дзен</label>
              </div>'''
    if old_platforms in text:
        text = text.replace(old_platforms, new_platforms)
        print("platforms checkboxes updated")
    elif "value=\"rutube\"" in text:
        print("platforms already updated")
    else:
        print("WARN: platforms block not matched")

    old_cover_btn = '''      const published = !!(clip.zen_published || clip.dzen_published || clip.publish_zen_ok);
      const zenBtn = clip.cover_ready
        ? (published
          ? `<div class="publish-ok-badge" data-zen-ok="${esc(idx)}"><span class="dot"></span>Опубликовано в Дзен</div>`
          : `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
            <button type="button" class="btn-blue" data-publish-zen="${esc(idx)}" style="font-size:12px;padding:8px 12px;">Опубликовать в Дзен</button>
            <button type="button" class="btn-dark" data-publish-zen-draft="${esc(idx)}" style="font-size:12px;padding:8px 12px;">Черновик Дзен</button>
          </div>`)
        : "";'''
    new_cover_btn = '''      const flags = [
        clip.zen_published || clip.dzen_published || clip.publish_zen_ok ? "Дзен" : null,
        clip.vk_published || clip.publish_vk_ok ? "VK" : null,
        clip.rutube_published || clip.publish_rutube_ok ? "RuTube" : null,
        clip.tiktok_published || clip.publish_tiktok_ok ? "TikTok" : null,
      ].filter(Boolean);
      let zenBtn = "";
      if (clip.cover_ready) {
        if (flags.length >= 4) {
          zenBtn = `<div class="publish-ok-badge"><span class="dot"></span>Опубликовано · ${esc(flags.join(" + "))}</div>`;
        } else {
          const badges = flags.map((f) => `<div class="publish-ok-badge"><span class="dot"></span>${esc(f)} ✓</div>`).join("");
          zenBtn = `${badges}
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
            <button type="button" class="btn-blue" data-publish-selected="${esc(idx)}" style="font-size:12px;padding:8px 12px;">Опубликовать (по галочкам)</button>
          </div>
          <div style="margin-top:6px;font-size:11px;color:#94a3b8;">Только отмеченные: Дзен / VK / RuTube / TikTok</div>`;
        }
      }'''
    if "data-publish-selected" not in text:
        if old_cover_btn in text:
            text = text.replace(old_cover_btn, new_cover_btn)
            print("cover publish button updated")
        else:
            print("WARN: cover button block not matched")

    # desk text
    text = text.replace(
        "Галочка → обложки (только выбранные) → Дзен через Playwright. Первый вход: «Войти в Дзен».",
        "Галочка клипа → платформы (Дзен / VK / RuTube / TikTok) → обложки → «Опубликовать (по галочкам)» — платформы стартуют параллельно.",
    )
    if 'id="platformsStatusLine"' not in text:
        text = text.replace(
            '<div id="dzenStatusLine" style="margin-top:6px;font-size:12px;color:#94a3b8;"></div>`;',
            '<div id="dzenStatusLine" style="margin-top:6px;font-size:12px;color:#94a3b8;"></div>\n        <div id="platformsStatusLine" style="margin-top:4px;font-size:12px;color:#94a3b8;"></div>`;',
        )

    # wire + publishSelectedFlow injection before refreshDzenStatus if missing
    if "function publishSelectedFlow" not in text:
        marker = "    async function refreshDzenStatus() {"
        inject = r'''
    function selectedPlatformsFor(index) {
      const box = document.querySelector(`[data-platforms-for="${index}"]`);
      if (!box) return [];
      return Array.from(box.querySelectorAll("input:checked"))
        .map((el) => String(el.value || "").toLowerCase())
        .filter((p) => ["zen", "vk", "rutube", "tiktok"].includes(p));
    }
    async function refreshPlatformsStatus() {
      const line = $("platformsStatusLine");
      if (!line || !isLocalBridge()) return;
      const q = clipsDir ? `?clips_dir=${encodeURIComponent(clipsDir)}` : "";
      const parts = [];
      for (const [name, api] of [
        ["VK", "/api/vk-status"],
        ["RuTube", "/api/rutube-status"],
        ["TikTok", "/api/tiktok-status"],
      ]) {
        try {
          const response = await fetch(`${api}${q}`);
          const data = await response.json();
          parts.push(`${name}: ${data.has_cookies ? "cookies OK" : "нет cookies"}`);
        } catch (e) {
          parts.push(`${name}: ${e.message}`);
        }
      }
      line.textContent = parts.join(" · ");
    }
    async function publishSelectedFlow(index) {
      const statusEl = $("publishStatus");
      if (!isLocalBridge() || !clipsDir) return;
      const platforms = selectedPlatformsFor(index);
      if (!platforms.length) {
        if (statusEl) statusEl.textContent = "Отметьте хотя бы одну платформу: Дзен / VK / RuTube / TikTok.";
        return;
      }
      const clipLabel = `clip_${String(index).padStart(2, "0")}`;
      openCoverWait(1, {
        title: `Публикую ${clipLabel}`,
        sub: platforms.map((p) => p.toUpperCase()).join(" + "),
        hint: "Параллельно: все отмеченные платформы сразу",
        hints: ["Playwright параллельно…", "Обложки и описания…", "Ждём Publish на всех…"],
        skipCoverPoll: true,
      });
      if (statusEl) statusEl.textContent = `${clipLabel} → параллельно: ${platforms.join(", ")}…`;
      try {
        const response = await fetch("/api/publish-platforms", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clips_dir: clipsDir, index, platforms, draft: false }),
        });
        const data = await response.json();
        const results = Array.isArray(data.results) ? data.results : [];
        const okList = results.filter((r) => r.ok).map((r) => r.platform);
        const failList = results.filter((r) => !r.ok).map((r) => `${r.platform}: ${r.error || "fail"}`);
        if (data.ok || okList.length) {
          showPublishSuccess(
            okList.length ? `${clipLabel}: ${okList.join(", ")}` : `${clipLabel} частично`,
            {
              title: data.ok ? "Опубликовано" : "Частичный успех",
              hint: failList.length ? failList.join(" · ") : "✓ можно работать дальше",
              holdMs: 2600,
            }
          );
          if (latestData && Array.isArray(latestData.clips)) {
            const clip = latestData.clips.find((c) => Number(c.index) === Number(index));
            if (clip) {
              if (okList.includes("zen")) { clip.zen_published = true; clip.dzen_published = true; clip.publish_zen_ok = true; }
              if (okList.includes("vk")) { clip.vk_published = true; clip.publish_vk_ok = true; }
              if (okList.includes("rutube")) { clip.rutube_published = true; clip.publish_rutube_ok = true; }
              if (okList.includes("tiktok")) { clip.tiktok_published = true; clip.publish_tiktok_ok = true; }
            }
            try { render(latestData); } catch (_) {}
          }
          if (statusEl) {
            statusEl.innerHTML = data.ok
              ? `<span class="publish-ok-badge"><span class="dot"></span>${esc(clipLabel)} · ${esc(okList.join(" + "))}</span>`
              : `Частично: OK ${esc(okList.join(", ") || "—")}; ошибки: ${esc(failList.join("; ") || data.error || "")}`;
          }
        } else {
          closeCoverWait();
          if (statusEl) statusEl.innerHTML = `Ошибка публикации: ${esc(data.error || "failed")}`;
        }
        try { await loadLatestResults(); await refreshDzenStatus(); await refreshPlatformsStatus(); } catch (_) {}
        if (data.ok || okList.length) setTimeout(() => closeCoverWait(), 2600);
        else closeCoverWait();
      } catch (error) {
        closeCoverWait();
        if (statusEl) statusEl.textContent = `Публикация: ${error.message}`;
      }
    }
''' + marker
        if marker in text:
            text = text.replace(marker, inject, 1)
            print("publishSelectedFlow injected")
        else:
            print("WARN: refreshDzenStatus marker missing")

    # wire selected button
    if "data-publish-selected" in text and "publishSelectedFlow(Number" not in text.split("function wirePublishUi")[1][:1200]:
        text = text.replace(
            '''      const dzenLogin = $("dzenLoginBtn");
      if (dzenLogin) dzenLogin.onclick = dzenLoginFlow;
      document.querySelectorAll("[data-publish-zen]").forEach((btn) => {
        btn.onclick = () => publishDzenFlow(Number(btn.getAttribute("data-publish-zen")), false);
      });
      document.querySelectorAll("[data-publish-zen-draft]").forEach((btn) => {
        btn.onclick = () => publishDzenFlow(Number(btn.getAttribute("data-publish-zen-draft")), true);
      });
    }''',
            '''      const dzenLogin = $("dzenLoginBtn");
      if (dzenLogin) dzenLogin.onclick = dzenLoginFlow;
      document.querySelectorAll("[data-publish-selected]").forEach((btn) => {
        btn.onclick = () => publishSelectedFlow(Number(btn.getAttribute("data-publish-selected")));
      });
    }''',
        )
        print("wirePublishUi updated")

    text = text.replace(
        "      wirePublishUi();\n      refreshDzenStatus();\n    }",
        "      wirePublishUi();\n      refreshDzenStatus();\n      if (typeof refreshPlatformsStatus === 'function') refreshPlatformsStatus();\n    }",
    )

    RESULTS.write_text(text, encoding="utf-8")
    print("patched results.html")


if __name__ == "__main__":
    patch_ui_server()
    patch_results()
    print("OK")
