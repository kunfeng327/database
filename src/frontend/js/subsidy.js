// subsidy.js — 线5：补贴申报与审核、业务总览看板
/* ================= 补贴 ================= */
async function loadSubsidy(){
  if (!['家属','社区管理员','监管人员'].includes(ME.role)) return;
  const [pol, clm] = await Promise.all([API('/api/subsidy/policies'), API('/api/subsidy/claims')]);
  $('#c-policy').innerHTML = pol.ok ? pol.data.map(p =>
    `<option value="${p.policy_id}">${p.district} · ${p.target_type} · ${esc(p.item_name)}（￥${p.standard}/次）</option>`).join('') : '';
  $('#c-elder').innerHTML = elderList.map(e => `<option value="${e.elder_id}">${esc(e.name)}</option>`).join('');
  const lastMonth = new Date(); lastMonth.setMonth(lastMonth.getMonth()-1);
  $('#c-period').value = lastMonth.toISOString().slice(0,7);
  const isReg = ME.role === '监管人员';
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
  const r = await API('/api/subsidy/claims', {method:'POST', body:{
    elder_id:+$('#c-elder').value, policy_id:+$('#c-policy').value, claim_period:$('#c-period').value}});
  r.ok ? toast(`申报成功：${r.data.order_ids.length} 笔订单，金额 ${fmtYuan(r.data.amount)}`)
       : toast('申报被拒绝：' + r.msg, true);
  loadSubsidy(); loadStats();
};
async function audit(id, action){
  const r = await API(`/api/subsidy/claims/${id}/audit`, {method:'POST', body:{action}});
  r.ok ? toast(`申报 ${id}：审核「${r.data.audit_status}」，拨付「${r.data.pay_status}」`) : toast(r.msg, true);
  loadSubsidy(); loadStats(); loadLine5Overview();
}

/* ================= 线5业务总览 ================= */
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
