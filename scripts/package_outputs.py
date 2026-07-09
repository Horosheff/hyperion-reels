#!/usr/bin/env python3
"""
VideoShorts — упаковка финальных артефактов для публикации.
Копирует sidecar ASS/SRT рядом с MP4 (ручная загрузка субтитров в YouTube Studio / Reels).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path

from videoshorts_core import configure_stdio, write_latest_results

configure_stdio()


def main() -> None:
    parser = argparse.ArgumentParser(description="VideoShorts: package clips + subtitle sidecars")
    parser.add_argument("clips_dir", type=Path)
    parser.add_argument("-o", "--publish-dir", type=Path, default=None)
    args = parser.parse_args()

    src = args.clips_dir
    if not src.is_dir():
        print(f"[ERROR] {src}", file=sys.stderr)
        sys.exit(1)

    publish = args.publish_dir or (src.parent / f"{src.name}-publish")
    publish.mkdir(parents=True, exist_ok=True)

    manifest_src = src / "manifest.json"
    manifest = json.loads(manifest_src.read_text(encoding="utf-8")) if manifest_src.is_file() else {"clips": []}
    sub_manifest_path = src / "subtitles-manifest.json"
    sub_manifest = json.loads(sub_manifest_path.read_text(encoding="utf-8")) if sub_manifest_path.is_file() else {}
    metadata_manifest_path = src / "metadata-manifest.json"
    metadata_manifest = json.loads(metadata_manifest_path.read_text(encoding="utf-8")) if metadata_manifest_path.is_file() else {}
    metadata_by_index = {
        str(item.get("index")): item
        for item in metadata_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(metadata_manifest, dict) else {}
    memory_root = Path(__file__).resolve().parents[1] / "videoshorts-memory"
    scores_path = memory_root / "moments" / "clip-scores.json"
    audio_metrics_path = src / "audio-metrics.json"
    safe_zone_path = src / "safe-zone-report.json"
    audio_qa_path = src / "audio-qa-report.json"
    retry_path = src / "retry-plan.json"
    candidate_path = memory_root / "moments" / "candidate-moments.json"
    editor_path = memory_root / "moments" / "editor-review.json"
    virality_path = memory_root / "moments" / "virality-review.json"
    dramaturgy_path = memory_root / "moments" / "dramaturgy-report.json"
    montage_path = memory_root / "moments" / "montage-plan.json"
    post_render_path = src / "post-render-review.json"
    scores_manifest = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.is_file() else {"clips": []}
    candidates_manifest = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.is_file() else {"candidates": []}
    editor_manifest = json.loads(editor_path.read_text(encoding="utf-8")) if editor_path.is_file() else {"clips": []}
    virality_manifest = json.loads(virality_path.read_text(encoding="utf-8")) if virality_path.is_file() else {"clips": []}
    dramaturgy_manifest = json.loads(dramaturgy_path.read_text(encoding="utf-8")) if dramaturgy_path.is_file() else {"clips": []}
    montage_manifest = json.loads(montage_path.read_text(encoding="utf-8")) if montage_path.is_file() else {"clips": []}
    post_render_manifest = json.loads(post_render_path.read_text(encoding="utf-8")) if post_render_path.is_file() else {"clips": []}
    audio_metrics = json.loads(audio_metrics_path.read_text(encoding="utf-8")) if audio_metrics_path.is_file() else {"clips": []}
    safe_zone = json.loads(safe_zone_path.read_text(encoding="utf-8")) if safe_zone_path.is_file() else {"clips": []}
    audio_qa = json.loads(audio_qa_path.read_text(encoding="utf-8")) if audio_qa_path.is_file() else {"clips": []}
    retry_plan = json.loads(retry_path.read_text(encoding="utf-8")) if retry_path.is_file() else {"failed_clips": []}
    scores_by_index = {
        str(item.get("index")): item
        for item in scores_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(scores_manifest, dict) else {}
    candidates_by_id = {
        str(item.get("candidate_id")): item
        for item in candidates_manifest.get("candidates", [])
        if isinstance(item, dict) and item.get("candidate_id")
    } if isinstance(candidates_manifest, dict) else {}
    editor_by_index = {
        str(item.get("index")): item
        for item in editor_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(editor_manifest, dict) else {}
    virality_by_index = {
        str(item.get("index")): item
        for item in virality_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(virality_manifest, dict) else {}
    dramaturgy_by_index = {
        str(item.get("index")): item
        for item in dramaturgy_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(dramaturgy_manifest, dict) else {}
    montage_by_index = {
        str(item.get("index")): item
        for item in montage_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(montage_manifest, dict) else {}
    post_render_by_index = {
        str(item.get("index")): item
        for item in post_render_manifest.get("clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(post_render_manifest, dict) else {}
    audio_by_file = {
        str(item.get("file")): item
        for item in audio_metrics.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(audio_metrics, dict) else {}
    safe_zone_by_file = {
        str(item.get("file")): item
        for item in safe_zone.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(safe_zone, dict) else {}
    audio_qa_by_file = {
        str(item.get("file")): item
        for item in audio_qa.get("clips", [])
        if isinstance(item, dict) and item.get("file")
    } if isinstance(audio_qa, dict) else {}
    retry_by_index = {
        str(item.get("index")): item
        for item in retry_plan.get("failed_clips", [])
        if isinstance(item, dict) and item.get("index") is not None
    } if isinstance(retry_plan, dict) else {}

    packaged = []
    for clip in manifest.get("clips", []):
        final_name = str(clip.get("final_file") or "")
        cropped_name = str(clip.get("cropped_file") or clip.get("file") or "")
        fname = final_name if final_name and (src / final_name).is_file() else cropped_name
        mp4 = src / fname
        if not mp4.is_file():
            continue
        dest_mp4 = publish / fname
        shutil.copy2(mp4, dest_mp4)
        entry = {
            "file": fname,
            "source_file": cropped_name,
            "burned": fname == final_name and fname != cropped_name,
            "start": clip.get("start"),
            "end": clip.get("end"),
        }

        idx = cropped_name.replace("clip_", "").replace("_cropped.mp4", "").replace(".mp4", "")
        normalized_idx = str(int(idx)) if idx.isdigit() else idx
        entry["scores"] = scores_by_index.get(normalized_idx)
        editor_item = editor_by_index.get(normalized_idx)
        entry["editor_review"] = editor_item
        entry["candidate"] = candidates_by_id.get(str(editor_item.get("candidate_id"))) if editor_item else None
        entry["virality_review"] = virality_by_index.get(normalized_idx)
        entry["dramaturgy"] = dramaturgy_by_index.get(normalized_idx)
        entry["montage_plan"] = montage_by_index.get(normalized_idx)
        entry["post_render_review"] = post_render_by_index.get(normalized_idx)
        entry["audio"] = audio_by_file.get(fname) or audio_by_file.get(cropped_name)
        entry["audio_qa"] = audio_qa_by_file.get(fname) or audio_qa_by_file.get(cropped_name)
        entry["safe_zone"] = safe_zone_by_file.get(fname) or safe_zone_by_file.get(cropped_name)
        entry["retry"] = retry_by_index.get(normalized_idx)
        sub_dir = src / "subtitles"
        for ext in (".ass", ".srt"):
            side = sub_dir / f"clip_{idx}{ext}"
            if side.is_file():
                dest_sub = publish / side.name
                shutil.copy2(side, dest_sub)
                entry[ext.lstrip(".")] = side.name
        metadata = metadata_by_index.get(str(int(idx)) if idx.isdigit() else idx) or {}
        if metadata:
            meta_dir = src / "metadata"
            for key, name in (("metadata_json", metadata.get("json")), ("metadata_markdown", metadata.get("markdown"))):
                if name and (meta_dir / str(name)).is_file():
                    shutil.copy2(meta_dir / str(name), publish / str(name))
                    entry[key] = str(name)
            entry["metadata"] = {
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "hashtags": metadata.get("hashtags"),
                "pinned_comment": metadata.get("pinned_comment"),
                "cover_prompt": metadata.get("cover_prompt"),
            }
        packaged.append(entry)

    out = {
        "source": str(src.resolve()),
        "publish_dir": str(publish.resolve()),
        "clips": packaged,
        "subtitles": sub_manifest,
        "metadata": metadata_manifest,
        "agent_room": {
            "candidate_moments": str(candidate_path.resolve()) if candidate_path.is_file() else None,
            "editor_review": str(editor_path.resolve()) if editor_path.is_file() else None,
            "virality_review": str(virality_path.resolve()) if virality_path.is_file() else None,
            "dramaturgy_report": str(dramaturgy_path.resolve()) if dramaturgy_path.is_file() else None,
            "montage_plan": str(montage_path.resolve()) if montage_path.is_file() else None,
            "post_render_review": str(post_render_path.resolve()) if post_render_path.is_file() else None,
        },
        "note": "MP4 берутся финальные clip_XX.mp4, если burn был выполнен; иначе fallback на clip_XX_cropped.mp4. Sidecar ASS/SRT рядом для ручной загрузки в YouTube Studio / Reels.",
    }
    (publish / "publish-manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = write_latest_results(src, publish_dir=publish, status="PASS")
    print(f"✅ Packaged {len(packaged)} clip(s) → {publish}")
    print(f"   Latest results: {latest_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
