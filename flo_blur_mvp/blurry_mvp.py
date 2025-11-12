#!/usr/bin/env python3
import os
import csv
import time
import math
import signal
import argparse
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, Optional, List, Tuple

from simulator import Simulator

DEFAULT_THRESHOLD_SEC = 60
DEFAULT_SUPPRESS_SEC = 5 * 60
DEFAULT_AGG_WINDOW_SEC = 45
DEFAULT_AGG_MIN = 2
DEFAULT_AGG_SUPPRESS_SEC = 5 * 60
DEFAULT_SITE_ID = "Default"


@dataclass
class Event:
    ts: datetime
    camera_id: str
    is_blurry: bool


@dataclass
class AlertCandidate:
    camera_id: str
    line_number: Optional[int]
    blur_since: datetime
    ready_at: datetime
    site_id: str


@dataclass
class AlertAction:
    kind: str  # "single" or "aggregate"
    candidates: List[AlertCandidate]
    site_id: str
    washdown_hint: bool = False


@dataclass
class CameraAlertState:
    is_blurry: bool = False
    blur_start: Optional[datetime] = None
    last_alert_until: Optional[datetime] = None
    alert_open: bool = False
    pending_candidate: bool = False


class CsvStore:
    def __init__(self, path: str):
        self.path = path
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                csv.writer(f).writerow(["ts_iso", "camera_id", "is_blurry"])

    def append(self, event: Event) -> None:
        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([event.ts.isoformat(), event.camera_id, int(event.is_blurry)])


class BlurEpisodeStore:
    def __init__(self, path: str):
        self.path = path
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                csv.writer(f).writerow(["camera_id", "blur_start_iso", "cleared_iso"])

    def append(self, camera_id: str, start: datetime, end: datetime) -> None:
        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([camera_id, start.isoformat(), end.isoformat()])


class GuiNotifier:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def alert_single(
        self,
        camera_label: str,
        line_number: Optional[int],
        blur_since: Optional[datetime],
    ) -> str:
        local_since = (blur_since or datetime.now(timezone.utc)).astimezone()
        time_label = local_since.strftime("%I:%M %p")
        line_display = str(line_number) if line_number and line_number > 0 else "?"
        message = (
            "FloVision Alert:\n"
            f" Camera #{camera_label} (Line {line_display}) blurry since {time_label}.\n"
            "Action: Please wipe lens."
        )
        return self._show_dialog(message, clean_label="Clean Lens")

    def alert_aggregate(
        self,
        site_id: str,
        candidates: List[AlertCandidate],
        washdown_hint: bool = False,
    ) -> str:
        lines = []
        for cand in candidates:
            local_since = cand.blur_since.astimezone()
            time_label = local_since.strftime("%I:%M %p")
            line_label = cand.camera_id.split("-")[-1] if "-" in cand.camera_id else cand.camera_id
            line_display = str(cand.line_number) if cand.line_number and cand.line_number > 0 else "?"
            lines.append(
                f" • Camera #{line_label} (Line {line_display}) blurry since {time_label}."
            )
        message = (
            f"FloVision Alert (Site {site_id}):\n"
            f" {len(candidates)} cameras blurry.\n"
            f"{os.linesep.join(lines)}\n"
            "Action: Please wipe lenses."
        )
        if washdown_hint:
            message += "\n(Likely washdown window.)"
        return self._show_dialog(message, clean_label="Clean Lenses")

    def _show_dialog(self, message: str, clean_label: str) -> str:
        result = {"action": "ignore"}

        top = tk.Toplevel(self.root)
        top.title("FloVision Alert")
        top.resizable(False, False)
        top.attributes("-topmost", True)

        def on_clean():
            result["action"] = "clean"
            top.destroy()

        def on_ignore():
            result["action"] = "ignore"
            top.destroy()

        top.protocol("WM_DELETE_WINDOW", on_ignore)

        label = tk.Label(top, text=message, justify="left", padx=20, pady=15)
        label.pack()

        btn_frame = tk.Frame(top)
        btn_frame.pack(padx=20, pady=(0, 15))

        clean_btn = tk.Button(btn_frame, text=clean_label, width=14, command=on_clean)
        clean_btn.pack(side="left", padx=(0, 10))

        ignore_btn = tk.Button(btn_frame, text="Ignore", width=12, command=on_ignore)
        ignore_btn.pack(side="left")

        clean_btn.focus_set()
        top.lift()
        top.grab_set()
        self.root.wait_window(top)
        return result["action"]


