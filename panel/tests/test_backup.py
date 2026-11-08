import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timezone

from bytepanel.backup import backup
from bytepanel.db import Db


class Backup(unittest.TestCase):
    def test_consistent_copy_private_files_and_pruning(self):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/panel.db"
            db = Db(path)
            db.run("INSERT INTO settings(key,value) VALUES('paused','1')")
            made = []
            for i in range(5):
                t = datetime(2026, 11, 8, 12, i, 0, tzinfo=timezone.utc)
                made.append(backup(path, f"{d}/backups", keep=3, now=lambda t=t: t))
            left = sorted(os.listdir(f"{d}/backups"))
            self.assertEqual(len(left), 3)
            self.assertEqual(left[-1], made[-1].name)
            self.assertEqual(stat.S_IMODE(os.stat(made[-1]).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(f"{d}/backups").st_mode), 0o700)
            con = sqlite3.connect(made[-1])
            self.assertEqual(con.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0], "1")
            con.close()
            db.close()


if __name__ == "__main__":
    unittest.main()
