#!/usr/bin/env python3
"""Thread Handoff の jsonl（STATE / REVIEW / log）と未解決一覧の書式を確かめる。

使い方（ワークスペースのどこからでも）:
    python _ops/schema/check.py              # _ops/threads/ の全スレッド
    python _ops/schema/check.py t-001 t-002  # 指定したスレッドだけ
    python _ops/schema/check.py --no-warn    # エラーだけ表示

書式の定義は同じフォルダの *.schema.json（JSON Schema）。このスクリプトは、
そのうち使っているキーワード（$ref, type, const, enum, minLength, pattern,
required, properties, additionalProperties, items, oneOf）と、独自の
x-keyOrder（キーを properties の順に並べる）・x-warnMaxLength（目安の字数）だけを解釈する。
行をまたぐ規則（meta は1行目、ID の重複、未解決一覧との一致など）はこのスクリプトが持つ。

Python 3.8 以上の標準ライブラリだけで動く。エラーがあれば終了コード 1、スキーマ自体に問題があれば 2（記録は確かめない）。
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent
OPS_DIR = SCHEMA_DIR.parent
WORKSPACE = OPS_DIR.parent
THREADS_DIR = OPS_DIR / "threads"

UNRESOLVED = ("open", "doing", "hold")
PENDING_HEADINGS = ("### 該当箇所", "### 指摘内容", "### 修正案", "### 次の対応")
PENDING_EMPTY = "未解決の指摘はありません。"


class Report:
    def __init__(self, show_warn):
        self.show_warn = show_warn
        self.errors = 0
        self.warnings = 0
        self.items = []

    def _emit(self, level, path, line, msg):
        self.items.append((rel(path), line or 0, len(self.items), level, msg))

    def flush(self):
        """ファイルごと・行番号順に表示する。"""
        for path, line, _, level, msg in sorted(self.items):
            where = path + (":%d" % line if line else "")
            print("%s %s: %s" % (level, where, msg))
        self.items = []

    def error(self, path, line, msg):
        self.errors += 1
        self._emit("ERROR", path, line, msg)

    def warn(self, path, line, msg):
        self.warnings += 1
        if self.show_warn:
            self._emit("WARN ", path, line, msg)


def rel(path):
    try:
        return path.resolve().relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.as_posix()


# ---- JSON Schema（使っているキーワードだけ） ----

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
}

# validate() が解釈するキーワード。これ以外がスキーマにあると、黙って無視せずに止める。
SUPPORTED = {
    "$ref", "type", "const", "enum", "minLength", "pattern",
    "required", "properties", "additionalProperties", "items", "oneOf",
    "x-keyOrder", "x-warnMaxLength",
}
# 検証には使わない注釈。あってよい。
ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs"}

_schemas = {}


class SchemaError(Exception):
    pass


def load_schema(name):
    if name not in _schemas:
        path = SCHEMA_DIR / name
        try:
            with open(path, encoding="utf-8") as f:
                schema = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise SchemaError("%s: 読めない（%s）" % (rel(path), e))
        check_schema(schema, schema, rel(path), "#")
        _schemas[name] = schema
    return _schemas[name]


def check_schema(node, root, file, where):
    """スキーマが validate() の解釈できるキーワードだけでできているか確かめる。"""
    if not isinstance(node, dict):
        raise SchemaError("%s %s: スキーマはオブジェクトにする" % (file, where))
    unknown = sorted(set(node) - SUPPORTED - ANNOTATIONS)
    if unknown:
        raise SchemaError("%s %s: check.py が解釈しないキーワード %s。check.py の validate() に実装するか、使わない" % (
            file, where, ", ".join(unknown)))
    if "type" in node and node["type"] not in TYPES:
        raise SchemaError("%s %s: type「%s」には対応していない（%s のどれか）" % (
            file, where, node["type"], " / ".join(TYPES)))
    if "$ref" in node:
        try:
            resolve(root, node["$ref"])
        except (KeyError, TypeError):
            raise SchemaError("%s %s: $ref「%s」の参照先が無い" % (file, where, node["$ref"]))
    for key in ("$defs", "properties"):
        for name, sub in node.get(key, {}).items():
            check_schema(sub, root, file, "%s/%s/%s" % (where, key, name))
    if isinstance(node.get("additionalProperties"), dict):
        check_schema(node["additionalProperties"], root, file, where + "/additionalProperties")
    if "items" in node:
        check_schema(node["items"], root, file, where + "/items")
    for i, sub in enumerate(node.get("oneOf", [])):
        check_schema(sub, root, file, "%s/oneOf/%d" % (where, i))


def resolve(root, ref):
    if not ref.startswith("#/"):
        raise SchemaError("ローカル以外の $ref には対応していない: " + ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(schema, value, root, where, out):
    """out に (level, message) を足す。level は "error" か "warn"。"""
    if "$ref" in schema:
        validate(resolve(root, schema["$ref"]), value, root, where, out)

    t = schema.get("type")
    if t is not None and not isinstance(value, TYPES[t]):
        out.append(("error", "%s: %s であるべき" % (where, t)))
        return

    if "const" in schema and value != schema["const"]:
        out.append(("error", "%s: 「%s」であるべき" % (where, schema["const"])))
    if "enum" in schema and value not in schema["enum"]:
        out.append(("error", "%s: %s のどれか（実際は %s）" % (
            where, " / ".join(map(str, schema["enum"])), json.dumps(value, ensure_ascii=False))))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(("error", "%s: 空にしない" % where))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(("error", "%s: 書式が違う（%s）" % (where, describe_pattern(value))))
        if "x-warnMaxLength" in schema and len(value) > schema["x-warnMaxLength"]:
            out.append(("warn", "%s: %d字（目安は%d字くらいまで）" % (
                where, len(value), schema["x-warnMaxLength"])))

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(schema["items"], item, root, "%s[%d]" % (where, i), out)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(("error", "%s: 「%s」が必要" % (where, key)))
        extra = schema.get("additionalProperties", True)
        for key, v in value.items():
            if key in props:
                validate(props[key], v, root, key, out)
            elif extra is False:
                out.append(("error", "未定義のキー「%s」" % key))
            elif isinstance(extra, dict):
                validate(extra, v, root, key, out)
        if root.get("x-keyOrder") and props:
            order = [k for k in value if k in props]
            expected = [k for k in props if k in value]
            if order != expected:
                out.append(("error", "キーの順が違う（%s の順にする）" % ", ".join(expected)))

    if "oneOf" in schema:
        passed = 0
        for sub in schema["oneOf"]:
            sub_out = []
            validate(sub, value, root, where, sub_out)
            if not any(level == "error" for level, _ in sub_out):
                passed += 1
        if passed != 1:
            keys = [k for sub in schema["oneOf"] for k in sub.get("required", [])]
            if keys and all(set(sub) == {"required"} for sub in schema["oneOf"]):
                out.append(("error", "%s のどれか1つだけが必要" % " / ".join("「%s」" % k for k in keys)))
            else:
                out.append(("error", "%s: 定義のどれか1つだけに合うべき" % where))


def describe_pattern(value):
    if "\n" in value or "\r" in value:
        return "改行を入れない"
    if "\\" in value:
        return "バックスラッシュを使わない。パスは / 区切り"
    return json.dumps(value, ensure_ascii=False)


# ---- ファイルの読み込み ----

def read_rows(path, rep):
    """(行番号, dict) のリストを返す。読めない行は報告して飛ばす。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        rep.warn(path, 1, "BOM 付きの UTF-8。BOM なしで保存する")
    text = raw.decode("utf-8-sig")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rows = []
    for no, line in enumerate(lines, 1):
        line = line.rstrip("\r")
        if not line.strip():
            rep.warn(path, no, "空行")
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            rep.error(path, no, "JSON として読めない（%s）" % e.msg)
            continue
        if not isinstance(obj, dict):
            rep.error(path, no, "1行に1つの JSON オブジェクトにする")
            continue
        rows.append((no, obj))
    return rows, len(lines)


