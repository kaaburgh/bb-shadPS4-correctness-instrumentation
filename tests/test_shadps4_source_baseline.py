import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import shadps4_source_baseline as baseline


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
FOREIGN = "deadbeef" * 5


def _declared() -> dict:
    return json.loads(baseline.BASELINE_PATH.read_text(encoding="utf-8"))


class DeclaredBaselineTests(unittest.TestCase):
    def test_module_constants_come_from_the_declared_file(self):
        declared = _declared()
        self.assertEqual(baseline.COMMIT, declared["commit"])
        self.assertEqual(baseline.TREE, declared["tree"])
        self.assertEqual(baseline.REPOSITORY, declared["repository"])
        self.assertEqual(baseline.REPOSITORY_SLUG, declared["repository_slug"])

    def test_committed_baseline_is_the_pinned_bb_bl1_identity(self):
        self.assertEqual(baseline.COMMIT, CANONICAL)

    def test_raw_source_url_is_built_from_the_declared_identity(self):
        self.assertEqual(
            baseline.raw_source_url("src/video_core/amdgpu/regs_color.h"),
            f"https://raw.githubusercontent.com/shadps4-emu/shadPS4/{baseline.COMMIT}"
            "/src/video_core/amdgpu/regs_color.h",
        )
        with self.assertRaises(baseline.SourceBaselineError):
            baseline.raw_source_url("/absolute/path.h")

    def test_declaration_fails_closed_on_malformed_input(self):
        with self.assertRaisesRegex(baseline.SourceBaselineError, "duplicate JSON member"):
            baseline.loads_strict('{"commit": "a", "commit": "b"}')
        for mutate in (
            lambda d: d.pop("tree"),
            lambda d: d.update(extra=1),
            lambda d: d.update(schema_version="bb-shadps4-source-baseline/v2"),
            lambda d: d.update(commit="not-a-sha"),
            lambda d: d.update(commit=CANONICAL.upper()),
            lambda d: d.update(repository_slug="someone-else/shadPS4"),
            lambda d: d.update(repository="https://example.invalid/shadPS4"),
        ):
            document = _declared()
            mutate(document)
            with self.subTest(document=document):
                with self.assertRaises(baseline.SourceBaselineError):
                    baseline.validate_baseline(document)


