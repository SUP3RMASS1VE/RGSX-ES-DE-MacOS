"""In-process libtorrent torrent backend (macOS).

Same public interface as qbittorrent_backend; qbittorrent_backend re-exports these names through lazy
trampolines on Darwin. This module only references qbittorrent_backend attributes at call time, so
either module can be imported first.

Environment: RGSX_TORRENT_LISTEN
  unset      listen on 6881 (falls back to a random port if busy); the macOS firewall may ask once
  off | none listen on loopback only and disable DHT/LSD/UPnP: no incoming connections, no firewall prompt
  other      used verbatim as libtorrent listen_interfaces
"""
import hashlib
import logging
import os
import shutil
import threading
import time

import requests  # type: ignore

import qbittorrent_backend
from language import _

logger = logging.getLogger(__name__)

_lt_module = None
_lt_checked = False
_session = None
_session_lock = threading.Lock()

# libtorrent alert categories (stable values): error_notification, status_notification
_ALERT_MASK = 0x1 | 0x40


def _lt():
    """Import libtorrent once; return the module or None."""
    global _lt_module, _lt_checked
    if not _lt_checked:
        _lt_checked = True
        try:
            import libtorrent  # type: ignore
            _lt_module = libtorrent
        except Exception as exc:
            logger.info("libtorrent_backend: libtorrent indisponible (%s)", exc)
            _lt_module = None
    return _lt_module


def is_available() -> bool:
    return _lt() is not None


def _listen_setting() -> tuple[str, bool]:
    """Return (listen_interfaces, incoming_allowed)."""
    raw = os.environ.get("RGSX_TORRENT_LISTEN", "").strip()
    if raw.lower() in ("off", "none"):
        return "127.0.0.1:0", False
    if raw:
        return raw, True
    return "0.0.0.0:6881,[::]:6881", True


def _make_session(lt, listen: str, incoming: bool):
    settings = {
        "listen_interfaces": listen,
        "enable_dht": incoming,
        "enable_lsd": incoming,
        "enable_upnp": incoming,
        "enable_natpmp": incoming,
        "alert_mask": _ALERT_MASK,
        "user_agent": "RGSX",
    }
    if not incoming:
        # Still allow DHT lookups for outgoing downloads; only incoming/NAT mapping is disabled
        settings["enable_dht"] = True
    return lt.session(settings)


def _check_listen(lt, ses) -> tuple[int, int, bool]:
    """Pop alerts for ~1 s. Return (succeeded, failed, ipv6_only_failure)."""
    ok = failed = failed_v6 = 0
    deadline = time.time() + 1.0
    while time.time() < deadline:
        for alert in ses.pop_alerts():
            if isinstance(alert, getattr(lt, "listen_succeeded_alert", ())):
                ok += 1
            elif isinstance(alert, getattr(lt, "listen_failed_alert", ())):
                failed += 1
                if ":" in str(getattr(alert, "address", "")):
                    failed_v6 += 1
        if ok:
            break
        time.sleep(0.1)
    return ok, failed, bool(failed) and failed == failed_v6


def _get_session():
    global _session
    lt = _lt()
    if lt is None:
        raise qbittorrent_backend.BackendUnavailableError("libtorrent indisponible")
    with _session_lock:
        if _session is not None:
            return _session
        listen, incoming = _listen_setting()
        ses = _make_session(lt, listen, incoming)
        ok, failed, v6_only = _check_listen(lt, ses)
        if failed and not ok:
            logger.info("libtorrent_backend: ports d'écoute occupés, nouvelle session sur un port aléatoire")
            try:
                ses.abort()
            except Exception:
                pass
            ses = _make_session(lt, "0.0.0.0:0,[::]:0" if incoming else listen, incoming)
        elif v6_only:
            logger.info("libtorrent_backend: IPv6 indisponible, IPv4 uniquement")
        _session = ses
        return _session


def _status_phase(lt, state, rate) -> str:
    st = lt.torrent_status
    if state in (getattr(st, "checking_files", -1), getattr(st, "checking_resume_data", -2), getattr(st, "allocating", -3)):
        return "verifying"
    if state == getattr(st, "downloading_metadata", -4):
        return "connecting"
    if state == getattr(st, "downloading", -5):
        return "downloading" if rate > 0 else "waiting"
    return "waiting"


