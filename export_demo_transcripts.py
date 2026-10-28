"""Render reviewed demo evidence as JSON file contents; never export raw inbox data.

Run with python -B export_demo_transcripts.py. Output is a mapping of relative
transcript paths to Markdown, suitable for review before saving or sharing.
"""
import http.cookiejar
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
OLD = ROOT / 'logs/20261027-181046-af2bcbb9'
NEW = ROOT / 'logs/20261027-182559-b22c58f5'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds')


def render(records, inbox=False):
    out=[]
    for record in records:
        message=record.get('message', {})
        role=message.get('role')
        if role == 'system':
            continue
        out.append(f"### {stamp(record['time'])}\n")
        if 'state' in record:
            out.append(f"State: **{record['state']}**. Reason: {record.get('reason') or '(none)'}.\n")
        elif 'usage' in record:
            counts=record['usage']
            out.append(f"Model usage: input {counts.get('input')}, output {counts.get('output')}.\n")
        elif role:
            out.append(f"**{role}**\n")
            if role == 'tool' and inbox:
                result=json.loads(message['content'])
                out.append(f"[Private inbox results withheld: {len(result.get('messages', []))} messages. Sender addresses, subjects, dates, and message IDs omitted.]\n")
            elif role == 'assistant' and inbox and message.get('content'):
                out.append('[Private inbox report withheld. The user confirmed that the reported email titles were correct.]\n')
            elif message.get('content'):
                content=message['content']
                out.append('```text\n'+content[:14000]+ ('\n[Truncated for transcript.]' if len(content)>14000 else '')+'\n```\n')
            for call in message.get('tool_calls', []):
                out.append(f"Tool call: `{call['function']['name']}`\n\n```json\n{call['function']['arguments']}\n```\n")
        else:
            out.append('```json\n'+json.dumps(record,ensure_ascii=False)+'\n```\n')
    return '\n'.join(out)


def live_events():
    try:
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base='http://127.0.0.1:8765'
        with client.open(base+'/',timeout=5) as response:
            response.read()
        with client.open(base+'/events?after=0',timeout=5) as response:
            return json.load(response)['events']
    except (OSError, ValueError):
        return []


def event_text(events):
    return '\n'.join(f"- Event {index}: `{event['kind']}` — {json.dumps(event,ensure_ascii=False)}" for index,event in events if event.get('kind') in ('user','assistant','command','decision','result','error'))


