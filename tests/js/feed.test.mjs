// Подгрузка «Всех примеров» порциями (static/feed.js): следующая порция, конец, один запрос за раз, ошибка.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createFeed, Phase } from "../../genfacade/viewer/static/feed.js";

const pages = (n) => async (page) => ({ items: [`p${page}`], pages: n });

test("порции идут по порядку и дописываются в конец", async () => {
  const feed = createFeed(pages(3));
  await feed.more();
  await feed.more();
  assert.deepEqual(feed.items, ["p1", "p2"]);
  assert.equal(feed.phase, Phase.IDLE);
});

test("последняя порция — конец, дальше запросов нет", async () => {
  const asked = [];
  const feed = createFeed(async (p) => { asked.push(p); return { items: [p], pages: 2 }; });
  await feed.more();
  await feed.more();
  assert.equal(feed.phase, Phase.DONE);
  assert.equal(await feed.more(), false);
  assert.deepEqual(asked, [1, 2]);
});

test("пока запрос в полёте, второй не уходит", async () => {
  let asked = 0, release;
  const feed = createFeed(() => { asked += 1; return new Promise((r) => { release = r; }); });
  const first = feed.more();
  assert.equal(await feed.more(), false);
  release({ items: ["a"], pages: 5 });
  await first;
  assert.equal(asked, 1);
  assert.deepEqual(feed.items, ["a"]);
});

test("ошибка — состояние; повтор просит ту же порцию", async () => {
  let fail = true;
  const asked = [];
  const feed = createFeed(async (p) => {
    asked.push(p);
    if (fail) throw new Error("сеть");
    return { items: [p], pages: 1 };
  });
  await feed.more();
  assert.equal(feed.phase, Phase.ERROR);
  assert.equal(feed.error.message, "сеть");
  fail = false;
  await feed.more();
  assert.deepEqual(asked, [1, 1]);
  assert.equal(feed.phase, Phase.DONE);
  assert.equal(feed.error, null);
});

test("сброс начинает с первой порции и отбрасывает запоздавший ответ", async () => {
  const waiting = [];
  const feed = createFeed((p) => new Promise((r) => waiting.push([p, r])));
  const old = feed.more();
  feed.reset();
  const fresh = feed.more();
  waiting[0][1]({ items: ["старый"], pages: 9 });
  await old;
  assert.deepEqual(feed.items, []);
  waiting[1][1]({ items: ["новый"], pages: 9 });
  await fresh;
  assert.deepEqual(feed.items, ["новый"]);
  assert.equal(feed.next, 2);
});
