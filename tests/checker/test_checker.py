"""Тесты самого чекера: проверяющий тоже должен быть проверен.

  python -m unittest discover -s tests
"""

import contextlib
import io
import json
import random
import tempfile
import unittest
from unittest import mock
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
SRC = KIT / "src"
sys.path.insert(0, str(SRC))

import checkers
import ebt_check as ec

SPEC = KIT / "examples" / "basic" / "spec.toml"


def cart(lines, dtype, dval, **override):
    sub = sum(p * q for p, q in lines)
    off = {"none": 0, "percent": sub * dval // 100, "fixed": min(dval, sub)}[dtype]
    w = {"lines": [list(x) for x in lines], "discount": {"type": dtype, "value": dval},
         "subtotal": sub, "off": off, "result": sub - off}
    w.update(override)
    return w


def rec(seq, inv, req, ok, data, scope="t"):
    return {"seq": seq, "scope": scope, "req": req, "inv": inv, "ok": ok, "data": data}


class CartChecker(unittest.TestCase):
    inv = {"checker": "cart_total"}

    def test_correct_percent_with_rounding(self):
        v = checkers.cart_total(cart([(333, 3)], "percent", 15), self.inv)
        self.assertTrue(v.ok)
        self.assertIn("percent_rounding", v.parts)

    def test_rounding_up_is_caught(self):
        v = checkers.cart_total(cart([(333, 3)], "percent", 15, off=150, result=849), self.inv)
        self.assertFalse(v.ok)
        self.assertIn("149", v.reason)

    def test_fixed_capped_by_subtotal(self):
        v = checkers.cart_total(cart([(100, 1)], "fixed", 500), self.inv)
        self.assertTrue(v.ok)
        self.assertEqual(v.parts, {"fixed", "fixed_exceeds_subtotal"})

    def test_subtotal_recomputed_from_lines(self):
        v = checkers.cart_total(cart([(100, 2)], "none", 0, subtotal=300, result=300), self.inv)
        self.assertFalse(v.ok)

    def test_bool_is_not_int(self):
        with self.assertRaises(checkers.WitnessError):
            checkers.cart_total(cart([(100, 1)], "none", 0, off=False), self.inv)


class TransitionChecker(unittest.TestCase):
    inv = {"checker": "transition", "transitions": [["a", "go", "b"], ["b", "back", "a"]]}

    def test_allowed(self):
        self.assertTrue(checkers.transition({"from": "a", "event": "go", "to": "b"}, self.inv).ok)

    def test_forbidden_lists_alternatives(self):
        v = checkers.transition({"from": "a", "event": "back", "to": "b"}, self.inv)
        self.assertFalse(v.ok)
        self.assertIn("go→b", v.reason)


class SyncChecker(unittest.TestCase):
    inv = {"checker": "sync_merge"}

    def test_tie_goes_to_server(self):
        w = {"local": [["x", 2, False]], "remote": [["x", 2, True]], "out": []}
        v = checkers.sync_merge(w, self.inv)
        self.assertTrue(v.ok)
        self.assertEqual(v.parts, {"conflict_tie", "tombstone"})

    def test_duplicate_in_output(self):
        w = {"local": [["x", 1, False]], "remote": [], "out": [["x", 1], ["x", 1]]}
        self.assertFalse(checkers.sync_merge(w, self.inv).ok)

    def test_wrong_types_are_malformed(self):
        for w in ({"local": [["x", 1, "false"]], "remote": [], "out": []},
                  {"local": [["x", 1, False]], "remote": [], "out": [["x", True]]},
                  {"local": [["x", 1, False]], "remote": [], "out": [["x", 1.0]]}):
            with self.assertRaises(checkers.WitnessError, msg=w):
                checkers.sync_merge(w, self.inv)


class Classification(unittest.TestCase):
    def setUp(self):
        self.spec, self.sha = ec.load_spec(SPEC)

    def report(self, records, **kw):
        numbered = list(enumerate(records, start=1))
        return ec.build_report(self.spec, self.sha, numbered, [], kw.get("baseline"), 50, kw.get("self_test", False))

    def kinds(self, r):
        return sorted(f.kind for f in r.findings)

    def test_false_proof(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True,
                             cart([(333, 3)], "percent", 15, off=150, result=849))])
        self.assertEqual(self.kinds(r), [ec.FALSE_PROOF])

    def test_confirmed_and_disagree(self):
        bad = cart([(333, 3)], "percent", 15, off=150, result=849)
        good = cart([(333, 3)], "percent", 15)
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", False, bad),
                         rec(2, "INV-CART-3", "REQ-CART-1", False, good)])
        self.assertEqual(self.kinds(r), [ec.CHECKER_DISAGREES, ec.CONFIRMED_VIOLATION])

    def test_ok_field_is_ignored_for_verdict(self):
        # Свидетельство корректно — поле ok не может «сломать» вердикт чекера в пользу кода.
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))])
        self.assertEqual(r.findings, [])

    def test_incomplete_unknown_req_mismatch(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, {"result": 1}),
                         rec(2, "INV-NOPE", "REQ-CART-1", True, {}),
                         rec(3, "INV-CART-3", "REQ-SYNC-1", True, cart([(1, 1)], "none", 0))])
        self.assertEqual(self.kinds(r), [ec.REQ_MISMATCH, ec.UNKNOWN_INV, ec.WITNESS_INCOMPLETE])

    def test_bool_seq_is_a_gap(self):
        w = {"from": "cart", "event": "confirm", "to": "confirmed"}
        r = self.report([{**rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w), "seq": True}])
        self.assertEqual(self.kinds(r), [ec.LOG_GAP])

    def test_gap_at_file_boundary(self):
        w = {"from": "cart", "event": "confirm", "to": "confirmed"}
        recs = [rec(s, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w) for s in (1, 2, 3, 4)]
        numbered = list(enumerate(recs, start=1))
        # Второй файл начинается с seq=4: его начало срезано, хоть склейка и выглядит непрерывной.
        r = ec.build_report(self.spec, self.sha, numbered, [], None, 50, False, file_starts={1, 4})
        self.assertEqual(self.kinds(r), [ec.LOG_GAP])
        r = ec.build_report(self.spec, self.sha, numbered, [], None, 50, False, file_starts={1})
        self.assertEqual(self.kinds(r), [])

    def test_log_gap(self):
        w = {"from": "cart", "event": "confirm", "to": "confirmed"}
        r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w),
                         rec(3, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w),
                         rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w, scope="u")])
        self.assertEqual(self.kinds(r), [ec.LOG_GAP])

    def test_coverage(self):
        w = {"from": "cart", "event": "confirm", "to": "confirmed"}
        r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)])
        self.assertIn("REQ-PROFILE-1", r.req_without_inv)
        self.assertIn("INV-CART-3", r.inv_never_fired)
        self.assertEqual(len(r.uncovered_partitions["SM-CHECKOUT"]), 4)

    def test_baseline_diff(self):
        base = [(1, rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(333, 3)], "percent", 15)))]
        cur = [rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(333, 3)], "percent", 15, off=150, result=849))]
        r = self.report(cur, baseline=base)
        self.assertEqual(r.baseline["changed_total"], 1)
        self.assertIn("off: 149 → 150", r.baseline["changed"][0]["diff"])

    def test_vanished_scenario_is_a_gap(self):
        w = cart([(333, 3)], "percent", 15)
        base = [(1, rec(1, "INV-CART-3", "REQ-CART-1", True, w)),
                (2, rec(1, "INV-CART-3", "REQ-CART-1", True, w, scope="u"))]
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, w)], baseline=base)
        self.assertEqual(r.baseline["vanished"], ["u / INV-CART-3"])
        # Остальное покрытие полное — красным отчёт делает только исчезнувший сценарий.
        full = ec.Report(records=1, baseline=r.baseline)
        self.assertTrue(full.has_coverage_gaps)
        self.assertFalse(ec.Report(records=1, baseline={**r.baseline, "vanished": []}).has_coverage_gaps)
        # Вне --scope исчезновение чужого инварианта не валит (D13), в scope — валит.
        self.assertFalse(ec.Report(records=1, baseline=r.baseline, coverage_scope=["SM-CHECKOUT"]).has_coverage_gaps)
        self.assertTrue(ec.Report(records=1, baseline=r.baseline, coverage_scope=["INV-CART-3"]).has_coverage_gaps)

    def test_self_test_finds_ignored_field(self):
        original = checkers.CHECKERS["transition"]

        def lazy(w, inv):  # «чекер», который не смотрит на поле to
            match = [t[2] for t in inv["transitions"] if t[0] == w["from"] and t[1] == w["event"]]
            return original({**w, "to": match[0] if match else w["to"]}, inv)

        ec.CHECKERS["transition"] = lazy
        try:
            w = {"from": "cart", "event": "confirm", "to": "confirmed"}
            r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)], self_test=True)
            self.assertEqual(r.self_test["SM-CHECKOUT"]["weak_fields"], ["to"])
            # Слабый чекер валит проверку, даже если остальное в порядке (D15)…
            self.assertEqual(r.weak_required, {"SM-CHECKOUT": ["to"]})
            self.assertTrue(r.failed(allow_uncovered=True))
            # …если владелец не пометил поле как не влияющее на вердикт.
            self.spec["inv"]["SM-CHECKOUT"]["not_in_verdict"] = ["to"]
            r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)], self_test=True)
            self.assertEqual(r.weak_required, {})
        finally:
            ec.CHECKERS["transition"] = original

    def test_self_test_finds_checker_reading_only_first_list_element(self):
        original = checkers.CHECKERS["cart_total"]
        w = cart([(333, 3), (100, 2)], "percent", 15)  # помощник cart() из того же файла

        def first_only(m, inv):  # хвост списка всегда берётся из неиспорченного образца
            return original({**m, "lines": m["lines"][:1] + w["lines"][1:]}, inv)

        ec.CHECKERS["cart_total"] = first_only
        try:
            r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, w)], self_test=True)
            weak = r.self_test["INV-CART-3"]["weak_paths"]
            self.assertTrue(weak and all(p.startswith("lines[1]") for p in weak), weak)
            self.assertEqual(r.self_test["INV-CART-3"]["weak_fields"], ["lines"])
            self.assertEqual(r.weak_required["INV-CART-3"], weak)
            self.spec["inv"]["INV-CART-3"]["not_in_verdict"] = ["lines[*]"]
            r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, w)], self_test=True)
            self.assertEqual(r.weak_required, {})
        finally:
            ec.CHECKERS["cart_total"] = original

    def test_self_test_reports_shape_only_rejection_without_failing(self):
        original = checkers.CHECKERS["transition"]
        states = {"cart", "confirmed"}

        def shape_only(w, inv):  # проверяет, что to — известное состояние, но не сверяет переход
            if w["to"] not in states:
                raise checkers.WitnessError("to: неизвестное состояние")
            match = [t[2] for t in inv["transitions"] if t[0] == w["from"] and t[1] == w["event"]]
            return original({**w, "to": match[0] if match else w["to"]}, inv)

        ec.CHECKERS["transition"] = shape_only
        try:
            w = {"from": "cart", "event": "confirm", "to": "confirmed"}
            r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)], self_test=True)
            s = r.self_test["SM-CHECKOUT"]
            self.assertEqual(s["shape_only_paths"], ["to"])
            self.assertEqual(s["fields"]["to"]["rejected"], s["fields"]["to"]["killed"])
            self.assertEqual(r.weak_required, {})
        finally:
            ec.CHECKERS["transition"] = original

    def test_cross_sample_substitution_kills_by_logic(self):
        transitions = self.spec["inv"]["SM-CHECKOUT"]["transitions"]
        first = {"from": transitions[0][0], "event": transitions[0][1], "to": transitions[0][2]}
        second = {"from": transitions[1][0], "event": transitions[1][1], "to": transitions[1][2]}
        r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, first),
                         rec(2, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, second)], self_test=True)
        s = r.self_test["SM-CHECKOUT"]
        self.assertGreater(s["fields"]["to"]["killed"], s["fields"]["to"]["rejected"])
        self.assertNotIn("to", s["shape_only_paths"])

    def test_substitution_only_path_is_not_weak(self):
        # fixed:0 и none:0 оба корректны; подстановка одного вместо другого не меняет
        # вердикт. У пути discount есть только подстановки, поэтому слабым он не считается.
        fixed = cart([(100, 1)], "fixed", 0)
        none = cart([(100, 1)], "none", 0)
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, fixed),
                         rec(2, "INV-CART-3", "REQ-CART-1", True, none)], self_test=True)
        s = r.self_test["INV-CART-3"]
        self.assertEqual(s["weak_paths"], [])
        self.assertEqual(r.weak_required, {})
        self.assertEqual(s["fields"]["discount"]["substituted"], 2)
        self.assertGreater(s["fields"]["discount"]["tried"], s["fields"]["discount"]["substituted"])

    def test_self_test_replaces_strings(self):
        # Чекер законно читает только начало строки (как amount_unit — число и единицу
        # в «1 day available»): порча суффиксом его не ловила, заменой — ловит (D16).
        original = checkers.CHECKERS["transition"]

        def prefix(w, inv):
            match = [t[2] for t in inv["transitions"] if t[0] == w["from"] and t[1] == w["event"]]
            to = match[0] if match and w["to"].startswith(match[0]) else w["to"]
            return original({**w, "to": to}, inv)

        ec.CHECKERS["transition"] = prefix
        try:
            w = {"from": "cart", "event": "confirm", "to": "confirmed"}
            r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)], self_test=True)
            self.assertEqual(r.self_test["SM-CHECKOUT"]["weak_fields"], [])
        finally:
            ec.CHECKERS["transition"] = original

    def test_mutants_cover_every_list_element_within_cap(self):
        self.assertEqual(ec._mutants(5), [("", 6), ("", 4)])
        self.assertEqual(ec._mutants(True), [("", False)])
        self.assertEqual(ec._mutants("2 employees"), [("", "3 employees")])
        self.assertEqual(ec._mutants(None), [])
        self.assertEqual(ec._mutants({}), [])
        self.assertEqual(ec._mutants([]), [("", [0])])
        paths = {p for p, _ in ec._mutants([{"q": 1}, {"q": 2}])}
        self.assertEqual(paths, {"[0]", "[0].q", "[1]", "[1].q"})
        self.assertFalse(any(p.startswith("[8]") for p, _ in ec._mutants(list(range(20)))))

    def test_string_mutation_changes_a_digit_or_the_whole_value(self):
        # Текст с числом портится в числе: «2 employees» → «3 employees» ловит чекер,
        # для которого слово вместо числа законно (инвариант локализации проекта).
        self.assertEqual(ec._mutate("2 employees"), (True, "3 employees"))
        self.assertEqual(ec._mutate("9 days"), (True, "0 days"))
        self.assertEqual(ec._mutate("confirmed"), (True, "_mut"))
        self.assertEqual(ec._mutate("_mut"), (True, "_mut2"))


