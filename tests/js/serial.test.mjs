// Очередь отметок страницы проверки (static/serial.js): «Не годен» и причина — два запроса
// подряд; второй уходит только после ответа на первый, отказ первого второй не отменяет.
import assert from "node:assert/strict";
import { test } from "node:test";

import { serial } from "../../genfacade/viewer/static/serial.js";

const later = (ms, value) => new Promise((ok) => setTimeout(() => ok(value), ms));

// Медленная задача (30 мс) и быстрая с ключами keys; порядок, в котором они закончились.
async function finished(keys) {
  const queue = serial(), done = [];
  await Promise.all(keys.map((key, i) => queue(key, () => later(i ? 0 : 30).then(() => done.push(i)))));
  return done;
}

test("задачи с одним ключом идут по очереди: медленная первая не обгоняется", async () => {
  assert.deepEqual(await finished(["A", "A"]), [0, 1]);
});

test("отказ задачи доходит до её вызова, но не останавливает следующую", async () => {
  const queue = serial();
  const failed = queue("A", () => Promise.reject(new Error("нет")));
  await assert.rejects(failed, /нет/);
  assert.equal(await queue("A", () => "дальше"), "дальше");
});

test("разные ключи друг друга не ждут", async () => {
  assert.deepEqual(await finished(["A", "B"]), [1, 0]);
});
