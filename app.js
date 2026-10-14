const token = location.hash.slice(1);
let cursor = 0, busy = false, connected = false, sending = false;
const messages = document.querySelector('#messages');
const input = document.querySelector('#input');
const status = document.querySelector('#status');
const notice = document.querySelector('#notice');
function showError(message) { notice.textContent = message; notice.hidden = false; }
function updateButtons() {
  document.querySelector('#send').disabled = !connected || busy || sending;
  document.querySelector('#reset').disabled = !connected || busy || sending;
}
const cards = new Map();
async function api(path, data) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST',
      signal: controller.signal,
      headers: {'X-Session-Token': token, 'Content-Type': 'application/json'},
      body: data === undefined ? undefined : JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Request failed');
    return result;
  } catch (error) {
    if (error.name === 'TypeError' || error.name === 'AbortError')
      throw new Error('Cannot reach the local server. Run uv run python web.py in the research-agent folder, then open its new browser link.');
    throw error;
  } finally { clearTimeout(timer); }
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
    connected = true; notice.hidden = true;
    status.textContent = busy ? 'Agent working | review any pending command below' : 'Ready';
    document.querySelector('#folder').textContent = `Working folder: ${result.folder}`;
    updateButtons();
  } catch (error) {
    connected = false; status.textContent = 'Disconnected';
    showError(error.message); updateButtons();
  }
  setTimeout(poll, 500);
}
document.querySelector('#chat').onsubmit = async event => {
  event.preventDefault(); const text = input.value.trim();
  if (!text || busy || sending || !connected) return;
  sending = true; updateButtons(); status.textContent = 'Sending...';
  try {await api('/chat', {text}); busy = true; input.value = ''; input.focus();}
  catch (error) {render({kind:'error', text:error.message}); status.textContent = 'Message was not sent';}
  finally {sending = false; updateButtons();}
};
input.onkeydown = event => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); document.querySelector('#chat').requestSubmit();}};
document.querySelector('#reset').onclick = async () => {try {await api('/reset', {});} catch(error) {status.textContent = error.message;}};
poll(); input.focus();