class CheckerCrash(unittest.TestCase):
    def test_crash_is_a_finding_not_a_traceback(self):
        spec, sha = ec.load_spec(SPEC)
        original = checkers.CHECKERS["cart_total"]
        ec.CHECKERS["cart_total"] = lambda w, inv: 1 / 0
        try:
            r = ec.build_report(spec, sha, [(1, rec(1, "INV-CART-3", "REQ-CART-1", True,
                                                     cart([(1, 1)], "none", 0)))], [], None, 50, True)
            self.assertEqual([f.kind for f in r.findings], [ec.CHECKER_ERROR])
        finally:
            ec.CHECKERS["cart_total"] = original


class Known(unittest.TestCase):
    bad = cart([(333, 3)], "percent", 15, off=150, result=849)
    other_bad = cart([(100, 1)], "percent", 15, off=16, result=84)

    def setUp(self):
        self.spec, self.sha = ec.load_spec(SPEC)

    def report(self, records, known):
        numbered = list(enumerate(records, start=1))
        return ec.build_report(self.spec, self.sha, numbered, [], None, 50, False, known)

    def entry(self, **kw):
        e = {"inv": "INV-CART-3", "kind": ec.FALSE_PROOF, "match": {"off": 150},
             "reason": "старый дефект", "accepted": "владелец"}
        e.update(kw)
        return e

    def test_known_does_not_fail_new_does(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, self.bad),
                         rec(2, "INV-CART-3", "REQ-CART-1", True, self.other_bad)], [self.entry()])
        self.assertEqual([f.kind for f in r.known_findings], [ec.FALSE_PROOF])
        self.assertEqual([f.witness["off"] for f in r.findings], [16])
        self.assertTrue(r.has_critical)

    def test_only_known_is_green(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, self.bad)], [self.entry()])
        self.assertFalse(r.has_critical)
        self.assertIn("Известные находки", ec.render_md(r, self.spec, 50, True))

    def test_kind_and_type_must_match(self):
        recs = [rec(1, "INV-CART-3", "REQ-CART-1", True, self.bad)]
        self.assertTrue(self.report(recs, [self.entry(kind=ec.CONFIRMED_VIOLATION)]).has_critical)
        self.assertTrue(self.report(recs, [self.entry(match={"off": 150.0})]).has_critical)

    def test_known_record_gives_no_coverage(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, self.bad)], [self.entry()])
        self.assertFalse(r.has_critical)
        self.assertIn("INV-CART-3", r.inv_never_fired)   # известное нарушение — не доказательство

    def test_unused_entry_is_reported(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))],
                        [self.entry()])
        self.assertEqual(len(r.known_unused), 1)
        self.assertIn("можно удалить", ec.render_md(r, self.spec, 50, True))

    def test_cli_known_and_bad_known(self):
        with tempfile.TemporaryDirectory() as d:
            ev, kn = Path(d) / "e.jsonl", Path(d) / "known.toml"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True, self.bad)) + "\n")
            argv = ["--spec", str(SPEC), "--evidence", str(ev), "--md", str(Path(d) / "r.md"),
                    "--allow-uncovered"]
            self.assertEqual(ec.main(argv), 1)
            good = '[[known]]\ninv = "INV-CART-3"\nkind = "FALSE_PROOF"\nreason = "старый дефект"\naccepted = "владелец"\n'
            kn.write_text(good + 'match = { off = 150 }\n')
            self.assertEqual(ec.main(argv + ["--known", str(kn)]), 0)
            # Покрытие известная находка не даёт: со --scope этого инварианта — красный.
            self.assertEqual(ec.main(argv[:-1] + ["--known", str(kn), "--scope", "INV-CART-3"]), 1)
            kn.write_text(good.replace('kind = "FALSE_PROOF"\n', "") + 'match = { off = 150 }\n')
            self.assertEqual(ec.main(argv + ["--known", str(kn)]), 2)  # без kind
            kn.write_text(good + 'match = { case = "legacy" }\n')
            self.assertEqual(ec.main(argv + ["--known", str(kn)]), 2)  # ключ не из witness
            kn.write_text('[[known]]\ninv = "INV-CART-3"\nkind = "FALSE_PROOF"\nmatch = {}\nreason = "x"\naccepted = "y"\n')
            self.assertEqual(ec.main(argv + ["--known", str(kn)]), 2)  # пустой match прятал бы всё


