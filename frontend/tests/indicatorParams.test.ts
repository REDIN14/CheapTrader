import assert from "node:assert/strict";
import { test } from "node:test";
import { paramText, paramsFromRows, rowsFromParams, sameParams } from "../src/lib/indicatorParams";

test("the settings show each parameter as a row of text", () => {
  assert.deepEqual(rowsFromParams({ period: 20, std: 2.5, source: "close" }), [
    { key: "period", value: "20" },
    { key: "std", value: "2.5" },
    { key: "source", value: "close" },
  ]);
  assert.deepEqual(rowsFromParams(null), []);
});

test("what was typed becomes numbers where it reads as one", () => {
  assert.deepEqual(
    paramsFromRows([
      { key: "period", value: "50" },
      { key: " std ", value: "2.5" },
      { key: "source", value: "close" },
      { key: "", value: "7" }, // a row without a name is left out
      { key: "empty", value: "" },
    ]),
    { period: 50, std: 2.5, source: "close", empty: "" },
  );
});

test("parameters typed back to what they were are the same", () => {
  assert.equal(sameParams({ period: 20 }, { period: 20 }), true);
  assert.equal(sameParams({ period: "20" }, { period: 20 }), true);
  assert.equal(sameParams({ period: 50 }, { period: 20 }), false);
  assert.equal(sameParams({ period: 20 }, { period: 20, std: 2 }), false);
  assert.equal(sameParams({}, null), true);
});

test("the legend shows the values after the name", () => {
  assert.equal(paramText({ period: 50 }), "50");
  assert.equal(paramText({ period: 20, std: 2 }), "20 2");
  assert.equal(paramText({ fast: 12, slow: 26, signal: 9 }), "12 26 9");
  assert.equal(paramText({ source: "close", period: 9 }), "close 9");
  // nothing long or nested, and no more than four
  assert.equal(paramText({ a: 1, b: 2, c: 3, d: 4, e: 5 }), "1 2 3 4");
  assert.equal(paramText({ levels: [1, 2], note: "a very long piece of text", n: 3 }), "3");
  assert.equal(paramText({}), "");
  assert.equal(paramText(undefined), "");
});
