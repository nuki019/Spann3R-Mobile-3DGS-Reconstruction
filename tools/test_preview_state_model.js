const assert = require("assert");
const path = require("path");

const model = require(path.join("..", "frontend", "utils", "preview_state_model"));

function testBasics() {
  assert.strictEqual(model.formatBytes(-1), "-");
  assert.strictEqual(model.formatBytes(0), "0 B");
  assert.strictEqual(model.formatBytes(1536), "1.50 KB");
  assert.deepStrictEqual(model.toObject('{"count":"2"}'), { count: "2" });
  assert.deepStrictEqual(model.toObject("{bad json"), {});
  assert.strictEqual(model.pickNumber({ count: "12" }, ["count"]), 12);
  assert.strictEqual(model.pickString({ name: "scene" }, ["name"]), "scene");
  assert.strictEqual(model.clipText("abcdef", 4), "abcd...");
  assert.strictEqual(model.asText({ ok: true }, 40), '{"ok":true}');
  assert.deepStrictEqual(
    model.buildCopyLinkTarget({ viewerUrl: "https://viewer.example" }, "viewerUrl"),
    { content: "https://viewer.example", label: "Viewer 地址" },
  );
  assert.deepStrictEqual(model.buildCopyLinkTarget({ viewerUrl: "https://viewer.example" }, "missing"), {
    content: "",
    label: "",
  });
  assert.strictEqual(
    model.pickDatasetUrl({ currentTarget: { dataset: { url: "https://files.example/a.ply" } } }),
    "https://files.example/a.ply",
  );
  assert.strictEqual(model.pickDatasetUrl({}), "");
  console.log("[OK] preview state basics");
}

function testJobNormalization() {
  const ready = model.normalizeJobItem(
    {
      job_id: "wx_session_1",
      status: "ready",
      image_count: "60",
      scene_name: "scene_a",
      updated_at: "2026-06-14T10:00:00Z",
      message: "ready",
    },
    0,
    (status) => "label:" + status,
  );
  assert.strictEqual(ready.id, "wx_session_1");
  assert.strictEqual(ready.statusText, "label:ready");
  assert.strictEqual(ready.statusClass, "pending");
  assert.strictEqual(ready.imageText, "60");
  assert.strictEqual(ready.canCancel, true);

  const completed = model.normalizeJobItem({ id: "done", status: "completed" }, 1);
  assert.strictEqual(completed.statusClass, "done");
  assert.strictEqual(completed.canCancel, false);

  const failed = model.normalizeJobItem({ id: "bad", status: "failed", error: "x".repeat(120) }, 2);
  assert.strictEqual(failed.statusClass, "warn");
  assert.strictEqual(failed.canCancel, false);
  assert.strictEqual(failed.message.length, 83);
  console.log("[OK] preview state job normalization");
}

function testPointcloudNormalization() {
  assert.strictEqual(
    model.inferPointcloudType({
      variant: "gaussian",
      name: "scene_gaussian_clipped_step1000.ply",
    }),
    "3DGaussian · 1000步 · 裁切/下采样",
  );
  assert.strictEqual(
    model.inferPointcloudType({
      variant: "gaussian",
      path: "/root/autodl-tmp/scene/iteration_1000/raw.ply",
    }),
    "3DGaussian · 1000步 · 原始",
  );
  assert.strictEqual(model.inferPointcloudType({ variant: "downsampled" }), "Spann3R · 下采样");

  const item = model.normalizePointcloudItem(
    {
      id: "pc_1",
      scene: "scene a",
      variant: "gaussian",
      name: "scene_gaussian_clipped_step1000.ply",
      size_bytes: 1048576,
      mtime: "2026-06-14 12:00:00",
      path: "/root/autodl-tmp/gs_train/scenes/scene_a/scene_gaussian_clipped_step1000.ply",
      download_url: "/download/id/pc_1",
    },
    "https://dashboard.example/",
    (obj) => "type:" + obj.variant,
  );
  assert.strictEqual(item.typeText, "type:gaussian");
  assert.strictEqual(item.sizeText, "1.00 MB");
  assert.strictEqual(item.downloadUrl, "https://dashboard.example/download/id/pc_1");
  assert.strictEqual(
    item.optimizedUrl,
    "https://dashboard.example/download/scene/scene%20a?prefer=gaussian&processed=true",
  );
  assert.strictEqual(
    item.rawUrl,
    "https://dashboard.example/download/scene/scene%20a?prefer=gaussian&processed=false",
  );
  assert.strictEqual(item.zipUrl, "https://dashboard.example/download/zip?ids=pc_1");

  const absolute = model.normalizePointcloudItem(
    { id: "pc_2", scene: "-", download_url: "https://files.example/pc_2.ply" },
    "https://dashboard.example",
  );
  assert.strictEqual(absolute.typeText, "other");
  assert.strictEqual(absolute.downloadUrl, "https://files.example/pc_2.ply");
  assert.strictEqual(absolute.optimizedUrl, "https://files.example/pc_2.ply?processed=true");
  console.log("[OK] preview state pointcloud normalization");
}

