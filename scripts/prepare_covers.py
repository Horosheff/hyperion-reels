#!/usr/bin/env python3
"""Подготовка обложек для выбранных клипов (ffmpeg кадр и/или Kie GPT Image 2 9:16)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kie_client import KieApiError, KieClient, load_api_key
from publish_selection import load_selection
from videoshorts_core import configure_stdio, find_ffmpeg

configure_stdio()

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRAND_DIR = PLUGIN_ROOT / "videoshorts-memory" / "brand" / "covers"
STYLE_NOTES = (
    "High-energy vertical Shorts/Reels thumbnail 9:16. "
    "Bold hook text readable on mobile. Dark dramatic background. "
    "Floating UI accents, arrows, icons allowed. "
    "Keep face identity from avatar: round black glasses, ash-blonde textured hair, short beard. "
    "Clothes, pose, expression MAY change to match the hook. "
    "Do NOT copy unrelated product logos from style refs unless they fit the topic. "
    "Text language: Russian for the hook."
)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clip_mp4(clips_dir: Path, index: int) -> Path | None:
    final = clips_dir / f"clip_{index:02d}.mp4"
    cropped = clips_dir / f"clip_{index:02d}_cropped.mp4"
    if final.is_file():
        return final
    if cropped.is_file():
        return cropped
    return None


def _load_metadata(clips_dir: Path, index: int, meta_by_index: dict) -> dict:
    meta = dict(meta_by_index.get(index) or {})
    path = clips_dir / "metadata" / f"clip_{index:02d}.metadata.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = {**meta, **raw}
        except Exception:
            pass
    return meta


def _hook_text(meta: dict, fallback_title: str | None = None) -> str:
    for key in ("cover_text", "hook", "title"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if len(text) > 72:
                text = text[:69].rstrip() + "…"
            return text
    title = (fallback_title or "").strip()
    return title[:72] if title else "Смотри до конца"


def extract_cover(video: Path, output: Path, *, at_sec: float = 1.0) -> bool:
    ffmpeg = find_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-ss", str(max(0.0, at_sec)),
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and output.is_file() and output.stat().st_size > 0


def resolve_brand(brand_dir: Path) -> tuple[Path | None, list[Path]]:
    avatar = brand_dir / "avatar.png"
    if not avatar.is_file():
        for alt in brand_dir.glob("avatar.*"):
            avatar = alt
            break
    refs_dir = brand_dir / "refs"
    refs = sorted(refs_dir.glob("ref-*.png")) if refs_dir.is_dir() else []
    if not refs and refs_dir.is_dir():
        refs = sorted(p for p in refs_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    return (avatar if avatar.is_file() else None), refs


def build_cover_prompt(*, hook: str, title: str, style_name: str, index: int) -> str:
    pose_cycle = [
        "confident pointing at the hook text",
        "shocked hands near mouth reaction",
        "both hands pointing up toward the headline",
        "friendly smile pointing at viewer",
        "serious expert explaining with open hand",
    ]
    outfit_cycle = [
        "black t-shirt",
        "red t-shirt",
        "black hoodie",
        "white shirt under dark blazer",
        "smart casual navy polo",
    ]
    pose = pose_cycle[(index - 1) % len(pose_cycle)]
    outfit = outfit_cycle[(index - 1) % len(outfit_cycle)]
    return (
        f"{STYLE_NOTES}\n"
        f"Style reference mood: {style_name} (layout/energy/colors only).\n"
        f"Subject: same man as avatar reference, {outfit}, pose: {pose}.\n"
        f"Main hook text on cover (exact, bold, short): «{hook}».\n"
        f"Optional small supporting line: «{title[:48]}».\n"
        "Composition: person in lower-middle, huge hook in upper third, high contrast, "
        "no watermark, no platform UI chrome."
    )


def ensure_cdn_urls(client: KieClient, brand_dir: Path, avatar: Path | None, refs: list[Path]) -> dict:
    """Prefer remote brand-urls.json (HTTPS). Fallback: upload local avatar/refs to Kie CDN."""
    remote = _read_json(brand_dir / "brand-urls.json")
    avatar_url = remote.get("avatar_url") if isinstance(remote.get("avatar_url"), str) else None
    remote_refs = remote.get("refs") if isinstance(remote.get("refs"), list) else []
    if avatar_url and avatar_url.startswith("http") and remote_refs:
        refs_out = []
        for item in remote_refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url.startswith("http"):
                refs_out.append({"name": str(item.get("name") or "ref"), "url": url})
        if refs_out:
            print(f"   brand-urls.json → avatar + {len(refs_out)} refs (HTTPS, no upload)")
            return {"avatar_url": avatar_url, "refs": refs_out, "source": "brand-urls.json"}

    if avatar is None:
        raise KieApiError("Нет avatar.png и нет brand-urls.json с avatar_url")

    cache_path = brand_dir / "cdn-cache.json"
    cache = _read_json(cache_path)
    files = cache.setdefault("files", {})
    changed = False

    def cached_url(path: Path) -> str:
        nonlocal changed
        key = str(path.resolve())
        entry = files.get(key) if isinstance(files.get(key), dict) else {}
        mtime = path.stat().st_mtime
        size = path.stat().st_size
        if (
            entry.get("url")
            and entry.get("mtime") == mtime
            and entry.get("size") == size
            and str(entry.get("url")).startswith("http")
        ):
            return str(entry["url"])
        print(f"   upload → {path.name}")
        url = client.upload_file(path, upload_path="videoshorts/covers")
        files[key] = {"url": url, "mtime": mtime, "size": size, "name": path.name}
        changed = True
        return url

    avatar_url = cached_url(avatar)
    ref_urls = [{"name": r.name, "url": cached_url(r)} for r in refs]
    if changed:
        cache["updated_at"] = datetime.now(timezone.utc).isoformat()
        cache["files"] = files
        _write_json(cache_path, cache)
    return {"avatar_url": avatar_url, "refs": ref_urls, "source": "local-upload"}


def generate_ai_cover(
    client: KieClient,
    *,
    prompt: str,
    avatar_url: str,
    ref_url: str | None,
    output: Path,
    resolution: str = "1K",
) -> tuple[bool, str | None, str | None]:
    input_urls = [avatar_url]
    if ref_url:
        input_urls.append(ref_url)
    try:
        task_id, urls = client.generate_image_i2i(
            prompt, input_urls, aspect_ratio="9:16", resolution=resolution
        )
        if not urls:
            return False, task_id, "empty_result_urls"
        client.download(urls[0], output)
        ok = output.is_file() and output.stat().st_size > 0
        return ok, task_id, None if ok else "download_empty"
    except KieApiError as exc:
        return False, None, str(exc)


def _write_progress(clips_dir: Path, payload: dict) -> None:
    path = clips_dir / "covers-progress.json"
    payload = {
        **payload,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: prepare covers for selected clips")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("--at-sec", type=float, default=1.2, help="Секунда кадра для ffmpeg-fallback")
    parser.add_argument(
        "--mode",
        choices=["auto", "kie", "ffmpeg"],
        default="auto",
        help="auto=Kie если есть ключ+avatar, иначе ffmpeg",
    )
    parser.add_argument("--brand-dir", type=Path, default=DEFAULT_BRAND_DIR)
    parser.add_argument("--resolution", default="1K", choices=["1K", "2K", "4K"])
    parser.add_argument("--skip-existing", action="store_true", help="Не перегенерировать уже готовые cover.jpg")
    args = parser.parse_args()

    clips_dir = args.clips_dir
    if not clips_dir.is_dir():
        print(f"[ERROR] clips_dir not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    selection = load_selection(clips_dir)
    selected = selection.get("selected") or []
    if not selected:
        print("[ERROR] Нет выбранных клипов. Сохраните publish-selection.json", file=sys.stderr)
        sys.exit(2)

    metadata_manifest = _read_json(clips_dir / "metadata-manifest.json")
    meta_by_index = {
        int(item["index"]): item
        for item in metadata_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    }

    brand_dir = args.brand_dir
    avatar, refs = resolve_brand(brand_dir)
    remote_brand = _read_json(brand_dir / "brand-urls.json")
    has_remote_avatar = isinstance(remote_brand.get("avatar_url"), str) and str(remote_brand["avatar_url"]).startswith("http")
    api_key = load_api_key(PLUGIN_ROOT)
    use_kie = args.mode == "kie" or (args.mode == "auto" and bool(api_key) and (avatar is not None or has_remote_avatar))
    if args.mode == "kie" and (not api_key or (avatar is None and not has_remote_avatar)):
        print("[ERROR] --mode kie требует KIE_API_KEY и avatar (файл или brand-urls.json)", file=sys.stderr)
        sys.exit(3)

    client: KieClient | None = None
    cdn: dict = {}
    if use_kie:
        assert api_key
        client = KieClient(api_key)
        print(f"🎨 AI covers (Kie gpt-image-2 i2i 9:16), local_refs={len(refs)}")
        cdn = ensure_cdn_urls(client, brand_dir, avatar, refs)

    covers_dir = clips_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    ok = 0
    total = len(selected)
    _write_progress(clips_dir, {
        "status": "running",
        "phase": "start",
        "message": "Готовлю генерацию обложек…",
        "current": 0,
        "total": total,
        "index": None,
        "hook": None,
        "pct": 0,
    })
    for pos, item in enumerate(selected, start=1):
        index = int(item["index"])
        video = _clip_mp4(clips_dir, index)
        meta = _load_metadata(clips_dir, index, meta_by_index)
        title = str(meta.get("title") or item.get("title") or f"clip_{index:02d}")
        hook = _hook_text(meta, title)
        cover_path = covers_dir / f"clip_{index:02d}_cover.jpg"
        prompt_path = covers_dir / f"clip_{index:02d}_cover.prompt.txt"

        ref = None
        style_name = "generic-viral"
        cdn_refs = cdn.get("refs") if isinstance(cdn.get("refs"), list) else []
        if cdn_refs:
            ref = cdn_refs[(index - 1) % len(cdn_refs)]
            style_name = str((ref or {}).get("name") or style_name)
        elif refs:
            ref_path = refs[(index - 1) % len(refs)]
            style_name = ref_path.stem

        prompt = build_cover_prompt(hook=hook, title=title, style_name=style_name, index=index)
        prompt_path.write_text(prompt, encoding="utf-8")

        entry: dict = {
            "index": index,
            "ok": False,
            "video": video.name if video else None,
            "cover_file": None,
            "cover_path": None,
            "cover_text": hook,
            "cover_prompt": prompt,
            "platforms": item.get("platforms") or ["youtube", "instagram", "tiktok"],
            "title": title,
            "mode": "kie" if use_kie else "ffmpeg",
            "style_ref": style_name if use_kie else None,
        }

        if args.skip_existing and cover_path.is_file() and cover_path.stat().st_size > 0:
            ok += 1
            entry["ok"] = True
            entry["mode"] = "skipped_existing"
            entry["cover_file"] = cover_path.name
            entry["cover_path"] = str(cover_path.resolve())
            entries.append(entry)
            _write_progress(clips_dir, {
                "status": "running",
                "phase": "skip",
                "message": f"Уже есть · clip_{index:02d}",
                "current": pos,
                "total": total,
                "index": index,
                "hook": hook,
                "pct": int(100 * pos / max(1, total)),
                "cover_path": str(cover_path.resolve()),
            })
            print(f"   clip_{index:02d}: SKIP existing «{hook}»")
            continue

        _write_progress(clips_dir, {
            "status": "running",
            "phase": "generating",
            "message": f"Kie рисует обложку {pos}/{total}…",
            "current": pos,
            "total": total,
            "index": index,
            "hook": hook,
            "pct": int(100 * (pos - 0.35) / max(1, total)),
        })

        success = False
        error = None
        task_id = None
        if use_kie and client is not None:
            success, task_id, error = generate_ai_cover(
                client,
                prompt=prompt,
                avatar_url=str(cdn["avatar_url"]),
                ref_url=(ref or {}).get("url") if isinstance(ref, dict) else None,
                output=cover_path,
                resolution=args.resolution,
            )
            entry["kie_task_id"] = task_id
            if not success and video:
                print(f"   [WARN] clip_{index:02d} Kie fail → ffmpeg fallback ({error})")
                success = extract_cover(video, cover_path, at_sec=args.at_sec)
                entry["mode"] = "ffmpeg_fallback"
                entry["error"] = error
        elif video:
            success = extract_cover(video, cover_path, at_sec=args.at_sec)
        else:
            error = "video_missing"

        if success:
            ok += 1
            entry["ok"] = True
            entry["cover_file"] = cover_path.name
            entry["cover_path"] = str(cover_path.resolve())
            _write_progress(clips_dir, {
                "status": "running",
                "phase": "done_clip",
                "message": f"Готово · clip_{index:02d}",
                "current": pos,
                "total": total,
                "index": index,
                "hook": hook,
                "pct": int(100 * pos / max(1, total)),
                "cover_path": str(cover_path.resolve()),
            })
        else:
            entry["error"] = error or entry.get("error") or "generate_failed"
            _write_progress(clips_dir, {
                "status": "running",
                "phase": "error_clip",
                "message": f"Ошибка · clip_{index:02d}",
                "current": pos,
                "total": total,
                "index": index,
                "hook": hook,
                "pct": int(100 * pos / max(1, total)),
                "error": entry["error"],
            })
        entries.append(entry)
        status = "OK" if success else "FAIL"
        print(f"   clip_{index:02d}: {status} [{entry['mode']}] «{hook}»")

    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips_dir": str(clips_dir.resolve()),
        "status": "COVERS_READY" if ok == len(selected) else ("PARTIAL" if ok else "FAIL"),
        "selected_count": len(selected),
        "ready_count": ok,
        "covers_dir": str(covers_dir.resolve()),
        "brand_dir": str(brand_dir.resolve()),
        "generator": "kie-gpt-image-2-i2i" if use_kie else "ffmpeg-frame",
        "aspect_ratio": "9:16",
        "covers": entries,
        "next_step": "prepare_publish_queue" if ok else "fix_covers",
        "note": (
            "AI-обложки Kie 9:16 (avatar + style refs + hook). "
            if use_kie
            else "Кадр извлечён ffmpeg. Для AI: avatar + KIE_API_KEY."
        ),
    }
    manifest_path = clips_dir / "covers-manifest.json"
    _write_json(manifest_path, manifest)
    _write_progress(clips_dir, {
        "status": "done" if ok else "fail",
        "phase": "finished",
        "message": f"Обложки готовы: {ok}/{len(selected)}" if ok else "Не удалось создать обложки",
        "current": len(selected),
        "total": len(selected),
        "index": None,
        "hook": None,
        "pct": 100 if ok else int(100 * ok / max(1, len(selected))),
        "ready_count": ok,
        "manifest_path": str(manifest_path.resolve()),
    })
    print(f"✅ Covers: {ok}/{len(selected)} → {covers_dir}")
    print(f"   Manifest: {manifest_path}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
