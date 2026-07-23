# VideoShorts Agent Pipeline (slim P0)

```
HTML bridge: .\open-videoshorts-ui.ps1 → http://127.0.0.1:8765/
READY_FOR_AGENT → Cursor Director (slim Task waves)

Wave A     intake
Wave B     transcriber
Wave C ||  cleanup-planner || candidate-generator
Wave D     moment-finder
Wave E     editor  → clip-scores + editor-review + virality-review
Wave F     boundary-refiner → refined + clip-decisions + montage-plan
Wave G     cutter → cropped + loudnorm (audio-metrics)
Wave H ||  subtitle-writer || metadata-writer
Wave I     subtitle-burner → clip_XX.mp4
Wave J     guardian → QA + post-render-review
Wave K     packager → latest-results + publish → Results UI → fixic

Убраны как отдельные Task: scorekeeper, virality-critic, dramaturg,
montage-planner, audio-polisher, post-render-reviewer.
```

Publish desk: `docs/PUBLISH.md`  
Handoff: `.cursor/videoshorts-handoff.md`  
Contract: `shared/agent-decision-contract.md`
