#!/usr/bin/env python3

"""VideoShorts — полный CLI-пайплайн (порт shorts_service + webinar_cutter)."""

from __future__ import annotations



import argparse

import os

import subprocess

import sys

from pathlib import Path

from run_state import init_state, update_stage
from videoshorts_core import configure_stdio, write_latest_results

configure_stdio()



_SCRIPTS = Path(__file__).resolve().parent





def run_step(
    cmd: list[str],
    env: dict[str, str] | None = None,
    *,
    state_path: Path | None = None,
    stage: str | None = None,
    artifact: Path | None = None,
    on_fail: list[str] | None = None,
) -> None:

    print(f"\n>>> {' '.join(cmd)}\n")
    if state_path and stage:
        update_stage(state_path, stage, "RUNNING", artifact=str(artifact.resolve()) if artifact else None)

    r = subprocess.run(cmd, cwd=str(_SCRIPTS), env=env)

    if r.returncode != 0:
        if state_path and stage:
            update_stage(state_path, stage, "FAIL", artifact=str(artifact.resolve()) if artifact else None, message=f"exit_code={r.returncode}")
        if on_fail:
            subprocess.run(on_fail, cwd=str(_SCRIPTS), env=env)

        sys.exit(r.returncode)
    if state_path and stage:
        update_stage(state_path, stage, "PASS", artifact=str(artifact.resolve()) if artifact else None)





