// subsidy.js — 线5：补贴申报与审核、业务总览看板
/* ================= 补贴 ================= */
const SUBSIDY_PERIOD_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
let subsidyPolicyTimer = null;
let subsidyPolicyReq = 0;

function setSubsidyPolicyState(msg){
  const sel = $('#c-policy');
  sel.innerHTML = '<option value="">暂无可申报补贴</option>';
  sel.disabled = true;
  $('#claim-submit').disabled = true;
  $('#c-policy-hint').textContent = msg;
}

/* 按「老人 + 账期」向后端取可申报政策：只把 claimable 的项放进下拉框 */
async function loadEligibleSubsidyPolicies(){
  const seq = ++subsidyPolicyReq;
  const elderId = +($('#c-elder').value || 0);
  const period = $('#c-period').value.trim();
  if (!elderId) return setSubsidyPolicyState('请先选择老人，系统会自动筛出该老人可申报的补贴');
  if (!SUBSIDY_PERIOD_RE.test(period))
    return setSubsidyPolicyState('账期请填写 YYYY-MM（如 2026-10），填好后自动筛选可申报补贴');

  const r = await API(`/api/subsidy/eligible-policies?elder_id=${elderId}&period=${encodeURIComponent(period)}`);
  if (seq !== subsidyPolicyReq) return;  // 只采用最后一次请求的结果
  if (!r.ok) return setSubsidyPolicyState(r.msg || '筛选可申报补贴失败');

  const data = r.data || {};
  const policies = data.policies || [];
  const claimable = policies.filter(p => p.claimable);
  const blocked = policies.filter(p => !p.claimable);

  const sel = $('#c-policy');
  sel.disabled = !claimable.length;
  $('#claim-submit').disabled = !claimable.length;
  sel.innerHTML = claimable.length
    ? claimable.map(p => `<option value="${p.policy_id}">${esc(p.district)} · ${esc(p.target_type)} · ${esc(p.item_name)}（${fmtYuan(p.standard)}/次 · ${p.order_count} 笔订单）</option>`).join('')
    : '<option value="">暂无可申报补贴</option>';

  const e = data.elder || {};
  const tags = (e.special_tag || '').split(',').filter(Boolean).join('/') || '无标签';
  const head = `当前老人：${esc(e.name)}（${esc(e.community)} · ${esc(e.district)}，${esc(tags)}）｜账期 ${esc(period)}：可申报 ${claimable.length} 项`;
  const extras = [];
  if (blocked.length) {
    extras.push(`已隐藏 ${blocked.length} 项（${blocked.map(p => `${esc(p.item_name)}：${esc(p.block_reason)}`).join('；')}）`);
  }
  if (data.excluded_count) extras.push(`另有 ${data.excluded_count} 项因区县或对象类别不符，不适用该老人`);
  if (!claimable.length && !blocked.length) extras.push('该区县暂无适用于该老人标签的有效政策');
  $('#c-policy-hint').innerHTML = extras.length ? `${head}<br>${extras.join('；')}` : head;
}

