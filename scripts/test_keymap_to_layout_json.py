"""Tests for keymap_to_layout_json.

Run from the repository root:
    python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import keymap_to_layout_json as k2j  # noqa: E402

FIXTURES = HERE / "fixtures"
REPO_KEYMAP = HERE.parent / "config" / "go60.keymap"


def norm(value):
    """The editor's own export stores layer numbers sometimes as 0 and sometimes
    as "0", so comparisons coerce numbers to strings."""
    if isinstance(value, dict):
        return {k: norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [norm(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value



class FactoryDefaultRoundTrip(unittest.TestCase):
    """Converting the stock template keymap must reproduce the Layout Editor's
    own Factory Default export."""

    @classmethod
    def setUpClass(cls):
        cls.doc = k2j.convert((FIXTURES / "factory_default.keymap").read_text())
        cls.expected = json.loads((FIXTURES / "factory_default_layout.json").read_text())

    def test_layer_names(self):
        self.assertEqual(self.doc["layer_names"], self.expected["layer_names"])

    def test_layers_identical(self):
        for name, got, want in zip(self.expected["layer_names"], self.doc["layers"], self.expected["layers"]):
            with self.subTest(layer=name):
                self.assertEqual(norm(got), norm(want))

    def test_editor_builtins_are_not_duplicated(self):
        self.assertEqual(self.doc["holdTaps"], [])
        self.assertEqual(self.doc["macros"], [])
        self.assertEqual(self.doc["combos"], [])
        self.assertEqual(self.doc["custom_defined_behaviors"], "")
        self.assertEqual(self.doc["custom_devicetree"], "")

    def test_right_hand_listener_matches(self):
        got = [l for l in self.doc["inputListeners"] if l["code"] == "&cirque_rh_listener"][0]
        want = [l for l in self.expected["inputListeners"] if l["code"] == "&cirque_rh_listener"][0]
        self.assertEqual(got, want)

    def test_left_hand_listener_shape(self):
        # The template ships older scaler values than the factory export, so
        # compare the structure rather than the numbers.
        got = [l for l in self.doc["inputListeners"] if l["code"] == "&cirque_lh_listener"][0]
        want = [l for l in self.expected["inputListeners"] if l["code"] == "&cirque_lh_listener"][0]
        self.assertEqual([n["code"] for n in got["nodes"]], [n["code"] for n in want["nodes"]])
        self.assertEqual([n["layers"] for n in got["nodes"]], [n["layers"] for n in want["nodes"]])
        self.assertIn("&zip_click_to_right_click_mapper", [p["code"] for p in got["inputProcessors"]])

    def test_top_level_shape_matches_export(self):
        self.assertEqual(set(self.doc), set(self.expected))
        self.assertEqual(self.doc["keyboard"], "go60")
        self.assertEqual(self.doc["firmware_api_version"], "1")
        self.assertEqual(self.doc["version"], 1)


class RepoKeymap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = k2j.convert(REPO_KEYMAP.read_text(), conf=HERE.parent / "config" / "go60.conf")

    def test_sixty_keys_per_layer(self):
        for layer in self.doc["layers"]:
            self.assertEqual(len(layer), 60)

    def test_swedish_combos(self):
        combos = {c["name"]: c for c in self.doc["combos"]}
        self.assertEqual(set(combos), {"combo_aring", "combo_adiaeresis", "combo_odiaeresis"})
        self.assertEqual(combos["combo_aring"]["keyPositions"], [25, 15])
        self.assertEqual(combos["combo_adiaeresis"]["keyPositions"], [19, 25])
        self.assertEqual(combos["combo_odiaeresis"]["keyPositions"], [19, 21])
        for name, key in (("combo_aring", "W"), ("combo_adiaeresis", "Q"), ("combo_odiaeresis", "P")):
            with self.subTest(combo=name):
                c = combos[name]
                self.assertEqual(c["binding"], {"value": "&kp", "params": [{"value": "RA", "params": [{"value": key}]}]})
                self.assertEqual(c["timeoutMs"], 30)
                self.assertEqual(c["layers"], [0])

    def test_shifted_symbols_use_editor_spelling(self):
        symbolnav = self.doc["layers"][self.doc["layer_names"].index("SymbolNav")]
        self.assertEqual(symbolnav[13], {"value": "&kp", "params": [{"value": "LS", "params": [{"value": "N1"}]}]})

    def test_euro_on_symbolnav_five(self):
        symbolnav = self.doc["layers"][self.doc["layer_names"].index("SymbolNav")]
        self.assertEqual(symbolnav[5], {"value": "&kp", "params": [{"value": "RA", "params": [{"value": "N5"}]}]})

    def test_base_layer_unchanged_from_factory(self):
        expected = json.loads((FIXTURES / "factory_default_layout.json").read_text())
        self.assertEqual(norm(self.doc["layers"][0]), norm(expected["layers"][0]))


SNIPPET = """
#include <behaviors.dtsi>
#define LAYER_Base 0
#define LAYER_Nav 1
#define TERM 175