def check_rows(path, rows, schema, defs_for, rep):
    """defs_for(obj) が $defs の名前を返す（None なら種類が分からない）。"""
    for no, obj in rows:
        name = defs_for(obj)
        if name is None:
            rep.error(path, no, "行の種類が分からない")
            continue
        out = []
        validate(schema["$defs"][name], obj, schema, name, out)
        for key, v in obj.items():
            for s in v if isinstance(v, list) else [v]:
                if isinstance(s, str) and '"' in s:
                    out.append(("warn", "%s: 値の中の引用符は「」を使う" % key))
                    break
        for level, msg in out:
            (rep.error if level == "error" else rep.warn)(path, no, msg)


# ---- STATE ----

def state_kind(obj):
    if obj.get("type") == "meta":
        return "meta"
    if obj.get("type") == "note":
        return "note"
    if next(iter(obj), None) == "id":
        return "task"
    return None


def check_state(tid, path, rep):
    schema = load_schema("state.schema.json")
    rows, nlines = read_rows(path, rep)
    check_rows(path, rows, schema, state_kind, rep)

    metas = [(no, o) for no, o in rows if state_kind(o) == "meta"]
    if not metas:
        rep.error(path, None, "meta の行が無い")
    elif len(metas) > 1:
        rep.error(path, metas[1][0], "meta の行は1つだけにする")
    if metas:
        no, meta = metas[0]
        if rows and rows[0][0] != no:
            rep.error(path, no, "meta は1行目に置く")
        if meta.get("thread") != tid:
            rep.error(path, no, "thread「%s」がフォルダ名「%s」と違う" % (meta.get("thread"), tid))

    seen = {}
    for no, o in rows:
        if state_kind(o) != "task" or not isinstance(o.get("id"), str):
            continue
        tid_ = o["id"]
        if tid_ in seen:
            rep.error(path, no, "task の id「%s」が重複（%d行目）" % (tid_, seen[tid_]))
        seen.setdefault(tid_, no)
    for tid_, no in seen.items():
        if "-" in tid_ and tid_.split("-")[0] not in seen:
            rep.warn(path, no, "親の task「%s」が無い" % tid_.split("-")[0])

    notes = [o for _, o in rows if state_kind(o) == "note"]
    if len(notes) > 5:
        rep.warn(path, None, "note が%d件（目安は5件まで。handoff で刈り取る）" % len(notes))
    if nlines >= 100:
        rep.warn(path, None, "%d行（100行未満にする）" % nlines)


