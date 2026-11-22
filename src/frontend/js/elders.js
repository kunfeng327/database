// elders.js — 基础下拉数据、老人档案、能力评估、照护计划与档案报表
/* ================= 数据加载 ================= */
async function loadItems(){
  const r = await API('/api/items');
  $('#f-item').innerHTML = r.data.map(i =>
    `<option value="${i.item_id}">${esc(i.name)}（￥${i.guide_price}/${i.unit}${i.subsidizable?'，可补贴':''}）</option>`).join('');
}
async function loadCommunities(){
  if (ME.role !== '社区管理员') return;
  const r = await API('/api/communities');
  if (!r.ok) return;
  communityList = r.data;
  $('#e-community').innerHTML = communityList.map(c =>
    `<option value="${c.community_id}">${esc(c.name)}（${esc(c.district)}）</option>`).join('');
}
async function loadCarePlanCaregivers(){
  if (ME.role !== '社区管理员') return;
  const r = await API('/api/care-plans/caregivers');
  if (!r.ok) return;
  $('#p-caregiver').innerHTML = '<option value="">无指定护工</option>' +
    r.data.map(c => `<option value="${c.caregiver_id}">${esc(c.name)}（${esc(c.agency)}）</option>`).join('');
}
async function loadCarePlanPackages(){
  if (ME.role !== '社区管理员') return;
  const r = await API('/api/care-plans/packages');
  if (!r.ok) return;
  $('#p-package').innerHTML = r.data
    .map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
}
function resetCarePlanForm(){
  $('#care-plan-form').reset();
  $('#p-id').value = '';
  $('#p-status').value = '生效';
  $('#care-plan-title').textContent = '照护计划';
  $('#p-submit').textContent = '新建计划';
  $('#p-cancel').style.display = 'none';
}
function editCarePlan(planId){
  const p = carePlanList.find(x => x.plan_id === planId);
  if (!p) return;
  $('#p-id').value = p.plan_id;
  $('#p-elder').value = p.elder_id;
  $('#p-package').value = p.package_name;
  $('#p-frequency').value = p.frequency;
  $('#p-start').value = p.start_date;
  $('#p-end').value = p.end_date;
  $('#p-caregiver').value = p.caregiver_id || '';
  $('#p-status').value = p.status;
  $('#care-plan-title').textContent = `编辑照护计划：#${p.plan_id}`;
  $('#p-submit').textContent = '保存计划';
  $('#p-cancel').style.display = '';
  $('#care-plan-card').scrollIntoView({behavior:'smooth', block:'start'});
  $('#care-plan-card').classList.add('edit-highlight');
  setTimeout(() => $('#care-plan-card').classList.remove('edit-highlight'), 1200);
  setTimeout(() => $('#p-package').focus({preventScroll:true}), 350);
}
async function loadCarePlans(){
  const r = await API('/api/care-plans');
  if (!r.ok) return;
  carePlanList = r.data;
  $('#care-plan-table').innerHTML = r.data.map(p => `<tr>
    <td>${p.plan_id}</td><td>${esc(p.elder_name)}</td><td>${esc(p.package_name)}</td>
    <td>${esc(p.frequency)}</td><td>${p.start_date}</td><td>${p.end_date}</td>
    <td>${esc(p.caregiver_name) || '<span class="muted">未指定</span>'}</td>
    <td>${p.status==='生效'?'<span class="badge b-done">生效</span>'
      :p.status==='暂停'?'<span class="badge b-wait">暂停</span>':'<span class="badge b-canc">结束</span>'}</td>
    ${ME.role==='社区管理员'?`<td><button class="btn small ghost" onclick="editCarePlan(${p.plan_id})">编辑</button></td>`:''}
  </tr>`).join('')
    || '<tr><td colspan="9" class="muted">暂无照护计划</td></tr>';
  if (ME.role === '社区管理员') {
    $('#p-elder').innerHTML = elderList.filter(e => e.elder_status==='正常')
      .map(e => `<option value="${e.elder_id}">${esc(e.name)}（${esc(e.community)}）</option>`).join('');
    await loadCarePlanPackages();
    await loadCarePlanCaregivers();
  }
}