def _info_hash_str(handle) -> str:
    try:
        return str(handle.info_hashes().get_best())
    except Exception:
        try:
            return str(handle.info_hash())
        except Exception:
            return ""


def _remove_handle(handle, delete_files: bool) -> None:
    ses = _session
    lt = _lt()
    if ses is None or lt is None or handle is None:
        return
    try:
        if delete_files:
            ses.remove_torrent(handle, lt.session.delete_files)
        else:
            ses.remove_torrent(handle)
    except Exception as exc:
        logger.debug("libtorrent_backend: remove_torrent a échoué: %s", exc)


def _place_payload(temp_payload: str, dest_path: str) -> bool:
    """Hard-link the payload to dest_path; copy via .part + rename if linking fails. Return True if copied."""
    if os.path.exists(dest_path):
        os.remove(dest_path)
    try:
        os.link(temp_payload, dest_path)
        return False
    except OSError:
        part = dest_path + ".part"
        shutil.copy2(temp_payload, part)
        os.replace(part, dest_path)
        return True


def _seed_status_worker(task_id: str) -> None:
    import network as _network
    while True:
        entry = qbittorrent_backend._active_qbt_seeds.get(task_id)
        if entry is None or entry.get("backend") != "libtorrent":
            return
        try:
            st = entry["handle"].status()
            ul = float(getattr(st, "upload_payload_rate", 0) or 0) / (1024 * 1024)
            peers = int(getattr(st, "num_peers", 0) or 0) if ul > 0 else 0
            _network._update_seeding_status(entry["original_history_url"], peers=peers, ul_speed=ul)
        except Exception:
            pass
        time.sleep(3.0)


def download_torrent_via_qbittorrent(
    torrent_meta: dict,
    dest_dir: str,
    dest_path: str,
    task_id: str,
    cancel_ev,
    progress_queue,
    original_history_url: str = "",
    pause_ev=None,
) -> tuple[bool, str]:
    lt = _lt()
    if lt is None:
        raise qbittorrent_backend.BackendUnavailableError("libtorrent indisponible")
    source_url = str(torrent_meta.get("source_url") or "")
    if not source_url:
        raise qbittorrent_backend.BackendUnavailableError("URL du torrent manquante")
    relative_path = str(torrent_meta.get("relative_path") or "").strip() or os.path.basename(dest_path)
    total_size = int(torrent_meta.get("size_bytes") or 0)

    resp = requests.get(source_url, timeout=30, headers=qbittorrent_backend._build_torrent_headers())
    resp.raise_for_status()
    ti = lt.torrent_info(lt.bdecode(resp.content))
    fs = ti.files()
    entries = [{"index": i, "name": fs.file_path(i)} for i in range(fs.num_files())]
    target = qbittorrent_backend._resolve_target_file_index(entries, relative_path)
    if target is None:
        raise RuntimeError(f"Fichier {relative_path} absent du torrent")
    target_size = int(fs.file_size(target))
    reported_total = target_size or total_size

    ses = _get_session()
    source_key = hashlib.sha1(source_url.encode("utf-8", errors="ignore")).hexdigest()[:12]
    temp_dir = os.path.join(dest_dir, ".rgsx_torrent", source_key)
    os.makedirs(temp_dir, exist_ok=True)

    params = lt.add_torrent_params()
    params.ti = ti
    params.save_path = temp_dir
    try:
        params.storage_mode = lt.storage_mode_t.storage_mode_sparse
    except Exception:
        pass
    priorities = [0] * fs.num_files()
    priorities[target] = 4
    params.file_priorities = priorities
    handle = ses.add_torrent(params)
    registered = False
    completed = False
    try:
        qbittorrent_backend._register_active_download(task_id, _info_hash_str(handle), original_history_url, target)
        registered = True
        if reported_total > 0:
            progress_queue.put((task_id, 0, reported_total, 0.0, 0, 0, "connecting"))
        while True:
            if cancel_ev is not None and cancel_ev.is_set():
                if registered:
                    qbittorrent_backend._pop_active_reference(task_id=task_id)
                    registered = False
                _remove_handle(handle, True)
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise RuntimeError(_("download_canceled") if _ else "Download canceled")
            if pause_ev is not None and pause_ev.is_set():
                handle.pause()
                done = int(handle.file_progress()[target])
                if reported_total > 0:
                    progress_queue.put((task_id, min(done, reported_total), reported_total, 0.0, 0, 0, "paused"))
                while pause_ev.is_set():
                    if cancel_ev is not None and cancel_ev.is_set():
                        break
                    time.sleep(0.3)
                handle.resume()
                continue
            st = handle.status()
            if st.errc.value():
                raise RuntimeError(f"libtorrent: {st.errc.message()}")
            done = int(handle.file_progress()[target])
            rate = float(st.download_payload_rate or 0)
            speed = rate / (1024 * 1024)
            peers = int(st.num_peers or 0)
            phase = _status_phase(lt, st.state, rate)
            if reported_total > 0:
                progress_queue.put((task_id, min(done, reported_total), reported_total, speed, peers if rate > 0 else 0, peers, phase))
            if target_size > 0 and done >= target_size:
                temp_payload = os.path.join(temp_dir, fs.file_path(target))
                if not os.path.isfile(temp_payload):
                    raise FileNotFoundError(f"Fichier téléchargé introuvable pour {relative_path}")
                completed = True
                copied = _place_payload(temp_payload, dest_path)
                qbittorrent_backend._promote_active_download_to_seed(task_id, {
                    "backend": "libtorrent", "handle": handle, "hash": _info_hash_str(handle), "tag": f"rgsx_{task_id}",
                    "dest_path": dest_path, "temp_dir": temp_dir, "payload_copied": copied,
                    "original_history_url": original_history_url,
                })
                registered = False
                if original_history_url:
                    threading.Thread(target=_seed_status_worker, args=(task_id,), name=f"lt-seed-{task_id}", daemon=True).start()
                final_size = os.path.getsize(dest_path)
                progress_queue.put((task_id, final_size, max(reported_total, final_size), 0.0))
                return True, _("network_download_ok").format(os.path.basename(dest_path))
            time.sleep(1.0)
    except Exception:
        if registered:
            qbittorrent_backend._pop_active_reference(task_id=task_id)
        if not completed:
            _remove_handle(handle, False)
            # keep partial data for resume unless the user canceled (already removed above)
        raise


