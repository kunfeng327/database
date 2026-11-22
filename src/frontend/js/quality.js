// quality.js — 线5：质量抽查、整改结果提交、随机抽查
/* ================= 质量抽查与整改 ================= */
function toggleQualityTarget(){
  const byOrder = $('#q-target-type').value === 'order';
  $('#q-order-field').classList.toggle('hide', !byOrder);
  $('#q-caregiver-field').classList.toggle('hide', byOrder);
}

async function loadQualityCaregivers(){
  if (ME.role !== '监管人员') return;
  const r = await API('/api/quality/caregivers');
  if (!r.ok) return;
  qualityCaregivers = r.data;
  $('#q-caregiver').innerHTML = qualityCaregivers.map(c =>
    `<option value="${c.caregiver_id}">${esc(c.caregiver_name)} · ${esc(c.agency)} · 均分 ${c.inspection_avg_score ?? '暂无'} · 未整改 ${c.open_rectifications}</option>`).join('');
}

async function loadQuality(){
  if (!['社区管理员','机构负责人','监管人员','护工'].includes(ME.role)) return;
  if ($('#tab-quality').classList.contains('hide')) return;
  const r = await API('/api/quality/inspections');
  const isReg = ME.role === '监管人员';
  const canRectify = ['社区管理员','机构负责人','护工'].includes(ME.role);
  const rectBadge = {'无需整改':'b-done','待整改':'b-red','整改中':'b-wait','已完成':'b-done'};
  $('#quality-table tbody').innerHTML = r.ok ? r.data.map(q => {
    let act = '—';
    if (isReg && q.inspection_status === '待抽查') {
      act = `<button class="btn small" onclick="openQualityResult(${q.inspection_id})">录入结果</button>`;
    } else if (canRectify && ['待整改','整改中'].includes(q.rectification_status)
               && (ME.role !== '护工' || q.caregiver_id === ME.caregiver_id)) {
      act = `<button class="btn small" onclick="openRectify(${q.inspection_id})">提交整改</button>`;
    }
    const target = q.order_id
      ? `#${q.order_id}<div class="muted">${esc(q.elder_name || '')} · ${esc(q.community || '')}</div>`
      : '<span class="tag">护工专项</span>';
    const issue = q.issue_tags ? q.issue_tags.split(',').map(x => `<span class="tag">${esc(x)}</span>`).join('') : '—';
    const rectStatus = q.inspection_status === '待抽查'
      ? '<span class="badge b-wait">待抽查</span>'
      : `<span class="badge ${rectBadge[q.rectification_status] || 'b-canc'}">${q.rectification_status || '—'}</span>`;
    const detail = q.rectification_result
      ? `<div>${esc(q.rectification_result)}</div><div class="muted">要求：${esc(q.rectification_requirement || '—')}</div>`
      : (q.rectification_requirement ? esc(q.rectification_requirement) : '—');
    return `<tr><td>${q.inspection_id}</td><td>${target}</td>
      <td>${esc(q.caregiver_name || '—')}<div class="muted">${esc(q.agency || '')}</div></td>
      <td>${esc(q.inspection_method)}</td><td>${q.score ?? '—'}</td><td>${issue}</td>
      <td>${rectStatus}${q.open_days > 0 ? `<div class="muted">已滞留 ${q.open_days} 天</div>` : ''}</td>
      <td>${detail}</td><td>${esc(q.inspector)}</td><td>${act}</td></tr>`;
  }).join('') || '<tr><td colspan="10" class="muted">暂无抽查记录</td></tr>'
    : '<tr><td colspan="10" class="muted">加载失败</td></tr>';
  await loadQualityCaregivers();
}

