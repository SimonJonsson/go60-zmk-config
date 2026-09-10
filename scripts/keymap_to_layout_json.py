#!/usr/bin/env python3
"""Convert a MoErgo Go60 ZMK keymap into a MoErgo Layout Editor JSON file.

The keymap in config/ is the source of truth. This script produces the JSON
that the Layout Editor (https://my.moergo.com/go60/) imports when the
"Local Backup and Restore" setting is enabled.

The JSON shape was taken from a Factory Default export and from the editor's
own schema. Layers, combos, macros, hold-taps and Cirque input listeners are
first-class. Anything else the keymap defines (tap-dances, mod-morphs, input
processors, extra devicetree overrides) is passed through verbatim in
custom_defined_behaviors and custom_devicetree.

Behaviours the editor already provides for the Go60 are recognised by shape and
translated to the editor's own keys instead of being duplicated:

  &magic LAYER_Magic 0       -> &magic
  tap-dance <&mo N>, <&to N> -> &layer N        (keypad_td, symbol_nav_td)
  tap-dance bt_select_N/BT_DISC N -> &bt_N     (and its bt_select_N macro)
  rgb_ug_status_macro, zip_click_to_right_click_mapper -> omitted
  &sys_reset                 -> &reset

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

KEYS_PER_LAYER = 60
MAX_LAYERS = 32
NAME_RE = re.compile(r"^[A-Za-z]\w*$")
LAYER_NAME_RE = re.compile(r"^\w+$")

# Editor-provided helper nodes that must not be duplicated in custom text.
EDITOR_PROVIDED_MACROS = {"rgb_ug_status_macro"}
EDITOR_PROVIDED_INPUT_PROCESSORS = {"zip_click_to_right_click_mapper"}
BT_SELECT_RE = re.compile(r"^bt_select_(\d)$")


PREPROCESSOR_RE = re.compile(r"^\s*#\s*(include|define|undef|if|ifdef|ifndef|elif|else|endif|pragma|error|warning)\b")


class KeymapError(Exception):
    pass


def substitute_defines(raw: str, defines: dict[str, str]) -> str:
    """Expand the keymap's own simple #defines inside pass-through text. The
    editor generates LAYER_<name> defines itself, so those are left alone."""
    for name, value in defines.items():
        if not name.startswith("LAYER_"):
            raw = re.sub(rf"\b{re.escape(name)}\b", value, raw)
    return raw


def reindent(raw: str, spaces: int) -> str:
    """Re-indent a node's source text so it sits at `spaces` columns."""
    lines = raw.splitlines()
    rest = [l for l in lines[1:] if l.strip()]
    common = min((len(l) - len(l.lstrip()) for l in rest), default=0)
    out = [" " * spaces + lines[0].strip()]
    for l in lines[1:]:
        out.append(" " * spaces + l[common:] if l.strip() else "")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Devicetree parsing
# --------------------------------------------------------------------------


@dataclass
class Node:
    name: str
    label: str | None
    props: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    raw: str = ""  # source text of the whole node, from name to closing "};"

    def child(self, name: str) -> "Node | None":
        for c in self.children:
            if c.name == name:
                return c
        return None

    def compatible(self) -> str | None:
        v = self.props.get("compatible")
        return v.strip().strip('"') if v else None


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def collect_defines(text: str) -> tuple[dict[str, str], str]:
    """Return simple `#define NAME VALUE` pairs and the text without any
    preprocessor lines."""
    defines: dict[str, str] = {}
    kept: list[str] = []
    text = re.sub(r"\\\n", " ", text)  # join backslash-continued lines
    for line in text.splitlines():
        if re.match(r"^\s*#\s*define\s+\w+\(", line):
            raise KeymapError("function-like #define macros are not supported; write the nodes out explicitly")
        m = re.match(r"^\s*#\s*define\s+(\w+)\s+(\S+)\s*$", line)
        if m:
            defines[m.group(1)] = m.group(2)
            continue
        if PREPROCESSOR_RE.match(line):
            continue
        kept.append(line)  # devicetree properties like #binding-cells stay
    return defines, "\n".join(kept)


def expand_defines(token: str, defines: dict[str, str]) -> str:
    seen = 0
    while token in defines and seen < 32:
        token = defines[token]
        seen += 1
    return token


