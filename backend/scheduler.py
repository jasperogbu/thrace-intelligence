"""Background scheduler making Thrace autonomous.

Runs inside the FastAPI process:
- re-validates watched chats when due (default weekly) via the Monitoring
  Agent, appending update exchanges server-side;
- generates the in-app intelligence digest (default daily) when there are
  new monitoring updates.
"""
import os
import threading
import time
import uuid

import agents
import store


class Scheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._busy = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thrace-scheduler")
        self._thread.start()
        print("[thrace] scheduler started", flush=True)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        check_interval = float(os.getenv("SCHEDULER_CHECK_SECONDS", "60"))
        while not self._stop.wait(check_interval):
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                print(f"[thrace] scheduler cycle failed: {exc}", flush=True)

    def run_once(self) -> dict:
        """One scheduler cycle: due re-validations, then due digest."""
        if not self._busy.acquire(blocking=False):
            return {"skipped": "already running"}
        try:
            now = time.time()
            results = {"revalidated": [], "digest": None}

            due = store.due_watches(now)
            for item in due:
                try:
                    self._revalidate(item)
                    results["revalidated"].append(item["run_id"])
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[thrace] re-validation failed for {item['run_id']}: {exc}",
                        flush=True,
                    )
                finally:
                    store.set_watch_checked(item["run_id"])

            digest_hours = float(os.getenv("DIGEST_INTERVAL_HOURS", "24"))
            last = float(store.get_meta("last_digest") or 0)
            if now - last >= digest_hours * 3600:
                results["digest"] = self.generate_digest()

            return results
        finally:
            self._busy.release()

    def _revalidate(self, item: dict) -> None:
        run_id = item["run_id"]
        prior = store.last_report_for_run(run_id)
        content = agents.monitor_report(item["query"], prior)
        store.upsert_exchange(
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "idx": store.next_exchange_idx(run_id),
                "kind": "monitor",
                "query": f"Re-validation: {item['query']}",
                "mode": "monitor",
                "content": content,
                "status": "done",
                "created_at": time.time(),
            }
        )
        print(f"[thrace] re-validated watch {run_id}", flush=True)

    def generate_digest(self) -> dict | None:
        """Aggregate monitoring updates since the last digest into one chat."""
        last = float(store.get_meta("last_digest") or 0)
        now = time.time()
        updates = []

        for item in store.list_watch():
            for ex in store.get_exchanges(item["run_id"]):
                if ex["kind"] == "monitor" and ex["created_at"] > last:
                    updates.append({"query": item["query"], "content": ex["content"]})

        if not updates:
            store.set_meta("last_digest", str(now))
            return None

        content = agents.digest_report(updates)
        digest_id = f"digest-{int(now)}"
        store.upsert_run(
            {
                "id": digest_id,
                "query": f"Intelligence Digest — {time.strftime('%d %b %Y', time.localtime(now))}",
                "mode": "digest",
                "created_at": now,
            }
        )
        store.upsert_exchange(
            {
                "id": str(uuid.uuid4()),
                "run_id": digest_id,
                "idx": 0,
                "kind": "digest",
                "query": "Periodic digest of watched subjects",
                "mode": "digest",
                "content": content,
                "status": "done",
                "created_at": now,
            }
        )
        store.set_meta("last_digest", str(now))
        print(f"[thrace] digest generated ({len(updates)} updates)", flush=True)
        return {"id": digest_id, "updates": len(updates)}


scheduler = Scheduler()
