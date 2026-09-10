"""Provenance d'un run : empreintes, etat du depot, avertissements."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from rsl.manifest import (
    TRACKED_DEPENDENCIES,
    DataSource,
    GitState,
    RunManifest,
    apply_seed,
    canonical_hash,
    capture_dependencies,
    capture_git_state,
)


def source(*, source_hash: str = "a" * 64, symbol: str = "ES.v.0") -> DataSource:
    return DataSource(
        symbol=symbol,
        path=f"/data/{symbol}.parquet",
        source_hash=source_hash,
        n_bars=1000,
        granularity="1m",
        first_ts="2016-01-01T00:00:00+00:00",
        last_ts="2020-01-01T00:00:00+00:00",
    )


class TestCanonicalHash:
    def test_key_order_does_not_matter(self):
        assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})

    def test_different_content_gives_a_different_hash(self):
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})

    def test_nested_structures_are_handled(self):
        left = {"x": [{"a": 1, "b": 2}], "y": {"c": 3}}
        right = {"y": {"c": 3}, "x": [{"b": 2, "a": 1}]}
        assert canonical_hash(left) == canonical_hash(right)

    def test_list_order_does_matter(self):
        """Deux instruments dans un ordre different, ce n'est pas le meme panier."""
        assert canonical_hash({"d": [1, 2]}) != canonical_hash({"d": [2, 1]})

    def test_it_is_a_full_sha256(self):
        assert len(canonical_hash({"a": 1})) == 64


class TestApplySeed:
    def test_the_standard_generator_becomes_reproducible(self):
        apply_seed(42)
        first = [random.random() for _ in range(5)]
        apply_seed(42)
        assert [random.random() for _ in range(5)] == first

    def test_the_numpy_generator_becomes_reproducible(self):
        apply_seed(7)
        first = np.random.rand(5).tolist()
        apply_seed(7)
        assert np.random.rand(5).tolist() == first

    def test_different_seeds_diverge(self):
        apply_seed(1)
        first = random.random()
        apply_seed(2)
        assert random.random() != first

    def test_a_large_seed_is_accepted(self):
        apply_seed(2**40)


class TestGitState:
    def test_the_project_repository_is_detected(self):
        state = capture_git_state(Path(__file__).resolve().parents[2])
        assert state.available
        assert state.commit is not None
        assert len(state.commit) == 40

    def test_a_directory_outside_any_repository(self, tmp_path: Path):
        state = capture_git_state(tmp_path)
        # Selon la machine, `tmp_path` peut ou non tomber dans un depot. On
        # verifie la coherence du resultat, pas une valeur qui dependrait de
        # l'environnement.
        if not state.available:
            assert state.commit is None
            assert not state.is_reproducible
            assert "git" in state.detail

    def test_a_dirty_tree_is_not_reproducible(self):
        assert not GitState(available=True, commit="abc", dirty=True).is_reproducible

    def test_a_clean_tree_is_reproducible(self):
        assert GitState(available=True, commit="abc", dirty=False).is_reproducible

    def test_no_repository_is_not_reproducible(self):
        assert not GitState(available=False).is_reproducible

    def test_describe_is_serialisable(self):
        import json

        state = capture_git_state(Path(__file__).resolve().parents[2])
        assert json.loads(json.dumps(state.describe())) == state.describe()


class TestDependencies:
    def test_tracked_packages_are_reported(self):
        versions = capture_dependencies()
        assert set(versions) == set(TRACKED_DEPENDENCIES)
        assert versions["numpy"] != "absent"

    def test_an_unknown_package_is_marked_absent(self):
        assert capture_dependencies(("paquet-inexistant-xyz",)) == {
            "paquet-inexistant-xyz": "absent"
        }

    def test_the_result_is_sorted(self):
        names = list(capture_dependencies().keys())
        assert names == sorted(names)


class TestRunManifest:
    def test_capture_records_the_configuration_hash(self):
        manifest = RunManifest.capture(config={"a": 1}, seed=3, data_sources=(source(),))
        assert manifest.config_hash == canonical_hash({"a": 1})
        assert manifest.seed == 3

    def test_the_same_configuration_gives_the_same_hash(self):
        first = RunManifest.capture(config={"a": 1, "b": 2}, seed=0)
        second = RunManifest.capture(config={"b": 2, "a": 1}, seed=0)
        assert first.config_hash == second.config_hash

    def test_the_timestamp_is_not_part_of_the_configuration_hash(self):
        """Deux runs identiques lances a des instants differents doivent avoir
        la meme empreinte de configuration."""
        first = RunManifest.capture(config={"a": 1}, seed=0)
        second = RunManifest.capture(config={"a": 1}, seed=0)
        assert first.config_hash == second.config_hash

    def test_missing_data_sources_are_flagged(self):
        manifest = RunManifest.capture(config={}, seed=0, data_sources=())
        assert any("aucune source de donnees" in w for w in manifest.warnings)
        assert not manifest.is_reproducible

    def test_a_source_without_a_hash_is_flagged(self):
        manifest = RunManifest.capture(
            config={}, seed=0, data_sources=(source(source_hash=""),)
        )
        assert any("sans empreinte" in w for w in manifest.warnings)
        assert not manifest.is_reproducible

    def test_a_dirty_tree_is_flagged(self, tmp_path: Path):
        manifest = RunManifest.capture(
            config={}, seed=0, data_sources=(source(),), repo_root=tmp_path
        )
        if manifest.git.available and manifest.git.dirty:
            assert any("arbre de travail modifie" in w for w in manifest.warnings)
        elif not manifest.git.available:
            assert any("aucun depot git" in w for w in manifest.warnings)

    def test_the_environment_is_recorded(self):
        manifest = RunManifest.capture(config={}, seed=0)
        assert manifest.python_version.startswith("3.")
        assert manifest.platform_name
        assert manifest.dependencies["numpy"] != "absent"

    def test_primitives_are_recorded(self):
        from rsl.primitives.registry import RegistrySnapshot

        manifest = RunManifest.capture(
            config={}, seed=0, primitives=RegistrySnapshot.capture().entries
        )
        assert "sma@1" in manifest.primitives

    def test_describe_is_serialisable(self):
        import json

        manifest = RunManifest.capture(config={"a": 1}, seed=0, data_sources=(source(),))
        assert json.loads(json.dumps(manifest.describe())) == manifest.describe()

    def test_render_shows_the_verdict(self):
        manifest = RunManifest.capture(config={"a": 1}, seed=0, data_sources=(source(),))
        text = manifest.render()
        assert "Rejouable" in text
        assert "Donnees" in text
        assert "ES.v.0" in text

    def test_transformations_appear_in_the_rendering(self):
        transformed = DataSource(
            symbol="ES.v.0", path="/data/es.parquet", source_hash="b" * 64,
            n_bars=128, granularity="1M",
            first_ts="2016-02-01T00:00:00+00:00", last_ts="2026-09-01T00:00:00+00:00",
            transformations=("resample:month(128 periodes, 0 ecartee(s))",),
        )
        manifest = RunManifest.capture(config={}, seed=0, data_sources=(transformed,))
        assert "resample:month" in manifest.render()


class TestDataSource:
    def test_describe_is_serialisable(self):
        import json

        assert json.loads(json.dumps(source().describe())) == source().describe()

    @pytest.mark.parametrize("field", ["symbol", "path", "source_hash", "n_bars"])
    def test_the_essential_fields_are_present(self, field):
        assert field in source().describe()
