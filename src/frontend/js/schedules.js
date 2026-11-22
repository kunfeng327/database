// schedules.js — 线3：排班余量视图、上门签到签退、工时复核、批量排班
async function loadSchedules(){
  if (!['社区管理员','机构负责人','护工','监管人员'].includes(ME.role)) return;
  if ($('#tab-schedules').classList.contains('hide')) return;

  const isAdmin = ME.role === '社区管理员', isOrg = ME.role === '机构负责人',
        isWorker = ME.role === '护工', isReg = ME.role === '监管人员';
  $('#l3-checkin-form').classList.toggle('hide', !(isWorker || isAdmin));
  $('#l3-batch-card').classList.toggle('hide', !(isOrg || isAdmin));
  $('#l3-warn-card').classList.toggle('hide', isWorker);

  // 1. 加载排班余量视图
  const r = await API('/api/schedules');
  $('#sched-table tbody').innerHTML = r.ok ? r.data.map(s => `<tr>
    <td>${esc(s.caregiver_name)}</td><td>${esc(s.cert_type)}</td>
    <td>${s.cert_expire} ${s.cert_valid?'':'<span class="badge b-red">已过期</span>'}</td>
    <td>${s.work_date}</td><td>${s.shift}</td><td>${s.booked}/${s.capacity}</td><td>${s.remaining}</td></tr>`).join('')
    : '';

  // 2. 加载待签到派单 & 工时记录
  if (isWorker || isAdmin) {
    const pd = await API('/api/line3/pending-checkin');
    $('#l3-dispatch').innerHTML = pd.ok && pd.data.length
      ? pd.data.map(d => `<option value="${d.dispatch_id}">派单#${d.dispatch_id} · ${esc(d.elder_name)} · ${esc(d.item_name)}（${esc(d.caregiver_name)}）</option>`).join('')
      : '<option value="">暂无待上门签到派单</option>';
    const nowStr = new Date(Date.now() - new Date().getTimezoneOffset()*60000).toISOString().slice(0,16);
    if (!$('#l3-in-time').value) $('#l3-in-time').value = nowStr;
  }

  const whRes = await API('/api/line3/work-hours');
  const revBadge = {'自动认定':'b-done','复核通过':'b-done','待人工复核':'b-red','复核驳回':'b-canc'};
  $('#l3-wh-table tbody').innerHTML = whRes.ok && whRes.data.length ? whRes.data.map(w => {
    let act = '—';
    if (!w.checkout_time && (isWorker || isAdmin)) {
      act = `<button class="btn small" onclick="doL3Checkout(${w.work_hour_id}, '通过')">正常签退</button> `
          + `<button class="btn small warn" onclick="doL3Checkout(${w.work_hour_id}, '围栏外异常')">模拟越界签退</button>`;
    } else if (w.review_status === '待人工复核' && (isAdmin || isOrg || isReg)) {
      act = `<button class="btn small" onclick="doL3Review(${w.work_hour_id}, '复核通过')">复核通过</button> `
          + `<button class="btn small warn" onclick="doL3Review(${w.work_hour_id}, '复核驳回')">驳回</button>`;
    }
    return `<tr>
      <td>${w.work_hour_id}</td>
      <td>#${w.order_id} · ${esc(w.elder_name)}</td>
      <td>${esc(w.item_name)}</td>
      <td>${esc(w.caregiver_name)}</td>
      <td>${w.checkin_time}</td>
      <td>${w.checkout_time || '<span class="muted">服务中...</span>'}</td>
      <td>${w.fence_result === '通过' ? '<span class="badge b-done">围栏内通过</span>' : '<span class="badge b-red">围栏外异常</span>'}</td>
      <td><b>${Number(w.valid_hours).toFixed(2)}</b></td>
      <td><span class="badge ${revBadge[w.review_status]||'b-wait'}">${esc(w.review_status)}</span></td>
      <td>${act}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="10" class="muted">暂无工时记录</td></tr>';

  // 3. 机构/管理员加载护工下拉与证书预警
  if (isOrg || isAdmin || isReg) {
    const [cgRes, warnRes] = await Promise.all([API('/api/line3/caregivers'), API('/api/line3/cert-warnings')]);
    if (cgRes.ok && (isOrg || isAdmin)) {
      $('#l3-cg-select').innerHTML = cgRes.data.map(c =>
        `<option value="${c.caregiver_id}">${esc(c.name)}（${esc(c.agency)} · ${esc(c.cert_type)} · ${esc(c.on_duty)}）</option>`).join('');
      const today = new Date().toISOString().slice(0,10);
      const next3 = new Date(Date.now() + 2*86400e3).toISOString().slice(0,10);
      if (!$('#l3-start-date').value) $('#l3-start-date').value = today;
      if (!$('#l3-end-date').value) $('#l3-end-date').value = next3;
    }
    if (warnRes.ok) {
      $('#l3-warn-table tbody').innerHTML = warnRes.data.length ? warnRes.data.map(w => `<tr>
        <td>${esc(w.name)}</td><td>${esc(w.agency)}</td>
        <td>${esc(w.cert_type)} ${esc(w.cert_level||'')}</td>
        <td>${w.cert_expire}</td><td>${w.days_remaining} 天</td>
        <td>${w.warning_status==='已过期'?'<span class="badge b-red">已过期</span>':'<span class="badge b-wait">30天内临期</span>'}</td>
      </tr>`).join('') : '<tr><td colspan="6" class="muted">暂无过期或临期证书</td></tr>';
    }
  }

  // 4. 加载工时汇总排行榜
  const sumRes = await API('/api/line3/summary');
  if (sumRes.ok) {
    $('#l3-summary-table tbody').innerHTML = sumRes.data.map(s => `<tr>
      <td>${esc(s.caregiver_name)}</td><td>${esc(s.agency)}</td>
      <td>${s.service_count} 单</td><td><b>${Number(s.total_valid_hours).toFixed(2)}</b></td>
      <td>${Number(s.archive_total_hours).toFixed(2)}</td>
    </tr>`).join('');
  }
}

$('#l3-checkin-form').onsubmit = async ev => {
  ev.preventDefault();
  const dispatchId = $('#l3-dispatch').value;
  if (!dispatchId) { toast('当前没有可签到的派单', true); return; }
  const r = await API('/api/line3/work-hours/checkin', {method:'POST', body:{
    dispatch_id: +dispatchId,
    checkin_time: $('#l3-in-time').value.replace('T',' '),
    checkin_location: $('#l3-in-loc').value
  }});
  if (r.ok) { toast(`上门签到成功，生成工时单 #${r.data.work_hour_id}`); loadSchedules(); loadOrders(); }
  else toast(r.msg, true);
};

async function doL3Checkout(whId, fenceResult){
  const nowStr = new Date(Date.now() + 90*60000 - new Date().getTimezoneOffset()*60000).toISOString().slice(0,16).replace('T',' ');
  const outTime = prompt('请输入签退时间（默认按签到后1.5小时生成）：', nowStr);
  if (!outTime) return;
  const r = await API(`/api/line3/work-hours/${whId}/checkout`, {method:'POST', body:{
    checkout_time: outTime, fence_result: fenceResult
  }});
  if (r.ok) {
    const msg = r.data.review_status === '待人工复核'
      ? '围栏外异常签退：触发器已自动将有效工时置 0 并转入「待人工复核」'
      : `正常签退成功：触发器自动核算有效工时 ${r.data.valid_hours} 小时并累加至档案`;
    toast(msg, r.data.review_status === '待人工复核');
    loadSchedules();
  } else toast(r.msg, true);
}

async function doL3Review(whId, decision){
  const r = await API(`/api/line3/work-hours/${whId}/review`, {method:'POST', body:{decision}});
  if (r.ok) { toast(`工时单 #${whId} 已${decision}`); loadSchedules(); }
  else toast(r.msg, true);
}

$('#l3-batch-form').onsubmit = async ev => {
  ev.preventDefault();
  const r = await API('/api/line3/schedules/batch', {method:'POST', body:{
    caregiver_id: +$('#l3-cg-select').value,
    start_date: $('#l3-start-date').value,
    end_date: $('#l3-end-date').value,
    shift: $('#l3-shift').value,
    capacity: +$('#l3-cap').value
  }});
  if (r.ok) {
    toast(`存储过程执行完成：成功新增 ${r.data.created_count} 条排班（已自动跳过冲突日期）`);
    loadSchedules();
  } else toast('排班被拒绝：' + r.msg, true);
};
