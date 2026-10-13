import type { AccessRecord, Settings } from './types';
export const publishers = [
  { id: 'elsevier', name: 'Elsevier / ScienceDirect', journals: 'JFE', url: 'https://www.elsevier.support/sciencedirect/answer/how-do-i-activate-and-use-remote-access-in-sciencedirect', steps: '在校园网内用 Safari 确认机构订阅可用，再从页脚 Remote access 按官方步骤设置个人 Elsevier 账号的远程访问。', duration: '官方范围为 24 小时至 180 天，依机构设置而定；请填你实际获准的天数。' },
  { id: 'wiley', name: 'Wiley', journals: 'JF、ECTA', url: 'https://onlinelibrary.wiley.com/researchers/read/access-options', steps: '在校园网内登录个人 Wiley Online Library 账号，账号可关联机构；离校后用同一账号访问机构订阅内容。', duration: '官方说明：上述个人 Wiley 账号关联方式为 60 天。其他访问方式请以学校说明为准。' },
  { id: 'oup', name: 'Oxford University Press', journals: 'QJE、RES、RFS', url: 'https://academic.oup.com/pages/get-help-with-access/institutional-access', steps: '先在校园网内确认 IP 认证。校外可使用学校支持的代理或机构登录（Shibboleth / OpenAthens）；通过图书馆提供的入口进入。', duration: '该说明未给出统一配对天数；如学校提供期限，请自行填写。' },
  { id: 'uchicago', name: 'UChicago Press', journals: 'JPE', url: 'https://www.journals.uchicago.edu/inst/lib-faq', steps: '在校园网内使用机构登记的 IP 访问。校外按图书馆的代理或 Shibboleth 指引操作；机构未被识别时请联系图书馆。', duration: '该说明未给出统一配对天数；如学校提供期限，请自行填写。' },
  { id: 'aea', name: 'American Economic Association', journals: 'AER', url: 'https://www.aeaweb.org/journals/subscriptions', steps: '在校园网内通过图书馆的 AEA 订阅入口确认可用；校外访问方式请向图书馆确认，不把个人会员登录当作机构配对。', duration: '该说明未给出统一配对天数；如学校提供期限，请自行填写。' },
  { id: 'jstor', name: 'JSTOR', journals: '期刊档案', url: 'https://support.jstor.org/hc/en-us/articles/115004983547-Access-Management-Overview', durationURL: 'https://support.jstor.org/hc/en-us/articles/7439227268887-User-Management-Overview', steps: '在校园网或学校登记的远程入口登录个人 JSTOR 账号，可与机构配对；以后再次这样登录可续期。', duration: '官方说明：个人账号配对为 365 天；管理员可提前终止，实际权限以 JSTOR 为准。' },
];
export function safariURL(url: string): string | undefined {
  try { const parsed = new URL(url); return parsed.protocol === 'https:' && !parsed.username && !parsed.password ? `x-safari-https://${parsed.host}${parsed.pathname}${parsed.search}${parsed.hash}` : undefined; } catch { return undefined; }
}
// Treat dates as local calendar days, rather than elapsed hours (DST-safe).
function calendarDay(value: string): number | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return;
  const time = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(time) || new Date(time).toISOString().slice(0, 10) !== value) return;
  return time / 86400000;
}
export function validAccess(record: AccessRecord): boolean {
  return calendarDay(record.pairedOn) !== undefined && Number.isInteger(record.days) && record.days > 0 && record.days <= 36500;
}
export function accessReminders(settings: Settings, now = new Date()) {
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86400000;
  return publishers.flatMap(publisher => {
    const record = settings.access?.[publisher.id];
    if (!record || !validAccess(record)) return [];
    const expires = calendarDay(record.pairedOn)! + record.days;
    const remaining = expires - today;
    return remaining <= 7 ? [{ ...publisher, remaining, expiresOn: new Date(expires * 86400000).toISOString().slice(0, 10) }] : [];
  });
}