class Parser:
    def __init__(self, text: str):
        self.t = text
        self.i = 0

    def parse_all(self) -> list[Node]:
        nodes: list[Node] = []
        while True:
            self.skip_ws()
            if self.i >= len(self.t):
                return nodes
            nodes.append(self.parse_node())

    def skip_ws(self) -> None:
        while self.i < len(self.t) and self.t[self.i].isspace():
            self.i += 1

    def read_until(self, stops: str) -> tuple[str, str]:
        """Read up to (not including) the first char in `stops`, skipping over
        quoted strings. Returns (text, stop_char)."""
        start = self.i
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == '"':
                self.i += 1
                while self.i < len(self.t) and self.t[self.i] != '"':
                    self.i += 1
            elif c in stops:
                return self.t[start:self.i], c
            self.i += 1
        raise KeymapError("unexpected end of file")

    def parse_node(self) -> Node:
        start = self.i
        header, _ = self.read_until("{")
        self.i += 1  # {
        header = header.strip()
        label = None
        if ":" in header:
            label, header = [h.strip() for h in header.split(":", 1)]
        node = Node(name=header, label=label)
        while True:
            self.skip_ws()
            if self.t[self.i] == "}":
                self.i += 1
                self.skip_ws()
                if self.i < len(self.t) and self.t[self.i] == ";":
                    self.i += 1
                node.raw = self.t[start:self.i]
                return node
            text, stop = self.read_until("{;")
            if stop == "{":
                self.i = self.i - len(text)  # rewind, parse_node re-reads header
                node.children.append(self.parse_node())
            else:
                self.i += 1  # ;
                text = text.strip()
                if not text:
                    continue
                if "=" in text:
                    k, v = text.split("=", 1)
                    node.props[k.strip()] = v.strip()
                else:
                    node.props[text] = ""


def cells(value: str) -> list[str]:
    """Tokens inside one or more `<...>` groups, in order."""
    out: list[str] = []
    for group in re.findall(r"<([^>]*)>", value):
        out.extend(group.split())
    return out


def cell_groups(value: str) -> list[list[str]]:
    return [g.split() for g in re.findall(r"<([^>]*)>", value)]


def ints(value: str, defines: dict[str, str]) -> list[int]:
    return [int(expand_defines(tok, defines)) for tok in cells(value)]


def optional_int(node: Node, prop: str, defines: dict[str, str]) -> int | None:
    if prop not in node.props:
        return None
    vals = ints(node.props[prop], defines)
    return vals[0] if vals else None


def flag(node: Node, prop: str) -> bool:
    return prop in node.props


# --------------------------------------------------------------------------
# Bindings
# --------------------------------------------------------------------------


# ZMK's shifted-symbol aliases. The Layout Editor stores them as LS(base key).
SHIFTED_ALIASES = {
    "EXCL": "N1", "EXCLAMATION": "N1",
    "AT": "N2", "AT_SIGN": "N2",
    "HASH": "N3", "POUND": "N3",
    "DLLR": "N4", "DOLLAR": "N4",
    "PRCNT": "N5", "PERCENT": "N5",
    "CARET": "N6",
    "AMPS": "N7", "AMPERSAND": "N7",
    "STAR": "N8", "ASTRK": "N8", "ASTERISK": "N8",
    "LPAR": "N9", "LEFT_PARENTHESIS": "N9",
    "RPAR": "N0", "RIGHT_PARENTHESIS": "N0",
    "UNDER": "MINUS", "UNDERSCORE": "MINUS",
    "PLUS": "EQUAL",
    "LBRC": "LBKT", "LEFT_BRACE": "LBKT",
    "RBRC": "RBKT", "RIGHT_BRACE": "RBKT",
    "PIPE": "BSLH",
    "COLON": "SEMI",
    "DQT": "SQT", "DOUBLE_QUOTES": "SQT",
    "TILDE": "GRAVE", "TILDE2": "GRAVE",
    "LT": "COMMA", "LESS_THAN": "COMMA",
    "GT": "DOT", "GREATER_THAN": "DOT",
    "QMARK": "FSLH", "QUESTION": "FSLH",
}


def parse_param(token: str, defines: dict[str, str]) -> dict:
    token = expand_defines(token, defines)
    if token in SHIFTED_ALIASES:
        return {"value": "LS", "params": [{"value": SHIFTED_ALIASES[token]}]}
    if re.fullmatch(r"-?\d+", token):
        return {"value": int(token)}
    m = re.match(r"^(\w+)\((.*)\)$", token)
    if m:
        return {"value": m.group(1), "params": [parse_param(m.group(2), defines)]}
    return {"value": token}


def split_bindings(tokens: list[str]) -> list[list[str]]:
    """Group a flat token list into [behaviour, params...] lists."""
    groups: list[list[str]] = []
    for tok in tokens:
        if tok.startswith("&"):
            groups.append([tok])
        elif groups:
            groups[-1].append(tok)
        else:
            raise KeymapError(f"parameter {tok!r} before any behaviour")
    return groups