async function loadSubsidy(){
  if (!['家属','社区管理员','监管人员'].includes(ME.role)) return;
  const isReg = ME.role === '监管人员';
  const isAdmin = ME.role === '社区管理员';

  if (isAdmin) {
    const normalElders = elderList.filter(e => e.elder_status === '正常');
    const selected = $('#c-elder').value;
    $('#c-elder').innerHTML = normalElders.map(e =>
      `<option value="${e.elder_id}">${esc(e.name)}（${esc(e.community)}）</option>`).join('');
    if (selected && normalElders.some(e => String(e.elder_id) === selected)) $('#c-elder').value = selected;
    if (!$('#c-period').value) {
      const d = new Date(); d.setMonth(d.getMonth() - 1);
      $('#c-period').value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    }
    loadEligibleSubsidyPolicies();
  }

  const clm = await API('/api/subsidy/claims');
  $('#claim-table tbody').innerHTML = clm.ok ? clm.data.map(c => {
    let act = '—';
    if (isReg) {
      if (c.audit_status === '待审核') act = `<button class="btn small" onclick="audit(${c.claim_id},'approve')">街道审核</button> <button class="btn small warn" onclick="audit(${c.claim_id},'reject')">驳回</button>`;
      else if (c.audit_status === '街道已审') act = `<button class="btn small" onclick="audit(${c.claim_id},'pass')">终审通过</button> <button class="btn small warn" onclick="audit(${c.claim_id},'reject')">驳回</button>`;
      else if (c.audit_status === '通过' && c.pay_status === '未拨付') act = `<button class="btn small" onclick="audit(${c.claim_id},'pay')">确认拨付</button>`;
    }
    const auditBadge = {'待审核':'b-wait','街道已审':'b-disp','通过':'b-done','驳回':'b-canc'}[c.audit_status];
    const payBadge = c.pay_status === '已拨付' ? 'b-done' : 'b-canc';
    return `<tr><td>${c.claim_id}</td><td>${esc(c.elder_name)}</td><td>${esc(c.district)}</td>
      <td><span class="tag">${esc(c.target_type)}</span></td><td>${esc(c.item_name)}</td>
      <td>${c.claim_period}</td><td>${fmtYuan(c.amount)}</td>
      <td><span class="badge ${auditBadge}">${c.audit_status}</span></td>
      <td><span class="badge ${payBadge}">${c.pay_status}</span></td><td>${esc(c.reviewer)||'—'}</td>
      <td class="${isReg?'':'hide'}">${act}</td></tr>`;
  }).join('') : '';
}
$('#claim-form').onsubmit = async ev => {
  ev.preventDefault();
  const policyId = +($('#c-policy').value || 0);
  if (!policyId) { toast('当前没有可申报的补贴，请先确认老人与账期', true); return; }
  const r = await API('/api/subsidy/claims', {method:'POST', body:{
    elder_id:+$('#c-elder').value, policy_id:policyId, claim_period:$('#c-period').value.trim()}});
  r.ok ? toast(`申报成功：${r.data.order_ids.length} 笔订单，金额 ${fmtYuan(r.data.amount)}`)
       : toast('申报被拒绝：' + r.msg, true);
  loadSubsidy(); loadStats();
};
if ($('#c-elder')) $('#c-elder').addEventListener('change', loadEligibleSubsidyPolicies);
if ($('#c-period')) $('#c-period').addEventListener('input', () => {
  clearTimeout(subsidyPolicyTimer);
  subsidyPolicyTimer = setTimeout(loadEligibleSubsidyPolicies, 300);
});
async function audit(id, action){
  const r = await API(`/api/subsidy/claims/${id}/audit`, {method:'POST', body:{action}});
  r.ok ? toast(`申报 ${id}：审核「${r.data.audit_status}」，拨付「${r.data.pay_status}」`) : toast(r.msg, true);
  loadSubsidy(); loadStats(); loadLine5Overview();
}

/* ================= 线5业务总览 ================= */
function goToLine5Tab(tab){
  const button = document.querySelector(`#nav button[data-tab="${tab}"]`);
  if (button) button.click();
}

