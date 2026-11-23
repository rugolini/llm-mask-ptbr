import os
import sqlite3


class Vault:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        if path != ":memory:":
            os.chmod(path, 0o600)
        self.db.execute("create table if not exists map (kind text, n integer, value text primary key)")
        self.by_value = {value: (kind, n) for kind, n, value in self.db.execute("select kind, n, value from map")}
        self.by_token = {f"[{kind}_{n}]": value for value, (kind, n) in self.by_value.items()}
        self.last = {}
        for kind, n in self.by_value.values():
            self.last[kind] = max(n, self.last.get(kind, 0))

    def token(self, kind, value):
        if value not in self.by_value:
            n = self.last[kind] = self.last.get(kind, 0) + 1
            with self.db:
                self.db.execute("insert into map values (?, ?, ?)", (kind, n, value))
            self.by_value[value] = (kind, n)
            self.by_token[f"[{kind}_{n}]"] = value
        kind, n = self.by_value[value]
        return f"[{kind}_{n}]"

    def value(self, token):
        return self.by_token.get(token)
