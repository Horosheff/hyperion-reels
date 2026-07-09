import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Code,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Select,
  Stack,
  Stat,
  Text,
  TextArea,
  TextInput,
  useCanvasAction,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";

const ROOT = "C:\\Users\\mrrut\\Desktop\\Video Plugin Subagents";
const INPUT_DIR = "videoshorts-memory\\input";
const BRIEF_PATH = "videoshorts-memory/00-brief.md";
const FILE_INPUT_ID = "videoshorts-local-file-input";

function quote(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return '"videoshorts-memory\\input\\source.mp4"';
  }
  return `"${trimmed.replaceAll('"', '\\"')}"`;
}

function buildCommand(options: {
  videoPath: string;
  clips: string;
  minSec: string;
  maxSec: string;
  model: string;
  template: string;
  subtitleFormat: string;
  language: string;
  device: string;
  burn: boolean;
  subtitles: boolean;
  packageBundle: boolean;
  qa: boolean;
  wordTimestamps: boolean;
  progressBar: boolean;
  zoomPunch: boolean;
  hookStyle: boolean;
  bRoll: boolean;
}): string {
  const parts = [
    "python",
    "scripts/run_pipeline.py",
    quote(options.videoPath),
    "-c",
    options.clips || "10",
    "--min",
    options.minSec || "30",
    "--max",
    options.maxSec || "60",
    "-m",
    options.model,
    "--template",
    options.template,
    "--subtitle-format",
    options.subtitleFormat,
    "--memory-root",
    "videoshorts-memory",
  ];

  if (options.language !== "auto") parts.push("--language", options.language);
  if (options.device === "cpu") parts.push("--force-cpu");
  parts.push(options.wordTimestamps ? "--word-timestamps" : "--no-word-timestamps");
  if (!options.subtitles) parts.push("--skip-subtitles");
  if (!options.burn) parts.push("--no-burn");
  if (!options.packageBundle) parts.push("--no-publish-bundle");
  if (!options.qa) parts.push("--no-qa");
  if (options.progressBar) parts.push("--progress-bar");
  if (options.zoomPunch) parts.push("--zoom-punch");
  if (options.bRoll) parts.push("--b-roll", "--b-roll-max", "3");
  if (options.hookStyle) parts.push("--subtitles-hook-style");

  return parts.join(" ");
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <Row justify="space-between" align="center" gap={12}>
      <Text tone="secondary" size="small">
        {label}
      </Text>
      <Text weight="semibold" size="small">
        {value}
      </Text>
    </Row>
  );
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "размер не определён";
  }
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export default function VideoShortsUploadCanvas() {
  const theme = useHostTheme();
  const dispatch = useCanvasAction();
  const [videoPath, setVideoPath] = useCanvasState("videoPath", `${ROOT}\\${INPUT_DIR}\\source.mp4`);
  const [clips, setClips] = useCanvasState("clips", "10");
  const [minSec, setMinSec] = useCanvasState("minSec", "30");
  const [maxSec, setMaxSec] = useCanvasState("maxSec", "60");
  const [model, setModel] = useCanvasState("model", "base");
  const [template, setTemplate] = useCanvasState("template", "mrbeast");
  const [subtitleFormat, setSubtitleFormat] = useCanvasState("subtitleFormat", "both");
  const [language, setLanguage] = useCanvasState("language", "auto");
  const [device, setDevice] = useCanvasState("device", "gpu");
  const [subtitles, setSubtitles] = useCanvasState("subtitles", true);
  const [burn, setBurn] = useCanvasState("burn", true);
  const [packageBundle, setPackageBundle] = useCanvasState("packageBundle", true);
  const [qa, setQa] = useCanvasState("qa", true);
  const [wordTimestamps, setWordTimestamps] = useCanvasState("wordTimestamps", true);
  const [progressBar, setProgressBar] = useCanvasState("progressBar", false);
  const [zoomPunch, setZoomPunch] = useCanvasState("zoomPunch", false);
  const [hookStyle, setHookStyle] = useCanvasState("hookStyle", false);
  const [bRoll, setBRoll] = useCanvasState("bRoll", false);
  const [selectedFileName, setSelectedFileName] = useCanvasState("selectedFileName", "");
  const [selectedFileSize, setSelectedFileSize] = useCanvasState("selectedFileSize", "");
  const [selectedFileType, setSelectedFileType] = useCanvasState("selectedFileType", "");

  const command = buildCommand({
    videoPath,
    clips,
    minSec,
    maxSec,
    model,
    template,
    subtitleFormat,
    language,
    device,
    burn,
    subtitles,
    packageBundle,
    qa,
    wordTimestamps,
    progressBar,
    zoomPunch,
    hookStyle,
    bRoll,
  });

  const askPrompt = `Запусти VideoShorts по этому brief. Видео: ${videoPath}. Команда CLI: ${command}`;

  const selectedFilePath = selectedFileName ? `${ROOT}\\${INPUT_DIR}\\${selectedFileName}` : "";

  return (
    <Stack gap={18} style={{ padding: 20, color: theme.text.primary }}>
      <Stack gap={8}>
        <Row align="center" gap={8} wrap>
          <Pill active>Path-first</Pill>
          <Pill>Большие файлы безопасно</Pill>
          <Pill>Без base64</Pill>
        </Row>
        <H1>VideoShorts: старт нарезки</H1>
        <Text tone="secondary">
          Нажми «Добавить файл локально» или положи видео в <Code>{INPUT_DIR}</Code>. Canvas не читает MP4 в память и не
          кодирует его в base64: он берёт имя/метаданные, а тяжёлую работу выполняют Python, Whisper и ffmpeg.
        </Text>
      </Stack>

      <Callout tone="info" title="Как работает локальный файл">
        Браузерный выбор файла не раскрывает абсолютный путь Windows. Поэтому Canvas подставляет безопасный рабочий путь
        <Code>{`${ROOT}\\${INPUT_DIR}\\<имя_файла>`}</Code>. Если файл лежит в другом месте, оставь выбранный файл как
        ориентир и уточни абсолютный путь вручную.
      </Callout>

      <Grid columns="minmax(0, 1.35fr) minmax(280px, 0.65fr)" gap={16} align="start">
        <Stack gap={14}>
          <Card size="lg">
            <CardHeader>Видео и команда</CardHeader>
            <CardBody>
              <Stack gap={12}>
                <Stack gap={6}>
                  <Text weight="semibold">Локальное видео</Text>
                  <input
                    id={FILE_INPUT_ID}
                    type="file"
                    accept="video/*,.mp4,.mov,.mkv,.webm,.avi"
                    style={{ display: "none" }}
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      if (!file) {
                        return;
                      }
                      setSelectedFileName(file.name);
                      setSelectedFileSize(formatBytes(file.size));
                      setSelectedFileType(file.type || "video/*");
                      setVideoPath(`${ROOT}\\${INPUT_DIR}\\${file.name}`);
                    }}
                  />
                  <Row gap={8} wrap align="center">
                    <Button
                      variant="primary"
                      onClick={() => document.getElementById(FILE_INPUT_ID)?.click()}
                    >
                      Добавить файл локально
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setSelectedFileName("");
                        setSelectedFileSize("");
                        setSelectedFileType("");
                        setVideoPath(`${ROOT}\\${INPUT_DIR}\\source.mp4`);
                      }}
                    >
                      Сбросить выбор
                    </Button>
                  </Row>
                  {selectedFileName ? (
                    <Card variant="borderless">
                      <CardBody style={{ background: theme.fill.tertiary, borderRadius: 8 }}>
                        <Stack gap={6}>
                          <SettingRow label="Файл" value={selectedFileName} />
                          <SettingRow label="Размер" value={selectedFileSize || "не определён"} />
                          <SettingRow label="Тип" value={selectedFileType || "video/*"} />
                          <SettingRow label="Рабочий путь" value={selectedFilePath} />
                        </Stack>
                      </CardBody>
                    </Card>
                  ) : null}
                </Stack>
                <Stack gap={6}>
                  <Text weight="semibold">Путь к видео для запуска</Text>
                  <TextInput value={videoPath} onChange={setVideoPath} />
                  <Text tone="tertiary" size="small">
                    Форматы: MP4, MOV, WebM, MKV, AVI. Для больших файлов лучше держать исходник локально; если файл выбран
                    кнопкой, но лежит не в <Code>{INPUT_DIR}</Code>, вставь здесь его абсолютный путь.
                  </Text>
                </Stack>
                <Stack gap={6}>
                  <Text weight="semibold">Готовая команда из корня плагина</Text>
                  <TextArea value={command} onChange={() => undefined} rows={5} />
                </Stack>
                <Row gap={8} wrap>
                  <Button variant="primary" onClick={() => dispatch({ type: "newComposerChat", userPrompt: askPrompt })}>
                    Запустить через Agent
                  </Button>
                  <Button variant="secondary" onClick={() => dispatch({ type: "openFile", path: BRIEF_PATH })}>
                    Открыть brief
                  </Button>
                </Row>
              </Stack>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>Настройки пайплайна</CardHeader>
            <CardBody>
              <Grid columns={3} gap={12}>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Клипов
                  </Text>
                  <TextInput value={clips} onChange={setClips} type="number" />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Минимум, сек
                  </Text>
                  <TextInput value={minSec} onChange={setMinSec} type="number" />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Максимум, сек
                  </Text>
                  <TextInput value={maxSec} onChange={setMaxSec} type="number" />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Whisper
                  </Text>
                  <Select
                    value={model}
                    onChange={setModel}
                    options={["tiny", "base", "small", "medium", "large", "turbo"].map((value) => ({ value, label: value }))}
                  />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Шаблон субтитров
                  </Text>
                  <Select
                    value={template}
                    onChange={setTemplate}
                    options={["mrbeast", "hormozi", "minimal", "neon", "fire"].map((value) => ({ value, label: value }))}
                  />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Формат sidecar
                  </Text>
                  <Select
                    value={subtitleFormat}
                    onChange={setSubtitleFormat}
                    options={[
                      { value: "both", label: "ASS + SRT" },
                      { value: "ass", label: "только ASS" },
                      { value: "srt", label: "только SRT" },
                    ]}
                  />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Язык
                  </Text>
                  <Select
                    value={language}
                    onChange={setLanguage}
                    options={[
                      { value: "auto", label: "авто" },
                      { value: "ru", label: "русский" },
                      { value: "en", label: "английский" },
                    ]}
                  />
                </Stack>
                <Stack gap={6}>
                  <Text size="small" tone="secondary">
                    Устройство
                  </Text>
                  <Select
                    value={device}
                    onChange={setDevice}
                    options={[
                      { value: "gpu", label: "GPU/CUDA если доступно" },
                      { value: "cpu", label: "CPU/int8" },
                    ]}
                  />
                </Stack>
              </Grid>
            </CardBody>
          </Card>
        </Stack>

        <Stack gap={14}>
          <Grid columns={2} gap={12}>
            <Stat value={clips || "10"} label="целевых клипов" />
            <Stat value={`${minSec || "30"}-${maxSec || "60"}с`} label="длина" />
          </Grid>

          <Card>
            <CardHeader>Включено</CardHeader>
            <CardBody>
              <Stack gap={10}>
                <Checkbox checked={subtitles} onChange={setSubtitles} label="Сгенерировать ASS/SRT" />
                <Checkbox checked={burn} onChange={setBurn} label="Вшить субтитры в MP4" />
                <Checkbox checked={packageBundle} onChange={setPackageBundle} label="Собрать publish bundle" />
                <Checkbox checked={qa} onChange={setQa} label="Запустить QA клипов" />
                <Checkbox checked={wordTimestamps} onChange={setWordTimestamps} label="Word timestamps для karaoke" />
                <Checkbox checked={progressBar} onChange={setProgressBar} label="Progress bar после burn" />
                <Checkbox checked={zoomPunch} onChange={setZoomPunch} label="Zoom punch по словам-триггерам" />
                <Checkbox checked={hookStyle} onChange={setHookStyle} label="Усилить первое слово строки" />
                <Checkbox checked={bRoll} onChange={setBRoll} label="B-roll: до 3 контекстных вставок на видео" />
              </Stack>
            </CardBody>
          </Card>

          <Stack gap={8}>
            <H2>Порядок работы</H2>
            <Text>
              1. Нажми «Добавить файл локально» или положи файл в <Code>{INPUT_DIR}</Code>.
            </Text>
            <Text>2. Если файл не лежит в папке input, уточни абсолютный путь в поле запуска.</Text>
            <Text>
              3. Проверь настройки и запусти через Agent или выполни команду из корня <Code>{ROOT}</Code>.
            </Text>
          </Stack>

          <Card variant="borderless">
            <CardBody style={{ background: theme.fill.tertiary, borderRadius: 8 }}>
              <Stack gap={8}>
                <H3>Рекомендации для больших файлов</H3>
                <SettingRow label="Файл" value="локальный путь, без копирования в Canvas" />
                <SettingRow label="Whisper" value="base/small для баланса скорости" />
                <SettingRow label="CPU fallback" value="включить при проблемах CUDA" />
                <SettingRow label="Результаты" value="latest-results.json + publish bundle" />
              </Stack>
            </CardBody>
          </Card>
        </Stack>
      </Grid>
    </Stack>
  );
}