class SiteAlertAggregator:
    def __init__(
        self,
        window_sec: int,
        min_count: int,
        suppress_sec: int,
        washdown_schedule: Optional[List[Tuple[dtime, dtime]]] = None,
    ):
        self.window = timedelta(seconds=max(1, window_sec))
        self.min_count = max(1, min_count)
        self.suppress = timedelta(seconds=max(1, suppress_sec))
        self.washdown_schedule = washdown_schedule or []
        self._pending_by_camera: Dict[str, AlertCandidate] = {}
        self._pending_by_site: Dict[str, Dict[str, AlertCandidate]] = {}
        self._site_cooldown: Dict[str, datetime] = {}

    def enqueue(self, candidate: AlertCandidate) -> None:
        self._pending_by_camera[candidate.camera_id] = candidate
        site_pool = self._pending_by_site.setdefault(candidate.site_id, {})
        site_pool[candidate.camera_id] = candidate

    def cancel(self, camera_id: str) -> None:
        candidate = self._pending_by_camera.pop(camera_id, None)
        if not candidate:
            return
        site_pool = self._pending_by_site.get(candidate.site_id)
        if site_pool is not None:
            site_pool.pop(camera_id, None)
            if not site_pool:
                self._pending_by_site.pop(candidate.site_id, None)

    def process(self, now: datetime) -> List[AlertAction]:
        dispatches: List[AlertAction] = []

        for site_id, site_pool in list(self._pending_by_site.items()):
            active = [cand for cand in site_pool.values() if now - cand.ready_at <= self.window]
            if len(active) >= self.min_count:
                cooldown = self._site_cooldown.get(site_id)
                if not cooldown or now >= cooldown:
                    dispatches.append(
                        AlertAction(
                            kind="aggregate",
                            candidates=active,
                            site_id=site_id,
                            washdown_hint=self._within_washdown(active),
                        )
                    )
                    for cand in active:
                        self._pending_by_camera.pop(cand.camera_id, None)
                        site_pool.pop(cand.camera_id, None)
                    self._site_cooldown[site_id] = now + self.suppress
            if not site_pool:
                self._pending_by_site.pop(site_id, None)

        for camera_id, candidate in list(self._pending_by_camera.items()):
            if now - candidate.ready_at >= self.window:
                dispatches.append(
                    AlertAction(kind="single", candidates=[candidate], site_id=candidate.site_id)
                )
                self._pending_by_camera.pop(camera_id, None)
                site_pool = self._pending_by_site.get(candidate.site_id)
                if site_pool is not None:
                    site_pool.pop(camera_id, None)
                    if not site_pool:
                        self._pending_by_site.pop(candidate.site_id, None)

        return dispatches

    def _within_washdown(self, candidates: List[AlertCandidate]) -> bool:
        if not self.washdown_schedule:
            return False
        for cand in candidates:
            local_time = cand.ready_at.astimezone().time()
            for start, end in self.washdown_schedule:
                if start <= end:
                    if start <= local_time <= end:
                        return True
                else:
                    if local_time >= start or local_time <= end:
                        return True
        return False