function resetElderForm(){
  $('#elder-form').reset();
  $('#e-id').value = '';
  $('#e-status').value = '正常';
  $('#elder-form-title').textContent = '新建老人档案';
  $('#e-submit').textContent = '新建档案';
  $('#e-idcard').disabled = false;
  $('#e-birth').disabled = false;
  $('#e-gender').disabled = false;
  $('#e-cancel').style.display = 'none';
}
function autofillElderIdentity(){
  const idCard = $('#e-idcard').value.trim().toUpperCase();
  if (!/^\d{17}[\dX]$/.test(idCard)) return;
  const birthDate = `${idCard.slice(6,10)}-${idCard.slice(10,12)}-${idCard.slice(12,14)}`;
  const date = new Date(`${birthDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0,10) !== birthDate) return;
  $('#e-birth').value = birthDate;
  $('#e-gender').value = Number(idCard[16]) % 2 ? '男' : '女';
}
$('#e-idcard').addEventListener('input', autofillElderIdentity);
async function editElder(elderId){
  const r = await API(`/api/elders/${elderId}/detail`);
  if (!r.ok) { toast(r.msg, true); return; }
  const e = r.data;
  if (e.status === '注销') { toast('档案已注销，不允许修改', true); return; }
  resetElderForm();
  $('#e-id').value = e.elder_id;
  $('#e-name').value = e.name;
  $('#e-idcard').value = e.id_card;
  $('#e-birth').value = e.birth_date;
  $('#e-gender').value = e.gender;
  $('#e-address').value = e.address;
  $('#e-community').value = e.community_id;
  $('#e-guardian-name').value = e.guardian_name;
  $('#e-guardian-phone').value = e.guardian_phone;
  $('#e-status').value = e.status;
  Array.from($('#e-tags').options).forEach(o => o.selected = (e.special_tag || '').split(',').includes(o.value));
  $('#e-idcard').disabled = true;
  $('#e-birth').disabled = true;
  $('#e-gender').disabled = true;
  $('#elder-form-title').textContent = `编辑老人档案：${e.name}`;
  $('#e-submit').textContent = '保存修改';
  $('#e-cancel').style.display = '';
  $('#elder-form-card').scrollIntoView({behavior:'smooth', block:'center'});
}

/* ================= 档案报表 ================= */
async function loadUnassessedSolitary(){
  const r = await API('/api/elder-reports/unassessed-solitary');
  if (!r.ok) { toast(r.msg, true); return; }
  $('#unassessed-solitary-table tbody').innerHTML = r.data.map(e => `<tr>
    <td>${esc(e.elder_id)}</td><td>${esc(e.name)}</td><td>${esc(e.age)}</td>
    <td>${esc(e.community)}</td><td>${esc(e.id_masked)}</td><td>${esc(e.special_tag)}</td>
    <td>${esc(e.last_assess_date || '从未评估')}</td><td>${esc(e.last_expire || '—')}</td>
    <td>${esc(e.assess_state)}</td><td>${esc(e.guardian_name)}</td><td>${esc(e.guardian_phone)}</td>
  </tr>`).join('') || '<tr><td colspan="11" class="muted">暂无待评估的独居老人</td></tr>';
}
async function loadCommunityDistribution(){
  const r = await API('/api/elder-reports/community-distribution');
  if (!r.ok) { toast(r.msg, true); return; }
  $('#community-distribution-table tbody').innerHTML = r.data.map(c => `<tr>
    <td>${esc(c.community)}</td><td>${esc(c.district)}</td><td>${esc(c.total_elders)}</td>
    <td>${esc(c.level_intact ?? 0)}</td><td>${esc(c.level_mild ?? 0)}</td>
    <td>${esc(c.level_moderate ?? 0)}</td><td>${esc(c.level_severe ?? 0)}</td>
    <td>${esc(c.unassessed ?? 0)}</td>
    <td>${c.disabled_pct == null ? '—' : `${Number(c.disabled_pct).toFixed(1)}%`}</td>
  </tr>`).join('') || '<tr><td colspan="9" class="muted">暂无社区评估数据</td></tr>';
}

/* ================= 老人档案列表 ================= */
async function loadElders(){
  const r = await API('/api/elders');
  elderList = r.data;
  $('#elder-table tbody').innerHTML = r.data.map(e => `<tr>
    <td>${e.elder_id}</td><td>${esc(e.name)}</td><td>${e.age}</td><td>${esc(e.community)}</td>
    <td>${esc(e.id_masked)}</td>
    <td>${(e.special_tag||'').split(',').filter(Boolean).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</td>
    <td>${esc(e.ability_level)||'<span class="muted">未评估</span>'}</td>
    <td>${e.assess_expire||''} ${e.assess_expired?'<span class="badge b-red">已过期</span>':''}</td>
    <td>${e.elder_status==='正常'?'<span class="badge b-done">正常</span>':`<span class="badge b-canc">${esc(e.elder_status)}</span>`}</td>
    <td>${esc(e.package_name)||'<span class="muted">无</span>'}${e.plan_status==='暂停'?' <span class="badge b-red">暂停</span>':''}</td>
    ${ME.role==='社区管理员'?`<td>${e.elder_status==='注销'
      ?'<button class="btn small ghost" disabled title="档案已注销，不允许修改">已注销</button>'
      :`<button class="btn small ghost" onclick="editElder(${e.elder_id})">编辑</button>`}</td>`:''}</tr>`).join('');
  $('#f-elder').innerHTML = elderList.filter(e => e.elder_status==='正常')
    .map(e => `<option value="${e.elder_id}">${esc(e.name)}（${esc(e.community)}${e.assess_expired?'，评估已过期':''}）</option>`).join('');
  if (ME.role === '社区管理员') {
    $('#p-elder').innerHTML = elderList.filter(e => e.elder_status==='正常')
      .map(e => `<option value="${e.elder_id}">${esc(e.name)}（${esc(e.community)}）</option>`).join('');
  }
  const t = new Date(Date.now() + 26*3600e3);
  $('#f-time').value = t.toISOString().slice(0,16);
  // 评估卡片：家属自动绑定自家老人，管理员可选
  $('#a-elder').innerHTML = elderList.map(e =>
    `<option value="${e.elder_id}">${esc(e.name)}${e.assess_expired?'（评估已过期）':''}</option>`).join('');
  loadAssessments();
  $('#a-elder').onchange = () => loadAssessments();
  if (ME.role === '社区管理员') await loadUnassessedSolitary();
  if (ME.role === '社区管理员' || ME.role === '监管人员') {
    await loadCommunityDistribution();
  }
}

$('#elder-form').onsubmit = async ev => {
  ev.preventDefault();
  const elderId = +$('#e-id').value;
  const tags = Array.from($('#e-tags').selectedOptions).map(o => o.value);
  const body = elderId ? {
    name: $('#e-name').value,
    address: $('#e-address').value,
    community_id: +$('#e-community').value,
    guardian_name: $('#e-guardian-name').value,
    guardian_phone: $('#e-guardian-phone').value,
    special_tag: tags,
    status: $('#e-status').value
  } : {
    name: $('#e-name').value,
    id_card: $('#e-idcard').value,
    birth_date: $('#e-birth').value,
    gender: $('#e-gender').value,
    address: $('#e-address').value,
    community_id: +$('#e-community').value,
    guardian_name: $('#e-guardian-name').value,
    guardian_phone: $('#e-guardian-phone').value,
    special_tag: tags,
    status: $('#e-status').value
  };
  const r = await API(elderId ? `/api/elders/${elderId}` : '/api/elders',
    {method: elderId ? 'PATCH' : 'POST', body});
  if (!r.ok) { toast(r.msg, true); return; }
  toast(elderId ? '老人档案已修改' : `老人档案创建成功：编号 ${r.data.elder_id}`);
  resetElderForm();
  await loadElders();
  loadStats();
};

$('#care-plan-form').onsubmit = async ev => {
  ev.preventDefault();
  const planId = +$('#p-id').value;
  const body = {
    elder_id: +$('#p-elder').value,
    package_name: $('#p-package').value,
    frequency: $('#p-frequency').value,
    start_date: $('#p-start').value,
    end_date: $('#p-end').value,
    caregiver_id: $('#p-caregiver').value ? +$('#p-caregiver').value : null,
    status: $('#p-status').value
  };
  const r = await API(planId ? `/api/care-plans/${planId}` : '/api/care-plans',
    {method: planId ? 'PATCH' : 'POST', body});
  if (!r.ok) { toast(r.msg, true); return; }
  toast(planId ? '照护计划已修改' : '照护计划创建成功');
  resetCarePlanForm();
  await loadCarePlans();
  await loadElders();
  loadStats();
};

/* ================= 能力评估 ================= */
async function loadAssessments(){
  if ($('#tab-elders').classList.contains('hide') && ME.role !== '家属') return;
  const isAdmin = ME.role === '社区管理员';
  const id = isAdmin ? +($('#a-elder').value || 0) : ME.elder_id;
  if (!id) return;
  const r = await API(`/api/elders/${id}/assessments`);
  if (!r.ok) return;
  $('#assess-table tbody').innerHTML = r.data.map(a => `<tr>
    <td>${esc(a.scale)}</td><td>${a.score}</td><td>${esc(a.ability_level)}</td>
    <td>${esc(a.assessor)}</td><td>${a.assess_date}</td><td>${a.expire_date}</td>
    <td>${a.days_left > 0 ? a.days_left : '—'}</td>
    <td>${a.expired ? '<span class="badge b-red">已过期</span>'
        : a.days_left <= 30 ? '<span class="badge b-wait">即将到期</span>'
        : '<span class="badge b-done">有效</span>'}</td></tr>`).join('')
    || '<tr><td colspan="8" class="muted">暂无评估记录，请联系社区安排首次评估</td></tr>';
  const latest = r.data[0];
  if (!latest) {
    $('#assess-alert').innerHTML = `<div class="badge b-red" style="display:block;padding:9px 14px;margin-bottom:12px">
      尚未做能力评估：不可下单，请联系社区安排评估</div>`;
  } else if (latest.expired) {
    $('#assess-alert').innerHTML = `<div class="badge b-red" style="display:block;padding:9px 14px;margin-bottom:12px">
      评估已于 ${latest.expire_date} 过期（逾期 ${-latest.days_left} 天）：暂不可下单，照护计划已暂停，请联系社区复评</div>`;
  } else if (latest.days_left <= 30) {
    $('#assess-alert').innerHTML = `<div class="badge b-wait" style="display:block;padding:9px 14px;margin-bottom:12px">
      评估 ${latest.days_left} 天后到期，请及时联系社区安排复评</div>`;
  } else $('#assess-alert').innerHTML = '';
}

$('#assess-form-card').onsubmit = async ev => {
  ev.preventDefault();
  const elderId = +$('#a-elder').value;
  const score = parseInt($('#a-score').value, 10);
  const r = await API(`/api/elders/${elderId}/assessments`, {method:'POST',
    body:{scale:$('#a-scale').value, score}});
  if (r.ok) {
    const extra = r.data.resumed_plans > 0 ? `，已自动恢复 ${r.data.resumed_plans} 份照护计划` : '';
    toast(`评估已录入：等级「${r.data.ability_level}」，有效期至 ${r.data.expire_date}${extra}`);
    $('#a-score').value = '';
    loadAssessments(); loadElders(); loadStats();
  } else toast(r.msg, true);
};