@dataclass
class Rewrites:
    """How keymap behaviours map onto editor built-ins."""

    magic: set[str] = field(default_factory=set)  # names that become &magic
    layer_td: dict[str, int] = field(default_factory=dict)  # name -> layer
    bt_td: set[str] = field(default_factory=set)  # bt_N tap-dances kept as is


def binding_to_json(group: list[str], defines: dict[str, str], rw: Rewrites) -> dict:
    behaviour, params = group[0], group[1:]
    name = behaviour[1:]
    if name in rw.magic:
        return {"value": "&magic"}
    if name in rw.layer_td:
        return {"value": "&layer", "params": [{"value": rw.layer_td[name]}]}
    if behaviour == "&sys_reset":
        return {"value": "&reset"}
    out: dict = {"value": behaviour}
    if params:
        out["params"] = [parse_param(p, defines) for p in params]
    return out


def binding_list(value: str, defines: dict[str, str], rw: Rewrites) -> list[dict]:
    return [binding_to_json(g, defines, rw) for g in split_bindings(cells(value))]


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


def detect_rewrites(root: Node, defines: dict[str, str]) -> tuple[Rewrites, set[str], set[str]]:
    """Find behaviours whose shape matches an editor built-in.

    Returns the rewrites plus the sets of behaviour and macro names to omit
    from the output because the editor generates them itself."""
    rw = Rewrites()
    skip_behaviours: set[str] = set()
    skip_macros: set[str] = set(EDITOR_PROVIDED_MACROS)
    behaviours = root.child("behaviors")
    if behaviours is None:
        return rw, skip_behaviours, skip_macros
    for b in behaviours.children:
        name = b.label or b.name
        comp = b.compatible()
        groups = cell_groups(b.props.get("bindings", ""))
        if comp == "zmk,behavior-hold-tap" and groups == [["&mo"], ["&rgb_ug_status_macro"]]:
            rw.magic.add(name)
            skip_behaviours.add(name)
        elif comp == "zmk,behavior-tap-dance" and len(groups) == 2:
            a, c = groups
            if a[0] == "&mo" and c[0] == "&to" and a[1:] == c[1:] and len(a) == 2:
                rw.layer_td[name] = int(expand_defines(a[1], defines))
                skip_behaviours.add(name)
            elif (
                BT_SELECT_RE.match(a[0][1:] if a[0].startswith("&") else "")
                and c[:2] == ["&bt", "BT_DISC"]
                and name == "bt_" + BT_SELECT_RE.match(a[0][1:]).group(1)
            ):
                rw.bt_td.add(name)
                skip_behaviours.add(name)
                skip_macros.add(a[0][1:])
    return rw, skip_behaviours, skip_macros


def hold_tap_to_json(b: Node, defines: dict[str, str]) -> dict:
    name = b.label or b.name
    groups = cell_groups(b.props.get("bindings", ""))
    if len(groups) != 2:
        raise KeymapError(f"hold-tap {name} must have exactly two bindings")
    out: dict = {
        "name": name,
        "description": "",
        "bindings": [groups[0][0], groups[1][0]],
        "tappingTermMs": optional_int(b, "tapping-term-ms", defines) or 200,
    }
    if "flavor" in b.props:
        out["flavor"] = b.props["flavor"].strip('"')
    for prop, key in (
        ("quick-tap-ms", "quickTapMs"),
        ("require-prior-idle-ms", "requirePriorIdleMs"),
    ):
        v = optional_int(b, prop, defines)
        if v is not None:
            out[key] = v
    for prop, key in (
        ("retro-tap", "retroTap"),
        ("hold-while-undecided", "holdWhileUndecided"),
        ("hold-while-undecided-linger", "holdWhileUndecidedLinger"),
        ("hold-trigger-on-release", "holdTriggerOnRelease"),
    ):
        if flag(b, prop):
            out[key] = True
    if "hold-trigger-key-positions" in b.props:
        out["holdTriggerKeyPositions"] = ints(b.props["hold-trigger-key-positions"], defines)
    return out


