import os
import subprocess
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .http_client import request_json
from .models import OnlineSession
from .session_registry import SessionRegistry


logger = logging.getLogger(__name__)


class OpenCodeClient:
    def __init__(self, settings: Settings):
        self._transport = settings.opencode_transport
        self._opencode_bin = settings.opencode_bin
        self._db_path = settings.opencode_db_path
        self._session_registry = SessionRegistry(
            settings.opencode_db_path,
            title_refresh_s=settings.opencode_session_title_refresh_s,
            title_max_len=settings.opencode_session_title_max_len,
            title_agent_enabled=bool(settings.opencode_title_agent_enabled),
            title_agent_session_id=settings.opencode_title_agent_session_id,
            title_agent_timeout_s=settings.opencode_title_agent_timeout_s,
            opencode_bin=settings.opencode_bin,
            hidden_session_ids=[
                settings.opencode_title_agent_session_id,
                settings.opencode_intent_agent_session_id,
            ],
        )
        self._base_url = settings.opencode_base_url.rstrip("/")
        self._list_path = settings.opencode_list_sessions_path
        self._list_path_alt = settings.opencode_list_sessions_path_alt
        self._send_path = settings.opencode_send_message_path
        self._send_path_alt = settings.opencode_send_message_path_alt
        self._timeout = settings.opencode_request_timeout_s
        self._api_key = settings.opencode_api_key

    def _headers(self) -> Dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def list_online_sessions(self) -> List[OnlineSession]:
        if self._transport == "cli":
            return self._session_registry.refresh()
        payload = await self._fetch_sessions_payload()

        raw = payload.get("sessions", payload)
        sessions: List[OnlineSession] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                session_id = str(item.get("session_id") or item.get("sessionId") or "")
                if not session_id:
                    continue
                display_name = str(item.get("display_name") or item.get("title") or session_id)
                status = str(item.get("status") or "online")
                sessions.append(
                    OnlineSession(session_id=session_id, display_name=display_name, status=status)
                )
        return sessions

    async def list_all_sessions(self) -> List[OnlineSession]:
        if self._transport != "cli":
            return await self.list_online_sessions()

        online = self._session_registry.refresh()
        online_map = {item.session_id: item for item in online}

        output: List[OnlineSession] = []
        for item in self._list_db_sessions():
            online_item = online_map.pop(item.session_id, None)
            if online_item is not None:
                output.append(online_item)
            else:
                output.append(item)

        if online_map:
            output.extend(online_map.values())

        output.sort(key=lambda item: (0 if item.status == "online" else 1, -item.last_seen_ts, item.session_id))
        return output

    async def refresh_session_titles_now(self) -> None:
        if self._transport != "cli":
            return
        self._session_registry.refresh(force_title_refresh=True)

    async def _fetch_sessions_payload(self) -> Any:
        urls = [f"{self._base_url}{self._list_path}"]
        if self._list_path_alt:
            urls.append(f"{self._base_url}{self._list_path_alt}")

        last_error: Optional[Exception] = None
        for url in urls:
            try:
                return await request_json("GET", url, headers=self._headers(), timeout=self._timeout)
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return {}

    async def send_to_session(self, session_id: str, text: str) -> str:
        if self._transport == "cli":
            return self._send_to_session_by_cli(session_id, text)

        url = f"{self._base_url}{self._send_path}"
        body = {
            "session_id": session_id,
            "sessionId": session_id,
            "message": text,
            "content": text,
        }
        payload: Any = await self._send_with_fallback(url, body)

        if isinstance(payload, dict):
            candidates = [
                payload.get("reply"),
                payload.get("message"),
                payload.get("content"),
                payload.get("text"),
            ]
            for value in candidates:
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str) and payload.strip():
            return payload
        return "会话已收到消息，但未返回可展示文本。"

    def create_session(self, directory: Optional[str] = None) -> Tuple[Optional[str], str]:
        if self._transport != "cli":
            return None, "当前传输模式不支持创建本地 session。"

        binary = self._opencode_bin
        if not os.path.exists(binary):
            binary = "opencode"

        target_dir = (directory or "").strip()
        if target_dir:
            target_dir = os.path.abspath(os.path.expanduser(target_dir))
            if not os.path.isdir(target_dir):
                return None, f"目录不存在或不可访问: {target_dir}"
        else:
            target_dir = os.getcwd()

        before_ids = self._list_session_ids_by_directory(target_dir)
        cmd = [
            binary,
            "run",
            "--format",
            "default",
            "--dir",
            target_dir,
            "创建一个会话锚点，直接回复 ok",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(10, int(self._timeout)),
                cwd=target_dir,
            )
        except subprocess.TimeoutExpired:
            return None, "创建 session 超时，请稍后重试。"
        except OSError as exc:
            return None, f"创建 session 失败: {exc}"

        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            if err:
                return None, f"创建 session 失败: {err}"
            return None, "创建 session 失败：opencode 未返回成功状态。"

        session_id = self._wait_for_new_session_id(target_dir, before_ids, wait_s=3.0)
        if not session_id:
            return None, "创建 session 成功，但暂未识别到新会话 ID，请稍后 /session_list 查看。"

        return session_id, f"已创建 session: {session_id}"

    def list_cached_sessions(self, include_offline: bool) -> List[OnlineSession]:
        if self._transport != "cli":
            return []
        return self._session_registry.list_sessions(include_offline=include_offline)

    def _send_to_session_by_cli(self, session_id: str, text: str) -> str:
        binary = self._opencode_bin
        if not os.path.exists(binary):
            binary = "opencode"
        target = self._find_target_session(session_id)
        if target is None:
            target = self._find_session_from_db(session_id)
        if target is None:
            return f"目标 session 不存在或不可解析: {session_id}。请先 /session_list 后重新绑定。"
        cmd = [binary, "run", "--session", session_id, "--format", "default"]
        target_dir = ""
        if target and target.directory:
            target_dir = target.directory
        if target_dir and os.path.isdir(target_dir):
            cmd.extend(["--dir", target_dir])
        elif target_dir:
            logger.warning("opencode cli ignore invalid session directory session=%s dir=%s", session_id, target_dir)
        cmd.append(text)
        cwd, session_env = self._resolve_cli_context_from_target(target)
        if not cwd and not (target_dir and os.path.isdir(target_dir)):
            return (
                f"目标 session 工作目录不可用: {session_id}。"
                "已阻止在默认目录执行，请在目标终端进入有效项目目录后重新绑定。"
            )
        if cwd:
            logger.info("opencode cli context resolved session=%s cwd=%s", session_id, cwd)
        else:
            logger.warning("opencode cli context fallback to process default session=%s", session_id)
        env = None
        if session_env:
            env = os.environ.copy()
            env.update(session_env)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(1, int(self._timeout)),
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return "发送到会话超时，请稍后重试；如持续超时请检查目标 session 是否仍在线。"
        except OSError as exc:
            return f"调用 opencode 失败: {exc}"
        err = (proc.stderr or "").strip()
        if self._should_retry_without_dir(proc.returncode, err, cmd):
            retry_cmd = self._drop_dir_flag(cmd)
            try:
                proc = subprocess.run(
                    retry_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=max(1, int(self._timeout)),
                    cwd=cwd,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return "发送到会话超时，请稍后重试；如持续超时请检查目标 session 是否仍在线。"
            except OSError as exc:
                return f"调用 opencode 失败: {exc}"
        output = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0 and output:
            return output
        if err:
            return err
        return "会话调用完成，但未返回文本输出。"

    @staticmethod
    def _drop_dir_flag(cmd: List[str]) -> List[str]:
        output: List[str] = []
        skip_next = False
        for item in cmd:
            if skip_next:
                skip_next = False
                continue
            if item == "--dir":
                skip_next = True
                continue
            output.append(item)
        return output

    @staticmethod
    def _should_retry_without_dir(returncode: int, err: str, cmd: List[str]) -> bool:
        if returncode == 0:
            return False
        if "--dir" not in cmd:
            return False
        lowered = err.lower()
        return "failed to change directory" in lowered

    def _resolve_cli_context(self, session_id: str) -> "Tuple[Optional[str], Optional[Dict[str, str]]]":
        target = self._find_target_session(session_id)
        return self._resolve_cli_context_from_target(target)

    def _find_target_session(self, session_id: str) -> Optional[OnlineSession]:
        sessions = self._session_registry.refresh()
        return next(
            (
                item
                for item in sessions
                if item.session_id == session_id and item.status == "online" and item.pid
            ),
            None,
        )

    def _resolve_cli_context_from_target(
        self, target: Optional[OnlineSession]
    ) -> "Tuple[Optional[str], Optional[Dict[str, str]]]":
        if target is None:
            return None, None

        cwd: Optional[str] = None
        env: Optional[Dict[str, str]] = None
        if target.directory and os.path.isdir(target.directory):
            cwd = target.directory
        if target.pid is None:
            return cwd, None
        proc_cwd = self._read_proc_cwd(target.pid)
        if proc_cwd and not cwd:
            cwd = proc_cwd
        proc_env = self._read_proc_env(target.pid)
        if proc_env:
            env = proc_env
        return cwd, env

    async def resolve_session(self, session_id: str) -> Optional[OnlineSession]:
        if self._transport != "cli":
            sessions = await self.list_online_sessions()
            return next((item for item in sessions if item.session_id == session_id), None)
        target = self._find_target_session(session_id)
        if target is not None:
            return target
        return self._find_session_from_db(session_id)

    def _find_session_from_db(self, session_id: str) -> Optional[OnlineSession]:
        db_path = os.path.expanduser(self._db_path)
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id, title, directory FROM session WHERE id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()
        if not row:
            return None
        sid = str(row[0])
        title = str(row[1]) if len(row) > 1 and row[1] else sid
        directory = str(row[2]) if len(row) > 2 and row[2] else ""
        return OnlineSession(
            session_id=sid,
            display_name=title,
            status="offline",
            pid=None,
            tty="",
            last_seen_ts=int(time.time()),
            directory=directory,
            workdir_available=bool(directory and os.path.isdir(directory)),
        )

    def _list_db_sessions(self) -> List[OnlineSession]:
        db_path = os.path.expanduser(self._db_path)
        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, title, directory, COALESCE(time_updated, 0) AS time_updated
                FROM session
                WHERE time_archived IS NULL OR time_archived = 0
                ORDER BY time_updated DESC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            try:
                rows = conn.execute(
                    """
                    SELECT id, title, directory, COALESCE(time_updated, 0) AS time_updated
                    FROM session
                    ORDER BY time_updated DESC
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        finally:
            conn.close()

        output: List[OnlineSession] = []
        for row in rows:
            sid = str(row["id"]) if row["id"] else ""
            if not sid:
                continue
            title = str(row["title"]) if row["title"] else sid
            directory = str(row["directory"]) if row["directory"] else ""
            updated = int(row["time_updated"]) if row["time_updated"] else 0
            output.append(
                OnlineSession(
                    session_id=sid,
                    display_name=title,
                    status="offline",
                    pid=None,
                    tty="",
                    last_seen_ts=updated,
                    directory=directory,
                    workdir_available=bool(directory and os.path.isdir(directory)),
                )
            )
        return output

    def _list_session_ids_by_directory(self, directory: str) -> "set[str]":
        db_path = os.path.expanduser(self._db_path)
        if not os.path.exists(db_path):
            return set()
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id FROM session WHERE directory = ?",
                (directory,),
            ).fetchall()
        except sqlite3.OperationalError:
            return set()
        finally:
            conn.close()
        return {str(row[0]) for row in rows if row and row[0]}

    def _wait_for_new_session_id(self, directory: str, before_ids: "set[str]", wait_s: float) -> Optional[str]:
        deadline = time.time() + max(0.5, wait_s)
        while time.time() < deadline:
            latest = self._latest_session_id_by_directory(directory)
            if latest and latest not in before_ids:
                return latest
            time.sleep(0.2)
        return None

    def _latest_session_id_by_directory(self, directory: str) -> Optional[str]:
        db_path = os.path.expanduser(self._db_path)
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM session WHERE directory = ? ORDER BY time_updated DESC LIMIT 1",
                (directory,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()
        if not row or not row[0]:
            return None
        return str(row[0])

    @staticmethod
    def _read_proc_cwd(pid: int) -> Optional[str]:
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return None
        if not cwd or not os.path.isdir(cwd):
            return None
        return cwd

    @staticmethod
    def _read_proc_env(pid: int) -> Dict[str, str]:
        try:
            with open(f"/proc/{pid}/environ", "rb") as handle:
                raw = handle.read()
        except OSError:
            return {}

        output: Dict[str, str] = {}
        for chunk in raw.split(b"\x00"):
            if not chunk or b"=" not in chunk:
                continue
            key_bytes, value_bytes = chunk.split(b"=", 1)
            key = key_bytes.decode("utf-8", errors="ignore")
            if not key:
                continue
            output[key] = value_bytes.decode("utf-8", errors="ignore")
        return output

    async def _send_with_fallback(self, url: str, body: Dict[str, Any]) -> Any:
        urls = [url]
        if self._send_path_alt:
            urls.append(f"{self._base_url}{self._send_path_alt}")
        last_error: Optional[Exception] = None
        for target in urls:
            try:
                return await request_json(
                    "POST",
                    target,
                    headers=self._headers(),
                    body=body,
                    timeout=self._timeout,
                )
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return {}