# ---- log ----

def check_log(path, rep):
    schema = load_schema("log.schema.json")
    rows, _ = read_rows(path, rep)
    check_rows(path, rows, schema, lambda o: "entry", rep)


# ---- REVIEW と未解決一覧 ----

def review_kind(obj):
    keys = list(obj)
    if len(keys) >= 2 and keys[1] == "status":
        return "issue"
    if len(keys) >= 2 and keys[1] == "kind":
        return "event"
    if "status" in obj:
        return "issue"
    if "kind" in obj:
        return "event"
    return None


def check_review(tid, path, thread_dir, rep):
    schema = load_schema("review.schema.json")
    rows, _ = read_rows(path, rep)
    check_rows(path, rows, schema, review_kind, rep)

    issues = {}
    events = {}
    last_date = None
    for no, o in rows:
        kind = review_kind(o)
        rid = o.get("id")
        if not isinstance(rid, str):
            continue
        if kind == "issue":
            if rid in issues:
                rep.error(path, no, "指摘の行「%s」が重複（%d行目）。状態は既存の行を書き換える" % (rid, issues[rid][0]))
                continue
            issues[rid] = (no, o)
        elif kind == "event":
            events.setdefault(rid, []).append(no)
            d = o.get("date")
            if isinstance(d, str):
                if last_date and d < last_date:
                    rep.warn(path, no, "date が前の行（%s）より古い。経緯の行は末尾に追記する" % last_date)
                last_date = max(last_date or d, d)

    for rid, nos in events.items():
        if rid not in issues:
            rep.error(path, nos[0], "経緯の行「%s」に対応する指摘の行が無い" % rid)
    for rid, (no, o) in issues.items():
        status = o.get("status")
        if rid not in events:
            rep.warn(path, no, "「%s」に経緯の行が無い" % rid)
        if status in UNRESOLVED and "action" not in o:
            rep.error(path, no, "未解決（%s）の指摘には「action」が必要" % status)
        if status in ("resolved", "withdrawn") and "waitingOn" in o:
            rep.warn(path, no, "%s なのに waitingOn が残っている" % status)

    unresolved = [rid for rid, (_, o) in issues.items() if o.get("status") in UNRESOLVED]
    check_pending(tid, thread_dir, unresolved, rep)