function testSummaryBuilders() {
  assert.strictEqual(
    model.buildUploadStatsText({ uploaded_files: "3", uploaded_bytes: 1536 }),
    "文件数: 3 | 字节数: 1.50 KB",
  );
  assert.strictEqual(
    model.buildUploadsSummaryText({
      count: "2",
      latest_mtime: "2026-06-14 12:00:00",
      watch_dir: "/root/autodl-tmp/input_images",
    }),
    "count:2 | latest:2026-06-14 12:00:00 | dir:/root/autodl-tmp/input_images",
  );
  assert.strictEqual(
    model.buildScenesSummaryText({
      latest_scene: "scene_a",
      dataset_count: "2",
      photo_scene_count: 1,
      pointcloud_count: "4",
    }),
    "latest:scene_a | dataset:2 | photo:1 | pointcloud:4",
  );

  const pointcloudSummary = model.buildPointcloudSummary(
    {
      summary: {
        count: 2,
        total_size: "3.00 MB",
        latest: { name: "scene_gaussian_clipped.ply" },
        scenes: { scene_a: 2 },
      },
      items: [
        {
          id: "pc_1",
          scene: "scene_a",
          variant: "gaussian",
          name: "scene_gaussian_clipped.ply",
          size_bytes: 2048,
          download_url: "/download/pc_1",
        },
        {
          id: "pc_2",
          scene: "scene_a",
          variant: "downsampled",
          name: "scene_downsampled.ply",
          size_bytes: 1024,
          download_url: "/download/pc_2",
        },
      ],
    },
    "https://dashboard.example",
    (obj) => "type:" + obj.variant,
    1,
  );
  assert.strictEqual(
    pointcloudSummary.text,
    "文件数:2 | 总大小:3.00 MB | 场景:1 | 最新:scene_gaussian_clipped.ply",
  );
  assert.strictEqual(pointcloudSummary.items.length, 1);
  assert.strictEqual(pointcloudSummary.items[0].typeText, "type:gaussian");

  const jobs = model.buildJobsData(
    {
      summary: { count: 2, queued: 1, running: 1, completed: 0, failed: 0 },
      items: [
        { id: "job_a", status: "queued", image_count: 60 },
        { id: "job_b", status: "running", image_count: 70 },
      ],
    },
    (status) => "label:" + status,
    1,
  );
  assert.strictEqual(jobs.text, "任务:2 | 排队:1 | 运行:1 | 完成:0 | 失败:0");
  assert.strictEqual(jobs.items.length, 1);
  assert.strictEqual(jobs.items[0].statusText, "label:queued");

  const logs = model.buildLogsData({ lines: ["old", "middle", "latest"] }, 2);
  assert.strictEqual(logs.text, "lines:3 | latest:latest");
  assert.deepStrictEqual(logs.items, [
    { id: "0", text: "middle" },
    { id: "1", text: "latest" },
  ]);
  assert.deepStrictEqual(model.buildLogsData({ lines: [] }), { text: "lines:0 | latest:-", items: [] });
  console.log("[OK] preview state summary builders");
}

