"""Real Git/CMake/Ninja admission controls; no proprietary target evidence."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import shadps4_build_manifest as build
from tools import run_target_experiment as runner
from tools import run_target_experiment_v3 as engine
from tests.test_run_target_experiment_review_regressions import _write_bound_target_fixture, _scenario

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ninja") and shutil.which("cc"),
                     "CMake/Ninja/C compiler required")
class BuildAdmissionTests(unittest.TestCase):
    def setUp(self):
        # Real auxiliary repositories stay under the job checkout, including CI.
        parent = ROOT / ".astra-repos" / "manifest-tests"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic build fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin", build.baseline.REPOSITORY)
        self.git("remote", "add", "patches", "https://example.invalid/shadPS4")
        (self.source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(control C CXX)\n"
            "add_executable(shadps4 main.c)\n")
        (self.source / "main.c").write_text("int main(void) { return 0; }\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        # Replace the exact baseline fixture, never the admission/verification gate.
        self.enterContext(mock.patch.multiple(build.baseline, COMMIT=self.base, TREE=self.tree))
        for module in (runner, engine):
            self.enterContext(mock.patch.multiple(module, PINNED_SOURCE_COMMIT=self.base,
                                                 PINNED_SOURCE_TREE=self.tree))
        self.patches = []
        self.document = self.produce("baseline")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def produce(self, label):
        self.binary = self.root / label / ("shadps4.exe" if os.name == "nt" else "shadps4")
        self.manifest = self.root / (label + ".json")
        return build.build(source=self.source, build_directory=self.root / label,
                           output=self.manifest, cc="cc", cxx="c++", patches=self.patches,
                           patch_repository="https://example.invalid/shadPS4" if self.patches else None)

    def patch_stack(self):
        for number in range(2):
            (self.source / f"patch-{number}.txt").write_text(f"synthetic patch {number}\n")
            (self.source / "main.c").write_text(f"/* patch {number} */\nint main(void) {{ volatile int status = 0; return status; }}\n")
            self.commit(f"patch {number}")
            self.patches.append(self.git("rev-parse", "HEAD"))
        self.document = self.produce("patched")

    def run_args(self):
        target, manifest = _write_bound_target_fixture(self.root, runtime_classified=True)
        work = self.root / "work"
        work.mkdir(exist_ok=True)
        scenario = self.root / "scenario.json"
        scenario.write_bytes(runner._json_bytes(_scenario()))
        command = self.root / "command.json"
        command.write_bytes(runner._json_bytes({"schema_id": runner.COMMAND_SCHEMA_ID,
            "schema_version": runner.COMMAND_SCHEMA_VERSION, "argv": [str(self.binary), str(target / "app")],
            "emulator_binary_index": 0, "target_path_index": 1}))
        return dict(target_manifest_path=manifest, scenario_path=scenario, command_path=command,
                    emulator_binary_path=self.binary, emulator_binary_sha256=self.document["binary"]["sha256"][7:],
                    source_repository=build.baseline.REPOSITORY, source_commit=self.base, source_tree=self.tree,
                    patch_commits=self.patches, target_root=target, working_directory=work,
                    output_path=self.root / "run.zip", graphics_backend="synthetic",
                    build_manifest_path=self.manifest, source_checkout=self.source)

    def assert_run(self):
        args = self.run_args()
        # Exercise the supported CLI dispatcher, real staged execution and ZIP validation.
        names = {"target_manifest_path": "target-manifest", "scenario_path": "scenario",
                 "command_path": "command-file", "emulator_binary_path": "emulator-binary",
                 "output_path": "output", "graphics_backend": "backend", "build_manifest_path": "build-manifest"}
        argv = ["run"]
        for name, value in args.items():
            if name == "patch_commits":
                for sha in value:
                    argv.extend(["--patch-commit", sha])
            else:
                argv.extend(["--" + names.get(name, name.replace("_", "-")), str(value)])
        self.assertEqual(runner.main(argv), 0)
        with zipfile.ZipFile(args["output_path"]) as archive:
            record = json.loads(archive.read("run-manifest.json"))
            self.assertEqual(set(archive.namelist()), {"run-manifest.json", "target-manifest.json",
                                                       "host-environment.json", "scenario.json"})
            for name in archive.namelist():
                self.assertNotIn(str(self.root).encode(), archive.read(name))
        runner.validate_run_manifest(record)
        self.assertEqual(record["target"]["post_run_tree_state"], "verified")
        self.assertEqual(record["emulator"]["build_provenance"]["source"], self.document["source"])
        self.assertEqual(record["emulator"]["source"]["patch_commits"], self.patches)
        return record

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "target execution requires Linux or Windows containment")
    def test_source_built_baseline_supported_entrypoint(self):
        record = self.assert_run()
        del record["emulator"]["admission"]
        del record["emulator"]["build_provenance"]
        with self.assertRaises(runner.TargetRunError):
            runner.validate_run_manifest(record)

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "target execution requires Linux or Windows containment")
    def test_patched_source_supported_entrypoint(self):
        self.patch_stack()
        record = self.assert_run()
        self.assertEqual(record["emulator"]["source"]["effective_head"], self.patches[-1])
        record["emulator"]["binary"]["size_bytes"] += 1
        with self.assertRaisesRegex(runner.TargetRunError, "binary disagrees"):
            runner.validate_run_manifest(record)

    @unittest.skipUnless(sys.platform == "darwin", "unsupported target POSIX host control")
    def test_macos_target_execution_stays_fail_closed(self):
        with self.assertRaisesRegex(runner.TargetRunError, "Linux subreaper containment"):
            runner.run_experiment(**self.run_args())

    def test_wrong_source_patch_and_binary_identities_fail_before_execution(self):
        self.patch_stack()
        args = self.run_args()
        mutations = [
            ("base commit", lambda d: d["source"].update(commit="1" * 40)),
            ("base tree", lambda d: d["source"].update(tree="2" * 40)),
            ("dirty", lambda d: d["source"].update(dirty=True)),
            ("missing patch repository", lambda d: d["source"].update(patch_repository=None)),
            ("missing effective tree", lambda d: d["source"].pop("effective_tree")),
            ("wrong patch order", lambda d: d["source"].update(patch_commits=self.patches[::-1], effective_head=self.patches[0])),
            ("missing first patch", lambda d: d["source"].update(patch_commits=self.patches[1:])),
            ("duplicate patch", lambda d: d["source"].update(patch_commits=[self.patches[-1]] * 2)),
            ("unknown patch", lambda d: d["source"].update(patch_commits=["a" * 40], effective_head="a" * 40)),
            ("wrong head", lambda d: d["source"].update(effective_head=self.base)),
            ("wrong effective tree", lambda d: d["source"].update(effective_tree=self.tree)),
            ("wrong digest", lambda d: d["binary"].update(sha256="sha256:" + "0" * 64)),
            ("wrong size", lambda d: d["binary"].update(size_bytes=d["binary"]["size_bytes"] + 1)),
            ("missing compiler", lambda d: d["build"]["tools"].pop("cc")),
            ("missing commands", lambda d: d["build"].update(commands=[])),
            ("missing fetched sources", lambda d: d["build"].pop("fetched_sources")),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                document = copy.deepcopy(self.document)
                mutate(document)
                self.manifest.write_bytes(build.canonical(document))
                # Match the declared CLI fields so patch order is tested against Git.
                args["patch_commits"] = document["source"]["patch_commits"]
                with mock.patch.object(runner, "_LEGACY_RUN_EXPERIMENT") as execute:
                    with self.assertRaises(runner.TargetRunError):
                        runner.run_experiment(**args)
                    execute.assert_not_called()
                self.assertFalse(args["output_path"].exists())

    def test_dirty_checkout_and_hidden_index_fail_closed(self):
        for filename in ["main.c", "untracked.h"]:
            with self.subTest(filename=filename):
                path = self.source / filename
                original = path.read_bytes() if path.exists() else None
                path.write_text("dirty")
                with self.assertRaisesRegex(build.BuildManifestError, "dirty"):
                    build.verify(self.document, self.source, self.binary)
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        self.git("update-index", "--assume-unchanged", "main.c")
        with self.assertRaisesRegex(build.BuildManifestError, "hidden index"):
            build.verify(self.document, self.source, self.binary)

    def test_unrecorded_effective_commit_is_rejected(self):
        (self.source / "extra.txt").write_text("unrecorded commit")
        self.commit("extra")
        with self.assertRaisesRegex(build.BuildManifestError, "HEAD mismatch"):
            build.verify(self.document, self.source, self.binary)

    def test_merge_and_ignored_source_state_are_rejected(self):
        self.git("checkout", "-qb", "side")
        (self.source / "side.txt").write_text("side")
        self.commit("side")
        side = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.base)
        self.git("merge", "--no-ff", side, "-m", "merge")
        merge = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(build.BuildManifestError, "linear parent order"):
            build.observe_source(self.source, "https://example.invalid/shadPS4", [merge])
        self.git("checkout", "--detach", self.base)
        exclude = self.source / ".git/info/exclude"
        with exclude.open("a") as stream:
            stream.write("\nignored.h\n")
        (self.source / "ignored.h").write_text("must not disappear from build evidence")
        with self.assertRaisesRegex(build.BuildManifestError, "dirty"):
            build.verify(self.document, self.source, self.binary)

    def test_recursive_submodules_are_compared_to_gitlinks(self):
        child = self.root / "child"
        child.mkdir()
        subprocess.run(["git", "init", "-q", str(child)], check=True)
        (child / "header.h").write_text("/* child */\n")
        subprocess.run(["git", "-C", str(child), "add", "."], check=True)
        subprocess.run(["git", "-C", str(child), "-c", "user.name=fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "-qm", "child"], check=True)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(child), "deps/child")
        self.git("config", "-f", ".gitmodules", "submodule.deps/child.url", "https://example.invalid/child")
        self.commit("submodule patch")
        self.patches = [self.git("rev-parse", "HEAD")]
        self.document = self.produce("submodule")
        self.assertEqual(len(self.document["source"]["submodules"]), 1)
        changed = copy.deepcopy(self.document)
        changed["source"]["submodules"] = []
        with self.assertRaisesRegex(build.BuildManifestError, "submodule identity"):
            build.verify(changed, self.source, self.binary)
        (self.source / "deps/child/header.h").write_text("dirty child")
        with self.assertRaisesRegex(build.BuildManifestError, "dirty"):
            build.verify(self.document, self.source, self.binary)

    def test_binary_changed_after_staging_is_rejected(self):
        args = self.run_args()
        original = runner._stage_emulator_binary

        def corrupt(*values):
            path = original(*values)
            with path.open("ab") as stream:
                stream.write(b"mutation")
            return path

        with mock.patch.object(runner, "_stage_emulator_binary", side_effect=corrupt):
            with self.assertRaisesRegex(runner.TargetRunError, "binary digest or size"):
                runner.run_experiment(**args)
        self.assertFalse(args["output_path"].exists())

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "target execution requires Linux or Windows containment")
    def test_build_manifest_input_is_snapshotted_once(self):
        expected = build.digest(self.manifest.read_bytes())
        original = runner._stage_emulator_binary

        def replace_manifest(*values):
            self.manifest.write_text("{}")
            return original(*values)

        with mock.patch.object(runner, "_stage_emulator_binary", side_effect=replace_manifest):
            record = self.assert_run()
        self.assertEqual(record["emulator"]["build_provenance"]["manifest_sha256"], expected)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX input type preflight")
    def test_manifest_fifo_is_rejected_without_reading(self):
        path = self.root / "manifest.fifo"
        os.mkfifo(path)
        with self.assertRaisesRegex(build.BuildManifestError, "regular input"):
            build.load(path)

    def test_published_build_and_run_definitions_agree(self):
        from jsonschema import Draft202012Validator
        schema = json.loads(build.SCHEMA_PATH.read_text())
        run_schema = json.loads((ROOT / "schemas/target-run.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(run_schema)
        for name, definition in schema["$defs"].items():
            self.assertEqual(run_schema["$defs"][name], definition)

    def test_fetched_archive_bytes_and_git_identity_are_bound(self):
        dependencies = self.root / "dependencies"
        archive = dependencies / "archive-src"
        archive.mkdir(parents=True)
        payload = archive / "header.h"
        payload.write_bytes(b"first")
        original = build.fetched_sources(dependencies)
        self.assertIsNone(original[0]["git"])
        payload.write_bytes(b"other")
        self.assertNotEqual(original[0]["sha256"], build.fetched_sources(dependencies)[0]["sha256"])
        clone = dependencies / "git-src"
        subprocess.run(["git", "clone", "-q", str(self.source), str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin",
                        build.baseline.REPOSITORY], check=True)
        observed = build.fetched_sources(dependencies)[1]["git"]
        self.assertEqual(observed["commit"], self.base)
        self.assertEqual(observed["tree"], self.tree)
        (clone / "main.c").write_text("dirty")
        with self.assertRaisesRegex(build.BuildManifestError, "dirty"):
            build.fetched_sources(dependencies)

    def test_ambiguous_fetched_source_names_are_rejected(self):
        document = copy.deepcopy(self.document)
        entry = {"name": "fmt-src", "algorithm": "sha256-build-inputs-v1",
                 "sha256": "sha256:" + "0" * 64, "git": None}
        second = dict(entry, sha256="sha256:" + "1" * 64)
        document["build"]["fetched_sources"] = [entry, second]
        with self.assertRaisesRegex(build.BuildManifestError, "ambiguous fetched"):
            build.validate(document)

    def test_duplicate_json_and_incomplete_provenance_are_rejected(self):
        with self.assertRaises(build.BuildManifestError):
            build.strict_load(b'{"source":{},"source":{}}')
        for key in ["producer", "source", "build", "binary"]:
            document = copy.deepcopy(self.document)
            del document[key]
            with self.assertRaises(build.BuildManifestError):
                build.validate(document)


if __name__ == "__main__":
    unittest.main()