class Scope(unittest.TestCase):
    def setUp(self):
        self.spec, self.sha = ec.load_spec(SPEC)

    def report(self, records, scope, known=None):
        numbered = list(enumerate(records, start=1))
        return ec.build_report(self.spec, self.sha, numbered, [], None, 50, False, known, scope)

    def test_coverage_only_for_task_invariants(self):
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))], ["INV-CART-3"])
        self.assertEqual(r.inv_never_fired, [])                   # SM-CHECKOUT, INV-SYNC-1 не требуются
        self.assertEqual(list(r.uncovered_partitions), ["INV-CART-3"])
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))], ["SM-CHECKOUT"])
        self.assertEqual(r.inv_never_fired, ["SM-CHECKOUT"])      # инвариант задачи не сработал

    def test_violation_outside_scope_still_fails(self):
        bad = {"local": [["e", 5, False]], "remote": [["e", 5, True]], "out": [["e", 5]]}
        r = self.report([rec(1, "INV-SYNC-1", "REQ-SYNC-1", True, bad)], ["INV-CART-3"])
        self.assertTrue(r.has_critical)

    def test_known_unused_only_for_fired(self):
        entry = {"inv": "INV-SYNC-1", "kind": ec.FALSE_PROOF, "match": {"out": []}, "reason": "x", "accepted": "y"}
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))], ["INV-CART-3"], [entry])
        self.assertEqual(r.known_unused, [])

    def test_cli_unknown_scope_is_launch_error(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "e.jsonl"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))) + "\n")
            argv = ["--spec", str(SPEC), "--evidence", str(ev), "--md", str(Path(d) / "r.md")]
            self.assertEqual(ec.main(argv + ["--scope", "INV-NOPE"]), 2)
            self.assertEqual(ec.main(argv + ["--scope", "INV-CART-3"]), 1)   # классы входов CART не пройдены
            self.assertEqual(ec.main(argv + ["--scope", "INV-CART-3", "--allow-uncovered"]), 0)