def check_pending(tid, thread_dir, unresolved, rep):
    path = thread_dir / "work" / "review" / ("%s-review-pending.md" % tid)
    if not path.exists():
        if unresolved:
            rep.error(path, None, "未解決の指摘（%s）があるのに未解決一覧が無い" % ", ".join(unresolved))
        return

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or not lines[0].startswith("# 未解決の指摘"):
        rep.warn(path, 1, "1行目は「# 未解決の指摘: %s」にする" % tid)

    sections = []  # (id, 開始行, 本文の行)
    for no, line in enumerate(lines, 1):
        m = re.match(r"^## (R-[0-9]{3})\b", line)
        if m:
            sections.append([m.group(1), no, []])
        elif line.startswith("## "):
            rep.error(path, no, "見出しは「## R-001: <タイトル>」の形にする")
            sections.append([None, no, []])
        elif sections:
            sections[-1][2].append(line)

    listed = [s[0] for s in sections if s[0]]
    for rid in unresolved:
        if rid not in listed:
            rep.error(path, None, "未解決の「%s」が一覧に無い" % rid)
    for rid, no, _ in sections:
        if rid and rid not in unresolved:
            rep.error(path, no, "「%s」は未解決ではない（解決・取り下げ済か、REVIEW.jsonl に無い）。一覧から消す" % rid)
        if rid and listed.count(rid) > 1:
            rep.error(path, no, "「%s」が一覧に重複している" % rid)

    for rid, no, body in sections:
        if not rid:
            continue
        for h in PENDING_HEADINGS:
            if not any(l.strip() == h for l in body):
                rep.error(path, no, "「%s」に「%s」が無い" % (rid, h))
        if not has_quote(body):
            rep.error(path, no, "「%s」の該当箇所に原文のコードブロックが無い" % rid)

    if not unresolved and not sections and not any(PENDING_EMPTY in l for l in lines):
        rep.warn(path, None, "未解決が無いときは「%s」と書く" % PENDING_EMPTY)


def has_quote(body):
    """「### 該当箇所」から次の「### 」までに、中身のあるコードブロックがあるか。"""
    inside = False
    fence = None
    content = False
    for line in body:
        s = line.strip()
        if not inside:
            if s == "### 該当箇所":
                inside = True
            continue
        if fence is None and s.startswith("### "):
            break
        m = re.match(r"^(`{3,}|~{3,})", s)
        if m:
            if fence is None:
                fence = m.group(1)
            elif s.startswith(fence) and s.strip("`~") == "":
                if content:
                    return True
                fence = None
            continue
        if fence is not None and s:
            content = True
    return False


# ---- 入口 ----

def check_thread(thread_dir, rep):
    tid = thread_dir.name
    state = thread_dir / ("%s-STATE.jsonl" % tid)
    if state.exists():
        check_state(tid, state, rep)
    else:
        rep.error(state, None, "STATE.jsonl が無い")
    log = thread_dir / ("%s-log.jsonl" % tid)
    if log.exists():
        check_log(log, rep)
    review = thread_dir / ("%s-REVIEW.jsonl" % tid)
    if review.exists():
        check_review(tid, review, thread_dir, rep)
    else:
        check_pending(tid, thread_dir, [], rep)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Thread Handoff の jsonl と未解決一覧の書式を確かめる")
    ap.add_argument("threads", nargs="*", help="スレッドID（省略すると全スレッド）")
    ap.add_argument("--no-warn", action="store_true", help="警告を表示しない")
    args = ap.parse_args(argv)

    rep = Report(show_warn=not args.no_warn)
    if args.threads:
        dirs = []
        for tid in args.threads:
            d = THREADS_DIR / tid
            if d.is_dir():
                dirs.append(d)
            else:
                rep.error(d, None, "スレッドが無い")
    else:
        dirs = sorted(d for d in THREADS_DIR.iterdir() if d.is_dir()) if THREADS_DIR.is_dir() else []

    try:
        for name in ("state.schema.json", "review.schema.json", "log.schema.json"):
            load_schema(name)
    except SchemaError as e:
        print("SCHEMA %s" % e)
        print("スキーマに問題があるので、記録の確認はしていない")
        return 2

    for d in dirs:
        check_thread(d, rep)
    rep.flush()

    print("確認: %dスレッド / エラー %d / 警告 %d" % (len(dirs), rep.errors, rep.warnings))
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