class DriftCheckTests(unittest.TestCase):
    """The check must fail closed on a partially applied baseline update."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        shutil.copytree(
            ROOT,
            self.root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )

    def _drift(self) -> list[str]:
        return baseline.collect_drift(self.root)

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_committed_repository_is_consistent(self):
        self.assertEqual(self._drift(), [])
        baseline.check_repository(self.root)

    def test_stale_prose_reference_is_rejected(self):
        self._write(
            "docs/re/stale.md",
            f"Static inspection is against `shadps4-emu/shadPS4@{FOREIGN}`.\n",
        )
        self.assertTrue(any("docs/re/stale.md" in item for item in self._drift()))
        with self.assertRaises(baseline.BaselineDriftError):
            baseline.check_repository(self.root)

    def test_stale_raw_url_and_blob_link_are_rejected(self):
        self._write(
            "docs/re/urls.md",
            f"https://raw.githubusercontent.com/shadps4-emu/shadPS4/{FOREIGN}/a.h\n"
            f"[x](https://github.com/shadps4-emu/shadPS4/blob/{FOREIGN}/a.h)\n",
        )
        self.assertEqual(
            len([item for item in self._drift() if "docs/re/urls.md" in item]), 2
        )

    def test_stale_python_constant_is_rejected(self):
        self._write("tools/stale_tool.py", f'PINNED_SOURCE_COMMIT = "{FOREIGN}"\n')
        self.assertTrue(any("tools/stale_tool.py" in item for item in self._drift()))

    def test_stale_labelled_constant_next_to_the_repository_is_rejected(self):
        self._write(
            "tools/stale.cpp",
            'constexpr auto kRepository = "https://github.com/shadps4-emu/shadPS4";\n'
            f'constexpr auto kCommit = "{FOREIGN}";\n',
        )
        self.assertTrue(any("tools/stale.cpp" in item for item in self._drift()))

    def test_stale_structured_json_provenance_is_rejected(self):
        self._write(
            "docs/instrumentation/examples/stale.json",
            json.dumps(
                {"source": {"repository": "shadps4-emu/shadPS4", "commit": FOREIGN}},
                indent=2,
            ),
        )
        self.assertTrue(any("stale.json" in item for item in self._drift()))

    def test_stale_schema_const_is_rejected(self):
        self._write(
            "schemas/stale.schema.json",
            json.dumps(
                {
                    "properties": {
                        "repository": {"const": "https://github.com/shadps4-emu/shadPS4"},
                        "commit": {"const": FOREIGN},
                    }
                },
                indent=2,
            ),
        )
        self.assertTrue(any("stale.schema.json" in item for item in self._drift()))

    def test_workflow_must_resolve_rather_than_embed_the_literal(self):
        """The original defect: a workflow keeps fetching the old headers."""
        self._write(
            ".github/workflows/stale.yml",
            "jobs:\n  x:\n    steps:\n"
            f"      - run: curl -fsSL https://raw.githubusercontent.com/shadps4-emu/shadPS4/{CANONICAL}/a.h\n",
        )
        findings = [item for item in self._drift() if "stale.yml" in item]
        self.assertEqual(len(findings), 1)
        self.assertIn("must not embed the literal", findings[0])

    def test_unrelated_forty_hex_values_are_not_flagged(self):
        """Action pins, patch blob SHAs and this repository's own commits."""
        self._write(
            "docs/re/unrelated.md",
            "- repository: `shadps4-emu/shadPS4`\n"
            f"- commit: `{CANONICAL}`\n"
            f"- Git blob SHA-1: `{FOREIGN}`\n"
            f"\nExact-head GitHub Actions at `{FOREIGN}` passed the contract.\n",
        )
        self._write(
            ".github/workflows/unrelated.yml",
            f"jobs:\n  x:\n    steps:\n      - uses: actions/checkout@{FOREIGN}\n",
        )
        self.assertEqual(self._drift(), [])

    def _edit_prose(self, locator: str, old: str, new: str) -> None:
        """Rewrite the value that wraps onto the line after ``locator``."""
        path = self.root / "docs" / "baseline" / "shadps4.md"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            if locator in line:
                self.assertIn(old, lines[index + 1])
                lines[index + 1] = lines[index + 1].replace(old, new)
                path.write_text("".join(lines), encoding="utf-8")
                return
        self.fail(f"locator not present in the baseline document: {locator}")

    def test_wrapped_label_binds_the_value_on_the_next_line(self):
        """The document spells longer entries as `label:` then the value."""
        self._edit_prose("**Effective source commit:**", baseline.COMMIT, baseline.TREE)
        self.assertTrue(
            any(
                "labelled as the shadPS4 source commit" in item
                for item in self._drift()
                if "shadps4.md" in item
            )
        )

    def test_baseline_document_rejects_a_revision_that_is_neither_identity(self):
        """Every revision this document names is about the baseline."""
        self._edit_prose("git -C shadPS4 fetch origin", baseline.COMMIT, FOREIGN)
        self.assertTrue(
            any(
                "neither the declared source commit nor tree" in item
                for item in self._drift()
                if "shadps4.md" in item
            )
        )

    def test_commit_and_tree_identities_are_not_interchangeable(self):
        """A field holding the *other* canonical SHA is a wrong identity."""
        self._write("tools/swapped_commit.py", f'PINNED_SOURCE_COMMIT = "{baseline.TREE}"\n')
        self._write("tools/swapped_tree.py", f'PINNED_SOURCE_TREE = "{baseline.COMMIT}"\n')
        self._write(
            "docs/re/swapped.md",
            f"Static inspection is against `shadps4-emu/shadPS4@{baseline.TREE}`.\n",
        )
        self._write(
            "docs/instrumentation/examples/swapped.json",
            json.dumps(
                {
                    "source": {
                        "repository": "shadps4-emu/shadPS4",
                        "commit": baseline.TREE,
                        "tree": baseline.COMMIT,
                    }
                },
                indent=2,
            ),
        )
        drift = self._drift()
        for name in ("swapped_commit.py", "swapped_tree.py", "swapped.md", "swapped.json"):
            with self.subTest(name=name):
                self.assertTrue(any(name in item for item in drift))
        with self.assertRaises(baseline.BaselineDriftError):
            baseline.check_repository(self.root)

    def test_each_identity_is_accepted_in_its_own_position(self):
        """The stricter rule must not reject a correctly recorded pair."""
        self._write(
            "docs/re/correct.md",
            f"Built from `shadps4-emu/shadPS4` commit `{baseline.COMMIT}` "
            f"/ tree `{baseline.TREE}`.\n",
        )
        self._write(
            "docs/instrumentation/examples/correct.json",
            json.dumps(
                {
                    "source": {
                        "repository": "shadps4-emu/shadPS4",
                        "commit": baseline.COMMIT,
                        "tree": baseline.TREE,
                    }
                },
                indent=2,
            ),
        )
        self.assertEqual(
            [item for item in self._drift() if "correct." in item], []
        )

    def test_nearest_label_classifies_a_line_carrying_both(self):
        """`commit <a> / tree <b>` must bind each value to its own label."""
        self.assertEqual(baseline._labelled_kind("... commit `"), baseline.COMMIT_KIND)
        self.assertEqual(
            baseline._labelled_kind("... commit `<sha>` / tree `"), baseline.TREE_KIND
        )
        self.assertEqual(
            baseline._labelled_kind("... tree `<sha>`, commit `"), baseline.COMMIT_KIND
        )
        self.assertIsNone(baseline._labelled_kind("- Git blob SHA-1: `"))
        self.assertIsNone(baseline._labelled_kind("Exact-head Actions run at `"))

    def test_declared_baseline_file_is_not_self_flagged(self):
        document = _declared()
        document["commit"] = FOREIGN
        self._write(
            "docs/baseline/shadps4-source.json", json.dumps(document, indent=2) + "\n"
        )
        # The declaration is the source of truth; drift is measured against the
        # loaded value, so the file itself is never a finding.
        self.assertEqual(
            [item for item in self._drift() if "shadps4-source.json" in item], []
        )


