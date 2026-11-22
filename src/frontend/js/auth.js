// auth.js — 登录 / 登出、角色导航表、启动引导 buildNav / boot
/* ================= 登录 / 登出 ================= */
function fillLogin(u){ $('#lg-user').value = u; $('#lg-pass').value = '123456'; }
function showLogin(){ $('#app-view').style.display='none'; $('#login-view').style.display='flex'; }
async function doLogin(){
  const r = await fetch('/api/login', { method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username:$('#lg-user').value, password:$('#lg-pass').value}) }).then(x=>x.json());
  if (r.ok) { toast(`欢迎，${r.data.real_name}（${r.data.role}）`); boot(); }
  else toast(r.msg, true);
}
async function doLogout(){
  await fetch('/api/logout', {method:'POST'});
  ME = null; showLogin(); toast('已退出登录');
}
document.getElementById('lg-pass').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });

/* ================= 各角色导航 ================= */
const ROLE_TABS = {
  '社区管理员': [['dashboard','总览','📊'],['orders','订单与派单','📋'],['schedules','护工排班','🧑‍⚕️'],['elders','老人档案','👴'],
                 ['line5','补贴与质量','🛡️'],['subsidy','补贴申报','💰'],['quality','质量整改','🔎'],['ops','运维工具','🛠']],
  '家属':       [['orders','服务订单','📋'],['elders','家庭档案','🏠']],
  '护工':       [['orders','我的派单','🧑‍⚕️'],['schedules','排班与打卡','📅'],['quality','我的整改','🔎']],
  '机构负责人': [['schedules','护工与排班','📅'],['quality','质量整改','🔎']],
  '监管人员':   [['dashboard','总览','📊'],['schedules','工时监管','🧑‍⚕️'],['line5','补贴与质量','🛡️'],['subsidy','补贴监管','💰'],['quality','质量抽查','🔎'],['elders','老人档案','👴']],
};

async function boot(){
  let me;
  try { me = await API('/api/me'); } catch(e) { return; }
  if (!me.ok) { showLogin(); return; }
  ME = me.data;
  $('#login-view').style.display = 'none';
  $('#app-view').style.display = 'block';
  $('#u-name').textContent = ME.name;
  $('#u-role').textContent = ME.role + (ME.role==='家属' ? ' · 绑定老人档案' : '');
  $('#role-badge').textContent = ME.role;
  buildNav();
  await loadItems();
  await Promise.all([loadCommunities(), loadElders(), loadOrders(), loadSchedules(), loadCarePlans()]);
  loadStats(); loadPending(); loadSubsidy(); loadQuality(); loadLine5Overview(); loadOps();
}

function buildNav(){
  const tabs = ROLE_TABS[ME.role] || [];
  $('#nav').innerHTML = tabs.map(([id,label,ico],i) =>
    `<button data-tab="${id}" class="${i===0?'active':''}"><span class="ico">${ico}</span>${label}</button>`).join('');
  document.querySelectorAll('#nav button').forEach(btn => btn.onclick = () => {
    document.querySelectorAll('#nav button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.content > section').forEach(s => s.classList.add('hide'));
    btn.classList.add('active');
    $('#tab-' + btn.dataset.tab).classList.remove('hide');
    $('#page-title').textContent = btn.textContent.trim().replace(/^[^\u4e00-\u9fa5]+/,'');
    loadSchedules(); // 切到排班页时刷新
    loadQuality();
    loadLine5Overview();
  });
  document.querySelectorAll('.content > section').forEach(s => s.classList.add('hide'));
  $('#tab-' + tabs[0][0]).classList.remove('hide');
  $('#page-title').textContent = tabs[0][1];
  // 按角色显隐控件
  const isAdmin = ME.role === '社区管理员', isFamily = ME.role === '家属', isReg = ME.role === '监管人员';
  $('#order-form-card').classList.toggle('hide', !(isAdmin || isFamily));
  $('#action-panel').style.display = 'none';
  $('#f-elder-field').classList.toggle('hide', isFamily);   // 家属自动绑定老人
  $('#f-channel-field').classList.toggle('hide', isFamily);
  $('#claim-form-card').classList.toggle('hide', !isAdmin);
  $('#claim-act-th').classList.toggle('hide', !isReg);
  $('#quality-random-card').classList.toggle('hide', !isReg);
  $('#quality-form-card').classList.toggle('hide', !isReg);
  $('#quality-action-panel').style.display = 'none';
  $('#assess-elder-field').classList.toggle('hide', !isAdmin);
  $('#assess-form-card').classList.toggle('hide', !isAdmin);
  $('#elder-form-card').classList.toggle('hide', !isAdmin);
  $('#elder-action-th').classList.toggle('hide', !isAdmin);
  $('#care-plan-form-wrap').classList.toggle('hide', !isAdmin);
  $('#care-plan-action-th').classList.toggle('hide', !isAdmin);
  $('#unassessed-solitary-card').classList.toggle('hide', !isAdmin);
  $('#community-distribution-card').classList.toggle('hide', !(isAdmin || isReg));
  $('#orders-title').textContent = ME.role==='护工' ? '我的派单记录' :
      isFamily ? '家庭服务订单' : '服务订单';
  $('#order-form-title').innerHTML = isFamily
      ? '为老人下单<small>应用层校验：档案正常 + 评估在有效期内</small>'
      : '下单<small>应用层校验：档案正常 + 评估在有效期内</small>';
  $('#q-target-type').onchange = toggleQualityTarget;
}