/ {
    combos {
        compatible = "zmk,combos";
        combo_esc {
            key-positions = <1 2>;
            bindings = <&kp ESC>;
            require-prior-idle-ms = <100>;
            slow-release;
        };
    };
    behaviors {
        hrm: hrm {
            compatible = "zmk,behavior-hold-tap";
            #binding-cells = <2>;
            flavor = "balanced";
            tapping-term-ms = <TERM>;
            quick-tap-ms = <150>;
            hold-trigger-on-release;
            hold-trigger-key-positions = <1 2 3>;
            bindings = <&kp>, <&kp>;
        };
        shifty: shifty {
            compatible = "zmk,behavior-mod-morph";
            #binding-cells = <0>;
            bindings = <&kp COMMA>, <&kp SEMI>;
            mods = <(MOD_LSFT|MOD_RSFT)>;
        };
    };
    macros {
        hello: hello {
            compatible = "zmk,behavior-macro";
            #binding-cells = <0>;
            wait-ms = <10>;
            bindings = <&macro_tap &kp H &kp I>;
        };
    };
    keymap {
        compatible = "zmk,keymap";
        layer_Base {
            bindings = <KEYS>;
        };
        layer_Nav {
            bindings = <KEYS>;
        };
    };
};

&cirque_rh_listener {
    input-processors = <&zip_xy_scaler 3 1>, <&zip_xy_transform (INPUT_TRANSFORM_X_INVERT|INPUT_TRANSFORM_Y_INVERT)>;
};

&some_other_node {
    status = "okay";
};
"""


def snippet(keys_per_layer: int = 4) -> str:
    keys = " ".join(["&hrm LCTRL A", "&kp LS(LC(V))", "&to LAYER_Nav", "&shifty"][:keys_per_layer])
    return SNIPPET.replace("KEYS", keys)


class Snippet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = k2j.convert(snippet(), keys=4)

    def test_nested_modifier_params(self):
        self.assertEqual(
            self.doc["layers"][0][1],
            {"value": "&kp", "params": [{"value": "LS", "params": [{"value": "LC", "params": [{"value": "V"}]}]}]},
        )

    def test_define_expansion_in_bindings(self):
        self.assertEqual(self.doc["layers"][0][2], {"value": "&to", "params": [{"value": 1}]})

    def test_hold_tap(self):
        self.assertEqual(
            self.doc["holdTaps"],
            [
                {
                    "name": "hrm",
                    "description": "",
                    "bindings": ["&kp", "&kp"],
                    "tappingTermMs": 175,
                    "flavor": "balanced",
                    "quickTapMs": 150,
                    "holdTriggerOnRelease": True,
                    "holdTriggerKeyPositions": [1, 2, 3],
                }
            ],
        )

    def test_macro(self):
        self.assertEqual(
            self.doc["macros"],
            [
                {
                    "name": "hello",
                    "description": "",
                    "bindings": [
                        {"value": "&macro_tap"},
                        {"value": "&kp", "params": [{"value": "H"}]},
                        {"value": "&kp", "params": [{"value": "I"}]},
                    ],
                    "params": [],
                    "waitMs": 10,
                }
            ],
        )

    def test_combo_options(self):
        self.assertEqual(
            self.doc["combos"],
            [
                {
                    "name": "combo_esc",
                    "description": "",
                    "binding": {"value": "&kp", "params": [{"value": "ESC"}]},
                    "keyPositions": [1, 2],
                    "requirePriorIdleMs": 100,
                    "slowRelease": True,
                    "layers": [-1],
                }
            ],
        )

    def test_mod_morph_goes_to_custom_behaviors(self):
        custom = self.doc["custom_defined_behaviors"]
        self.assertIn('compatible = "zmk,behavior-mod-morph"', custom)
        self.assertNotIn("zmk,behavior-hold-tap", custom)
        self.assertTrue(custom.startswith("/ {\n    behaviors {"))

    def test_listener_flag_params(self):
        listener = self.doc["inputListeners"][0]
        self.assertEqual(listener["code"], "&cirque_rh_listener")
        self.assertEqual(
            listener["inputProcessors"],
            [
                {"code": "&zip_xy_scaler", "params": [3, 1]},
                {"code": "&zip_xy_transform", "params": [["INPUT_TRANSFORM_X_INVERT", "INPUT_TRANSFORM_Y_INVERT"]]},
            ],
        )

    def test_unknown_override_goes_to_custom_devicetree(self):
        self.assertIn("&some_other_node", self.doc["custom_devicetree"])


class Validation(unittest.TestCase):
    def test_wrong_key_count_is_rejected(self):
        with self.assertRaises(k2j.KeymapError):
            k2j.convert(snippet(3), keys=4)

    def test_combo_position_out_of_range(self):
        bad = snippet().replace("key-positions = <1 2>", "key-positions = <1 99>")
        with self.assertRaises(k2j.KeymapError):
            k2j.convert(bad, keys=4)

    def test_cli_writes_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            rc = k2j.main([str(REPO_KEYMAP), "-o", str(out), "--title", "t", "--tag", "qwerty"])
            self.assertEqual(rc, 0)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["title"], "t")
            self.assertEqual(doc["tags"], ["qwerty"])


if __name__ == "__main__":
    unittest.main()
