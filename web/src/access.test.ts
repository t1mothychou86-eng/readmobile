import { expect, it } from 'vitest';
import { accessReminders, safariURL, validAccess } from './access';
import { emptyState } from './store';
const settings = emptyState().settings;
it('converts HTTPS links preserving encoded paths, query and fragment', () => {
  expect(safariURL('https://doi.org/10.1/a%20b?x=1#abstract')).toBe('x-safari-https://doi.org/10.1/a%20b?x=1#abstract');
  for (const url of ['http://example.org', 'javascript:alert(1)', 'https://user:password@example.org', 'not-a-url']) expect(safariURL(url)).toBeUndefined();
});
it.each([['2026-10-05', 0], ['2026-10-06', 1], ['2026-10-12', 7], ['2026-10-04', -1]])('reminds near and after expiry (%s)', (pairedOn, remaining) => {
  expect(accessReminders({ ...settings, access: { wiley: { pairedOn, days: 8 } } }, new Date(2026, 9, 13, 23, 59))[0].remaining).toBe(remaining);
});
it('ignores missing, invalid and distant records and handles leap years', () => {
  expect(accessReminders(settings)).toEqual([]);
  expect(accessReminders({ ...settings, access: { wiley: { pairedOn: '2026-10-13', days: 8 }, oup: { pairedOn: '2026-02-30', days: 1 } } }, new Date(2026, 9, 13))).toEqual([]);
  expect(validAccess({ pairedOn: '2024-02-29', days: 1 })).toBe(true);
  for (const days of [0, -1, 1.5, NaN, Infinity]) expect(validAccess({ pairedOn: '2026-10-13', days })).toBe(false);
  expect(accessReminders({ ...settings, access: { jstor: { pairedOn: '2024-02-29', days: 365 } } }, new Date(2025, 1, 28))[0].remaining).toBe(0);
});
