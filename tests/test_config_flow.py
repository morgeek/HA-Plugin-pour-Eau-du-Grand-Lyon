"""Tests for config_flow validation helpers."""
import pytest
import voluptuous as vol

from custom_components.eau_grand_lyon.config_flow import _is_valid_email, _INTERVAL_OPTIONS


class TestIsValidEmail:
    def test_valid_email(self):
        assert _is_valid_email("user@example.com")

    def test_strips_whitespace(self):
        assert _is_valid_email("  user@example.com  ")

    def test_subdomain_email(self):
        assert _is_valid_email("user@mail.example.co.uk")

    def test_plus_tag(self):
        assert _is_valid_email("user+tag@example.com")

    def test_missing_at(self):
        assert not _is_valid_email("notanemail")

    def test_missing_domain(self):
        assert not _is_valid_email("user@")

    def test_missing_local(self):
        assert not _is_valid_email("@example.com")

    def test_empty_string(self):
        assert not _is_valid_email("")

    def test_spaces_only(self):
        assert not _is_valid_email("   ")

    def test_none(self):
        assert not _is_valid_email(None)


# ── Intervalle de mise à jour — vol.Coerce(int) ───────────────────────────────

class TestIntervalSchema:
    """Couvre le fix vol.Coerce(int) — HA soumet des strings depuis le formulaire."""

    _schema = vol.All(vol.Coerce(int), vol.In(_INTERVAL_OPTIONS))

    def test_string_24_accepte(self):
        """HA envoie "24" sous forme de string — doit être converti et validé."""
        assert self._schema("24") == 24

    def test_int_24_accepte(self):
        assert self._schema(24) == 24

    def test_toutes_les_valeurs_valides(self):
        for v in _INTERVAL_OPTIONS:
            assert self._schema(str(v)) == v

    def test_valeur_non_listee_rejete(self):
        with pytest.raises((vol.Invalid, ValueError)):
            self._schema("7")

    def test_string_vide_rejete(self):
        with pytest.raises((vol.Invalid, ValueError)):
            self._schema("")
