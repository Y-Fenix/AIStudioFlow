/* Public shell notification configuration; secrets never enter persistent browser storage. */
const NotificationsUI=(()=>{
 let cleanup=()=>{};
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const events=[['completed','执行完成'],['failed','执行失败'],['interrupted','执行中断'],['manual','人工提交交付物'],['approved','人工确认通过'],['public_published','公区内容发布']];
 const statuses={pending:'待发送',sending:'发送中',sent:'已发送',failed:'发送失败',unknown:'送达待核对',cancelled:'已取消'};
 function page(){return `<details id="notification-config" class="panel notification-config"><summary><span>飞书节点提醒</span><span class="muted small">Webhook · 保存即生效</span></summary><div id="notify-body"><p class="muted">展开后加载配置。</p></div></details>`}
 function mount({studio,project,departments,api,toast,beijing}){
  cleanup();const root=document.querySelector('#notification-config');if(!root||!studio)return;
  let live=true,timer,version=0,busy=false,saved=null,dirty=false;const $=selector=>root.querySelector(selector);
  cleanup=()=>{live=false;version++;clearTimeout(timer)};
  const base='/api/studios/'+encodeURIComponent(studio)+'/notifications';
  function scope(){const type=$('#notify-scope')?.value|| (project?'project':'studio');return {type,project:type==='studio'?'':project||'',department:['department','node'].includes(type)?$('#notify-department').value:'',node:type==='node'?$('#notify-node').value:''}}
  function query(s=scope()){return '?'+new URLSearchParams({project:s.project,department:s.department,node:s.node})}
  function nodes(){const d=departments.find(d=>d.id===$('#notify-department').value);$('#notify-node').innerHTML=(d?.nodes||[]).map((n,i)=>`<option value="${escape(d.node_keys?.[i]||d.id+':'+i)}">${escape(n[0])}</option>`).join('')}
  function skeleton(){const types=[['studio','工作室默认'],...(project?[['project','当前项目'],['department','当前项目 / 部门'],['node','当前项目 / 节点']]:[])];
   $('#notify-body').innerHTML=`<p class="muted">仅范围负责人可配置。工作室 → 项目 → 部门 → 节点逐级覆盖；保存下级配置后，整组设置独立生效。关闭不影响节点运行。</p><div class="notify-fields"><div class="field"><label for="notify-scope">配置范围</label><select id="notify-scope">${types.map(([id,label])=>`<option value="${id}" ${id===(project?'project':'studio')?'selected':''}>${label}</option>`).join('')}</select></div><div class="field" id="notify-department-field" hidden><label for="notify-department">部门</label><select id="notify-department">${departments.filter(d=>d.enabled!==false).map(d=>`<option value="${escape(d.id)}">${escape(d.title)}</option>`).join('')}</select></div><div class="field" id="notify-node-field" hidden><label for="notify-node">节点</label><select id="notify-node"></select></div></div><div id="notify-source" class="info-strip"></div><div id="notify-form"></div><h3>最近发送记录</h3><p class="muted small">飞书接受消息后显示“已发送”，不代表成员已读。网络结果不确定时先核对群消息，再补发。</p><div id="notify-history" aria-live="polite"></div>`;nodes();
   $('#notify-body').insertAdjacentHTML('afterbegin','<p id="notify-context" class="notify-context"></p>');
   for(const id of ['#notify-scope','#notify-department','#notify-node'])$(id).onchange=()=>{if(id==='#notify-department')nodes();load().catch(e=>toast(e.message))};
  }
  async function load(){const current=++version,s=scope();$('#notify-department-field').hidden=!['department','node'].includes(s.type);$('#notify-node-field').hidden=s.type!=='node';
   saved=null;dirty=false;$('#notify-form').innerHTML='<p>读取配置中…</p>';const value=await api(base+query(s));if(!live||current!==version)return;const c=value.effective;saved=value;
   $('#notify-context').textContent=s.project?`${value.context.studio_name} / ${value.context.project_name} · 项目通知配置`:`${value.context.studio_name} · 工作室默认配置`;
   $('#notify-source').innerHTML=`已保存生效来源：<strong>${escape(c.source)}</strong> · ${c.enabled?'已开启':'已关闭'} · 接收群：${escape(c.destination_name||(c.has_webhook?'已配置（未填写备注）':'未配置'))}`;
   $('#notify-form').innerHTML=`<label class="admin-check"><input id="notify-enabled" type="checkbox" ${c.enabled?'checked':''}> 启用本范围提醒</label><div class="notify-fields"><div class="field"><label for="notify-webhook">飞书群机器人 Webhook</label><input type="password" id="notify-webhook" autocomplete="new-password" placeholder="${c.has_webhook?'已配置；留空保留现有地址':'https://open.feishu.cn/open-apis/bot/v2/hook/…'}"></div><div class="field"><label for="notify-secret">签名密钥（机器人开启签名时填写）</label><input type="password" id="notify-secret" autocomplete="new-password" placeholder="${c.has_secret?'已配置；留空保留':'可选'}"><label class="admin-check"><input id="notify-clear-secret" type="checkbox"> 清除已有签名密钥</label></div></div><div class="field"><label for="notify-url">团队访问地址（卡片中的结果入口）</label><input id="notify-url" value="${escape(c.public_url)}" placeholder="http://192.168.1.50:8766"><small class="muted">使用同事可访问的局域网 IP 或 HTTPS 域名，不填本机 127.0.0.1。</small></div><div class="notify-events">${events.map(([id,label])=>`<label class="admin-check"><input type="checkbox" data-notify-event="${id}" ${(c.events||[]).includes(id)?'checked':''}> ${label}</label>`).join('')}</div><div class="notify-actions"><button type="button" class="primary" data-notify="save">保存通知配置</button><button type="button" data-notify="test">发送测试提醒</button>${s.type!=='studio'?'<button type="button" data-notify="inherit">恢复上级配置</button>':''}</div><p class="muted small">凭据仅保存在服务端私密配置中。通知仅含结果摘要；完整证据仍需登录平台查看。</p>`;
   enhanceForm(value,s);
  }
  function enhanceForm(value,s){
   const c=value.effective,form=$('#notify-form'),actions=$('.notify-actions'),fields=document.createElement('fieldset');fields.id='notify-fields';
   const hasProjectWebhook=value.rule?.has_webhook===true;
   while(form.firstChild!==actions)fields.append(form.firstChild);form.prepend(fields);
   fields.insertAdjacentHTML('afterbegin',`<div class="field"><label for="notify-destination">接收群备注</label><input id="notify-destination" maxlength="100" value="${escape(c.destination_name||'')}" placeholder="例如：GagaSort 测试群"><small class="muted">手工备注，仅用于识别配置，不代表已读取飞书群名。</small></div>`);
   const presets={actionable:['completed','failed','interrupted','manual'],all:events.map(([id])=>id),errors:['failed','interrupted']};
   fields.querySelector('.notify-events').insertAdjacentHTML('beforebegin','<div class="field"><label for="notify-event-preset">提醒事件预设</label><select id="notify-event-preset"><option value="custom">自定义事件</option><option value="actionable">结果待审核 + 执行异常</option><option value="errors">仅失败与中断</option><option value="all">全部结果（含人工确认）</option></select><small class="muted">只调整下面的事件选择，保存后生效。暂不合并批次消息。</small></div>');
   const preset=$('#notify-event-preset');
   const selected=()=>[...fields.querySelectorAll('[data-notify-event]:checked')].map(el=>el.dataset.notifyEvent);
   function syncPreset(){const current=selected();preset.value=Object.keys(presets).find(key=>presets[key].length===current.length&&presets[key].every(id=>current.includes(id)))||'custom'}
   preset.onchange=()=>{if(presets[preset.value]){fields.querySelectorAll('[data-notify-event]').forEach(el=>{el.checked=presets[preset.value].includes(el.dataset.notifyEvent)});dirty=true}};
   fields.querySelectorAll('[data-notify-event]').forEach(el=>{el.onchange=()=>{syncPreset();dirty=true}});syncPreset();
   const note=document.createElement('p');note.className='muted small';note.textContent='更换 Webhook 会清除旧签名密钥，请填写新机器人的签名密钥。部门、节点的已有独立覆盖仍优先生效。';actions.before(note);
   fields.oninput=()=>{dirty=true};
   if(s.type!=='project')return;
   form.insertAdjacentHTML('afterbegin',`<div class="field"><label for="notify-mode">项目配置方式</label><select id="notify-mode"><option value="inherit">跟随工作室默认</option><option value="independent">本项目独立配置</option></select><small id="notify-mode-hint" class="muted"></small></div>`);
   const select=$('#notify-mode');select.value=value.mode;let previous=select.value;
   function applyMode(){
    const inherited=select.value==='inherit';fields.disabled=inherited;
    $('#notify-mode-hint').textContent=inherited?'使用工作室默认接收群；保存后生效。':'仅影响当前项目。独立配置必须使用本项目自己的 Webhook，不会复制工作室地址或签名密钥。';
    $('#notify-webhook').value='';$('#notify-secret').value='';
    if(!inherited&&!hasProjectWebhook){$('#notify-webhook').placeholder='请填写本项目自己的 Webhook';$('#notify-secret').placeholder='可选；不继承工作室密钥';$('#notify-destination').value=''}
    else{$('#notify-destination').value=c.destination_name||'';$('#notify-webhook').placeholder=hasProjectWebhook?'已配置；留空保留现有地址':'请填写本项目自己的 Webhook'}
   }
   select.onchange=()=>{if(dirty&&!confirm('切换配置方式会清空未保存的凭据，继续？')){select.value=previous;return}applyMode();previous=select.value;dirty=select.value!==value.mode};applyMode();
  }
  async function history(){const current=version;try{const s=scope(),data=await api(base+'/history?'+new URLSearchParams({project:s.project}));if(!live||!root.isConnected||current!==version)return;const html=data.items.map(r=>`<div class="notify-history-row"><div><strong>${escape(r.title)}</strong> <span class="notify-status ${escape(r.status)}">${escape(statuses[r.status]||r.status)}</span><p>${escape(beijing(r.created_at))} · #${r.id} · 尝试 ${r.attempts} 次</p>${r.error?`<p>${escape(r.error)}</p>`:''}</div>${!['pending','sending'].includes(r.status)?`<button type="button" data-notify="resend" data-id="${r.id}" data-project="${escape(r.project_id)}" data-status="${escape(r.status)}">补发</button>`:''}</div>`).join('')||'<p class="muted small">暂无发送记录。启用后只提醒新的运行结果。</p>';if($('#notify-history').innerHTML!==html)$('#notify-history').innerHTML=html}catch(e){if(live&&current===version)$('#notify-history').textContent='发送记录读取失败：'+e.message}finally{if(live&&current===version)timer=setTimeout(history,2000)}}
  root.onclick=async event=>{const target=event.target.closest('[data-notify]');if(!target||busy||!saved)return;busy=true;target.disabled=true;try{const action=target.dataset.notify,s=scope();if(action==='save'){const mode=s.type==='project'?$('#notify-mode').value:null;if(mode==='inherit'){await api(base+query(s),{mode:'inherit'});await load();toast('已恢复工作室默认配置');return}const body={enabled:$('#notify-enabled').checked,webhook:$('#notify-webhook').value,secret:$('#notify-secret').value,clear_secret:$('#notify-clear-secret').checked,public_url:$('#notify-url').value,destination_name:$('#notify-destination')?.value||'',events:[...root.querySelectorAll('[data-notify-event]:checked')].map(e=>e.dataset.notifyEvent)};if(mode)body.mode=mode;if(mode==='independent'&&!saved.rule?.has_webhook&&!body.webhook.trim())throw Error('请填写本项目自己的 Webhook');await api(base+query(s),body);await load();toast('通知配置已生效')}
    else if(action==='inherit'){if(dirty&&!confirm('恢复上级配置会丢弃未保存的修改，继续？'))return;await api(base+query(s),s.type==='project'?{mode:'inherit'}:{inherit:true});await load();toast('已恢复上级通知配置')}
    else if(action==='test'){if(dirty)throw Error('请先保存通知配置，再发送测试提醒');await api(base+'/test'+query(s),{});toast('测试提醒已排队，请查看发送记录')}
    else if(action==='resend'){if(!confirm(target.dataset.status==='unknown'?'这条消息可能已经送达。请先核对飞书群，确定再次发送？':'确定补发此提醒？不会重新执行节点。'))return;await api(base+'/'+target.dataset.id+'/resend?'+new URLSearchParams({project:target.dataset.project}),{});toast('提醒已重新排队')}
   }catch(e){toast(e.message)}finally{busy=false;if(target.isConnected)target.disabled=false}};
  let loaded=false;root.ontoggle=()=>{if(root.open&&!loaded){loaded=true;skeleton();load().then(history).catch(e=>{if(live)$('#notify-form').textContent=e.message})}};
 }
 return {page,mount,dispose:()=>cleanup()};
})();
