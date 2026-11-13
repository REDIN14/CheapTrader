/** A requested historical moment, independent of which candles happen to be loaded. */
export function replayDate(day: string, clock: string, intraday: boolean): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const time = intraday ? clock || "00:00" : "00:00";
  const date = new Date(`${day}T${time}Z`);
  const value = date.getTime() / 1000;
  return Number.isFinite(value) && date.toISOString().slice(0, 10) === day ? value : null;
}