class ProjectCheckers(unittest.TestCase):
    PROJECT = ('from checkers import Verdict\n'
               'def even(w, inv):\n'
               '    ok = w["n"] % 2 == 0\n'
               '    return Verdict(ok, "" if ok else f"n={w[\'n\']} нечётное", {"zero"} if w["n"] == 0 else {"other"})\n'
               'CHECKERS = {"even": even}\n'
               'DERIVED_PARTITIONS = {"even": lambda inv: ["zero", "other"]}\n')
    SPEC = ('[req.REQ-N]\ntext = "n чётное"\n'
            '[inv.INV-N]\nreq = "REQ-N"\nchecker = "even"\nwitness = ["n"]\n')

    def tearDown(self):
        ec.CHECKERS.pop("even", None)
        ec.DERIVED_PARTITIONS.pop("even", None)

    def run_cli(self, d, project, values):
        # Каждый вызов — отдельный запуск: регистрация прошлого вызова не должна дать коллизию имён.
        ec.CHECKERS.pop("even", None)
        ec.DERIVED_PARTITIONS.pop("even", None)
        d = Path(d)
        (d / "checks.py").write_text(project)
        (d / "spec.toml").write_text(self.SPEC)
        (d / "e.jsonl").write_text("".join(json.dumps(rec(i, "INV-N", "REQ-N", True, {"n": n})) + "\n"
                                           for i, n in enumerate(values, start=1)))
        return ec.main(["--spec", str(d / "spec.toml"), "--evidence", str(d / "e.jsonl"),
                        "--checkers", str(d / "checks.py"), "--md", str(d / "r.md")])

    def test_project_checker_proves_and_catches(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli(d, self.PROJECT, [0, 2]), 0)
            self.assertEqual(self.run_cli(d, self.PROJECT, [0, 3]), 1)   # нечётное — ложное доказательство
            self.assertEqual(self.run_cli(d, self.PROJECT, [2]), 1)      # класс zero не пройден

    def test_project_checker_name_collision_is_error(self):
        original = ec.CHECKERS["cart_total"]
        try:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "c.py").write_text("CHECKERS = {'cart_total': lambda w, inv: None}\n")
                with self.assertRaisesRegex(ValueError, "cart_total"):
                    ec.load_checkers(Path(d) / "c.py")
                self.assertIs(ec.CHECKERS["cart_total"], original)
                self.assertEqual(self.run_cli(d, "CHECKERS = {'cart_total': lambda w, inv: None}\n", [0]), 2)
                self.assertIs(ec.CHECKERS["cart_total"], original)
        finally:
            ec.CHECKERS["cart_total"] = original

    def test_project_derived_partitions_collision_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "c.py").write_text("CHECKERS = {}\nDERIVED_PARTITIONS = {'transition': lambda inv: []}\n")
            with self.assertRaisesRegex(ValueError, "transition"):
                ec.load_checkers(Path(d) / "c.py")

    def test_bad_checkers_file_is_launch_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli(d, "x = 1\n", [0]), 2)              # нет CHECKERS
            self.assertEqual(self.run_cli(d, "import no_such_module\n", [0]), 2)