def build_legacy():
    inbox=rows(OLD/'sa-1.jsonl')
    research=[rows(OLD/f'sa-{i}.jsonl') for i in (2,3,4)]
    initial=[]
    follow=[]
    for records in research:
        end=next(i for i,r in enumerate(records) if r.get('state')=='idle')
        initial.append(records[:end+1])
        if records is research[-1]:
            tail=records[end+1:]
            follow=tail[:next(i for i,r in enumerate(tail) if r.get('state')=='idle')+1]
    events=live_events()
    stop_start=next((i for i,e in enumerate(events) if e.get('kind')=='user' and e.get('text','').startswith('Start stop-demo in the background. Do not stop')),None)
    limit_start=next((i for i,e in enumerate(events) if e.get('kind')=='user' and e.get('text','').startswith('Delegate to limit-demo to perform')),None)
    stop_events=list(enumerate(events))[stop_start:limit_start] if stop_start is not None else []
    limit_events=list(enumerate(events))[limit_start:] if limit_start is not None else []
    files={}
    inbox_end=next(i for i,r in enumerate(inbox) if r.get('state')=='idle')
    files['01-inbox-delegation.md']='''# Demo 1: inbox delegation

Source: `logs/20261027-181046-af2bcbb9/sa-1.jsonl`. Dates below are UTC. This is a redacted worker transcript, not a reconstruction of the missing main-agent conversation.

Review: mail-reader called only email__check_inbox and returned an inbox report. The user confirmed the email titles in the web interface. No email body was read or sent in this demo. The original main-agent delegate call/result was held only in memory and was lost on restart; this transcript alone does not establish the main agent's report-only view. The implementation's automated isolation test covers that behavior separately.

Privacy: all inbox result fields and the inbox report are withheld, including account/security subjects and addresses. Full private evidence remains in ignored local logs.

'''+render(inbox[:inbox_end+1],inbox=True)
    windows=[(r[0]['time'],r[-1]['time']) for r in initial]
    overlap=max(a for a,b in windows)<min(b for a,b in windows)
    files['02-research-fan-out.md']='''# Demo 2: three-way research fan-out

Sources: `logs/20261027-181046-af2bcbb9/sa-{2,3,4}.jsonl`. The main-agent combined report was user-confirmed in the web interface, but its text and the original start/wait calls were lost on restart. Worker reports below are verbatim excerpts, not scientifically endorsed conclusions.

Review: the three active intervals overlap (verified from creation to first idle). Each worker called search_papers and get_paper and returned a report. This proves concurrent work; the missing main-agent trace limits direct evidence for the wait/combine steps.

Scientific review: the core source is a 2017 pre-InSight review with no retrieved abstract, so it is not an observational InSight core result. The magnetometer source is an EGU conference abstract about electromagnetic sounding, not a verified calibration-method paper. The crust summary relies on deposited abstract metadata without full-text verification. Preserve these limitations when evaluating the reports.

'''+f"Concurrency overlap: **{overlap}**.\n\n"+'\n'.join(f"- sa-{i+2}: {stamp(a)} to {stamp(b)}" for i,(a,b) in enumerate(windows))+'\n\n'+'\n'.join(f"## sa-{i+2}\n\n"+render(r) for i,r in enumerate(initial))
    files['03-preserved-context-follow-up.md']='''# Demo 3: preserved-context follow-up

Source: `logs/20261027-181046-af2bcbb9/sa-4.jsonl`, after its first idle event. The worker ID and log file are unchanged from demo 2. The follow-up is appended after the initial report, then answered with one model call and no tool calls. This supports preserved-context continuation. The main agent's send/wait calls were lost on restart.

Scientific review: the answer's suggestions about calibration steps and post-calibration data exceed what the retrieved abstract establishes. Treat those phrases as speculation, not verified calibration findings. The demonstration tests context reuse rather than scientific correctness.

'''+render(follow)
    files['04-stop-running-command.md']='''# Demo 4: stopping a long command

Source: `logs/20261027-182559-b22c58f5/sa-2.jsonl` and the still-running web session's ordered events. sa-1 in this session was an earlier unsuccessful attempt stopped before approval; it is excluded.

Review: the corrected sa-2 run requested Start-Sleep -Seconds 600. The web events show user approval before the subsequent instruction to list/read/stop, followed by the stopped notification. A read-only process check after the test found no matching sleep process. However, the logger does not preserve process-start/exit events or the main model's list/read tool calls. The assistant's claim that it listed/read the worker is a report, not a captured tool trace. Process termination is supported by ordering and the process check, but the saved artifacts lack a PID/exit record. Record a fresh demo with improved audit logging if direct proof of every step is required.

## Web events (ordered; no timestamps were stored)

'''+(event_text(stop_events) or '[Web events unavailable during export.]')+'\n\n## Worker log\n\n'+render(rows(NEW/'sa-2.jsonl'))
    files['05-turn-limit-failure.md']='''# Demo 5: enforced turn-limit failure

Source: `logs/20261027-182559-b22c58f5/sa-3.jsonl` and ordered web events. limit-demo has max_turns: 3 and requests four sequential reference-source calls, one per model turn.

Review: exactly three model calls and three successful insight_reference_sources tool results are recorded. The worker then becomes failed with reason max_turns exceeded before a fourth model/tool call. The web session records the failure notification and the main agent's explanation. This is an intentional limits test, not an external service failure.

## Worker log

'''+render(rows(NEW/'sa-3.jsonl'))+'\n\n## Web events\n\n'+(event_text(limit_events) or '[Web events unavailable during export.]')
    files['README.md']='''# Week 4 demo transcript review

These transcripts preserve the available evidence from the October 27, 2026 demonstrations. All log timestamps are UTC; the demonstrations occurred October 27 in America/Los_Angeles. They are evidence excerpts, not recreated main-agent conversations. Raw logs remain private and ignored by Git.

| Demo | Review |
| --- | --- |
| 1. Inbox delegation | Worker read-only access and report recorded; private inbox details removed. Original main delegate trace lost on restart. |
| 2. Research fan-out | Three overlapping worker runs and their reports recorded. Main start/wait/combine trace lost; combined report user-confirmed. Research caveats appear in the transcript. |
| 3. Follow-up | Same worker conversation, one new model call, no new tools. Original main send/wait trace lost. |
| 4. Stop | Approval precedes stop; stopped state recorded; no matching process found afterward. Direct process PID/exit and list/read call records are missing. |
| 5. Limit | Three turns/calls, failed state, max_turns reason, and main-agent notification recorded. |

## Before submission

- Decide whether to rerun demos 1–4 with main tool-call and process audit logging to close the evidence gaps. Do not claim missing traces exist.
- Review the scientific limitations in demos 2–3; source discovery is not independent validation of the scientific claims.
- Copy reviewed transcripts, agents/, and the email plugin into week-4/submissions/hleinweber/ with a submission README linking to the harness and explaining worker lifecycle and stop behavior.
- The class hello was sent October 27, 2026. A class-agent reply has not been confirmed in these transcripts.
- No raw inbox subjects, bodies, sender addresses, credentials, or browser cookies are included in these exports.

No pull request or publication is performed by saving these files.
'''
    return files


