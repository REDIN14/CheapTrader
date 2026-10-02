import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BALANCE_MAX,
  NAME_MAX,
  balanceProblem,
  historyLabel,
  nameProblem,
  nextProfileName,
  parseBalance,
  returnLabel,
} from "../src/lib/profiles";
import type { ReplayProfile } from "../src/lib/types";

const profile = (id: string, name: string, change: Partial<ReplayProfile> = {}): ReplayProfile => ({
  id,
  name,
  initial_balance: 10_000,
  balance: 10_000,
  realized: 0,
  return_pct: 0,
  trades: 0,
  wins: 0,
  losses: 0,
  open_positions: 0,
  created_at: 0,
  updated_at: 0,
  ...change,
});

test("a new profile is called Paper account, then Paper account 2, 3 …", () => {
  assert.equal(nextProfileName([]), "Paper account");
  assert.equal(nextProfileName(["Paper account"]), "Paper account 2");
  assert.equal(nextProfileName(["Paper account", "Paper account 2"]), "Paper account 3");
  // the first free number, whatever the letters, and a gap is filled
  assert.equal(nextProfileName(["paper ACCOUNT", "Paper account 3"]), "Paper account 2");
  assert.equal(nextProfileName(["Swing"]), "Paper account");
});

test("a name has to be there, short enough and not taken", () => {
  const list = [profile("a", "Swing"), profile("b", "Scalp")];
  assert.equal(nameProblem("New one", list), null);
  assert.match(nameProblem("   ", list) ?? "", /name/);
  assert.match(nameProblem("x".repeat(NAME_MAX + 1), list) ?? "", /40/);
  assert.equal(nameProblem("x".repeat(NAME_MAX), list), null);
  assert.match(nameProblem("  swing ", list) ?? "", /already.*Swing/);
  // renaming a profile to its own name (or other letters of it) is fine, to another's is not
  assert.equal(nameProblem("SWING", list, "a"), null);
  assert.match(nameProblem("scalp", list, "a") ?? "", /Scalp/);
});

test("a balance can be typed the way people write numbers", () => {
  const cases: [string, number][] = [
    ["10000", 10_000],
    ["  10000  ", 10_000],
    ["10 000", 10_000],
    ["10 000", 10_000],
    ["10'000", 10_000],
    ["10,000", 10_000],
    ["1,234,567", 1_234_567],
    ["1.234.567", 1_234_567],
    ["10,000.50", 10_000.5],
    ["10.000,50", 10_000.5],
    ["10000.5", 10_000.5],
    ["10000,5", 10_000.5],
    ["2500.75", 2_500.75],
    ["0.5", 0.5],
    ["0,5", 0.5],
    ["10.000", 10_000], // a dot and three digits: ten thousand, never ten with three decimals
    ["100.000", 100_000],
    ["1000.000", 1_000],
    ["5", 5],
  ];
  for (const [text, value] of cases) assert.equal(parseBalance(text), value, `“${text}”`);
});

test("what is not a number is not accepted", () => {
  for (const text of ["", "   ", "abc", "10k", "-5", "1e5", "1.2,3.4", "1..2", ".5", "10,,000x", "€100", "0x10"]) {
    assert.equal(parseBalance(text), null, `“${text}”`);
  }
});

test("a balance has to be between 1 and a billion", () => {
  assert.equal(balanceProblem("10000"), null);
  assert.equal(balanceProblem("1"), null);
  assert.equal(balanceProblem(String(BALANCE_MAX)), null);
  assert.match(balanceProblem("0") ?? "", /at least 1/);
  assert.match(balanceProblem("0.5") ?? "", /at least 1/);
  assert.match(balanceProblem("1000000001") ?? "", /more than/);
  assert.match(balanceProblem("lots") ?? "", /number/);
  assert.match(balanceProblem("") ?? "", /number/);
});

test("a return is written with its sign", () => {
  assert.equal(returnLabel(2.5), "+2.50 %");
  assert.equal(returnLabel(-1.234), "−1.23 %");
  assert.equal(returnLabel(0), "0.00 %");
  assert.equal(returnLabel(0.001), "0.00 %");
  assert.equal(returnLabel(-0.001), "0.00 %");
});

test("a profile's history is described in a few words", () => {
  assert.equal(historyLabel(profile("a", "A")), "no trades yet");
  assert.equal(historyLabel(profile("a", "A", { trades: 1, wins: 1 })), "1 trade · 1 won, 0 lost");
  assert.equal(historyLabel(profile("a", "A", { trades: 14, wins: 8, losses: 6 })), "14 trades · 8 won, 6 lost");
  assert.equal(historyLabel(profile("a", "A", { trades: 2, wins: 1, losses: 1, open_positions: 1 })), "2 trades · 1 won, 1 lost · 1 open");
  assert.equal(historyLabel(profile("a", "A", { open_positions: 2 })), "no trades yet · 2 open");
});