class ProducerIntegrationTests(unittest.TestCase):
    """Producers must take the pinned identity from the declaration."""

    def test_producers_expose_the_declared_commit(self):
        from tools import capture_baseline, graphics_pipeline_cpp_source_mapping
        from tools import graphics_identity_model, graphics_pipeline_key_surface
        from tools import graphics_pipeline_producer_contract, run_target_experiment_v3

        self.assertEqual(capture_baseline.SOURCE_COMMIT, baseline.COMMIT)
        self.assertEqual(capture_baseline.SOURCE_REPOSITORY, baseline.REPOSITORY)
        self.assertEqual(
            graphics_pipeline_cpp_source_mapping.SOURCE_COMMIT, baseline.COMMIT
        )
        self.assertEqual(run_target_experiment_v3.PINNED_SOURCE_COMMIT, baseline.COMMIT)
        self.assertEqual(run_target_experiment_v3.PINNED_SOURCE_TREE, baseline.TREE)
        for module in (
            graphics_identity_model,
            graphics_pipeline_key_surface,
            graphics_pipeline_producer_contract,
        ):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.PINNED_SOURCE["commit"], baseline.COMMIT)
                self.assertEqual(module.PINNED_SOURCE["repository"], baseline.REPOSITORY)

    def test_patch_preparers_expose_the_declared_commit(self):
        from tools import prepare_buffer_live_range_observer_patch as buffer_patch
        from tools import prepare_graphics_pipeline_producer_patch as pipeline_patch
        from tools import prepare_guest_cpu_accepted_observer_patch as accepted_patch
        from tools import prepare_guest_cpu_observer_patch as guest_patch

        self.assertEqual(buffer_patch.SOURCE_COMMIT, baseline.COMMIT)
        self.assertEqual(accepted_patch.SOURCE_COMMIT, baseline.COMMIT)
        self.assertEqual(pipeline_patch.PINNED_SOURCE_COMMIT, baseline.COMMIT)
        self.assertEqual(guest_patch.PINNED_SOURCE_COMMIT, baseline.COMMIT)

    def test_patch_preparers_still_reject_a_foreign_source_commit(self):
        """Deriving the constant must not weaken the preparer's own gate."""
        from tools import prepare_guest_cpu_observer_patch as guest_patch

        with self.assertRaisesRegex(
            guest_patch.PatchPreparationError, "unsupported source commit"
        ):
            guest_patch.verify_source_identity(b"", FOREIGN)


class RepositoryConsistencyTests(unittest.TestCase):
    """Runs in every suite, so a partial baseline update cannot pass unnoticed."""

    def test_repository_has_no_drifted_baseline_reference(self):
        baseline.check_repository(ROOT)


if __name__ == "__main__":
    unittest.main()
