// Seasonal themes, the same rule as src/dharmeme/themes.py: a festival theme (one with
// `dates`) is offered from two weeks before one of its dates until a few days after.
export const DAYS_BEFORE = 14;
export const DAYS_AFTER = 3;

// Today's date in Singapore, as YYYY-MM-DD, whatever the visitor's own time zone.
export function todaySgt(now = Date.now()) {
  return new Date(now + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

export function inSeason(theme, today) {
  if (!theme.dates) return true;
  const t = Date.parse(today);
  return theme.dates.some((d) => {
    const days = (Date.parse(d) - t) / 86400000;
    return days >= -DAYS_AFTER && days <= DAYS_BEFORE;
  });
}

// The themes to show today: festivals in season first, then the evergreen ones.
export function offered(themes, today = todaySgt()) {
  const current = themes.filter((t) => inSeason(t, today));
  return [...current.filter((t) => t.dates), ...current.filter((t) => !t.dates)];
}