function testStatusAndProgressParsing() {
  assert.deepStrictEqual(
    model.parseStatus({
      running: true,
      pid: 1234,
      queue_length: "2",
      active_job: { id: "job_a", started_at: "2026-06-14T10:00:00Z" },
    }),
    {
      runningText: "运行中",
      pidText: "1234",
      queueText: "等待队列:2",
      jobText: "job_a | 2026-06-14T10:00:00Z",
    },
  );
  assert.deepStrictEqual(
    model.parseStatus({ pid: "", queue: {} }),
    {
      runningText: "未运行",
      pidText: "-",
      queueText: "等待队列:-",
      jobText: "-",
    },
  );

  assert.deepStrictEqual(
    model.parseProgress({
      phase: "gaussian",
      step: "120",
      scene_name: "scene_a",
      loss: "0.25",
      uploaded_images: "60",
      percent: 0.125,
    }),
    {
      phaseKey: "gaussian",
      stageText: "gaussian",
      stepText: "120",
      sceneNameText: "scene_a",
      lossText: "0.25",
      uploadedImagesText: "60",
      percentText: "12.5%",
    },
  );
  assert.deepStrictEqual(
    model.parseProgress({ stage: "spann3r", percent: "75" }),
    {
      phaseKey: "spann3r",
      stageText: "spann3r",
      stepText: "-",
      sceneNameText: "-",
      lossText: "-",
      uploadedImagesText: "-",
      percentText: "75.0%",
    },
  );
  console.log("[OK] preview status/progress parsing");
}

function testBackendPhaseBuilders() {
  assert.deepStrictEqual(
    model.getPhaseState("gaussian", {
      uploadHealthy: true,
      uploadAllow: true,
      queueEnabled: true,
      hasPointclouds: false,
    }),
    {
      phaseKey: "gaussian",
      phaseActionHint: "当前为 gaussian 阶段：Viewer 可访问，新采集会进入等待队列。",
      phaseCanUpload: true,
      phaseCanViewer: true,
      phaseCanDownload: true,
    },
  );
  assert.deepStrictEqual(
    model.getPhaseState("failed", { hasPointclouds: true }),
    {
      phaseKey: "failed",
      phaseActionHint: "流程执行失败，请查看后端最新日志。",
      phaseCanUpload: false,
      phaseCanViewer: false,
      phaseCanDownload: true,
    },
  );

  const gaussianPhases = model.buildBackendPhases(
    {
      phaseKey: "gaussian",
      sceneNameText: "demo_scene",
      stepText: "420",
      percentText: "42.0%",
      uploadedImagesText: "80",
    },
    {
      uploadHealthOk: true,
      dashboardHealthOk: true,
      statusData: { queueText: "等待队列:1", runningText: "运行中" },
      uploadAllow: true,
      queueEnabled: true,
      hasPointclouds: false,
    },
  );
  assert.deepStrictEqual(gaussianPhases.map((item) => item.state), ["队列就绪", "已完成", "训练中", "生成中"]);
  assert.strictEqual(gaussianPhases[0].detail, "新采集会进入等待队列，等待队列:1");
  assert.strictEqual(gaussianPhases[2].detail, "Step 420 | 42.0%");

  const completedPhases = model.buildBackendPhases(
    { phaseKey: "completed", sceneNameText: "demo_scene" },
    {
      uploadHealthOk: true,
      dashboardHealthOk: true,
      statusData: { queueText: "等待队列:0" },
      uploadAllow: false,
      hasPointclouds: false,
    },
  );
  assert.deepStrictEqual(completedPhases.map((item) => item.state), ["已完成", "已完成", "已完成", "可查看"]);
  assert.strictEqual(completedPhases[3].detail, "点云下载已准备");
  console.log("[OK] preview backend phase builders");
}

