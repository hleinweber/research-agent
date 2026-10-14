const token = location.hash.slice(1);
let cursor = 0, busy = false;
const messages = document.querySelector('#messages');
const input = document.querySelector('#input');
const status = document.querySelector('#status');
const cards = new Map();
async function api(path, data) {
  const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST',
    headers: {'X-Session-Token': token, 'Content-Type': 'application/json'},
    body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function card(label, text, kind) {
  document.querySelector('#welcome')?.remove();
  const item = document.createElement('article'); item.className = kind;
  const heading = document.createElement('strong'); heading.textContent = label;
  const body = document.createElement('pre'); body.textContent = text;
  item.append(heading, body); messages.append(item); return item;
}
function render(event) {
  if (event.kind === 'reset') {messages.replaceChildren(); cards.clear(); return;}
  if (event.kind === 'user' || event.kind === 'assistant' || event.kind === 'error')
    card({user:'You', assistant:'Assistant', error:'Request error'}[event.kind], event.text, event.kind);
  if (event.kind === 'usage') {
    const row = document.createElement('p'); row.className = 'usage';
    row.textContent = `API call | Input: ${event.input ?? 'not reported'} | Cached input: ${event.cached ?? 'not reported'} | Output: ${event.output ?? 'not reported'}`;
    messages.append(row);
  }
  if (event.kind === 'command') {
    const item = card('Command awaiting your approval', event.text, 'command');
    const actions = document.createElement('div'); actions.className = 'actions';
    for (const [label, approved] of [['Approve',true],['Deny',false]]) {
      const button = document.createElement('button'); button.textContent = label;
      if (!approved) button.className = 'secondary';
      button.onclick = async () => {
        actions.querySelectorAll('button').forEach(b => b.disabled = true);
        try {await api('/approve', {id:event.id, approved});}
        catch (error) {status.textContent = error.message; actions.querySelectorAll('button').forEach(b => b.disabled = false);}
      };
      actions.append(button);
    }
    item.append(actions); cards.set(event.id, item);
  }
  if (event.kind === 'decision') {
    const item = cards.get(event.id);
    if (item) {item.querySelector('.actions')?.remove(); item.querySelector('strong').textContent = event.approved ? 'Approved | running command' : 'Command denied';}
  }
  if (event.kind === 'result') {
    const item = cards.get(event.id);
    item?.querySelector('.actions')?.remove();
    const result = card('Command result', event.output, 'result');
    const detail = document.createElement('small');
    detail.textContent = `Exit code: ${event.exit_code ?? 'not run'}${event.timed_out ? ' | Timed out' : ''}${event.truncated ? ' | Output truncated; showing tail' : ''}`;
    result.append(detail);
  }
  messages.scrollTop = messages.scrollHeight;
}
async function poll() {
  try {
    const result = await api(`/events?after=${cursor}`);
    result.events.forEach(render); cursor = result.cursor; busy = result.busy;
    status.textContent = busy ? 'Agent working | review any pending command below' : 'Ready';
    document.querySelector('#folder').textContent = `Working folder: ${result.folder}`;
    document.querySelector('#send').disabled = busy;
    document.querySelector('#reset').disabled = busy;
  } catch (error) {status.textContent = error.message;}
  setTimeout(poll, 500);
}
document.querySelector('#chat').onsubmit = async event => {
  event.preventDefault(); const text = input.value.trim(); if (!text || busy) return;
  busy = true; document.querySelector('#send').disabled = true;
  try {await api('/chat', {text}); input.value = ''; input.focus();}
  catch (error) {status.textContent = error.message; busy = false; document.querySelector('#send').disabled = false;}
};
input.onkeydown = event => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); document.querySelector('#chat').requestSubmit();}};
document.querySelector('#reset').onclick = async () => {try {await api('/reset', {});} catch(error) {status.textContent = error.message;}};
poll(); input.focus();