class Cli(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "e.jsonl"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))) + "\n")
            argv = ["--spec", str(SPEC), "--evidence", str(ev), "--md", str(Path(d) / "r.md")]
            self.assertEqual(ec.main(argv), 1)                         # дыры в покрытии
            self.assertEqual(ec.main(argv + ["--allow-uncovered"]), 0)
            ev.write_text("{not json\n")
            self.assertEqual(ec.main(argv + ["--allow-uncovered"]), 1)  # битая строка
            self.assertEqual(ec.main(["--spec", "/nope.toml", "--evidence", str(ev)]), 2)

    def test_unregistered_checker_is_launch_error_even_without_records(self):
        """Иначе инвариант вне --scope молча проходил бы: NO_CHECKER возникает только на записи."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            spec = d / "spec.toml"
            spec.write_text(SPEC.read_text(encoding="utf-8") + (
                '\n[inv.INV-OUT]\nreq = "REQ-CART-1"\nchecker = "missing_rule"\n'
                'witness = ["a"]\n'), encoding="utf-8")
            ev = d / "e.jsonl"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True,
                                         cart([(1, 1)], "none", 0))) + "\n")
            argv = ["--spec", str(spec), "--evidence", str(ev), "--md", str(d / "r.md"),
                    "--scope", "INV-CART-3"]
            self.assertEqual(ec.main(argv), 2)

    def test_non_string_ids_are_malformed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "e.jsonl"
            ev.write_text(json.dumps({**rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0)),
                                      "inv": ["INV-CART-3"]}) + "\n")
            md = Path(d) / "r.md"
            self.assertEqual(ec.main(["--spec", str(SPEC), "--evidence", str(ev), "--md", str(md)]), 1)
            self.assertIn("должен быть строкой", md.read_text())

    def test_deeply_nested_line_is_malformed(self):
        # На Python 3.11 json.loads бросает RecursionError; это битая строка, а не падение.
        with tempfile.TemporaryDirectory() as d:
            ev, md, out = Path(d) / "e.jsonl", Path(d) / "r.md", Path(d) / "r.json"
            ev.write_text("[" * 5000 + "]" * 5000 + "\n")
            self.assertEqual(ec.main(["--spec", str(SPEC), "--evidence", str(ev),
                                      "--md", str(md), "--json", str(out)]), 1)
            report = json.loads(out.read_text())
            self.assertIn(ec.MALFORMED_LINE, [f["kind"] for f in report["findings"]])

    def test_several_evidence_files(self):
        with tempfile.TemporaryDirectory() as d:
            w = cart([(1, 1)], "none", 0)
            a, b = Path(d) / "a.jsonl", Path(d) / "b.jsonl"
            a.write_text("\n".join(json.dumps(rec(s, "INV-CART-3", "REQ-CART-1", True, w)) for s in (1, 2, 3)))
            b.write_text(json.dumps(rec(4, "INV-CART-3", "REQ-CART-1", True, w)) + "\n")
            out = Path(d) / "r.json"
            ec.main(["--spec", str(SPEC), "--evidence", str(a), str(b), "--json", str(out), "--md", str(Path(d) / "r.md")])
            gaps = [f for f in json.loads(out.read_text())["findings"] if f["kind"] == ec.LOG_GAP]
            self.assertEqual([f["line"] for f in gaps], [4])

    def test_empty_log_is_never_proof(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Path(d) / "e.jsonl"
            ev.write_text("")
            md = Path(d) / "r.md"
            argv = ["--spec", str(SPEC), "--evidence", str(ev), "--md", str(md), "--allow-uncovered"]
            self.assertEqual(ec.main(argv), 1)
            self.assertIn("нет ни одной записи", md.read_text())

    def test_spec_without_invariants_is_launch_error(self):
        with tempfile.TemporaryDirectory() as d:
            spec, ev = Path(d) / "s.toml", Path(d) / "e.jsonl"
            spec.write_text("")
            ev.write_text("")
            self.assertEqual(ec.main(["--spec", str(spec), "--evidence", str(ev)]), 2)

    def test_broken_baseline_is_launch_error(self):
        with tempfile.TemporaryDirectory() as d:
            ev, base = Path(d) / "e.jsonl", Path(d) / "b.jsonl"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True, cart([(1, 1)], "none", 0))) + "\n")
            base.write_text("{not json\n")
            argv = ["--spec", str(SPEC), "--evidence", str(ev), "--baseline", str(base), "--md", str(Path(d) / "r.md")]
            self.assertEqual(ec.main(argv), 2)



class FormatFixture(unittest.TestCase):
    """fixtures/record.jsonl — запись в формате, который пишут SDK (ebt.ts, Ebt.java): чекер её принимает."""

    def test_format_fixture_is_valid_record(self):
        records, bad = ec.load_jsonl(KIT / "src/witnessbox/checker/fixtures/record.jsonl")
        self.assertEqual(bad, [])
        self.assertEqual(len(records), 1)
        spec, _ = ec.load_spec(SPEC)
        n, rec = records[0]
        self.assertIsNone(ec.check_record(n, rec, spec, {}, set()))

class Packaging(unittest.TestCase):
    def test_checker_version_remains_public(self):
        # Версия поставки теперь независима от версии контракта CLI-чекера.
        import subprocess
        p = subprocess.run([sys.executable, "-m", "witnessbox.checker.ebt_check", "--version"],
                           capture_output=True, text=True,
                           env={**__import__("os").environ, "PYTHONPATH": str(SRC)})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), f"ebt-check {ec.__version__}")




class InputBoundaries(unittest.TestCase):
    SPEC = ('[req.R]\ntext = "rule"\n'
            '[inv.I]\nreq = "R"\nchecker = "cart_total"\nwitness = ["n"]\n')
    KNOWN = ('[[known]]\ninv = "I"\nkind = "FALSE_PROOF"\n'
             'reason = "accepted defect"\naccepted = "owner"\nmatch = {n = 1}\n')

    def assert_launch_error(self, spec=None, known=None, project=None, evidence=b""):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "s.toml").write_text(self.SPEC if spec is None else spec)
            (d / "e.jsonl").write_bytes(evidence)
            args = ["--spec", str(d / "s.toml"), "--evidence", str(d / "e.jsonl"),
                    "--md", str(d / "r.md")]
            if known is not None:
                (d / "known.toml").write_text(known)
                args += ["--known", str(d / "known.toml")]
            if project is not None:
                (d / "checks.py").write_text(project)
                args += ["--checkers", str(d / "checks.py")]
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(ec.main(args), 2)
            self.assertIn("ebt_check:", errors.getvalue())
            self.assertFalse((d / "r.md").exists())

    def test_spec_sections_must_be_tables(self):
        for section in ("req", "inv", "meta"):
            with self.subTest(section=section):
                self.assert_launch_error(spec=f'{section} = "bad"\n')

    def test_requirement_table_and_optional_text_types(self):
        for spec in ('req = {R = 1}\n[inv.I]\nreq = "R"\nchecker = "x"\nwitness = []\n',
                     self.SPEC.replace('text = "rule"', 'text = ["rule"]')):
            with self.subTest(spec=spec):
                self.assert_launch_error(spec=spec)

    def test_invariant_structure_and_field_types(self):
        changes = [('req = "R"', 'req = ["R"]'),
                   ('checker = "cart_total"', 'checker = ["cart_total"]'),
                   ('witness = ["n"]', 'witness = "n"'),
                   ('witness = ["n"]', 'witness = [1]')]
        for old, new in changes:
            with self.subTest(new=new):
                self.assert_launch_error(spec=self.SPEC.replace(old, new))
        self.assert_launch_error(spec='inv = {I = 1}\n[req.R]\ntext = "rule"\n')

    def test_coverage_and_transition_structure(self):
        for field in ('partitions = "n"', 'partitions = [1]',
                      'not_in_verdict = "n"'):
            with self.subTest(field=field):
                self.assert_launch_error(spec=self.SPEC + field + "\n")

        for transitions in ('[["a", "go"]]', '[1]', '[["a", "go", 1]]'):
            with self.subTest(transitions=transitions):
                self.assert_launch_error(spec=self.SPEC.replace('cart_total', 'transition')
                                         + f'transitions = {transitions}\n')

    def test_previous_optional_metadata_and_project_parameters_remain_valid(self):
        spec = ('[meta]\nversion = 7\n[req.R]\n'
                '[inv.I]\nreq = "R"\nchecker = "boundary_check"\n'
                'witness = ["n", "n"]\npartitions = ["one", "one"]\n'
                'not_in_verdict = ["unused", "unused"]\ntransitions = "project-specific"\n')
        project = ('from witnessbox.api import Verdict\n'
                   'CHECKERS = {"boundary_check": lambda w, inv: Verdict(True, parts={"one"})}\n')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "spec.toml").write_text(spec)
            (d / "checks.py").write_text(project)
            (d / "e.jsonl").write_text(json.dumps(rec(1, "I", "R", True, {"n": 2})) + "\n")
            try:
                self.assertEqual(ec.main(["--spec", str(d / "spec.toml"), "--checkers", str(d / "checks.py"),
                                          "--evidence", str(d / "e.jsonl"), "--md", str(d / "r.md")]), 0)
                self.assertIn("Спецификация `7`", (d / "r.md").read_text())
            finally:
                ec.CHECKERS.pop("boundary_check", None)

    def test_known_needs_list_of_tables(self):
        for known in ('known = "bad"', 'known = [1]', 'known = {inv = "I"}'):
            with self.subTest(known=known):
                self.assert_launch_error(known=known)

    def test_known_fields_have_checked_types(self):
        for field, value in (("inv", '["I"]'), ("kind", 'true'),
                             ("reason", '["accepted defect"]'), ("accepted", '1')):
            with self.subTest(field=field):
                old = next(line for line in self.KNOWN.splitlines() if line.startswith(field + " ="))
                self.assert_launch_error(known=self.KNOWN.replace(old, f"{field} = {value}"))
        self.assert_launch_error(known=self.KNOWN.replace('match = {n = 1}', 'match = "n"'))

    def test_known_match_must_be_json_compatible(self):
        self.assert_launch_error(known=self.KNOWN.replace('match = {n = 1}',
                                                        'match = {n = 2026-10-31}'))

    def test_malformed_toml_and_utf8_are_launch_errors(self):
        self.assert_launch_error(spec='[inv.')
        self.assert_launch_error(known='[[known]')
        self.assert_launch_error(evidence=b"\xff")

    def test_extension_registries_are_validated_before_update(self):
        projects = ('CHECKERS = {"boundary_check": lambda w, inv: None}\nDERIVED_PARTITIONS = []',
                    'CHECKERS = {"boundary_check": None}',
                    'CHECKERS = {1: lambda w, inv: None}',
                    'CHECKERS = {"boundary_check": lambda w, inv: None}\n'
                    'DERIVED_PARTITIONS = {"boundary_check": None}',
                    'CHECKERS = {}\nDERIVED_PARTITIONS = {"boundary_missing": lambda inv: []}')
        for project in projects:
            with self.subTest(project=project):
                before_checks, before_parts = dict(ec.CHECKERS), dict(ec.DERIVED_PARTITIONS)
                self.assert_launch_error(project=project)
                self.assertEqual(ec.CHECKERS, before_checks)
                self.assertEqual(ec.DERIVED_PARTITIONS, before_parts)

    def test_derived_partitions_return_and_exception_are_launch_errors(self):
        for body in ('return "one"', 'return [1]', 'raise RuntimeError("broken coverage")'):
            with self.subTest(body=body):
                project = ('from checkers import Verdict\n'
                           'def derive(inv):\n    ' + body + '\n'
                           'CHECKERS = {"boundary_check": lambda w, inv: Verdict(True)}\n'
                           'DERIVED_PARTITIONS = {"boundary_check": derive}\n')
                try:
                    self.assert_launch_error(project=project,
                                             spec=self.SPEC.replace('cart_total', 'boundary_check'),
                                             evidence=(json.dumps(rec(1, "I", "R", True, {"n": 2})) + "\n").encode())
                finally:
                    ec.CHECKERS.pop("boundary_check", None)
                    ec.DERIVED_PARTITIONS.pop("boundary_check", None)

    def test_extension_system_exit_at_import_is_a_launch_error(self):
        self.assert_launch_error(project="raise SystemExit(0)\n")

    def test_extension_system_exit_at_checker_call_is_a_checker_error(self):
        spec = {"req": {"R": {"text": "rule"}},
                "inv": {"I": {"req": "R", "checker": "boundary_exit", "witness": ["n"]}}}
        record = rec(1, "I", "R", True, {"n": 1})
        try:
            ec.CHECKERS["boundary_exit"] = lambda w, inv: (_ for _ in ()).throw(SystemExit(0))
            report = ec.build_report(spec, "sha", [(1, record)], [], None, 50, True)
            self.assertEqual([finding.kind for finding in report.findings], [ec.CHECKER_ERROR])
            self.assertIn("SystemExit: 0", report.findings[0].reason)
            self.assertTrue(report.failed(True))
        finally:
            ec.CHECKERS.pop("boundary_exit", None)

    def test_extension_system_exit_at_derived_callback_is_a_launch_error(self):
        project = ('from checkers import Verdict\n'
                   'def derive(inv):\n    raise SystemExit(0)\n'
                   'CHECKERS = {"boundary_check": lambda w, inv: Verdict(True, parts={"one"})}\n'
                   'DERIVED_PARTITIONS = {"boundary_check": derive}\n')
        try:
            self.assert_launch_error(project=project,
                spec=self.SPEC.replace('cart_total', 'boundary_check'),
                evidence=(json.dumps(rec(1, "I", "R", True, {"n": 2})) + "\n").encode())
        finally:
            ec.CHECKERS.pop("boundary_check", None)
            ec.DERIVED_PARTITIONS.pop("boundary_check", None)

    def test_keyboard_interrupt_propagates_from_extension_boundaries(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "checks.py"
            path.write_text("raise KeyboardInterrupt()\n")
            with self.assertRaises(KeyboardInterrupt):
                ec.load_checkers(path)
        spec = {"req": {"R": {}},
                "inv": {"I": {"req": "R", "checker": "boundary_interrupt", "witness": ["n"]}}}
        record = rec(1, "I", "R", True, {"n": 1})
        try:
            ec.CHECKERS["boundary_interrupt"] = lambda w, inv: (_ for _ in ()).throw(KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                ec.check_record(1, record, spec, {}, set())
            ec.DERIVED_PARTITIONS["boundary_interrupt"] = lambda inv: (_ for _ in ()).throw(KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                ec.declared_partitions(spec["inv"]["I"])
        finally:
            ec.CHECKERS.pop("boundary_interrupt", None)
            ec.DERIVED_PARTITIONS.pop("boundary_interrupt", None)


class CheckerReturnBoundary(unittest.TestCase):
    def test_invalid_results_are_checker_errors_with_self_test(self):
        spec = {"req": {"R": {"text": "rule"}},
                "inv": {"I": {"req": "R", "checker": "boundary_check", "witness": ["n"]}}}
        results = [None, True, {"ok": True}, ec.Verdict(1), ec.Verdict(True, None),
                   ec.Verdict(True, parts=["one"]), ec.Verdict(True, parts={1})]
        try:
            for result in results:
                with self.subTest(result=result):
                    ec.CHECKERS["boundary_check"] = lambda w, inv, result=result: result
                    report = ec.build_report(spec, "sha", [(1, rec(1, "I", "R", True, {"n": 2}))],
                                             [], None, 50, True)
                    self.assertEqual([f.kind for f in report.findings], [ec.CHECKER_ERROR])
                    self.assertIn("Verdict", report.findings[0].reason)
                    self.assertEqual(report.inv_never_fired, ["I"])
                    self.assertTrue(report.failed(True))
        finally:
            ec.CHECKERS.pop("boundary_check", None)

    def test_derived_callback_runs_once_only_for_relevant_fired_invariants(self):
        calls = []
        spec = {"req": {"R": {}}, "inv": {
            name: {"req": "R", "checker": "boundary_check", "witness": ["n"], "label": name}
            for name in ("I", "J")}}
        try:
            ec.CHECKERS["boundary_check"] = lambda w, inv: ec.Verdict(True, parts={"one"})
            def derive(inv):
                calls.append(inv["label"])
                return ["one"]
            ec.DERIVED_PARTITIONS["boundary_check"] = derive
            records = [(1, rec(1, "I", "R", True, {"n": 2})),
                       (2, rec(2, "J", "R", True, {"n": 4}))]
            ec.build_report(spec, "sha", records, [], None, 50, False, scope=["I"])
            self.assertEqual(calls, ["I"])
            calls.clear()
            ec.build_report(spec, "sha", records[:1], [], None, 50, False, scope=["J"])
            self.assertEqual(calls, [])
        finally:
            ec.CHECKERS.pop("boundary_check", None)
            ec.DERIVED_PARTITIONS.pop("boundary_check", None)

    def test_invalid_project_return_is_a_report_finding_and_exit_one(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "s.toml").write_text(InputBoundaries.SPEC.replace("cart_total", "boundary_check"))
            (d / "checks.py").write_text('CHECKERS = {"boundary_check": lambda w, inv: None}\n')
            (d / "e.jsonl").write_text(json.dumps(rec(1, "I", "R", True, {"n": 2})) + "\n")
            try:
                self.assertEqual(ec.main(["--spec", str(d / "s.toml"), "--evidence", str(d / "e.jsonl"),
                                          "--checkers", str(d / "checks.py"), "--md", str(d / "r.md"),
                                          "--json", str(d / "r.json"), "--self-test", "--allow-uncovered"]), 1)
                report = json.loads((d / "r.json").read_text())
                self.assertEqual([f["kind"] for f in report["findings"]], [ec.CHECKER_ERROR])
            finally:
                ec.CHECKERS.pop("boundary_check", None)

    def test_public_and_legacy_types_and_registries_share_identity(self):
        from witnessbox import api
        from witnessbox.checker import checkers as canonical, engine
        self.assertIs(checkers, canonical)
        self.assertIs(checkers.Verdict, api.Verdict)
        self.assertIs(checkers.WitnessError, api.WitnessError)
        self.assertIs(checkers.CheckFn, api.CheckFn)
        self.assertIs(checkers.PartitionsFn, api.PartitionsFn)
        self.assertIs(ec.Verdict, api.Verdict)
        self.assertIs(ec.CHECKERS, engine.CHECKERS)
        self.assertIs(ec.CHECKERS, canonical.CHECKERS)
        self.assertIs(ec.DERIVED_PARTITIONS, engine.DERIVED_PARTITIONS)

    def test_legacy_ebt_verification_api_reexports_witnessbox_objects(self):
        """Совместимый импорт возвращает те же объекты и не заводит вторую реализацию."""
        from ebt_verification import api as compat
        from witnessbox import api
        for name in ("Verdict", "WitnessError", "CheckFn", "PartitionsFn"):
            with self.subTest(name=name):
                self.assertIs(getattr(compat, name), getattr(api, name))
        self.assertEqual(api.Verdict.__module__, "witnessbox.api")
        self.assertEqual(compat.Verdict.__module__, "witnessbox.api")


class OutputBoundaries(unittest.TestCase):
    def test_report_write_failures_return_two(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ev = d / "e.jsonl"
            ev.write_text(json.dumps(rec(1, "INV-CART-3", "REQ-CART-1", True,
                                         cart([(1, 1)], "none", 0))) + "\n")
            blocker = d / "file"
            blocker.write_text("keep")
            args = ["--spec", str(SPEC), "--evidence", str(ev), "--allow-uncovered"]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ec.main(args + ["--md", str(blocker / "r.md")]), 2)
                self.assertEqual(ec.main(args + ["--md", str(d / "r.md"), "--json", str(d)]), 2)
                for error in (OSError("broken output"), UnicodeEncodeError("ascii", "я", 0, 1, "encoding")):
                    with self.subTest(error=error), mock.patch("sys.stdout.write", side_effect=error):
                        self.assertEqual(ec.main(args), 2)
            self.assertEqual(blocker.read_text(), "keep")


class HostileEvidence(unittest.TestCase):
    """Испорченные свидетельства не роняют разбор, классификацию и отчёт."""

    VALUES = (None, True, 0, -1, 2**63, 10**400, 1.5, float("nan"), float("inf"),
              "", "x" * 5000, [], {}, [[[]]], {"a": {}})
    RAW = ("{", "[]", "null", "\x00", '{"seq":', "[" * 5000 + "]" * 5000)

    @classmethod
    def _slots(cls, value):
        """Все поля словарей и элементы списков на любой глубине: что можно испортить."""
        slots = []
        if isinstance(value, dict):
            for key, item in value.items():
                slots.append((value, key))
                slots.extend(cls._slots(item))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                slots.append((value, index))
                slots.extend(cls._slots(item))
        return slots

    def test_mutated_evidence_never_crashes(self):
        base = [json.loads(line) for line in
                (KIT / "examples/basic/evidence.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        rng = random.Random(20261101)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for case in range(200):
                records = [json.loads(json.dumps(record)) for record in base]
                for record in records:
                    if rng.random() >= 0.3:
                        continue
                    container, key = rng.choice(self._slots(record))
                    if rng.random() < 0.5:
                        del container[key]
                    else:
                        container[key] = rng.choice(self.VALUES)
                lines = [json.dumps(record, allow_nan=True) for record in records]
                if rng.random() < 0.1:
                    lines.insert(rng.randrange(len(lines) + 1), rng.choice(self.RAW))
                ev = d / "evidence.jsonl"
                ev.write_text("\n".join(lines) + "\n", encoding="utf-8")
                err = io.StringIO()
                with self.subTest(case=case), contextlib.redirect_stderr(err):
                    rc = ec.main(["--spec", str(SPEC), "--evidence", str(ev),
                                  "--md", str(d / "report.md"), "--json", str(d / "report.json"),
                                  "--self-test"])
                    self.assertIn(rc, (0, 1, 2))
                    self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