function testFastPollData() {
  const poll = model.buildFastPollData(
    [
      { status: "fulfilled", value: { status: "ok" } },
      { status: "fulfilled", value: { status: "ok", allow_upload: true, queue_enabled: true } },
      { status: "fulfilled", value: { uploaded_files: 12, uploaded_bytes: 2048 } },
      {
        status: "fulfilled",
        value: {
          running: true,
          pid: 4321,
          queue_length: 1,
          active_job: { id: "job_fast", created_at: "2026-06-14T11:00:00Z" },
        },
      },
      {
        status: "fulfilled",
        value: {
          phase: "gaussian",
          step: "250",
          percent: 0.25,
          loss: "0.12",
          uploaded_images: "66",
          scene_name: "scene_fast",
        },
      },
    ],
    { hasPointclouds: false },
  );
  assert.strictEqual(poll.failed, false);
  assert.strictEqual(poll.data.uploadHealthText, "正常");
  assert.strictEqual(poll.data.dashboardHealthText, "正常");
  assert.strictEqual(poll.data.uploadStatsText, "文件数: 12 | 字节数: 2.00 KB");
  assert.strictEqual(poll.data.pipelineRunningText, "运行中");
  assert.strictEqual(poll.data.pipelinePidText, "4321");
  assert.strictEqual(poll.data.pipelineQueueText, "等待队列:1");
  assert.strictEqual(poll.data.pipelineJobText, "job_fast | 2026-06-14T11:00:00Z");
  assert.strictEqual(poll.data.phaseKey, "gaussian");
  assert.strictEqual(poll.data.phaseCanUpload, true);
  assert.strictEqual(poll.data.pipelinePercentText, "25.0%");
  assert.deepStrictEqual(poll.data.backendPhases.map((item) => item.state), ["队列就绪", "已完成", "训练中", "生成中"]);

  const failed = model.buildFastPollData([
    { status: "rejected", reason: new Error("health failed") },
    { status: "fulfilled", value: { status: "starting" } },
    { status: "rejected", reason: new Error("stats failed") },
    { status: "rejected", reason: new Error("status failed") },
    { status: "fulfilled", value: { phase: "input" } },
  ]);
  assert.strictEqual(failed.failed, true);
  assert.strictEqual(failed.data.dashboardHealthText, "异常");
  assert.strictEqual(failed.data.uploadHealthText, "不可用");
  assert.strictEqual(failed.data.uploadStatsText, "拉取失败");
  assert.strictEqual(failed.data.pipelineRunningText, "拉取失败");
  assert.strictEqual(failed.data.phaseKey, "input");
  console.log("[OK] preview fast poll data");
}

