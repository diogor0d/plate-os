export function formatMealTime(instant: string, timeZone?: string, locale?: string): string {
  return new Date(instant).toLocaleTimeString(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });
}

export function dateRangeEndingOn(end: string, days: number): { start: string; end: string } {
  const [year, month, day] = end.split("-").map(Number);
  const start = new Date(Date.UTC(year, month - 1, day - days + 1));
  return { start: start.toISOString().slice(0, 10), end };
}
