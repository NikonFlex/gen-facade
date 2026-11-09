// Запрос «Все примеры» без фильтра по разбиению (static/query.js): пустое поле не уходит на сервер.
import assert from "node:assert/strict";
import { test } from "node:test";

import { query } from "../../genfacade/viewer/static/query.js";

test("пустые поля не попадают в запрос", () => {
  assert.equal(query({ page: 1, split: "", q: null }).toString(), "page=1");
});

test("заданный фильтр остаётся", () => {
  assert.equal(query({ page: 2, split: "val", q: "tiny" }).toString(), "page=2&split=val&q=tiny");
});