def main() -> None:

    parser = argparse.ArgumentParser(description="VideoShorts full production-like pipeline")

    parser.add_argument("video", type=Path, help="Локальный MP4/MOV/webm файл")

    parser.add_argument("-c", "--clips", type=int, default=10, help="Количество клипов")

    parser.add_argument("--min", type=float, default=30, help="Минимальная длина клипа")

    parser.add_argument("--max", type=float, default=60, help="Максимальная длина клипа")

    parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large", "turbo"])

    parser.add_argument("--template", default="mrbeast", help="ASS шаблон: mrbeast/hormozi/minimal/neon/fire")
    parser.add_argument("--profile", default=None, choices=["webinar", "sales", "education", "podcast"], help="Профиль публикационных метаданных (по умолчанию из --layout)")
    parser.add_argument(
        "--layout",
        default="regular",
        choices=["regular", "webinar", "podcast", "sales"],
        help="Режим кадра: regular / webinar / podcast(tracking) / sales",
    )

    parser.add_argument("--template-json", type=Path, default=None, help="Custom JSON subtitle template")

    parser.add_argument("--subtitle-format", choices=("ass", "srt", "both"), default="both")

    parser.add_argument("--memory-root", type=Path, default=Path("videoshorts-memory"))

    parser.add_argument("--quality-preset", default="release", choices=["draft", "release"], help="draft=720p fast, release=1080p publish")

    parser.add_argument("--width", type=int, default=None)

    parser.add_argument("--height", type=int, default=None)

    parser.add_argument("--top-ratio", type=float, default=0.30)

    parser.add_argument("--force-cpu", action="store_true", help="Whisper CPU/int8")

    parser.add_argument("--word-timestamps", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--loudnorm", action=argparse.BooleanOptionalAction, default=True, help="Two-pass loudnorm в audio-polisher")

    parser.add_argument("--language", default=None, help="Whisper language: ru/en или auto")

    parser.add_argument("--beam-size", type=int, default=None)

    parser.add_argument("--skip-subtitles", action="store_true")

    parser.add_argument("--burn", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--skip-burn", action="store_true", help="Alias: --no-burn")

    parser.add_argument("--emoji-subtitles", action="store_true", help="Локальные emoji subtitles без внешнего API")

    parser.add_argument("--subtitles-hook-style", action="store_true")

    parser.add_argument("--hook-scale", type=float, default=1.3)

    parser.add_argument("--progress-bar", action="store_true", help="Post-burn progress bar")

    parser.add_argument("--progress-position", choices=("top", "bottom"), default="bottom")

    parser.add_argument("--zoom-punch", action="store_true", help="Post-burn punch-in по trigger words")
    parser.add_argument("--b-roll", action="store_true", help="Применить готовый broll-plan.json перед subtitle burn")
    parser.add_argument("--b-roll-max", type=int, default=3, choices=range(1, 4), help="Лимит B-roll для Agent mode")
    parser.add_argument("--b-roll-dry-run", action="store_true", help="Проверить B-roll compositing без ffmpeg render")

    parser.add_argument("--publish-bundle", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--skip-package", action="store_true")

    parser.add_argument("--qa", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--skip-qa", action="store_true", help="Alias: --no-qa")

    parser.add_argument("--basic-moments", action="store_true", help="webinar_cutter hook only")

    args = parser.parse_args()



    from quality_presets import resolve_preset
    from videoshorts_core import metadata_profile_for_layout, normalize_layout_mode

    quality = resolve_preset(args.quality_preset)
    if args.width is None:
        args.width = int(quality["width"])
    if args.height is None:
        args.height = int(quality["height"])
    args.layout = normalize_layout_mode(args.layout)
    if not args.profile:
        args.profile = metadata_profile_for_layout(args.layout)

    if not args.video.is_file():

        print(f"[ERROR] Video not found: {args.video}", file=sys.stderr)

        sys.exit(1)

    # Child scripts run with cwd=scripts, so resolve all paths before handoff.
    args.video = args.video.resolve()
    args.memory_root = args.memory_root.resolve()
    if args.template_json:
        args.template_json = args.template_json.resolve()

    env = {
        **os.environ,
        "VIDEOSHORTS_WHISPER_WORD_TIMESTAMPS": "1" if args.word_timestamps else "0",
    }
    if args.force_cpu:
        env["VIDEOSHORTS_WHISPER_FORCE_CPU"] = "1"
    if args.language:
        env["VIDEOSHORTS_WHISPER_LANGUAGE"] = args.language
    if args.beam_size is not None:
        env["VIDEOSHORTS_WHISPER_BEAM_SIZE"] = str(args.beam_size)
    if args.subtitles_hook_style:
        env["VIDEOSHORTS_SUBTITLES_HOOK_STYLE"] = "1"
        env["VIDEOSHORTS_SUBTITLES_HOOK_SCALE"] = str(args.hook_scale)
    if args.template_json:
        env["VIDEOSHORTS_SUBTITLES_TEMPLATE_JSON"] = str(args.template_json)



    stem = args.video.stem

    transcript_dir = args.memory_root / "transcripts" / stem

    transcript_json = transcript_dir / "transcript.json"

    moments_path = args.memory_root / "moments" / f"{stem}-moments.json"
    cleanup_plan_path = transcript_dir / "cleanup-plan.json"
    filler_plan_path = transcript_dir / "filler-removal-plan.json"
    candidate_moments_path = args.memory_root / "moments" / "candidate-moments.json"
    scores_path = args.memory_root / "moments" / "clip-scores.json"
    editor_review_path = args.memory_root / "moments" / "editor-review.json"
    virality_review_path = args.memory_root / "moments" / "virality-review.json"
    refined_moments_path = args.memory_root / "moments" / "refined-moments.json"
    dramaturgy_report_path = args.memory_root / "moments" / "dramaturgy-report.json"
    montage_plan_path = args.memory_root / "moments" / "montage-plan.json"
    clip_decisions_path = args.memory_root / "moments" / "clip-decisions.json"

    clips_dir = args.memory_root / "output" / "clips" / stem
    run_state_path = args.memory_root / "output" / "run-state.json"
    retry_plan_path = clips_dir / "retry-plan.json"
    post_render_review_path = clips_dir / "post-render-review.json"



    py = sys.executable
    settings = {
        "clips": args.clips,
        "min": args.min,
        "max": args.max,
        "model": args.model,
        "template": args.template,
        "profile": args.profile,
        "layout": args.layout,
        "template_json": str(args.template_json.resolve()) if args.template_json else None,
        "subtitle_format": args.subtitle_format,
        "memory_root": str(args.memory_root.resolve()),
        "quality_preset": args.quality_preset,
        "width": args.width,
        "height": args.height,
        "top_ratio": args.top_ratio,
        "force_cpu": args.force_cpu,
        "word_timestamps": args.word_timestamps,
        "loudnorm": args.loudnorm,
        "language": args.language,
        "skip_subtitles": args.skip_subtitles,
        "burn": args.burn and not args.skip_burn,
        "emoji_subtitles": args.emoji_subtitles,
        "subtitles_hook_style": args.subtitles_hook_style,
        "progress_bar": args.progress_bar,
        "zoom_punch": args.zoom_punch,
        "publish_bundle": args.publish_bundle and not args.skip_package,
        "qa": args.qa and not args.skip_qa,
        "basic_moments": args.basic_moments,
        "run_mode": "local_diagnostic_fallback",
    }
    init_state(run_state_path, source_video=str(args.video), settings=settings)

    transcribe_cmd = [
        py, str(_SCRIPTS / "transcribe.py"),
        str(args.video),
        "-o", str(transcript_dir),
        "-m", args.model,
        "--word-timestamps" if args.word_timestamps else "--no-word-timestamps",
    ]
    if args.force_cpu:
        transcribe_cmd.append("--force-cpu")
    if args.language and str(args.language).strip().lower() not in {"auto", "none", ""}:
        transcribe_cmd += ["--language", args.language]
    if args.beam_size is not None:
        transcribe_cmd += ["--beam-size", str(args.beam_size)]
    run_step(transcribe_cmd, env=env, state_path=run_state_path, stage="transcriber", artifact=transcript_json)

    run_step([
        py, str(_SCRIPTS / "cleanup_plan.py"),
        "--heuristic",
        str(transcript_json),
        "-o", str(cleanup_plan_path),
        "--filler-output", str(filler_plan_path),
    ], env=env, state_path=run_state_path, stage="cleanup-planner", artifact=cleanup_plan_path)

    run_step([
        py, str(_SCRIPTS / "generate_candidates.py"),
        "--heuristic",
        str(transcript_json),
        "-o", str(candidate_moments_path),
        "--min", str(args.min),
        "--max", str(args.max),
        "--target", "60",
    ], env=env, state_path=run_state_path, stage="candidate-generator-draft", artifact=candidate_moments_path)



    fm_cmd = [

        py, str(_SCRIPTS / "find_moments.py"),

        "--heuristic",

        str(transcript_json),

        "-o", str(moments_path),

        "-c", str(args.clips),

        "--min", str(args.min),

        "--max", str(args.max),

    ]

    if args.basic_moments:

        fm_cmd.append("--basic")

    run_step(fm_cmd, env=env, state_path=run_state_path, stage="moment-finder", artifact=moments_path)

    run_step([
        py, str(_SCRIPTS / "score_clips.py"),
        "--heuristic",
        str(moments_path),
        str(transcript_json),
        "--cleanup-plan", str(cleanup_plan_path),
        "-o", str(scores_path),
        "--min", str(args.min),
        "--max", str(args.max),
    ], env=env, state_path=run_state_path, stage="scorekeeper", artifact=scores_path)

    run_step([
        py, str(_SCRIPTS / "editor_review.py"),
        "--heuristic",
        str(moments_path),
        str(transcript_json),
        "--candidates", str(candidate_moments_path),
        "-o", str(editor_review_path),
    ], env=env, state_path=run_state_path, stage="editor-review-draft", artifact=editor_review_path)

    run_step([
        py, str(_SCRIPTS / "virality_review.py"),
        "--heuristic",
        str(moments_path),
        str(transcript_json),
        "--scores", str(scores_path),
        "--editor-review", str(editor_review_path),
        "-o", str(virality_review_path),
    ], env=env, state_path=run_state_path, stage="virality-review-draft", artifact=virality_review_path)

    run_step([
        py, str(_SCRIPTS / "refine_boundaries.py"),
        "--heuristic",
        str(moments_path),
        str(transcript_json),
        "--cleanup-plan", str(cleanup_plan_path),
        "--scores", str(scores_path),
        "-o", str(refined_moments_path),
        "--min", str(args.min),
        "--max", str(args.max),
    ], env=env, state_path=run_state_path, stage="boundary-refiner", artifact=refined_moments_path)

    run_step([
        py, str(_SCRIPTS / "dramaturgy_report.py"),
        "--heuristic",
        str(refined_moments_path),
        str(transcript_json),
        "--editor-review", str(editor_review_path),
        "--virality-review", str(virality_review_path),
        "-o", str(dramaturgy_report_path),
    ], env=env, state_path=run_state_path, stage="dramaturg-draft", artifact=dramaturgy_report_path)

    run_step([
        py, str(_SCRIPTS / "montage_plan.py"),
        "--heuristic",
        str(refined_moments_path),
        "--cleanup-plan", str(cleanup_plan_path),
        "--dramaturgy-report", str(dramaturgy_report_path),
        "--min-duration", str(args.min),
        "-o", str(montage_plan_path),
    ], env=env, state_path=run_state_path, stage="montage-planner-draft", artifact=montage_plan_path)

    run_step([
        py, str(_SCRIPTS / "write_agent_decisions.py"),
        "--heuristic",
        str(transcript_json),
        str(moments_path),
        "--cleanup-plan", str(cleanup_plan_path),
        "--scores", str(scores_path),
        "--refined", str(refined_moments_path),
        "-o", str(clip_decisions_path),
    ], env=env, state_path=run_state_path, stage="agent-decisions-draft", artifact=clip_decisions_path)



    run_step([

        py, str(_SCRIPTS / "cut_clips.py"),

        str(args.video),

        str(refined_moments_path),

        "-o", str(clips_dir),

        "--montage-plan", str(montage_plan_path),

        "--min-duration", str(args.min),

        "--width", str(args.width),

        "--height", str(args.height),

        "--top-ratio", str(args.top_ratio),

        "--layout", str(args.layout),

        "--quality-preset", args.quality_preset,

        "--no-require-agent-decisions",

    ], env=env, state_path=run_state_path, stage="cutter", artifact=clips_dir / "manifest.json")

    run_step([
        py, str(_SCRIPTS / "audio_polish.py"),
        str(clips_dir),
        "--apply-loudnorm" if args.loudnorm else "--no-apply-loudnorm",
        "--quality-preset", args.quality_preset,
    ], env=env, state_path=run_state_path, stage="audio-polisher", artifact=clips_dir / "audio-metrics.json")

    broll_plan_path = clips_dir / "broll-plan.json"
    if args.b_roll and broll_plan_path.is_file():
        broll_cmd = [py, str(_SCRIPTS / "broll_composite.py"), str(clips_dir), "--plan", str(broll_plan_path)]
        if args.b_roll_dry_run:
            broll_cmd.append("--dry-run")
        run_step(broll_cmd, env=env, state_path=run_state_path, stage="broll", artifact=clips_dir / "broll-report.json")
    elif args.b_roll:
        update_stage(run_state_path, "broll", "SKIPPED", message="Agent B-roll plan is required; no broll-plan.json")



    if not args.skip_subtitles:

        subtitle_cmd = [

            py, str(_SCRIPTS / "write_subtitles.py"),

            str(transcript_json),

            str(refined_moments_path),

            "-o", str(clips_dir),

            "-t", args.template,

            "--format", args.subtitle_format,

            "--width", str(args.width),

            "--height", str(args.height),

        ]

        if args.template_json:
            subtitle_cmd += ["--template-json", str(args.template_json)]
        if args.emoji_subtitles:
            subtitle_cmd.append("--emoji")
        if args.subtitles_hook_style:
            subtitle_cmd += ["--hook-style", "--hook-scale", str(args.hook_scale)]

        run_step(subtitle_cmd, env=env, state_path=run_state_path, stage="subtitle-writer", artifact=clips_dir / "subtitles-manifest.json")

        if args.burn and not args.skip_burn:

            burn_cmd = [
                py, str(_SCRIPTS / "burn_subtitles.py"),
                str(clips_dir),
                "--moments", str(refined_moments_path),
                "--transcript", str(transcript_json),
                "--quality-preset", args.quality_preset,
            ]
            if args.progress_bar:
                burn_cmd += ["--progress-bar", "--progress-position", args.progress_position]
            if args.zoom_punch:
                burn_cmd.append("--zoom-punch")

            run_step(burn_cmd, env=env, state_path=run_state_path, stage="subtitle-burner", artifact=clips_dir / "manifest.json")
        else:
            update_stage(run_state_path, "subtitle-burner", "SKIPPED", message="burn disabled")
    else:
        update_stage(run_state_path, "subtitle-writer", "SKIPPED", message="subtitles disabled")
        update_stage(run_state_path, "subtitle-burner", "SKIPPED", message="subtitles disabled")



    if args.qa and not args.skip_qa:

        run_step(
            [
                py, str(_SCRIPTS / "qa_clips.py"), str(clips_dir),
                "--min", str(args.min), "--max", str(args.max),
                "--no-require-agent-decisions",
            ],
            env=env,
            state_path=run_state_path,
            stage="guardian-v2",
            artifact=clips_dir / "qa-report.json",
            on_fail=[py, str(_SCRIPTS / "retry_plan.py"), str(clips_dir), "--state", str(run_state_path), "-o", str(retry_plan_path)],
        )
    else:
        update_stage(run_state_path, "guardian-v2", "SKIPPED", message="qa disabled")

    run_step([
        py, str(_SCRIPTS / "post_render_review.py"),
        "--heuristic",
        str(clips_dir),
        "--qa-report", str(clips_dir / "qa-report.json"),
        "--montage-plan", str(montage_plan_path),
        "--scores", str(scores_path),
        "-o", str(post_render_review_path),
    ], env=env, state_path=run_state_path, stage="post-render-review-draft", artifact=post_render_review_path)


    run_step([
        py, str(_SCRIPTS / "write_metadata.py"),
        "--heuristic",
        str(transcript_json),
        str(refined_moments_path),
        str(clips_dir),
        "--profile", args.profile,
    ], env=env, state_path=run_state_path, stage="metadata-writer", artifact=clips_dir / "metadata-manifest.json")

    run_step([
        py, str(_SCRIPTS / "retry_plan.py"),
        str(clips_dir),
        "--state", str(run_state_path),
        "-o", str(retry_plan_path),
    ], env=env, state_path=run_state_path, stage="retry-cache", artifact=retry_plan_path)



    if args.publish_bundle and not args.skip_package:

        run_step([
            py, str(_SCRIPTS / "package_outputs.py"), str(clips_dir),
            "--no-require-agent-decisions",
        ], env=env, state_path=run_state_path, stage="packager", artifact=clips_dir.parent / f"{clips_dir.name}-publish" / "publish-manifest.json")
    else:
        update_stage(run_state_path, "packager", "SKIPPED", message="publish bundle disabled")

    command = subprocess.list2cmdline([sys.executable, "scripts/run_pipeline.py", str(args.video), "-c", str(args.clips), "--min", str(args.min), "--max", str(args.max), "-m", args.model, "--template", args.template, "--profile", args.profile, "--subtitle-format", args.subtitle_format, "--memory-root", str(args.memory_root)])
    latest_path = write_latest_results(
        clips_dir,
        source_video=args.video,
        settings=settings,
        status="PASS",
        run_command=command,
    )

    print(f"\n✅ Pipeline complete. Clips: {clips_dir}")
    print(f"   Latest results: {latest_path}")





if __name__ == "__main__":

    main()