async function loadLine5Overview(){
  if (!['社区管理员','监管人员'].includes(ME.role)) return;
  if ($('#tab-line5').classList.contains('hide')) return;
  const [policyRes, claimRes, qualityRes, caregiverRes] = await Promise.all([
    API('/api/subsidy/policies'),
    API('/api/subsidy/claims'),
    API('/api/quality/inspections'),
    API('/api/quality/caregivers')
  ]);
  if (!claimRes.ok || !qualityRes.ok) return;
  const claims = claimRes.data || [];
  const inspections = qualityRes.data || [];
  const pendingAudit = claims.filter(c => c.audit_status === '待审核').length;
  const pendingPayment = claims.filter(c => c.audit_status === '通过' && c.pay_status === '未拨付').length;
  const paidAmount = claims.filter(c => c.pay_status === '已拨付')
    .reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const pendingInspection = inspections.filter(q => q.inspection_status === '待抽查').length;
  const openRectify = inspections.filter(q => ['待整改','整改中'].includes(q.rectification_status)).length;

  const metrics = [
    ['待街道审核', pendingAudit, '📝', 'i-yellow'],
    ['待确认拨付', pendingPayment, '💳', 'i-blue'],
    ['已拨付金额', fmtYuan(paidAmount), '💰', 'i-teal'],
    ['待录入抽查', pendingInspection, '🔎', 'i-purple'],
    ['未完成整改', openRectify, '⚠️', 'i-orange']
  ];
  $('#line5-metrics').innerHTML = metrics.map(([label, value, icon, cls]) =>
    `<div class="stat"><div class="icon ${cls}">${icon}</div><div>
      <div class="num">${value}</div><div class="label">${label}</div></div></div>`).join('');

  const queue = claims.filter(c =>
    c.audit_status === '待审核' || c.audit_status === '街道已审' ||
    (c.audit_status === '通过' && c.pay_status === '未拨付')
  ).slice(0, 6);
  $('#line5-claim-queue tbody').innerHTML = queue.map(c => {
    let stage = '待街道审核';
    if (c.audit_status === '街道已审') stage = '待终审';
    if (c.audit_status === '通过') stage = '待拨付';
    return `<tr><td>${c.claim_id}</td><td>${esc(c.elder_name)}</td>
      <td>${c.claim_period}</td><td>${fmtYuan(c.amount)}</td>
      <td><span class="badge ${c.audit_status === '通过' ? 'b-done' : 'b-wait'}">${stage}</span></td>
      <td><button class="btn small ghost" onclick="goToLine5Tab('subsidy')">进入处理</button></td></tr>`;
  }).join('') || '<tr><td colspan="6"><div class="queue-empty">当前没有待处理补贴</div></td></tr>';

  const rectifications = inspections.filter(q =>
    ['待整改','整改中'].includes(q.rectification_status)).slice(0, 6);
  $('#line5-rectify-queue').innerHTML = rectifications.map(q => `
    <div class="policy-current">
      <div><b>${esc(q.caregiver_name || '未关联护工')}</b>
        <small>${esc(q.issue_tags || '质量问题')} · ${esc(q.rectification_requirement || '待补充整改要求')}</small></div>
      <div class="queue-actions">
        <span class="badge b-red">${esc(q.rectification_status)}</span>
        <button class="btn small ghost" onclick="goToLine5Tab('quality')">进入整改</button>
      </div>
    </div>`).join('') || '<div class="queue-empty">当前没有未完成整改</div>';

  const policies = (policyRes.ok ? policyRes.data : []).slice(0, 6);
  $('#line5-policy-list').innerHTML = policies.map(p => `
    <div class="policy-current">
      <div><b>${esc(p.district)} · ${esc(p.target_type)} · ${esc(p.item_name)}</b>
        <small>${esc(p.period)}结算 · 有效期至 ${p.effective_to}</small></div>
      <span class="policy-money">${fmtYuan(p.standard)}</span>
    </div>`).join('') || '<div class="queue-empty">暂无有效政策</div>';

  const caregivers = (caregiverRes.ok ? caregiverRes.data : [])
    .filter(c => c.inspection_avg_score !== null)
    .sort((a, b) => Number(b.inspection_avg_score) - Number(a.inspection_avg_score))
    .slice(0, 6);
  $('#line5-quality-ranking').innerHTML = caregivers.map((c, i) => `
    <div class="quality-rank">
      <span class="rank">${i + 1}</span>
      <div class="who"><b>${esc(c.caregiver_name)}</b>
        <small>${esc(c.agency)} · 抽查 ${c.inspected_count} 次 · 未整改 ${c.open_rectifications}</small></div>
      <span class="quality-score">${Number(c.inspection_avg_score).toFixed(1)}</span>
    </div>`).join('') || '<div class="queue-empty">暂无质量抽查数据</div>';
}
