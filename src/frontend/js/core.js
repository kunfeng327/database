// core.js — 全局状态、$ 选择器、fetch 封装、toast、转义与金额格式化
const $ = s => document.querySelector(s);
let ME = null;                 // 当前登录用户 {name, role, elder_id, caregiver_id}
let elderList = [];
let orderList = [];
let qualityCaregivers = [];
let communityList = [];
let carePlanList = [];

async function API(url, opts) {
  const r = await fetch(url, { headers:{'Content-Type':'application/json'}, ...opts,
    body: opts && opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({ok:false, msg:'网络错误'}));
  if (r.status === 401) { showLogin(); throw new Error(j.msg || '请先登录'); }
  return j;
}
function toast(msg, err=false) {
  const t = $('#toast');
  t.textContent = msg; t.className = err ? 'err' : ''; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 3500);
}
function esc(s){ return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
const fmtYuan = n => '￥' + Number(n).toFixed(2);