def macro_to_json(m: Node, defines: dict[str, str], rw: Rewrites) -> dict:
    name = m.label or m.name
    comp = m.compatible() or ""
    params = {
        "zmk,behavior-macro": [],
        "zmk,behavior-macro-one-param": ["code"],
        "zmk,behavior-macro-two-param": ["code", "code"],
    }.get(comp)
    if params is None:
        raise KeymapError(f"macro {name} has unsupported compatible {comp!r}")
    out: dict = {
        "name": name,
        "description": "",
        "bindings": binding_list(m.props.get("bindings", ""), defines, rw),
        "params": params,
    }
    for prop, key in (("wait-ms", "waitMs"), ("tap-ms", "tapMs")):
        v = optional_int(m, prop, defines)
        if v is not None:
            out[key] = v
    if not out["bindings"]:
        raise KeymapError(f"macro {name} has no bindings")
    return out


def combo_to_json(c: Node, defines: dict[str, str], rw: Rewrites) -> dict:
    name = c.label or c.name
    bindings = binding_list(c.props.get("bindings", ""), defines, rw)
    if len(bindings) != 1:
        raise KeymapError(f"combo {name} must have exactly one binding")
    out: dict = {
        "name": name,
        "description": "",
        "binding": bindings[0],
        "keyPositions": ints(c.props.get("key-positions", ""), defines),
    }
    for prop, key in (
        ("timeout-ms", "timeoutMs"),
        ("require-prior-idle-ms", "requirePriorIdleMs"),
    ):
        v = optional_int(c, prop, defines)
        if v is not None:
            out[key] = v
    if flag(c, "slow-release"):
        out["slowRelease"] = True
    out["layers"] = ints(c.props["layers"], defines) if "layers" in c.props else [-1]
    return out


def processor_param(token: str, defines: dict[str, str]):
    token = expand_defines(token, defines)
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return [t for t in re.split(r"[|()\s]+", token) if t]


def input_processors(value: str, defines: dict[str, str]) -> list[dict]:
    out = []
    for group in cell_groups(value):
        out.append(
            {
                "code": group[0],
                "params": [processor_param(p, defines) for p in group[1:]],
            }
        )
    return out


def listener_to_json(n: Node, defines: dict[str, str]) -> dict:
    out: dict = {
        "code": "&" + n.name.lstrip("&"),
        "inputProcessors": input_processors(n.props.get("input-processors", ""), defines),
        "nodes": [],
    }
    for child in n.children:
        out["nodes"].append(
            {
                "code": child.name,
                "layers": ints(child.props.get("layers", ""), defines),
                "inputProcessors": input_processors(child.props.get("input-processors", ""), defines),
            }
        )
    return out