def build():
    """Use persistent audit records; never infer concurrency from a summary."""
    first=ROOT/'logs/20261027-190241-1b25730d'
    second=ROOT/'logs/20261027-191604-b857ab60'
    specs=[
        ('01-inbox-delegation.md','Demo 1: inbox delegation',first,34,64,['sa-2'],
         'PASS: the main agent called delegate for mail-reader. The worker called email__check_inbox with unread_only=false and returned four messages. Its report returned to the main agent. Private inbox fields and reports are redacted. The earlier unread-only check returned none; this transcript uses the subsequent successful recent-message check.'),
        ('02-research-fan-out.md','Demo 2: three-way research fan-out',second,99,None,['sa-3','sa-4','sa-5'],
         '''PASS for orchestration: three background start calls precede wait for sa-3, sa-4, and sa-5. All three active intervals overlap; each returns a report and the main agent combines them. This replaces the earlier sequential-delegation attempt.

### Scientific caveats

- A search returning no matching magnetometer-calibration paper does not show that no such papers exist, nor that calibration is undocumented. It establishes only that this particular query, source, ranking, and returned results did not identify a match. The worker's suggestion that this implies a lack of publications is unsupported.
- NASA PDS and mission technical reports were suggested but were not consulted during this run. No conclusion about their contents or calibration validation follows from this transcript.
- DOI lookup verifies retrieved bibliographic metadata, not the truth of findings or a complete review of the literature. Deposited abstracts are not full-text verification; missing or truncated abstracts leave findings unsupported by this run.
- Keep conference abstracts, review articles, journal research, and explanatory articles distinct. In particular, the EPSC abstract DOI 10.5194/epsc2021-512 must not be presented as a full peer-reviewed journal paper. Reported publication years and source labels still need checking against the original source before reuse in scientific writing.
- Findings about the shallow crust beneath the landing site must not be generalized to the entire Martian crust or to an absence of water/ice everywhere. Model-dependent bounds are not direct measurements of every material property.
- Claims of active faults, novelty, or a first planetary achievement are not established merely by a title or the existence of a DOI. Omit them unless checked against an appropriate primary source.

The historical worker reports and combined report below are preserved as recorded, including overstatements. These caveats qualify their interpretation; the transcript is a software demonstration, not a validated scientific synthesis.'''),
        ('03-preserved-context-follow-up.md','Demo 3: preserved-context follow-up',first,125,151,['sa-5'],
         'PASS for lifecycle/context: the main agent sent a follow-up to the same idle worker sa-5, then waited. The existing conversation was resumed, with one additional model call and no new tool calls. Caveat: the preceding search found no magnetometer source, so this is a context-reuse demonstration about that absence, not an explanation grounded in a retrieved paper.'),
        ('04-stop-running-command.md','Demo 4: stop a running command',second,4,63,['sa-1'],
         'PASS: background start returned sa-1; the user approved the sleep command; PID 24228 started. Captured list/read calls inspected the running worker. stop requested termination and process_termination_confirmed recorded PID 24228 with exit code 1. process_exited recorded cancelled=true, timed_out=false. A final list showed stopped, pid=null, command_running=false. Nonzero exit is expected for this intentionally terminated command.'),
        ('05-turn-limit-failure.md','Demo 5: enforced turn-limit failure',second,63,99,['sa-2'],
         'PASS: limit-demo was started and awaited. Its three model turns made three successful reference-source calls; before the fourth model call it failed with max_turns exceeded. The main agent received the failure and reported it. Although the user requested delegate, the model used start/wait; this still demonstrates the required background limit enforcement, and blocking delegate is independently exercised in demo 1.'),
    ]
    files={}
    for filename,title,folder,start,end,ids,review in specs:
        all_rows=rows(folder/'main.jsonl')
        selected=[r for r in all_rows if r['sequence']>=start and (end is None or r['sequence']<end)]
        text=f'# {title}\n\nSource: `logs/{folder.name}/main.jsonl`, audit sequence {start} to {end-1 if end else "end"}. All timestamps are UTC. Records below are actual saved events; no missing calls are reconstructed. Worker system prompts and duplicate web-render events are omitted.\n\n## Review\n\n{review}\n\n'
        for key in ids:
            records=rows(folder/f'{key}.jsonl')
            idle=next((r['time'] for r in records if r.get('state')=='idle'),None)
            if filename=='02-research-fan-out.md':
                text+=f'- {key}: created {stamp(records[0]["time"])}; first idle {stamp(idle)}.\n'
        text+='\n## Recorded sequence\n\n'
        for r in selected:
            kind=r['event']
            entry=None
            if kind=='message':
                m=dict(r['message'])
                if m.get('role')=='system':
                    continue
                if filename=='01-inbox-delegation.md':
                    if m.get('role')=='tool':
                        result=json.loads(m['content'])
                        if isinstance(result,dict):
                            result={k:v for k,v in result.items() if k in ('id','agent','state','turns','tokens','seconds','reason')}
                            result['report']='[Private inbox report redacted.]'
                        m['content']=json.dumps(result)
                    elif m.get('role')=='assistant' and m.get('content'):
                        m['content']='[Private inbox summary redacted.]'
                    elif m.get('role')=='user' and m.get('content','').startswith('[subagent notes'):
                        m['content']='[Worker completion note: private inbox report redacted.]'
                entry={'message':m}
            elif kind=='worker_event' and r['worker_id'] in ids:
                e=dict(r['record'])
                m=e.get('message',{})
                if m.get('role')=='system':
                    continue
                if filename=='01-inbox-delegation.md':
                    if m.get('role')=='tool':
                        result=json.loads(m['content'])
                        e={'message':{'role':'tool','tool_call_id':m.get('tool_call_id'),'content':f'[Private inbox data redacted: {len(result.get("messages",[]))} messages.]'}}
                    elif m.get('role')=='assistant' and m.get('content'):
                        e={'message':{'role':'assistant','content':'[Private inbox report redacted.]'}}
                    elif 'report' in e:
                        e['report']='[Private inbox report redacted.]'
                entry={'worker_id':r['worker_id'],'record':e}
            elif kind in ('tool_started','tool_finished','tool_error','tool_authorization','model_error','model_usage'):
                entry={k:v for k,v in r.items() if k not in ('time','sequence','timestamp','session_id','schema_version')}
            if entry is not None:
                text+=f'### Sequence {r["sequence"]} — {r["timestamp"]}\n\n```json\n'+json.dumps(entry,ensure_ascii=False,indent=2)+'\n```\n\n'
        files[filename]=text
    files['README.md']='''# Reviewed Week 4 demo transcripts

These transcripts replace the earlier excerpts with persistent main/worker audit evidence from the reruns on October 27, 2026 (America/Los_Angeles). Timestamps are UTC. They preserve actual call arguments, correlated tool results, approval evidence, and process events while omitting duplicate UI events and private inbox contents.

| Demo | Review |
| --- | --- |
| 1. Inbox delegation | PASS: delegate, read-only inbox call, report return, and main response recorded; private fields redacted. |
| 2. Three-way fan-out | PASS: corrected rerun starts three background workers before wait; their active intervals overlap and the main agent combines their reports. Scientific caveats qualify the recorded claims. |
| 3. Follow-up | PASS for preserved context and no new tools. Search had found no magnetometer source, so paper-specific scientific discussion was unavailable. |
| 4. Stop | PASS: background start, approval, PID, running list/read, stop, confirmed termination, cancellation, final stopped list. |
| 5. Limit | PASS: three successful calls, enforced failure before fourth, main-agent notification. |

## Remaining before submission

All five lifecycle demonstrations have supporting main/worker audit records. Demo 3 remains a context-reuse example about a search that found no source; a follow-up to a retrieved paper would provide a richer scientific example but is not needed to prove conversation continuation. The class-agent reply was received and read back on October 28, 2026; see the submission README. Final publication remains to be done.

The scientific reports are model outputs with limitations, not independently validated research conclusions. No email addresses, inbox subjects/bodies, credentials, or browser cookies are included in these exports. Private raw logs remain ignored by Git. Class hello receipt and reply read-back are confirmed. Nothing here has been published.
'''
    # Keep technical paths useful without publishing the student's home directory.
    return {name: re.sub(r'C:(?:\\+|/)Users(?:\\+|/)hleinweber(?:\\+|/)research-agent',
                         '[HARNESS_ROOT]', content) for name, content in files.items()}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(build(),ensure_ascii=False))
