import assert from "node:assert/strict";
import { test } from "node:test";
import { createSyncCourse } from "../src/syncStream.ts";

test("StrictMode subscribers share one request and receive earlier events", async () => {
  let requests = 0;
  let controller;
  const sync = createSyncCourse(async () => {
    requests++;
    return new Response(new ReadableStream({ start(value) { controller = value; } }));
  });
  const first = [], second = [];
  const pending = sync(1, (event) => first.push(event));
  await new Promise((resolve) => setTimeout(resolve, 0));
  controller.enqueue(new TextEncoder().encode('{"item":"lecture.txt","status":"done"}\n'));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const repeated = sync(1, (event) => second.push(event));
  controller.enqueue(new TextEncoder().encode('{"done":true,"failed":0}'));
  controller.close();
  await Promise.all([pending, repeated]);
  assert.equal(requests, 1);
  assert.deepEqual(first, second);
  assert.equal(second.length, 2);
});

test("Tauri string errors are preserved and a later request can retry", async () => {
  let attempts = 0;
  const sync = createSyncCourse(async () => {
    if (++attempts === 1) throw "error decoding response body";
    return new Response('{"done":true}\n');
  });
  await assert.rejects(sync(1, () => {}), /error decoding response body/);
  await sync(1, () => {});
  assert.equal(attempts, 2);
});

test("truncated streams fail instead of being marked successful", async () => {
  const sync = createSyncCourse(async () => new Response('{"item":"lecture.txt","status":"done"}\n'));
  await assert.rejects(sync(1, () => {}), /stopped before completion/);
});
