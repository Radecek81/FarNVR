"""Administration CLI.

    nvr-cli user add <jmeno> [--totp]
    nvr-cli user passwd <jmeno>
    nvr-cli user totp <jmeno> [--off]
    nvr-cli user del <jmeno>
    nvr-cli user list
    nvr-cli storage-init          # mark the mounted NAS as recording storage
    nvr-cli reindex [--cam ID]    # rebuild the index from journals on the NAS
    nvr-cli check                 # test connectivity to the cameras
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

import pyotp

from . import auth
from .config import load_config
from .db import Database
from .recorder import STORAGE_MARKER, probe_codec


def _password(prompt="Heslo: ") -> str:
    while True:
        p1 = getpass.getpass(prompt)
        p2 = getpass.getpass("Heslo znovu: ")
        if p1 != p2:
            print("Hesla se neshodují.")
            continue
        if len(p1) < 10:
            print("Heslo musí mít alespoň 10 znaků.")
            continue
        return p1


def _show_totp(username: str, secret: str, site: str):
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=site)
    print("\nDvoufázové ověření (TOTP) je zapnuté.")
    print("Naskenujte v aplikaci (Google/Microsoft Authenticator) tento odkaz nebo zadejte klíč ručně:")
    print("  klíč:", secret)
    print("  URI: ", uri)
    try:
        import qrcode  # optional
        qr = qrcode.QRCode()
        qr.add_data(uri)
        qr.print_ascii(invert=True)
    except ImportError:
        pass


def reindex(cfg, db: Database, cam_filter: str | None = None) -> int:
    root = cfg.storage_path
    count = 0
    for cam in cfg.cameras:
        if cam_filter and cam.id != cam_filter:
            continue
        sess_root = root / cam.id / "sessions"
        if not sess_root.is_dir():
            continue
        for sdir in sorted(sess_root.iterdir()):
            journal = sdir / "segments.csv"
            init = sdir / "init.mp4"
            if not journal.exists() or not init.exists():
                continue
            rows = []
            for line in journal.read_text().splitlines():
                parts = line.split(",")
                if len(parts) < 3:
                    continue
                start, dur, rel = float(parts[0]), float(parts[1]), parts[2]
                size = int(parts[3]) if len(parts) > 3 else 0
                if (root / rel).exists():
                    rows.append((cam.id, sdir.name, start, dur, rel, size))
            if not rows:
                continue
            codec = asyncio.run(probe_codec(str(init), []))
            db.add_session(sdir.name, cam.id, rows[0][2], str(init.relative_to(root)), codec)
            db.end_session(sdir.name, rows[-1][2] + rows[-1][3])
            db.add_segments(rows)
            count += len(rows)
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nvr-cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("user")
    usub = u.add_subparsers(dest="action", required=True)
    a = usub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--totp", action="store_true")
    for name in ("passwd", "del"):
        usub.add_parser(name).add_argument("username")
    t = usub.add_parser("totp")
    t.add_argument("username")
    t.add_argument("--off", action="store_true")
    usub.add_parser("list")
    sub.add_parser("storage-init")
    r = sub.add_parser("reindex")
    r.add_argument("--cam")
    sub.add_parser("check")
    args = ap.parse_args(argv)

    cfg = load_config()
    db = Database(cfg.data_path / "nvr.db")

    if args.cmd == "user":
        name = getattr(args, "username", "").strip().lower()
        if args.action == "add":
            secret = auth.create_user(db, name, _password(), args.totp)
            print(f"Uživatel {name} vytvořen.")
            if secret:
                _show_totp(name, secret, cfg.site_name)
        elif args.action == "list":
            for row in db.query("SELECT username, totp_secret FROM users ORDER BY username"):
                print(f"{row['username']:20} {'2FA' if row['totp_secret'] else ''}")
        else:
            row = db.one("SELECT id FROM users WHERE username=?", (name,))
            if not row:
                sys.exit(f"Uživatel {name} neexistuje")
            if args.action == "passwd":
                auth.set_password(db, row["id"], _password("Nové heslo: "))
                print("Heslo změněno, všechna přihlášení byla odhlášena.")
            elif args.action == "del":
                db.execute("DELETE FROM users WHERE id=?", (row["id"],))
                print(f"Uživatel {name} smazán.")
            elif args.action == "totp":
                secret = None if args.off else pyotp.random_base32()
                db.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, row["id"]))
                if secret:
                    _show_totp(name, secret, cfg.site_name)
                else:
                    print("Dvoufázové ověření vypnuto.")
    elif args.cmd == "storage-init":
        root: Path = cfg.storage_path
        if not root.is_dir():
            sys.exit(f"{root} neexistuje")
        (root / STORAGE_MARKER).write_text("FarNVR recording storage\n")
        print(f"Úložiště {root} označeno ({STORAGE_MARKER}).")
    elif args.cmd == "reindex":
        print(f"Zaindexováno {reindex(cfg, db, args.cam)} úseků.")
    elif args.cmd == "check":
        async def check():
            for cam in cfg.cameras:
                main = await probe_codec(cam.main_rtsp, [])
                sub = await probe_codec(cam.sub_rtsp, [])
                print(f"{cam.id:10} hlavní stream: {main or 'NEDOSTUPNÝ'}  sub stream: {sub or 'NEDOSTUPNÝ'}")
        asyncio.run(check())


if __name__ == "__main__":
    main()
