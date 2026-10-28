"""Deterministic subagent checks; fake model, no external API or email calls."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from subagents import Subagents
from shell_tool import WINDOWS


class Plugins:
    routes = {"email__check_inbox": None, "email__read_message": None}
    tools = [{"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
             for name in routes]
    allow = set()
    def call(self, name, args):
        raise AssertionError("No live plugins in deterministic checks")


def answer(text="report"):
    return {"role": "assistant", "content": text}


def call(name, args):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "test-call", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / "reader.md").write_text(
            "---\nname: reader\ndescription: Test reader\ntools: email__check_inbox\nmax_turns: 3\n---\nReader system.")
        (self.folder / "shell.md").write_text(
            "---\nname: shell\ndescription: Test shell\ntools: bash\nmax_turns: 3\n---\nShell system.")
        self.manager = Subagents(Plugins(), self.folder, self.folder / "logs", time_limit=10)

    def tearDown(self):
        self.manager.close()
        for worker in self.manager.workers.values():
            worker.thread.join(timeout=2)
        self.temp.cleanup()

    def start_wait(self, agent="reader"):
        key = self.manager.start(agent, "isolated task")["id"]
        result = self.manager.wait([key], 3)[0]
        return key, result

    def test_delegate_followup_logs_and_usage(self):
        seen = []
        def model(messages, on_usage, **kwargs):
            seen.append([dict(m) for m in messages])
            on_usage({"input": 7, "output": 2, "cached": 0})
            self.assertEqual([t['function']['name'] for t in kwargs['tools']], ['email__check_inbox'])
            return answer("first" if len(seen) == 1 else "follow-up")
        with patch("agent.complete", side_effect=model):
            result = self.manager.call("delegate", {"agent": "reader", "task": "isolated task"})
            self.assertEqual(result['state'], 'idle')
            key = result['id']
            self.manager.call('subagent', {'action': 'send', 'id': key, 'message': 'continue'})
            result = self.manager.wait([key], 3)[0]
        self.assertEqual(result['report'], 'follow-up')
        self.assertEqual(seen[0], [{'role':'system','content':'Reader system.'}, {'role':'user','content':'isolated task'}])
        self.assertTrue(any(m.get('content') == 'first' for m in seen[1]))
        self.assertEqual(self.manager.total_tokens, 18)
        self.assertEqual(len(self.manager.drain_notes()), 2)
        records = [json.loads(line) for line in Path(result['log']).read_text().splitlines()]
        self.assertTrue(any(r.get('message', {}).get('content') == 'continue' for r in records))
        self.assertTrue(self.manager.call('subagent', {'action':'read','id':key,'last':2})['steps'])

    def test_forbidden_tool_and_recursion_never_execute(self):
        with patch('agent.complete', side_effect=[call('bash', {'command':'NEVER RUN'}), call('delegate', {}), answer()]), patch('subagents.run_command', side_effect=AssertionError('Forbidden shell executed')):
            key, result = self.start_wait()
        self.assertEqual(result['state'], 'idle')
        errors = [json.loads(m['content']) for m in self.manager.workers[key].messages if m['role']=='tool']
        self.assertTrue(all('not permitted' in e['output'] for e in errors))

    def test_turn_limit(self):
        with patch('agent.complete', return_value=call('bash', {'command':'NEVER RUN'})):
            _, result = self.start_wait()
        self.assertEqual(result['state'], 'failed')
        self.assertIn('max_turns', result['reason'])

    def test_four_workers_limit_stop_and_terminal_states(self):
        release = threading.Event()
        def model(*args, **kwargs):
            release.wait(3)
            return answer()
        with patch('agent.complete', side_effect=model):
            keys = [self.manager.start('reader', str(i))['id'] for i in range(4)]
            try:
                with self.assertRaisesRegex(ValueError, '4 subagents'):
                    self.manager.start('reader','fifth')
                self.assertEqual(len(self.manager.call('subagent', {'action':'list'})),4)
                self.assertEqual(self.manager.wait(keys,0)[0]['state'],'running')
                self.manager.call('subagent', {'action':'stop','id':keys[0]})
                with self.assertRaisesRegex(ValueError,'stopped'):
                    self.manager.call('subagent', {'action':'send','id':keys[0],'message':'wake'})
            finally:
                release.set()
            self.manager.wait(keys,3)

    def test_approval_denial_and_label(self):
        labels=[]
        self.manager.approve_shell=lambda label: labels.append(label) or False
        with patch('agent.complete', side_effect=[call('bash',{'command':'NEVER RUN'}), answer()]), patch('subagents.run_command', side_effect=AssertionError('Denied command ran')):
            _, result = self.start_wait('shell')
        self.assertEqual(result['state'],'idle')
        self.assertIn('[sa-1 · shell]',labels[0])

    def test_stop_kills_running_command(self):
        self.manager.approve_shell=lambda label: True  # Test-only approval of the sleep below.
        command='Start-Sleep -Seconds 600' if WINDOWS else 'sleep 600'
        with patch('agent.complete', return_value=call('bash', {'command':command})):
            key=self.manager.start('shell','test cancellation')['id']
            worker=self.manager.workers[key]
            deadline=time.monotonic()+4
            while worker.process is None and time.monotonic()<deadline:
                time.sleep(.02)
            process=worker.process
            self.assertIsNotNone(process)
            self.manager.call('subagent', {'action':'stop','id':key})
            worker.thread.join(3)
            self.assertIsNotNone(process.poll())
            self.assertEqual(worker.state,'stopped')
            records=[json.loads(line) for line in worker.path.read_text().splitlines()]
            events=[r.get('event') for r in records]
            for event in ('approval_requested','approval_decision','process_started','stop_requested','process_termination_confirmed','process_exited','command_result'):
                self.assertIn(event,events)
            self.assertLess(events.index('approval_decision'),events.index('process_started'))
            self.assertLess(events.index('process_started'),events.index('stop_requested'))
            started=next(r for r in records if r.get('event')=='process_started')
            exited=next(r for r in records if r.get('event')=='process_exited')
            self.assertEqual(started['pid'],process.pid)
            self.assertEqual(exited['pid'],process.pid)
            self.assertIsNotNone(exited['exit_code'])
            self.assertTrue(exited['cancelled'])

    def test_time_limit(self):
        self.manager.time_limit=.1
        with patch('agent.complete', side_effect=lambda *a,**k: (time.sleep(.3) or answer())):
            key,result=self.start_wait()
            self.manager.workers[key].thread.join(1)
        self.assertEqual(result['state'],'failed')
        self.assertIn('time limit',result['reason'])

    def test_unknown_tool_definition_fails_startup(self):
        (self.folder/'bad.md').write_text('---\nname: bad\ntools: nonexistent\n---\nTest')
        with self.assertRaisesRegex(ValueError,'unknown tool nonexistent'):
            Subagents(Plugins(), self.folder)

    def test_main_dispatch_returns_only_report_and_stats(self):
        from agent import agent_turn
        plugins = Plugins()
        plugins.subagents = self.manager
        messages = [{'role':'system','content':'Main private context'}, {'role':'user','content':'Delegate a task'}]
        def model(history, **kwargs):
            if history[0]['content'] == 'Reader system.':
                self.assertNotIn('Main private context', str(history))
                return answer('Only the report')
            if not any(m['role']=='tool' for m in history):
                names={t['function']['name'] for t in kwargs['tools']}
                self.assertTrue({'delegate','subagent'} <= names)
                return call('delegate',{'agent':'reader','task':'isolated task'})
            return answer('Done')
        with patch('agent.complete', side_effect=model):
            agent_turn(messages,plugins=plugins,on_text=lambda text:None)
        result=json.loads(next(m['content'] for m in messages if m['role']=='tool'))
        self.assertEqual(result['report'],'Only the report')
        self.assertNotIn('Reader system.', str(messages))
        audit=[json.loads(line) for line in (self.manager.logs/'main.jsonl').read_text().splitlines()]
        saved=[r['message'] for r in audit if r.get('event')=='message']
        self.assertEqual(saved,messages)
        self.assertTrue(any(m.get('tool_calls') for m in saved))
        self.assertTrue(any(m.get('role')=='tool' for m in saved))
        self.assertEqual([r['sequence'] for r in audit],list(range(1,len(audit)+1)))
        with patch('agent.complete',return_value=answer('Second turn')):
            messages.append({'role':'user','content':'Continue'})
            agent_turn(messages,plugins=plugins,on_text=lambda text:None)
        saved=[r['message'] for r in map(json.loads,(self.manager.logs/'main.jsonl').read_text().splitlines()) if r.get('event')=='message']
        self.assertEqual(saved,messages)  # Prior turns are not duplicated.

    def test_web_shell_approval_requires_positive_user_decision(self):
        import web
        for answered, decision, expected in [(True,False,False),(False,True,False),(True,True,True)]:
            approval={'id':'test','approved':decision}
            with patch('web.request_approval',return_value=(approval,answered)), patch('web.emit'):
                self.assertIs(web.web_approve_shell('[sa-1] command'),expected)

    def test_web_decisions_persist_without_session_cookie(self):
        import web
        plugins=Plugins()
        plugins.subagents=self.manager
        with patch.object(web,'PLUGINS',plugins), patch.object(web,'EVENTS',[]):
            web.emit('decision',id='approval-id',approved=True)
            self.assertEqual(len(web.EVENTS),1)
        saved=[json.loads(line) for line in (self.manager.logs/'main.jsonl').read_text().splitlines()]
        event=next(r for r in saved if r['event']=='web_event')
        self.assertEqual(event['data'],{'kind':'decision','id':'approval-id','approved':True})
        self.assertIn('time',event)

    def test_session_metadata_and_close_are_persistent(self):
        self.manager.close()
        self.manager.close()
        records=[json.loads(line) for line in (self.manager.logs/'main.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records],['session_started','session_closed'])
        self.assertTrue(all(r['session_id']==self.manager.session_id for r in records))
        self.assertTrue(all(r['schema_version']==1 and '+00:00' in r['timestamp'] for r in records))

    def test_unhandled_tool_error_is_logged_without_exception_text(self):
        from agent import agent_turn
        plugins=Plugins()
        plugins.subagents=self.manager
        with patch('agent.complete',return_value=call('subagent',{'action':'list'})), patch.object(self.manager,'call',side_effect=RuntimeError('private error detail')):
            with self.assertRaises(RuntimeError):
                agent_turn([{'role':'system','content':'Test'}],plugins=plugins)
        records=[json.loads(line) for line in (self.manager.logs/'main.jsonl').read_text().splitlines()]
        error=next(r for r in records if r['event']=='tool_error')
        self.assertEqual(error['tool_call_id'],'test-call')
        self.assertEqual(error['error_type'],'RuntimeError')
        self.assertTrue(error['propagated'])
        self.assertNotIn('private error detail',json.dumps(error))

    def test_main_command_process_events_are_correlated(self):
        from agent import agent_turn
        from shell_tool import run_command
        plugins=Plugins()
        plugins.subagents=self.manager
        command='Write-Output audit-check' if WINDOWS else 'printf audit-check'
        messages=[{'role':'system','content':'Test'}]
        # A fixed harmless command; production approval callbacks are unchanged.
        with patch('agent.complete',side_effect=[call('bash',{'command':command}),answer()]):
            agent_turn(messages,plugins=plugins,run_tool=run_command,on_text=lambda text:None)
        saved=[json.loads(line) for line in (self.manager.logs/'main.jsonl').read_text().splitlines()]
        processes=[r for r in saved if r.get('event') in ('process_started','process_exited')]
        self.assertEqual(len(processes),2)
        self.assertTrue(all(r['tool_call_id']=='test-call' and r['actor']=='main' for r in processes))
        self.assertEqual(processes[0]['pid'],processes[1]['pid'])
        self.assertEqual(processes[1]['exit_code'],0)


if __name__ == '__main__':
    unittest.main()
