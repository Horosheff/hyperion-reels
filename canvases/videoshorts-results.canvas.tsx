import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Code,
  Grid,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  TextArea,
  useCanvasAction,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";

const LATEST_RESULTS_PATH = "videoshorts-memory/output/latest-results.json";

const DEFAULT_RESULTS = {
  schema_version: 1,
  updated_at: "2026-07-06T00:00:00+00:00",
  status: "PENDING",
  source_video: "videoshorts-memory/input/source.mp4",
  settings: {
    clips: 10,
    min: 30,
    max: 60,
    model: "base",
    template: "mrbeast",
    subtitle_format: "both",
    force_cpu: false,
    word_timestamps: true,
    burn: true,
    publish_bundle: true,
    qa: true,
  },
  clips_dir: "videoshorts-memory/output/clips/<stem>",
  publish_dir: "videoshorts-memory/output/clips/<stem>-publish",
  manifest_path: "videoshorts-memory/output/clips/<stem>/manifest.json",
  qa_report_path: "videoshorts-memory/output/clips/<stem>/qa-report.json",
  subtitles_manifest_path: "videoshorts-memory/output/clips/<stem>/subtitles-manifest.json",
  publish_manifest_path: "videoshorts-memory/output/clips/<stem>-publish/publish-manifest.json",
  totals: {
    clips: 1,
    qa_passed: 1,
    qa_total: 1,
    packaged: 1,
  },
  clips: [
    {
      index: 1,
      file: "clip_01.mp4",
      path: "videoshorts-memory/output/clips/<stem>/clip_01.mp4",
      publish_path: "videoshorts-memory/output/clips/<stem>-publish/clip_01.mp4",
      cropped_file: "clip_01_cropped.mp4",
      final_file: "clip_01.mp4",
      start: 120,
      end: 165,
      duration: 45,
      score: 80,
      reason: "hook",
      qa_ok: true,
      resolution: [720, 1280],
      has_audio: true,
      burned: true,
      subtitles: {
        ass: "videoshorts-memory/output/clips/<stem>/subtitles/clip_01.ass",
        srt: "videoshorts-memory/output/clips/<stem>/subtitles/clip_01.srt",
      },
    },
  ],
  qa: {
    status: "PASS",
    issues: [],
  },
  commands: {
    open_clips_dir: 'explorer "videoshorts-memory\\output\\clips\\<stem>"',
    open_publish_dir: 'explorer "videoshorts-memory\\output\\clips\\<stem>-publish"',
    run_pipeline: "python scripts/run_pipeline.py videoshorts-memory\\input\\source.mp4 -c 10 --memory-root videoshorts-memory",
  },
  note: "Canvas использует только JSON, пути и метаданные; MP4 не кодируются в base64.",
};

type LatestResults = typeof DEFAULT_RESULTS;

function parseResults(raw: string): { data: LatestResults; error: string | null } {
  try {
    const parsed = JSON.parse(raw);
    return { data: { ...DEFAULT_RESULTS, ...parsed }, error: null };
  } catch (error) {
    return {
      data: DEFAULT_RESULTS,
      error: error instanceof Error ? error.message : "JSON не удалось разобрать",
    };
  }
}

function formatSeconds(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "нет данных";
  return `${value.toFixed(1)}с`;
}

function formatRange(start: unknown, end: unknown): string {
  if (typeof start !== "number" || typeof end !== "number") return "нет данных";
  return `${formatSeconds(start)} - ${formatSeconds(end)}`;
}

function statusTone(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "PASS") return "success";
  if (status === "FAIL") return "danger";
  if (status === "PENDING") return "warning";
  return "info";
}

function yesNo(value: unknown): string {
  if (value === true) return "да";
  if (value === false) return "нет";
  return "неизвестно";
}

