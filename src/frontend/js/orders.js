// orders.js — 总览统计、待派单队列、订单列表、推荐护工、派单 / 完成 / 改派
async function loadStats(){
  if (!['社区管理员','监管人员','机构负责人'].includes(ME.role)) { $('#stat-cards').innerHTML=''; return; }
  const r = await API('/api/stats');
  const d = r.data, cards = [
    ['elders_normal','在册正常老人','👴','i-teal'],['orders_active','进行中订单','📋','i-blue'],
    ['orders_timeout','超时未派单','⏰','i-red'],['plans_to_pause','待暂停计划','⚠️','i-yellow'],
    ['claims_in_progress','审核中申报','💰','i-purple'],['open_rectifications','未完成整改','🔎','i-orange']];
  $('#stat-cards').innerHTML = cards.map(([k,l,i,c]) =>
    `<div class="stat"><div class="icon ${c}">${i}</div><div><div class="num">${d[k]}</div><div class="label">${l}</div></div></div>`).join('');
}
async function loadPending(){
  if (ME.role !== '社区管理员') return;
  const p = await API('/api/pending-orders');
  $('#pending-table tbody').innerHTML = p.data.map(o => `<tr>
    <td>${o.order_id}</td><td>${esc(o.elder_name)}</td><td>${esc(o.community)}</td>
    <td>${esc(o.item_name)}</td><td>${o.appoint_time}</td><td>${o.waited_min}</td>
    <td>${o.timeout_flag==='超时'?'<span class="badge b-red">超时</span>':o.timeout_flag==='临近超时'?'<span class="badge b-wait">临近超时</span>':'<span class="badge b-done">正常</span>'}</td></tr>`).join('')
    || '<tr><td colspan="7" class="muted">暂无待派单订单</td></tr>';
}

/* ================= 订单与派单 ================= */
async function loadOrders(){
  const r = await API('/api/orders');
  orderList = r.data;
  const isAdmin = ME.role === '社区管理员', isWorker = ME.role === '护工';
  $('#order-table tbody').innerHTML = r.data.map(o => {
    let act = '—';
    if (isAdmin) {
      if (o.status === '待派单') act = `<button class="btn small" onclick="openRecommend(${o.order_id})">推荐护工</button>`;
      else if (o.status === '已派单' && o.dispatch_id) act = `<button class="btn small" onclick="openComplete(${o.dispatch_id},${o.order_id})">完成确认</button> <button class="btn small ghost" onclick="openReassign(${o.dispatch_id})">改派</button>`;
      else if (o.status === '服务中' && o.dispatch_id) act = `<button class="btn small" onclick="openComplete(${o.dispatch_id},${o.order_id})">完成确认</button>`;
    } else if (isWorker && o.dispatch_id && o.status === '已派单') {
      act = `<button class="btn small" onclick="openComplete(${o.dispatch_id},${o.order_id})">上门服务 · 完成确认</button>`;
    }
    const badge = {'待派单':'b-wait','已派单':'b-disp','服务中':'b-serv','已完成':'b-done','已取消':'b-canc'}[o.status];
    const note = o.service_note ? `<div class="muted" style="margin-top:3px">${esc(o.service_note)}</div>` : '';
    return `<tr><td>${o.order_id}</td><td>${esc(o.elder_name)}</td><td>${esc(o.item_name)}${note}</td>
      <td>${o.appoint_time}</td><td>${esc(o.channel)}</td><td>${fmtYuan(o.amount)}</td>
      <td><span class="badge ${badge}">${o.status}</span></td>
      <td>${esc(o.caregiver_name)||'—'}</td><td>${act}</td></tr>`;
  }).join('') || '<tr><td colspan="9" class="muted">暂无订单</td></tr>';
  $('#q-order').innerHTML = orderList.filter(o => o.status === '已完成')
    .map(o => `<option value="${o.order_id}">#${o.order_id} · ${esc(o.elder_name)} · ${esc(o.item_name)} · ${esc(o.caregiver_name || '无护工')}</option>`)
    .join('') || '<option value="">暂无已完成订单</option>';
}

