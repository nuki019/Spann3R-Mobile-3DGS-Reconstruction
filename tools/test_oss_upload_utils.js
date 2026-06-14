const assert = require("assert");
const path = require("path");

const uploadUtils = require(path.join("..", "frontend", "utils", "oss_upload_utils"));

function testUploadResultParsing() {
  assert.deepStrictEqual(uploadUtils.parseUploadResult({ statusCode: 404 }), {
    ok: false,
    message: "HTTP 404",
  });
  assert.deepStrictEqual(uploadUtils.parseUploadResult({ statusCode: 200, data: "" }), {
    ok: true,
    message: "",
  });
  assert.deepStrictEqual(uploadUtils.parseUploadResult({ statusCode: 200, data: "{\"code\":200}" }), {
    ok: true,
    message: "",
  });
  assert.deepStrictEqual(uploadUtils.parseUploadResult({ statusCode: 200, data: { code: 500, msg: "bad" } }), {
    ok: false,
    message: "bad",
  });
  assert.deepStrictEqual(uploadUtils.parseUploadResult({ statusCode: 200, data: { ok: false, message: "blocked" } }), {
    ok: false,
    message: "blocked",
  });
  console.log("[OK] upload result parsing");
}

function testUploadServiceHealthParsing() {
  assert.deepStrictEqual(
    uploadUtils.parseUploadServiceReadyResult({ statusCode: 200, data: { status: "ok", allow_upload: true } }),
    { ok: true, message: "" },
  );
  assert.deepStrictEqual(
    uploadUtils.parseUploadServiceReadyResult({ statusCode: 200, data: { status: "ok", allow_upload: false } }),
    { ok: false, message: "上传服务已连接，但当前阶段暂不接收新照片" },
  );
  assert.deepStrictEqual(
    uploadUtils.parseUploadServiceReadyResult({ statusCode: 200, data: { status: "starting" } }),
    { ok: false, message: "上传服务检查失败（6008 /upload-proxy/healthz）：status!=ok" },
  );
  assert.deepStrictEqual(
    uploadUtils.parseUploadServiceReadyResult({ statusCode: 404 }),
    { ok: false, message: "上传服务检查失败（6008 /upload-proxy/healthz）：HTTP 404" },
  );
  assert.strictEqual(
    uploadUtils.buildUploadServiceNetworkMessage({ errMsg: "timeout" }),
    "上传服务检查失败（6008 /upload-proxy/healthz）：timeout",
  );
  console.log("[OK] upload service health parsing");
}

function main() {
  testUploadResultParsing();
  testUploadServiceHealthParsing();
  console.log("[OK] oss upload utils checks passed");
}

main();