export default function VideoShortsResultsCanvas() {
  const theme = useHostTheme();
  const dispatch = useCanvasAction();
  const [rawJson, setRawJson] = useCanvasState("latestResultsJson", JSON.stringify(DEFAULT_RESULTS, null, 2));
  const { data, error } = parseResults(rawJson);
  const status = String(data.status || data.qa?.status || "PENDING");
  const clips = Array.isArray(data.clips) && data.clips.length > 0 ? data.clips : DEFAULT_RESULTS.clips;
  const qaIssues = Array.isArray(data.qa?.issues) ? data.qa.issues : [];

  const rows = clips.map((clip) => [
    `#${clip.index}`,
    clip.file,
    formatRange(clip.start, clip.end),
    formatSeconds(clip.duration),
    Array.isArray(clip.resolution) ? `${clip.resolution[0]}x${clip.resolution[1]}` : "нет данных",
    yesNo(clip.has_audio),
    yesNo(clip.qa_ok),
    [clip.subtitles?.ass ? "ASS" : null, clip.subtitles?.srt ? "SRT" : null].filter(Boolean).join(" + ") || "нет",
    yesNo(Boolean(clip.publish_path)),
  ]);

  const rowTone = clips.map((clip) => (clip.qa_ok === false ? "danger" : clip.qa_ok === true ? "success" : "warning" as const));

  return (
    <Stack gap={18} style={{ padding: 20, color: theme.text.primary }}>
      <Stack gap={8}>
        <Row gap={8} align="center" wrap>
          <Pill active>{status}</Pill>
          <Pill>latest-results.json</Pill>
          <Pill>Без MP4 в памяти</Pill>
        </Row>
        <H1>VideoShorts: результаты</H1>
        <Text tone="secondary">
          Панель показывает клипы, QA, sidecar-субтитры и publish bundle по лёгкому индексу <Code>{LATEST_RESULTS_PATH}</Code>.
          Большие видео и готовые MP4 не встраиваются в Canvas.
        </Text>
      </Stack>

      {error ? (
        <Callout tone="danger" title="JSON не разобран">
          Проверь содержимое поля ниже. Пока показан безопасный шаблон структуры latest-results.json.
        </Callout>
      ) : (
        <Callout tone={statusTone(status)} title={`Статус пайплайна: ${status}`}>
          Обновлено: <Code>{String(data.updated_at)}</Code>. Источник: <Code>{String(data.source_video || "не указан")}</Code>.
        </Callout>
      )}

      <Grid columns={4} gap={12}>
        <Stat value={String(data.totals?.clips ?? clips.length)} label="клипов в индексе" tone={statusTone(status)} />
        <Stat value={`${data.totals?.qa_passed ?? 0}/${data.totals?.qa_total ?? clips.length}`} label="QA pass" />
        <Stat value={String(data.totals?.packaged ?? 0)} label="в publish bundle" />
        <Stat value={data.settings?.model || "base"} label="Whisper" />
      </Grid>

      <Grid columns="minmax(0, 1.25fr) minmax(320px, 0.75fr)" gap={16} align="start">
        <Stack gap={14}>
          <Stack gap={8}>
            <H2>Клипы и QA</H2>
            <Table
              headers={["Клип", "Файл", "Таймкод", "Длительность", "Размер", "Аудио", "QA", "Sidecar", "Publish"]}
              rows={rows}
              rowTone={rowTone}
              columnAlign={["left", "left", "left", "right", "right", "center", "center", "left", "center"]}
              striped
            />
          </Stack>

          <Card>
            <CardHeader>Команды и пути</CardHeader>
            <CardBody>
              <Stack gap={10}>
                <Text>
                  Папка клипов: <Code>{String(data.clips_dir)}</Code>
                </Text>
                <Text>
                  Publish bundle: <Code>{String(data.publish_dir || "ещё не собран")}</Code>
                </Text>
                <Text>
                  Открыть клипы: <Code>{String(data.commands?.open_clips_dir || "команда появится после run_pipeline")}</Code>
                </Text>
                <Text>
                  Открыть publish: <Code>{String(data.commands?.open_publish_dir || "команда появится после package_outputs")}</Code>
                </Text>
                <Text>
                  Повторить запуск: <Code>{String(data.commands?.run_pipeline || "см. upload canvas")}</Code>
                </Text>
                <Row gap={8} wrap>
                  <Button variant="primary" onClick={() => dispatch({ type: "openFile", path: LATEST_RESULTS_PATH })}>
                    Открыть latest-results
                  </Button>
                  <Button variant="secondary" onClick={() => dispatch({ type: "openFile", path: String(data.qa_report_path || LATEST_RESULTS_PATH) })}>
                    Открыть QA
                  </Button>
                  <Button variant="secondary" onClick={() => dispatch({ type: "openFile", path: String(data.publish_manifest_path || LATEST_RESULTS_PATH) })}>
                    Открыть publish manifest
                  </Button>
                </Row>
              </Stack>
            </CardBody>
          </Card>
        </Stack>

        <Stack gap={14}>
          <Card>
            <CardHeader>Артефакты</CardHeader>
            <CardBody>
              <Stack gap={10}>
                <Text>
                  Manifest: <Code>{String(data.manifest_path || "ожидается")}</Code>
                </Text>
                <Text>
                  QA: <Code>{String(data.qa_report_path || "ожидается")}</Code>
                </Text>
                <Text>
                  Субтитры: <Code>{String(data.subtitles_manifest_path || "ожидается")}</Code>
                </Text>
                <Text>
                  Упаковка: <Code>{String(data.publish_manifest_path || "ожидается")}</Code>
                </Text>
              </Stack>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>Настройки запуска</CardHeader>
            <CardBody>
              <Stack gap={8}>
                <Text>Клипов: <Code>{String(data.settings?.clips ?? "10")}</Code></Text>
                <Text>Длина: <Code>{String(data.settings?.min ?? "30")}-{String(data.settings?.max ?? "60")}с</Code></Text>
                <Text>Шаблон: <Code>{String(data.settings?.template ?? "mrbeast")}</Code></Text>
                <Text>Субтитры: <Code>{String(data.settings?.subtitle_format ?? "both")}</Code></Text>
                <Text>CPU: <Code>{yesNo(data.settings?.force_cpu)}</Code></Text>
                <Text>Burn: <Code>{yesNo(data.settings?.burn)}</Code></Text>
                <Text>Bundle: <Code>{yesNo(data.settings?.publish_bundle)}</Code></Text>
              </Stack>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>Обновить данные</CardHeader>
            <CardBody>
              <Stack gap={10}>
                <Text tone="secondary" size="small">
                  Cursor Canvas не делает <Code>fetch()</Code> и не читает локальный JSON сам. После packager открой
                  <Code>{LATEST_RESULTS_PATH}</Code>, вставь его содержимое сюда или попроси Agent обновить встроенный JSON.
                </Text>
                <TextArea value={rawJson} onChange={setRawJson} rows={12} />
              </Stack>
            </CardBody>
          </Card>
        </Stack>
      </Grid>

      {qaIssues.length > 0 ? (
        <Card>
          <CardHeader>Проблемы QA</CardHeader>
          <CardBody>
            <Stack gap={6}>
              {qaIssues.map((issue, index) => (
                <Text key={`${index}-${issue}`} tone="secondary">
                  {String(issue)}
                </Text>
              ))}
            </Stack>
          </CardBody>
        </Card>
      ) : null}
    </Stack>
  );
}