$('#order-form').onsubmit = async ev => {
  ev.preventDefault();
  const body = { item_id:+$('#f-item').value,
    appoint_time: $('#f-time').value.replace('T',' '), channel:$('#f-channel').value };
  if (ME.role === '社区管理员') body.elder_id = +$('#f-elder').value;
  const r = await API('/api/orders', {method:'POST', body});
  r.ok ? toast(`下单成功：订单 ${r.data.order_id}，金额 ${fmtYuan(r.data.amount)}`) : toast(r.msg, true);
  loadOrders(); loadPending(); loadStats();
};

/* --- 派单操作面板（仅社区管理员） --- */
async function openRecommend(orderId){
  const r = await API(`/api/orders/${orderId}/recommend`);
  $('#action-panel').style.display = 'block';
  $('#action-title').textContent = `订单 ${orderId} · 推荐护工（在岗+证书有效+区域匹配+班次有余量）`;
  $('#action-body').innerHTML = r.ok && r.data.length ? '<table><thead><tr><th>护工</th><th>机构</th><th>证书</th><th>评分</th><th>班次余量</th><th>操作</th></tr></thead><tbody>'
    + r.data.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.agency)}</td><td>${esc(c.cert_type)}</td>
      <td>${c.rating}</td><td>${c.booked}/${c.capacity}</td>
      <td><button class="btn small" onclick="doDispatch(${orderId},${c.caregiver_id})">派单</button></td></tr>`).join('')
    + '</tbody></table>' : '<p class="muted">没有符合条件的护工（可改约日期，或到运维页看排班余量）。</p>';
  $('#action-panel').scrollIntoView({behavior:'smooth'});
}
async function doDispatch(orderId, caregiverId){
  const r = await API(`/api/orders/${orderId}/dispatch`, {method:'POST', body:{caregiver_id:caregiverId}});
  r.ok ? toast(`派单成功，排班已接单量已由触发器自动 +1`)
       : toast('派单被数据库拒绝：' + r.msg, true);
  $('#action-panel').style.display = 'none';
  loadOrders(); loadPending(); loadStats(); loadSchedules();
}
function openComplete(dispatchId, orderId){
  $('#action-panel').style.display = 'block';
  $('#action-title').textContent = `订单 ${orderId} · 服务完成（家属确认后触发器回写订单状态）`;
  $('#action-body').innerHTML = `<div class="row"><div style="flex:1">
    <textarea id="note" placeholder="服务记录：例如 助餐送达，老人用餐正常，家属已签字确认"></textarea></div>
    <button class="btn" onclick="doComplete(${dispatchId})">确认完成</button></div>`;
  $('#action-panel').scrollIntoView({behavior:'smooth'});
}
async function doComplete(dispatchId){
  const r = await API(`/api/dispatches/${dispatchId}/complete`, {method:'POST',
    body:{service_note: $('#note').value || '服务完成'}});
  r.ok ? toast('已完成：订单状态已由触发器自动置为「已完成」，可用于补贴申报') : toast(r.msg, true);
  $('#action-panel').style.display = 'none';
  loadOrders(); loadStats();
}
function openReassign(dispatchId){
  $('#action-panel').style.display = 'block';
  $('#action-title').textContent = `派单 ${dispatchId} · 改派（保留原记录与原因，订单回到待派单）`;
  $('#action-body').innerHTML = `<div class="row"><div style="flex:1">
    <input id="reason" style="width:100%" placeholder="改派原因：例如 护工临时请假"></div>
    <button class="btn warn" onclick="doReassign(${dispatchId})">确认改派</button></div>`;
  $('#action-panel').scrollIntoView({behavior:'smooth'});
}
async function doReassign(dispatchId){
  const r = await API(`/api/dispatches/${dispatchId}/reassign`, {method:'POST',
    body:{reason: $('#reason').value}});
  r.ok ? toast('已改派，订单回到待派单，可重新推荐护工') : toast(r.msg, true);
  $('#action-panel').style.display = 'none';
  loadOrders(); loadStats(); loadSchedules();
}