def has_active_seed(task_id=None, original_history_url=None) -> bool:
    seeds = qbittorrent_backend._active_qbt_seeds
    if task_id and task_id in seeds:
        return True
    if original_history_url:
        return any(info.get("original_history_url") == original_history_url for info in seeds.values())
    return False


def _release_seed(entry, update_history: bool, original_history_url=None) -> None:
    _remove_handle(entry.get("handle"), False)
    temp_dir = entry.get("temp_dir")
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)
    url = original_history_url or entry.get("original_history_url")
    if update_history and url:
        try:
            import network as _network
            _network._stop_seeding_status(url)
        except Exception as exc:
            logger.debug("libtorrent_backend: reset historique échoué: %s", exc)


def stop_seed(task_id=None, original_history_url=None) -> bool:
    if not has_active_seed(task_id, original_history_url):
        return False
    tid, entry = qbittorrent_backend._pop_active_reference(task_id=task_id, original_history_url=original_history_url)
    if not tid or entry is None:
        return False
    _release_seed(entry, True, original_history_url)
    logger.info("libtorrent_backend: seed arrêté pour task_id=%s", tid)
    return True


def prewarm_startup_async() -> None:
    return  # the session is created lazily on the first torrent


def is_process_running() -> bool:
    return _session is not None


def shutdown() -> None:
    """Stop every seed started by this backend and drop the session. Never raises, bounded to ~5 s."""
    global _session
    deadline = time.time() + 5.0
    try:
        for tid, entry in list(qbittorrent_backend._active_qbt_seeds.items()):
            if entry.get("backend") != "libtorrent" or time.time() > deadline:
                continue
            try:
                qbittorrent_backend._active_qbt_seeds.pop(tid, None)
                _release_seed(entry, True)
            except Exception as exc:
                logger.debug("libtorrent_backend: nettoyage seed %s échoué: %s", tid, exc)
        with _session_lock:
            ses, _session = _session, None
        if ses is not None:
            try:
                ses.pause()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("libtorrent_backend: shutdown: %s", exc)
