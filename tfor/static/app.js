document.querySelectorAll('[data-dialog]').forEach(button => {
  button.addEventListener('click', () => document.getElementById(button.dataset.dialog)?.showModal())
})
document.querySelectorAll('[data-close]').forEach(button => {
  button.addEventListener('click', () => button.closest('dialog')?.close())
})
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close()
  })
})
document.querySelectorAll('[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault()
  })
})
document.getElementById('menu-toggle')?.addEventListener('click', () => {
  document.querySelector('.sidebar')?.classList.toggle('open')
})

const filterList = document.getElementById('filter-list')
if (filterList) {
  const empty = document.getElementById('filter-empty')
  const hidden = document.getElementById('filters-json')
  const labels = {
    text: '消息正文', sender_name: '发送者昵称', sender_username: '@username', sender_id: 'Telegram ID'
  }

  function option(value, text, selected) {
    return `<option value="${value}" ${value === selected ? 'selected' : ''}>${text}</option>`
  }

  function addStep(step = {}) {
    const row = document.createElement('div')
    row.className = 'filter-step'
    row.draggable = true
    const values = Array.isArray(step.values) ? step.values.join('\n') : (step.values || '')
    row.innerHTML = `
      <span class="handle" title="拖动排序">⠿</span>
      <select data-key="kind">${option('blacklist', '黑名单', step.kind || 'blacklist')}${option('whitelist', '白名单', step.kind)}</select>
      <select data-key="field">${Object.entries(labels).map(([key, label]) => option(key, label, step.field || 'text')).join('')}</select>
      <select data-key="match_mode">${option('contains', '包含', step.match_mode || 'contains')}${option('exact', '完全匹配', step.match_mode)}${option('regex', '正则', step.match_mode)}</select>
      <textarea data-key="values" placeholder="一行一个值（ANY）"></textarea>
      <button type="button" class="remove" title="删除">×</button>
      <label class="enable"><input type="checkbox" data-key="enabled" ${step.enabled === false || step.enabled === 0 ? '' : 'checked'}> 启用本步骤</label>`
    row.querySelector('textarea').value = values
    row.querySelector('.remove').addEventListener('click', () => { row.remove(); sync() })
    row.querySelectorAll('input,select,textarea').forEach(control => control.addEventListener('change', sync))
    row.addEventListener('dragstart', () => row.classList.add('dragging'))
    row.addEventListener('dragend', () => { row.classList.remove('dragging'); sync() })
    filterList.appendChild(row)
    sync()
  }

  function sync() {
    const rows = [...filterList.querySelectorAll('.filter-step')]
    empty.hidden = rows.length > 0
    hidden.value = JSON.stringify(rows.map(row => ({
      kind: row.querySelector('[data-key="kind"]').value,
      field: row.querySelector('[data-key="field"]').value,
      match_mode: row.querySelector('[data-key="match_mode"]').value,
      values: row.querySelector('[data-key="values"]').value,
      enabled: row.querySelector('[data-key="enabled"]').checked
    })))
  }

  filterList.addEventListener('dragover', event => {
    event.preventDefault()
    const dragging = filterList.querySelector('.dragging')
    if (!dragging) return
    const siblings = [...filterList.querySelectorAll('.filter-step:not(.dragging)')]
    const next = siblings.find(element => event.clientY < element.getBoundingClientRect().top + element.offsetHeight / 2)
    filterList.insertBefore(dragging, next || null)
  })
  document.getElementById('add-filter').addEventListener('click', () => addStep())
  ;(window.initialFilters || []).forEach(addStep)
  document.getElementById('rule-form').addEventListener('submit', sync)
  sync()
}