function openQualityResult(id){
  $('#quality-action-panel').style.display = 'block';
  $('#quality-action-title').textContent = `抽查 ${id} · 录入结果`;
  $('#quality-action-body').innerHTML = `<form class="inline" onsubmit="submitQualityResult(event,${id})">
    <div class="field"><label>方式</label><select id="qr-method"><option>电话回访</option><option>上门核查</option></select></div>
    <div class="field"><label>评分</label><input id="qr-score" type="number" min="0" max="100" style="width:100px"></div>
    <div class="field"><label>问题标签</label><input id="qr-issues" placeholder="多个问题用逗号分隔"></div>
    <div class="field" style="flex:1;min-width:240px"><label>整改要求</label><input id="qr-requirement" placeholder="无问题可留空"></div>
    <button class="btn" type="submit">保存结果</button>
  </form>`;
  $('#quality-action-panel').scrollIntoView({behavior:'smooth'});
}

async function submitQualityResult(ev, id){
  ev.preventDefault();
  const r = await API(`/api/quality/inspections/${id}/result`, {method:'POST', body:{
    inspection_method:$('#qr-method').value,
    score:parseInt($('#qr-score').value,10),
    issue_tags:$('#qr-issues').value.trim(),
    rectification_requirement:$('#qr-requirement').value.trim()
  }});
  if (r.ok) {
    toast(`抽查结果已保存，整改状态「${r.data.rectification_status}」`);
    $('#quality-action-panel').style.display = 'none';
    loadQuality(); loadStats(); loadOrders(); loadLine5Overview();
  } else toast(r.msg, true);
}

function openRectify(id){
  $('#quality-action-panel').style.display = 'block';
  $('#quality-action-title').textContent = `抽查 ${id} · 提交整改结果`;
  $('#quality-action-body').innerHTML = `<div class="row">
    <div style="flex:1"><textarea id="q-rect-result" placeholder="填写整改措施、证明材料与复查情况"></textarea></div>
    <button class="btn" onclick="submitRectify(${id})">确认完成</button></div>`;
  $('#quality-action-panel').scrollIntoView({behavior:'smooth'});
}

async function submitRectify(id){
  const result = $('#q-rect-result').value.trim();
  if (!result) { toast('整改结果不能为空', true); return; }
  const r = await API(`/api/quality/inspections/${id}/rectification`, {method:'POST',
    body:{rectification_result:result}});
  if (r.ok) {
    toast('整改结果已提交，护工接单限制已解除');
    $('#quality-action-panel').style.display = 'none';
    loadQuality(); loadStats(); loadOrders(); loadLine5Overview();
  } else toast(r.msg, true);
}

$('#quality-random-form').onsubmit = async ev => {
  ev.preventDefault();
  const r = await API('/api/quality/inspections/random', {method:'POST', body:{
    sample_rate:parseInt($('#q-rate').value,10),
    inspection_method:$('#q-random-method').value
  }});
  r.ok ? toast(`已按 ${r.data.sample_rate}% 抽取 ${r.data.created_count} 笔，覆盖候选 ${r.data.candidate_count} 笔`)
       : toast(r.msg, true);
  loadQuality(); loadStats(); loadLine5Overview();
};

$('#quality-form').onsubmit = async ev => {
  ev.preventDefault();
  const targetType = $('#q-target-type').value;
  const body = {
    inspection_method:$('#q-method').value,
    score:parseInt($('#q-score').value,10),
    issue_tags:$('#q-issues').value.trim(),
    rectification_requirement:$('#q-requirement').value.trim()
  };
  if (targetType === 'order') body.order_id = parseInt($('#q-order').value,10);
  else body.caregiver_id = parseInt($('#q-caregiver').value,10);
  const r = await API('/api/quality/inspections', {method:'POST', body});
  if (r.ok) {
    toast(`抽查已录入，评分 ${r.data.score}，整改状态「${r.data.rectification_status}」`);
    $('#q-score').value = ''; $('#q-issues').value = ''; $('#q-requirement').value = '';
    loadQuality(); loadStats(); loadLine5Overview();
  } else toast(r.msg, true);
};