class AlertEngine:
    def __init__(
        self,
        notifier: GuiNotifier,
        line_lookup: Dict[str, int],
        site_lookup: Dict[str, str],
        simulator: Optional[Simulator],
        episode_store: BlurEpisodeStore,
        threshold_sec: int,
        suppress_sec: int,
        aggregate_window_sec: int,
        aggregate_min: int,
        aggregate_suppress_sec: int,
        washdown_schedule: Optional[List[Tuple[dtime, dtime]]],
    ):
        self.notifier = notifier
        self.line_lookup = line_lookup
        self.site_lookup = site_lookup
        self.simulator = simulator
        self.episode_store = episode_store
        self.threshold = timedelta(seconds=max(0, threshold_sec))
        self.suppress = timedelta(seconds=max(1, suppress_sec))
        self.state: Dict[str, CameraAlertState] = {}
        self.aggregator = SiteAlertAggregator(
            window_sec=aggregate_window_sec,
            min_count=aggregate_min,
            suppress_sec=aggregate_suppress_sec,
            washdown_schedule=washdown_schedule,
        )

    def process(self, now: datetime, camera_id: str, is_blurry: bool) -> None:
        st = self.state.setdefault(camera_id, CameraAlertState())
        if is_blurry:
            if not st.is_blurry:
                st.is_blurry = True
                st.blur_start = now
            allow_realert = True
            if st.alert_open and st.last_alert_until and now < st.last_alert_until:
                allow_realert = False
            if st.blur_start and allow_realert and not st.pending_candidate:
                if now - st.blur_start >= self.threshold:
                    candidate = AlertCandidate(
                        camera_id=camera_id,
                        line_number=self.line_lookup.get(camera_id),
                        blur_since=st.blur_start,
                        ready_at=now,
                        site_id=self.site_lookup.get(camera_id, DEFAULT_SITE_ID),
                    )
                    self.aggregator.enqueue(candidate)
                    st.pending_candidate = True
        else:
            if st.pending_candidate:
                self.aggregator.cancel(camera_id)
                st.pending_candidate = False
            if st.is_blurry:
                if st.alert_open:
                    self._resolve(now, camera_id, st)
                st.is_blurry = False
                st.blur_start = None
                st.alert_open = False
                st.last_alert_until = None

    def flush(self, now: datetime) -> None:
        for action in self.aggregator.process(now):
            if action.kind == "aggregate":
                self._handle_aggregate(action, now)
            else:
                self._handle_single(action, now)

    def _handle_single(self, action: AlertAction, now: datetime) -> None:
        candidate = action.candidates[0]
        st = self.state.get(candidate.camera_id)
        if not st:
            return
        mins = max(1, math.floor((now - candidate.blur_since).total_seconds() / 60))
        print(
            f"[ALERT] Camera {candidate.camera_id}: blurry for {mins} min. Action: wipe lens. ({now.isoformat()})"
        )
        camera_label = candidate.camera_id.split("-")[-1] if "-" in candidate.camera_id else candidate.camera_id
        decision = self.notifier.alert_single(
            camera_label=camera_label,
            line_number=candidate.line_number,
            blur_since=candidate.blur_since,
        )
        self._after_alert(now, [candidate.camera_id], decision)

    def _handle_aggregate(self, action: AlertAction, now: datetime) -> None:
        camera_ids = [cand.camera_id for cand in action.candidates]
        lens_list = ", ".join(camera_ids)
        print(
            f"[ALERT][AGG] Site {action.site_id}: {len(action.candidates)} cameras blurry ({lens_list}). ({now.isoformat()})"
        )
        decision = self.notifier.alert_aggregate(
            site_id=action.site_id,
            candidates=action.candidates,
            washdown_hint=action.washdown_hint,
        )
        self._after_alert(now, camera_ids, decision)

    def _after_alert(self, now: datetime, camera_ids: List[str], decision: str) -> None:
        for camera_id in camera_ids:
            st = self.state.get(camera_id)
            if not st:
                continue
            st.pending_candidate = False
            if decision == "clean":
                if self.simulator:
                    self.simulator.set_blurry(camera_id, False)
                if st.blur_start:
                    self.episode_store.append(camera_id, st.blur_start, now)
                    self._resolve(now, camera_id, st)
                st.is_blurry = False
                st.blur_start = None
                st.alert_open = False
                st.last_alert_until = None
            else:
                st.alert_open = True
                st.last_alert_until = now + self.suppress

    def _resolve(self, now: datetime, camera_id: str, st: CameraAlertState) -> None:
        blur_since = st.blur_start or now
        resolved_minutes = max(0, int((now - blur_since).total_seconds() // 60))
        print(f"[RESOLVED] Camera {camera_id}: blur cleared after {resolved_minutes} min. ({now.isoformat()})")


def parse_washdown_schedule(spec: Optional[str]) -> List[Tuple[dtime, dtime]]:
    if not spec:
        return []
    windows: List[Tuple[dtime, dtime]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            start_str, end_str = chunk.split("-")
            start = datetime.strptime(start_str.strip(), "%H:%M").time()
            end = datetime.strptime(end_str.strip(), "%H:%M").time()
            windows.append((start, end))
        except ValueError:
            print(f"[WARN] Could not parse washdown window '{chunk}'. Expected HH:MM-HH:MM.")
    return windows


def run(
    cameras: int,
    interval: int,
    csv_path: str,
    episodes_csv: str,
    alert_threshold: int,
    suppress_seconds: int,
    site_id: str,
    aggregate_window: int,
    aggregate_min: int,
    aggregate_suppress: int,
    washdown_schedule: Optional[List[Tuple[dtime, dtime]]],
    max_ticks: Optional[int] = None,
    simulator: Optional[Simulator] = None,
    notifier: Optional[GuiNotifier] = None,
):
    camera_ids = [f"CAM-{i+1:02d}" for i in range(cameras)]
    store = CsvStore(csv_path)
    episode_store = BlurEpisodeStore(episodes_csv)
    sim = simulator if simulator is not None else Simulator(camera_ids)
    notifier_obj = notifier if notifier is not None else GuiNotifier()
    line_lookup = {cid: idx + 1 for idx, cid in enumerate(camera_ids)}
    site_lookup = {cid: site_id for cid in camera_ids}
    engine = AlertEngine(
        notifier=notifier_obj,
        line_lookup=line_lookup,
        site_lookup=site_lookup,
        simulator=sim,
        episode_store=episode_store,
        threshold_sec=alert_threshold,
        suppress_sec=suppress_seconds,
        aggregate_window_sec=aggregate_window,
        aggregate_min=aggregate_min,
        aggregate_suppress_sec=aggregate_suppress,
        washdown_schedule=washdown_schedule,
    )
    print(
        f"Starting simulation for cameras={camera_ids}, interval={interval}s, csv={csv_path}, "
        f"threshold={alert_threshold}s, aggregate_window={aggregate_window}s"
    )
    stop = False
    ticks = 0

    def handle_sigint(signum, frame):
        nonlocal stop
        stop = True
        print("\nStopping...")

    signal.signal(signal.SIGINT, handle_sigint)

    while not stop:
        now = datetime.now(timezone.utc)
        states = sim.tick()
        for cid, is_blur in states.items():
            store.append(Event(ts=now, camera_id=cid, is_blurry=is_blur))
            engine.process(now=now, camera_id=cid, is_blurry=is_blur)
        engine.flush(now)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        time.sleep(max(0, interval))


def main():
    parser = argparse.ArgumentParser(description="Blurry camera MVP simulator + alert engine")
    parser.add_argument("--cameras", type=int, default=3)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--csv", type=str, default="events.csv")
    parser.add_argument(
        "--episodes-csv",
        type=str,
        default="blur_episodes.csv",
        help="File to log blur start/end times once a lens is cleaned",
    )
    parser.add_argument(
        "--alert-threshold",
        type=int,
        default=DEFAULT_THRESHOLD_SEC,
        help="Seconds a camera must stay blurry before the alert dialog appears",
    )
    parser.add_argument(
        "--suppress",
        type=int,
        default=DEFAULT_SUPPRESS_SEC,
        help="Seconds to suppress repeat alerts per camera after one is shown",
    )
    parser.add_argument("--site", type=str, default=DEFAULT_SITE_ID, help="Logical site identifier for aggregation")
    parser.add_argument(
        "--aggregate-window",
        type=int,
        default=DEFAULT_AGG_WINDOW_SEC,
        help="Seconds to wait for multiple cameras before aggregating alerts",
    )
    parser.add_argument(
        "--aggregate-min",
        type=int,
        default=DEFAULT_AGG_MIN,
        help="Minimum number of cameras to trigger an aggregate alert",
    )
    parser.add_argument(
        "--aggregate-suppress",
        type=int,
        default=DEFAULT_AGG_SUPPRESS_SEC,
        help="Seconds to suppress repeat aggregate alerts for the same site",
    )
    parser.add_argument(
        "--washdown",
        type=str,
        default=None,
        help="Comma separated HH:MM-HH:MM windows (local time) considered washdown periods",
    )
    args = parser.parse_args()
    washdown_schedule = parse_washdown_schedule(args.washdown)
    run(
        cameras=args.cameras,
        interval=args.interval,
        csv_path=args.csv,
        episodes_csv=args.episodes_csv,
        alert_threshold=args.alert_threshold,
        suppress_seconds=args.suppress,
        site_id=args.site,
        aggregate_window=args.aggregate_window,
        aggregate_min=args.aggregate_min,
        aggregate_suppress=args.aggregate_suppress,
        washdown_schedule=washdown_schedule,
    )


if __name__ == "__main__":
    main()
