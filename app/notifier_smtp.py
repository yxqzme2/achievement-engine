import os
import smtplib
import ssl
import socket
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Optional, Dict

from .models import Achievement


# -----------------------------------------
# Section 1: Email Notifier (SMTP)
# -----------------------------------------
class EmailNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        to_override: str = "",
        project_root: Optional[str] = None,
        icons_dir: Optional[str] = None,
    ):
        self.host = host
        self.port = int(port) if port else 0
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_override = (to_override or "").strip()

        # Keep for backward-compat, but icons should NOT live here long-term
        self.project_root = project_root or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        # ✅ FIX: Default icons to /data/icons (your mounted Unraid appdata)
        # Can be overridden via env EMAIL_ICONS_DIR if you ever want to move it.
        env_icons_dir = (os.getenv("EMAIL_ICONS_DIR") or "").strip()
        self.icons_dir = Path(env_icons_dir or icons_dir or "/data/icons")

    # -----------------------------------------
    # Section 2: Helpers
    # -----------------------------------------
    def enabled(self) -> bool:
        return bool(self.host and self.port and self.from_addr)

    def _resolve_icon_fs_path(self, icon_path: str) -> str:
        """
        Resolve icon references to a real filesystem path.

        Supported inputs:
        - "icons/12.png"   (from old configs)
        - "12.png"         (preferred)
        - "author_collector.png"
        - "icons\\12.png"  (windows paths)

        Search order:
        1) /data/icons/<filename>   (preferred, mounted)
        2) /data/icons/<original relative path> if it includes folders
        3) <project_root>/<original relative path> (legacy fallback)
        """
        raw = (icon_path or "").strip()
        if not raw:
            return ""

        norm = raw.replace("\\", "/").lstrip("/")

        # If caller passed "icons/xyz.png", prefer "xyz.png" inside /data/icons
        base_name = os.path.basename(norm)

        # 1) /data/icons/<basename>
        p1 = self.icons_dir / base_name
        if p1.is_file():
            return str(p1)

        # 2) /data/icons/<norm> (if they used nested paths)
        p2 = self.icons_dir / norm
        if p2.is_file():
            return str(p2)

        # 3) Legacy fallback: <project_root>/<norm>
        p3 = Path(self.project_root) / norm
        if p3.is_file():
            return str(p3)

        # Not found
        return str(p1)  # return the "expected" path for logging

    def _pick_ipv4(self, host: str, port: int) -> str:
        """Force IPv4 to avoid environments where IPv6 routes are blackholed."""
        try:
            infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
            if infos:
                return infos[0][4][0]
        except Exception:
            pass
        return host  # fallback

    # -----------------------------------------
    # Section 3: Send Awards Email
    # -----------------------------------------
    def send_awards(self, to_addr: str, username: str, awards: List[Achievement]) -> None:
        if not self.enabled():
            return

        real_to = self.to_override or (to_addr or "").strip()
        if not real_to:
            return

        # ✅ DEDUPE: collapse duplicates within a single run/email
        # Prefer unique achievement id; fallback to a stable tuple.
        seen: set = set()
        awards_deduped: List[Achievement] = []
        for a in awards or []:
            ach_id = getattr(a, "id", None)
            key = ach_id or (
                getattr(a, "achievement", None),
                getattr(a, "title", None),
                getattr(a, "points", None),
            )
            if key in seen:
                continue
            seen.add(key)
            awards_deduped.append(a)

        # If everything was duplicate/empty, don't send noise
        if not awards_deduped:
            return

        msg = EmailMessage()
        msg["Subject"] = f"Audiobookshelf Achievements: {len(awards_deduped)} new"
        msg["From"] = self.from_addr
        msg["To"] = real_to

        # Plain text
        lines = [f"Hey {username},", "", "New achievements earned:", ""]
        for a in awards_deduped:
            lines.append(f"- {a.achievement} ({a.title}) [+{a.points}]")
        msg.set_content("\n".join(lines))

        # Reserve CIDs for existing icons
        cid_for_ach_id: Dict[str, str] = {}
        icon_path_for_ach_id: Dict[str, str] = {}

        for a in awards_deduped:
            # Your model uses iconPath
            if not getattr(a, "iconPath", None):
                continue

            icon_fs_path = self._resolve_icon_fs_path(a.iconPath)
            if os.path.isfile(icon_fs_path):
                cid_for_ach_id[a.id] = make_msgid(domain="achievement-engine").strip("<>")
                icon_path_for_ach_id[a.id] = icon_fs_path
            else:
                print(f"[email] icon missing: {icon_fs_path}")

        # HTML
        html_awards = []
        for a in awards_deduped:
            icon_src = "https://static.wikia.nocookie.net/wowpedia/images/f/f3/Ui-achievement-levelup.png"
            cid = cid_for_ach_id.get(a.id)
            if cid:
                icon_src = f"cid:{cid}"

            subtitle = a.flavorText if a.flavorText else a.title

            html_awards.append(f"""
                <table cellspacing="0" cellpadding="0" style="
                    background: linear-gradient(180deg, #2b251d 0%, #1a1612 100%);
                    border: 2px solid #635034; padding: 12px; margin-bottom: 15px;
                    border-radius: 4px; width: 540px;
                    font-family: 'Palatino Linotype', 'Book Antiqua', Palatino, serif;">
                    <tr>
                        <td style="width: 64px; height: 64px; background: #000; border: 2px solid #a38652;">
                            <img src="{icon_src}" alt="Icon"
                                 style="width: 58px; height: 58px; display: block; margin: auto;">
                        </td>
                        <td style="padding-left: 20px; vertical-align: middle;">
                            <div style="color: #f7d16d; font-size: 19px; font-weight: bold; text-shadow: 1px 1px 2px #000;">{a.achievement}</div>
                            <div style="color: #d1d1d1; font-size: 13px; font-style: italic; margin-top: 4px;">{subtitle}</div>
                        </td>
                        <td style="width: 80px; text-align: center; vertical-align: middle;">
                            <div style="width: 54px; height: 54px; background: #1a1612; border-radius: 50%;
                                border: 1px solid #635034; display: table; margin: auto;">
                                <div style="color: #cd7f32; font-weight: bold; font-size: 22px; text-align: center;
                                    vertical-align: middle; display: table-cell; text-shadow: 1px 1px 2px #000;">
                                    {a.points}
                                </div>
                            </div>
                        </td>
                    </tr>
                </table>
            """)

        full_html = f"""
        <html>
            <body style="background-color: #1a1a1a; padding: 20px; color: #fff; font-family: sans-serif;">
                <h3 style="color: #eee; border-bottom: 1px solid #333; padding-bottom: 10px;">New Achievements Unlocked</h3>
                {"".join(html_awards)}
                <p style="color: #666; font-size: 11px; margin-top: 20px;">— Achievement Engine</p>
            </body>
        </html>
        """

        msg.add_alternative(full_html, subtype="html")
        html_part = msg.get_payload()[-1]

        # Attach inline images
        for a in awards_deduped:
            cid = cid_for_ach_id.get(a.id)
            icon_fs_path = icon_path_for_ach_id.get(a.id)
            if not cid or not icon_fs_path:
                continue

            try:
                with open(icon_fs_path, "rb") as f:
                    data = f.read()

                html_part.add_related(
                    data,
                    maintype="image",
                    subtype="png",
                    cid=f"<{cid}>",
                    filename=os.path.basename(icon_fs_path),
                )
            except Exception as e:
                print(f"[email] failed attaching icon {icon_fs_path}: {e}")

        # SMTP send
        timeout = int(os.getenv("SMTP_TIMEOUT", "30"))
        tls_context = ssl.create_default_context()
        debug = os.getenv("SMTP_DEBUG", "0") in ("1", "true", "TRUE", "yes", "YES")

        try:
            # Force IPv4 connect, but keep hostname for SNI
            ipv4 = self._pick_ipv4(self.host, self.port)

            if self.port == 465:
                with smtplib.SMTP_SSL(ipv4, self.port, timeout=timeout, context=tls_context) as server:
                    server._host = self.host  # keep original hostname
                    if debug:
                        server.set_debuglevel(1)
                    server.ehlo()
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
                return

            with smtplib.SMTP(ipv4, self.port, timeout=timeout) as server:
                server._host = self.host  # keep original hostname
                if debug:
                    server.set_debuglevel(1)

                server.ehlo()
                if self.port == 587:
                    server.starttls(context=tls_context)
                    server.ehlo()

                if self.username and self.password:
                    server.login(self.username, self.password)

                server.send_message(msg)

        except Exception as e:
            print(f"Failed to send email: {e}")
