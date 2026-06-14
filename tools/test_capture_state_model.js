const assert = require("assert");
const path = require("path");

const model = require(path.join("..", "frontend", "utils", "capture_state_model"));

function testPhaseParsingAndText() {
  assert.strictEqual(model.getPhaseFromProgress({ phase: "gaussian", stage: "input" }), "gaussian");
  assert.strictEqual(model.getPhaseFromProgress({ stage: "spann3r" }), "spann3r");
  assert.strictEqual(model.getPhaseFromProgress({}), "unknown");
  assert.strictEqual(model.getPhaseText("input"), "input（可上传）");
  assert.strictEqual(model.getPhaseText("custom"), "custom（未知映射）");
  console.log("[OK] capture phase parsing");
}

function testUploadPolicy() {
  ["idle", "input", "upload", "stopped", "unknown"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), true);
  });
  assert.strictEqual(model.canUploadByPhase(" INPUT "), true);
  ["spann3r", "gaussian", "export", "completed", "failed"].forEach((phase) => {
    assert.strictEqual(model.canUploadByPhase(phase), false);
  });
  assert.strictEqual(model.isUploadAllowed("input", true, true), true);
  assert.strictEqual(model.isUploadAllowed("input", false, true), false);
  assert.strictEqual(model.isUploadAllowed("gaussian", true, true), false);
  assert.strictEqual(model.isUploadAllowed("gaussian", true, true, true), true);
  assert.strictEqual(model.isUploadAllowed("input", true, true, false), false);
  console.log("[OK] capture upload policy");
}

function testStatusLabels() {
  assert.strictEqual(model.getBackendStatusLabel("input", true, true), "后端就绪");
  assert.strictEqual(model.getBackendStatusClass("input", true, true), "ok");
  assert.strictEqual(model.getBackendStatusLabel("input", false, false), "等待服务");
  assert.strictEqual(model.getBackendStatusClass("input", false, false), "idle");
  assert.strictEqual(model.getBackendStatusLabel("input", false, true), "等待上传服务");
  assert.strictEqual(model.getBackendStatusClass("input", false, true), "warn");
  assert.strictEqual(model.getBackendStatusLabel("spann3r", true, true), "重建中");
  assert.strictEqual(model.getBackendStatusLabel("gaussian", true, true), "训练中");
  assert.strictEqual(model.getBackendStatusLabel("export", true, true), "导出中");
  assert.strictEqual(model.getBackendStatusLabel("completed", true, true), "已完成");
  assert.strictEqual(model.getBackendStatusLabel("failed", true, true), "失败");
  assert.strictEqual(model.getUploadBlockLabel("gaussian", true, true), "训练中");
  assert.strictEqual(model.getUploadBlockLabel("input", false, true), "等待上传服务");
  console.log("[OK] capture status labels");
}

function testPhaseState() {
  const ready = model.buildPhaseState("input", true, true, undefined, true);
  assert.deepStrictEqual(ready, {
    currentPhase: "input",
    phaseText: "input（可上传）",
    phaseAllowUpload: true,
    backendStatusLabel: "后端就绪",
    backendStatusClass: "ok",
    uploadBlockLabel: "暂不可传",
    uploadHealthOk: true,
    dashboardHealthOk: true,
    queueUploadEnabled: true,
    phaseHint: "队列上传就绪，可继续提交新任务",
  });

  const blocked = model.buildPhaseState("gaussian", true, true, undefined, false);
  assert.strictEqual(blocked.phaseAllowUpload, false);
  assert.strictEqual(blocked.backendStatusLabel, "训练中");
  assert.strictEqual(blocked.uploadBlockLabel, "训练中");
  assert.strictEqual(blocked.phaseHint, "当前为查看或导出阶段，上传暂不可用");
  console.log("[OK] capture phase state");
}

function main() {
  testPhaseParsingAndText();
  testUploadPolicy();
  testStatusLabels();
  testPhaseState();
  console.log("[OK] capture state model checks passed");
}

main();
