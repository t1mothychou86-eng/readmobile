import { accessReminders } from '../access';
import type { Settings } from '../types';
export function AccessReminder({ settings }: { settings: Settings }) {
  const reminders = accessReminders(settings);
  return reminders.length > 0 ? <aside class="access-reminder notice" role="status"><div><strong>机构访问到期提醒</strong>{reminders.map(r => <p key={r.id}>{r.name} · {r.remaining < 0 ? `已到期 ${-r.remaining} 天` : r.remaining === 0 ? '今天到期' : `${r.remaining} 天后到期`}（{r.expiresOn}）</p>)}<a href="#access">更新日期 →</a><p class="hint">按你记录的日期估算，不代表当前登录状态。</p></div></aside> : null;
}