def parse_conf(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*CONFIG_(\w+)\s*=\s*(.+?)\s*$", line)
        if m:
            out.append({"paramName": m.group(1), "value": m.group(2)})
    return out


def convert(
    keymap_text: str,
    *,
    conf: Path | None = None,
    keyboard: str = "go60",
    keys: int = KEYS_PER_LAYER,
    locale: str = "en-US",
    title: str = "",
    creator: str = "",
    notes: str = "",
    tags: list[str] | None = None,
    date: int | None = None,
) -> dict:
    defines, text = collect_defines(strip_comments(keymap_text))
    top = Parser(text).parse_all()

    roots = [n for n in top if n.name == "/"]
    overrides = [n for n in top if n.name != "/"]
    root = Node(name="/", label=None)
    for r in roots:
        root.props.update(r.props)
        root.children.extend(r.children)

    keymap = root.child("keymap")
    if keymap is None:
        raise KeymapError("no keymap node found")
    macros_node = root.child("macros")
    rw, skip_behaviours, skip_macros = detect_rewrites(root, defines)

    layer_names: list[str] = []
    layers: list[list[dict]] = []
    for layer in keymap.children:
        name = re.sub(r"^layer_", "", layer.name)
        layer_names.append(name)
        layers.append(binding_list(layer.props.get("bindings", ""), defines, rw))

    hold_taps: list[dict] = []
    custom_behaviours: list[str] = []
    behaviours = root.child("behaviors")
    if behaviours is not None:
        for b in behaviours.children:
            name = b.label or b.name
            if name in skip_behaviours:
                continue
            if b.compatible() == "zmk,behavior-hold-tap":
                hold_taps.append(hold_tap_to_json(b, defines))
            else:
                custom_behaviours.append(reindent(substitute_defines(b.raw, defines), 8))

    macros: list[dict] = []
    if macros_node is not None:
        for m in macros_node.children:
            if (m.label or m.name) in skip_macros:
                continue
            macros.append(macro_to_json(m, defines, rw))

    combos: list[dict] = []
    combos_node = root.child("combos")
    if combos_node is not None:
        for c in combos_node.children:
            combos.append(combo_to_json(c, defines, rw))

    custom_root_nodes: list[str] = []
    for n in root.children:
        if n.name in ("keymap", "behaviors", "macros", "combos"):
            continue
        if n.name == "input_processors":
            kept = [reindent(substitute_defines(c.raw, defines), 8) for c in n.children if (c.label or c.name) not in EDITOR_PROVIDED_INPUT_PROCESSORS]
            if kept:
                custom_root_nodes.append("    input_processors {\n" + "\n".join(kept) + "\n    };")
            continue
        custom_root_nodes.append(reindent(substitute_defines(n.raw, defines), 4))

    listeners: list[dict] = []
    custom_devicetree: list[str] = []
    for n in overrides:
        if n.name.startswith("&") and n.name.endswith("_listener"):
            listeners.append(listener_to_json(n, defines))
        else:
            custom_devicetree.append(reindent(substitute_defines(n.raw, defines), 0))

    custom_parts: list[str] = []
    if custom_behaviours:
        custom_parts.append("/ {\n    behaviors {\n" + "\n".join(custom_behaviours) + "\n    };\n};")
    for raw in custom_root_nodes:
        custom_parts.append("/ {\n" + raw + "\n};")

    doc = {
        "version": 1,
        "keyboard": keyboard,
        "firmware_api_version": "1",
        "locale": locale,
        "uuid": "",
        "parent_uuid": "",
        "unlisted": False,
        "date": date,
        "creator": creator,
        "title": title,
        "notes": notes,
        "tags": tags or [],
        "custom_defined_behaviors": "\n\n".join(custom_parts),
        "custom_devicetree": "\n\n".join(custom_devicetree),
        "config_parameters": parse_conf(conf),
        "layout_parameters": {},
        "layer_names": layer_names,
        "layers": layers,
        "macros": macros,
        "inputListeners": listeners,
        "holdTaps": hold_taps,
        "combos": combos,
    }
    validate(doc, keys=keys)
    return doc


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(doc: dict, *, keys: int = KEYS_PER_LAYER) -> None:
    problems: list[str] = []
    names = doc["layer_names"]
    if len(names) != len(doc["layers"]):
        problems.append("layer_names and layers differ in length")
    if len(names) > MAX_LAYERS:
        problems.append(f"more than {MAX_LAYERS} layers")
    if len(set(names)) != len(names):
        problems.append("duplicate layer names")
    for name in names:
        if not LAYER_NAME_RE.match(name):
            problems.append(f"bad layer name {name!r}")
    for name, layer in zip(names, doc["layers"]):
        if len(layer) != keys:
            problems.append(f"layer {name} has {len(layer)} keys, expected {keys}")
    for kind in ("macros", "holdTaps", "combos"):
        for item in doc[kind]:
            if not NAME_RE.match(item["name"]):
                problems.append(f"bad {kind} name {item['name']!r}")
    for combo in doc["combos"]:
        for pos in combo["keyPositions"]:
            if not 0 <= pos < keys:
                problems.append(f"combo {combo['name']} position {pos} out of range")
        for layer in combo["layers"]:
            if layer != -1 and not 0 <= layer < len(names):
                problems.append(f"combo {combo['name']} refers to missing layer {layer}")
        if combo["layers"] != [-1] and -1 in combo["layers"]:
            problems.append(f"combo {combo['name']} mixes -1 with layer indices")
        if "timeoutMs" in combo and combo["timeoutMs"] < 1:
            problems.append(f"combo {combo['name']} timeout must be positive")
    for macro in doc["macros"]:
        if not 1 <= len(macro["bindings"]) <= 512:
            problems.append(f"macro {macro['name']} has {len(macro['bindings'])} bindings")
    if problems:
        raise KeymapError("; ".join(problems))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keymap", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="write JSON here (default: stdout)")
    ap.add_argument("--conf", type=Path, help="Kconfig fragment to turn into config_parameters")
    ap.add_argument("--keyboard", default="go60")
    ap.add_argument("--keys", type=int, default=KEYS_PER_LAYER)
    ap.add_argument("--locale", default="en-US")
    ap.add_argument("--title", default="")
    ap.add_argument("--creator", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--tag", action="append", default=[], help="repeatable")
    ap.add_argument("--date", type=int, default=None, help="unix timestamp; omitted by default for stable output")
    args = ap.parse_args(argv)

    try:
        doc = convert(
            args.keymap.read_text(),
            conf=args.conf,
            keyboard=args.keyboard,
            keys=args.keys,
            locale=args.locale,
            title=args.title,
            creator=args.creator,
            notes=args.notes,
            tags=args.tag,
            date=args.date,
        )
    except KeymapError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text)
        print(f"wrote {args.output} ({len(doc['layers'])} layers, {len(doc['combos'])} combos)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
