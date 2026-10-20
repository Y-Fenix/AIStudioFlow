/* Public, intentionally narrow context for repository-owned department UI modules. */
(function (root) {
  'use strict';
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  function createContext({department, studio, project, nodeIndex = 0, workspace = null}) {
    const node = department?.nodes?.[nodeIndex];
    return {
      department: department ? {
        id: department.id, name: department.name, title: department.title, desc: department.desc,
        nodes: department.nodes.map(item => item.slice())
      } : null,
      studio: studio ? {id: studio.id, name: studio.name} : null,
      project: project ? {id: project.id, name: project.name} : null,
      node: node ? {
        id: department.node_keys?.[nodeIndex] ?? department.id+':'+nodeIndex, index: nodeIndex, name: node[0], purpose: node[1], deliverable: node[2], goal: node[4],
        inputContract: node[5], outputContract: node[6]
      } : null,
      workspace: workspace ? {
        revision: workspace.revision, status: workspace.status, inputs: workspace.inputs,
        deliverable: workspace.deliverable,
        skill: workspace.skill ? {
          name: workspace.skill.name, source_kind: workspace.skill.source_kind,
          sha256: workspace.skill.sha256
        } : null
      } : null,
      escape: escapeHtml
    };
  }

  function render(ui, slot, context) {
    if (typeof ui?.[slot] !== 'function') return '';
    const markup = ui[slot](context);
    return typeof markup === 'string' && markup.length <= 100000 ? markup : '';
  }

  function mount(ui, slot, {element, context, readDraft, updateDraft, notify, isCurrent = () => true, onError = () => {}}) {
    const controller = new AbortController();
    let cleanup;
    const active = () => {
      if (controller.signal.aborted || !isCurrent()) throw Error('当前部门界面已失效，请返回后重试');
    };
    const tools = Object.freeze({
      signal: controller.signal,
      readDraft() { active(); return readDraft ? {...readDraft()} : null; },
      updateDraft(patch) {
        active();
        if (!patch || typeof patch !== 'object' || Array.isArray(patch) ||
            !Object.keys(patch).length || Object.entries(patch).some(([key, value]) =>
              !['inputs', 'deliverable'].includes(key) || typeof value !== 'string')) {
          throw Error('部门草稿仅支持 inputs / deliverable 文本');
        }
        if (!updateDraft) throw Error('当前界面不支持修改草稿');
        return updateDraft({...patch});
      },
      notify(message) { active(); if (notify) notify(String(message)); }
    });
    const runCleanup = fn => { try { fn(); } catch (error) { onError(error); } };
    try {
      if (typeof ui?.[slot] === 'function') {
        const result = ui[slot](element, context, tools);
        if (typeof result === 'function') cleanup = result;
        else if (result && typeof result.then === 'function') {
          Promise.resolve(result).then(fn => {
            if (typeof fn !== 'function') return;
            if (controller.signal.aborted) runCleanup(fn);
            else cleanup = fn;
          }).catch(error => { if (!controller.signal.aborted) onError(error); });
        }
      }
    } catch (error) { controller.abort(); onError(error); }
    return () => {
      if (controller.signal.aborted) return;
      controller.abort();
      if (cleanup) { const fn = cleanup; cleanup = null; runCleanup(fn); }
    };
  }

  function canCreateEntity(kind, capabilities = {}) {
    if (kind === 'studios') return capabilities.studio_create === true;
    if (kind === 'projects') return capabilities.project_create === true;
    return false;
  }

  function skillControls(capabilities = {}, node) {
    const nodeCaps = capabilities.nodes?.[node] || {};
    const view = nodeCaps.skill_view === true;
    return {
      view,
      import: view && nodeCaps.skill_import === true,
      export: view && nodeCaps.skill_export === true
    };
  }

  root.DepartmentUIContract = Object.freeze({createContext, render, mount, canCreateEntity, skillControls});
})(globalThis);