function testMediumAndSlowPollData() {
  const medium = model.buildMediumPollData([
    { status: "fulfilled", value: { lines: ["one", "two", "three"] } },
  ]);
  assert.strictEqual(medium.failed, false);
  assert.strictEqual(medium.data.logsSummaryText, "lines:3 | latest:three");
  assert.deepStrictEqual(medium.data.latestLogLines, [
    { id: "0", text: "one" },
    { id: "1", text: "two" },
    { id: "2", text: "three" },
  ]);

  const mediumFailed = model.buildMediumPollData([{ status: "rejected", reason: new Error("logs") }]);
  assert.strictEqual(mediumFailed.failed, true);
  assert.deepStrictEqual(mediumFailed.data, { logsSummaryText: "拉取失败", latestLogLines: [] });

  const slow = model.buildSlowPollData(
    [
      {
        status: "fulfilled",
        value: { count: 2, latest_mtime: "2026-06-14 12:00:00", watch_dir: "/tmp/input" },
      },
      {
        status: "fulfilled",
        value: { latest_scene: "scene_a", dataset_count: 1, photo_scene_count: 1, pointcloud_count: 2 },
      },
      {
        status: "fulfilled",
        value: {
          summary: { count: 1, total_size: "2.00 MB", latest: { name: "scene_a_gaussian_clipped.ply" }, scenes: { scene_a: 1 } },
          items: [
            {
              id: "pc_a",
              scene: "scene_a",
              variant: "gaussian",
              name: "scene_a_gaussian_clipped.ply",
              size_bytes: 2048,
              download_url: "/download/pc_a",
            },
          ],
        },
      },
      {
        status: "fulfilled",
        value: {
          summary: { count: 1, queued: 1, running: 0, completed: 0, failed: 0 },
          items: [{ id: "job_a", status: "queued", image_count: 66 }],
        },
      },
    ],
    { dashboardUrl: "https://dashboard.example", statusTextFn: (status) => "job:" + status },
  );
  assert.strictEqual(slow.failed, false);
  assert.strictEqual(slow.data.uploadsSummaryText, "count:2 | latest:2026-06-14 12:00:00 | dir:/tmp/input");
  assert.strictEqual(slow.data.scenesSummaryText, "latest:scene_a | dataset:1 | photo:1 | pointcloud:2");
  assert.strictEqual(slow.data.pointcloudList.length, 1);
  assert.strictEqual(slow.data.pointcloudList[0].downloadUrl, "https://dashboard.example/download/pc_a");
  assert.strictEqual(slow.data.jobsSummaryText, "任务:1 | 排队:1 | 运行:0 | 完成:0 | 失败:0");
  assert.strictEqual(slow.data.jobList[0].statusText, "job:queued");
  assert.strictEqual(slow.data.jobsError, "");
  assert.strictEqual(slow.data.pointcloudError, "");

  const slowFailed = model.buildSlowPollData([
    { status: "rejected", reason: new Error("uploads") },
    { status: "fulfilled", value: {} },
    { status: "rejected", reason: new Error("pointclouds") },
    { status: "rejected", reason: new Error("jobs") },
  ]);
  assert.strictEqual(slowFailed.failed, true);
  assert.strictEqual(slowFailed.data.uploadsSummaryText, "拉取失败");
  assert.strictEqual(slowFailed.data.pointcloudError, "点云清单拉取失败，请检查 /api/pointclouds/summary");
  assert.strictEqual(slowFailed.data.jobsError, "任务队列拉取失败，请检查 /api/jobs");
  console.log("[OK] preview medium/slow poll data");
}

function testActionResultBuilders() {
  assert.deepStrictEqual(model.buildActionSuccessData("启动流程", { ok: true, pid: 1234 }), {
    ok: true,
    actionMessage: '启动流程成功：{"ok":true,"pid":1234}',
    toastTitle: "启动流程成功",
  });
  assert.deepStrictEqual(model.buildActionSuccessData("停止流程", { ok: false, error: "not running" }), {
    ok: false,
    error: "not running",
  });
  assert.deepStrictEqual(model.buildActionFailureData("导出Gaussian", new Error("export failed")), {
    actionMessage: "导出Gaussian失败：export failed",
    toastTitle: "导出Gaussian失败",
  });
  assert.deepStrictEqual(model.buildCancelSuccessData("job_a"), {
    actionMessage: "取消任务成功：job_a",
    toastTitle: "已取消",
  });
  assert.deepStrictEqual(model.buildCancelFailureData(new Error("cannot cancel")), {
    actionMessage: "取消任务失败：cannot cancel",
    toastTitle: "取消失败",
  });
  console.log("[OK] preview action result builders");
}

function testPhasePolicy() {
  ["idle", "input", "upload", "stopped", "unknown"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), true);
  });
  assert.strictEqual(model.canUploadByPhase(" INPUT "), true);
  ["spann3r", "gaussian", "export", "completed", "failed"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), false);
  });
  assert.strictEqual(model.canCancelJobStatus(" READY "), true);
  assert.strictEqual(
    model.toDashboardAbsoluteUrl("/healthz", "https://dashboard.example/"),
    "https://dashboard.example/healthz",
  );
  assert.strictEqual(model.withQuery("https://a/b?x=1", "y=2"), "https://a/b?x=1&y=2");
  console.log("[OK] preview state phase/url policy");
}

function main() {
  testBasics();
  testJobNormalization();
  testPointcloudNormalization();
  testSummaryBuilders();
  testStatusAndProgressParsing();
  testBackendPhaseBuilders();
  testFastPollData();
  testMediumAndSlowPollData();
  testActionResultBuilders();
  testPhasePolicy();
  console.log("[OK] preview state model checks passed");
}

main();
