"""Durable event delivery and terminal reconciliation, independent of execution."""
from __future__ import annotations

import asyncio
import copy

from b04.model_adapter.contracts import utc_now
from .contracts import RECEIPT_SCHEMA, RECONCILE_SCHEMA, RunnerError, TERMINALS, validate


class EventOutbox:
    def __init__(self,*,store,sink,transport_budget,control_budget,timeout_seconds=1):
        self.store,self.sink,self.transport,self.control_budget=store,sink,transport_budget,control_budget
        self.timeout_seconds=timeout_seconds
        self._locks={}
        self._background=set()

    async def _call(self,awaitable):
        task=asyncio.create_task(awaitable)
        try:
            done,_=await asyncio.wait([task],timeout=self.timeout_seconds)
            if task in done:return task.result()
            raise RunnerError("EXEC_TIMEOUT",stage="event_transport")
        finally:
            if not task.done():
                task.cancel();self._background.add(task)
                def finished(future):
                    self._background.discard(future)
                    try:future.result()
                    except BaseException:pass
                task.add_done_callback(finished)

    async def flush(self,ref,controls):
        from b04.model_adapter.contracts import canonical
        lock=self._locks.setdefault(canonical(ref),asyncio.Lock())
        async with lock:
            rows=self.store.events(ref,controls.observe.context)
            for row in rows:
                event=row["event"]
                if row["delivery"] not in {"pending","rejected"}:continue
                try:
                    if row["delivery"]=="rejected":
                        if event["event_type"] in TERMINALS:
                            await self._reconcile(ref,event,row["receipt"],controls)
                        continue
                    self.transport.consume_transport(controls.transport_ticket_ref,ref)
                    receipt=await self._call(self.sink.submit_event(copy.deepcopy(event)))
                    validate(receipt,RECEIPT_SCHEMA,"EXEC_RUNNER_ERROR",stage="event_receipt")
                    status=receipt["receipt_status"]
                    if receipt["reconciliation_required"]!=(status=="rejected") or receipt["event_id"] not in {event["event_id"],None} or status!="rejected" and receipt["event_id"] is None or status=="rejected" and not receipt["reason_code"]:
                        raise RunnerError("EXEC_RUNNER_ERROR",stage="event_receipt_identity")
                    self.store.delivery(event["event_id"],status,receipt,controls.report.context)
                    if status=="rejected":
                        if event["event_type"] in TERMINALS:
                            await self._reconcile(ref,event,receipt,controls)
                        else:
                            self.store.note(ref,"nonterminal_event_rejected",dict(event_id=event["event_id"],receipt_ref=receipt["receipt_ref"],responsible="B02"),controls.report.context)
                except Exception:
                    # Delivery trouble never reopens execution or creates a new terminal.
                    self.store.note(ref,"delivery_or_reconciliation_pending",dict(event_id=event["event_id"],responsible="B02",required_action="inspect_original_event_and_receipt"),controls.report.context)
                    break

    async def _reconcile(self,ref,event,receipt,controls):
        request=dict(submission_id=event["payload"]["submission_id"],invocation_ref=copy.deepcopy(ref),original_event_id=event["event_id"],
                     rejection_receipt_ref=receipt["receipt_ref"],terminal_record_ref=event["payload"]["terminal_record_ref"])
        self.control_budget.consume_control(controls.report.context["budget_ticket_ref"],ref,utc_now())
        self.transport.consume_transport(controls.transport_ticket_ref,ref)
        decision=await self._call(self.sink.reconcile_terminal(request,controls.report.context))
        validate(decision,RECONCILE_SCHEMA,"EXEC_RUNNER_ERROR",stage="terminal_reconciliation")
        if decision["submission_id"]!=request["submission_id"]:
            raise RunnerError("EXEC_RUNNER_ERROR",stage="reconciliation_identity")
        resolution=decision["resolution"]
        status={"recorded":"reconciled","stale":"stale","retry_delivery":"pending","new_attempt_required":"new_attempt_required","manual_required":"manual_required"}[resolution]
        self.store.delivery(event["event_id"],status,receipt,controls.report.context,reconciliation=decision)

