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

function testPhasePolicy() {
  ["idle", "input", "upload", "stopped", "unknown"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), true);
  });
  ["spann3r", "gaussian", "export", "completed", "failed"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), false);
  });
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
  testPhasePolicy();
  console.log("[OK] preview state model checks passed");
}

main();
