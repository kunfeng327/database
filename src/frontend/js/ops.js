// ops.js — 运维工具：评估过期计划预览与批量暂停
/* ================= 运维 / 排班 ================= */
async function loadOps(){
  if (ME.role !== '社区管理员') return;
  const r = await API('/api/maintenance/expired-preview');
  $('#expired-table tbody').innerHTML = r.data.length ? r.data.map(x => `<tr>
    <td>${x.plan_id}</td><td>${esc(x.elder_name)}</td><td>${esc(x.package_name)}</td>
    <td>${esc(x.status)}</td><td>${x.expire_date} <span class="badge b-red">已过期</span></td></tr>`).join('')
    : '<tr><td colspan="5" class="muted">没有需要暂停的计划</td></tr>';
}
$('#btn-pause').onclick = async () => {
  const r = await API('/api/maintenance/pause-expired-plans', {method:'POST'});
  r.ok ? toast(`存储过程执行成功：暂停了 ${r.data.paused_plans} 份照护计划`) : toast(r.msg, true);
  loadOps(); loadElders(); loadStats();
};
