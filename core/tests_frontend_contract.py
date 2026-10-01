"""
core/tests_frontend_contract.py
-------------------------------
Static checks that the frontend's API calls line up with the Django URL conf.
They read frontend/src as text, so they need no browser, node or database.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"

# Every endpoint defined in api.config.js must have a backend route (the 11 stale definitions that
# used to be allow-listed here were deleted with the frontend cleanup).

def _backend_routes():
    routes = set()

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                full = prefix + str(p.pattern)
                if full.startswith("api/v1/"):
                    routes.add(re.sub(r"<[^>]+>", "{}", "/" + full[len("api/v1/"):]))

    walk(get_resolver().url_patterns)
    return routes


class FrontendApiContractTests(SimpleTestCase):
    def test_no_client_call_uses_a_path_without_the_api_prefix(self):
        """
        apiClient's baseURL is the bare host, so a literal like "/org/settings/" hits
        http://host/org/settings/ (404) instead of /api/v1/org/settings/. Literal paths
        must either start with /api/v1/ or come from API_ENDPOINTS.
        """
        call = re.compile(r"""\b\w*[cC]lient\.(?:get|post|put|patch|delete)\(\s*[`"'](/(?!api/v1/)[^`"']*)""")
        call_api = re.compile(r"""\bapi\.(?:get|post|put|patch|delete)\(\s*[`"'](/(?!api/v1/)[^`"']*)""")
        offenders = []
        for path in FRONTEND_SRC.rglob("*.js*"):
            text = path.read_text(encoding="utf8")
            for rx in (call, call_api):
                for m in rx.finditer(text):
                    offenders.append(f"{path.relative_to(FRONTEND_SRC)}: {m.group(1)}")
        self.assertEqual(offenders, [])

    def test_every_configured_endpoint_has_a_backend_route(self):
        cfg = (FRONTEND_SRC / "config" / "api.config.js").read_text(encoding="utf8")
        entry = re.compile(r"^\s+[A-Z_0-9]+:\s*(?:\(.*?\)\s*=>\s*)?`\$\{API_V1\}(/[^`]*)`", re.M)
        configured = {re.sub(r"\$\{[^}]+\}", "{}", m.group(1)).split("?")[0] for m in entry.finditer(cfg)}
        self.assertGreater(len(configured), 200)  # guards against the regex silently matching nothing
        unrouted = configured - _backend_routes()
        self.assertEqual(sorted(unrouted), [])

    def test_org_settings_endpoint_is_configured_and_routed(self):
        cfg = (FRONTEND_SRC / "config" / "api.config.js").read_text(encoding="utf8")
        self.assertIn("${API_V1}/org/settings/", cfg)
        self.assertIn("/org/settings/", _backend_routes())

    def test_every_endpoint_key_used_in_the_frontend_is_defined(self):
        """A typo like API_ENDPOINTS.OPD.ENCOUNTER_SGN is `undefined` at runtime, not a build error."""
        cfg = (FRONTEND_SRC / "config" / "api.config.js").read_text(encoding="utf8")
        defined, group = set(), None
        for line in cfg.splitlines():
            m = re.match(r"^  ([A-Z_]+):\s*\{", line)
            if m:
                group = m.group(1)
                continue
            m = re.match(r"^\s{4}([A-Z_0-9]+):", line)
            if m and group:
                defined.add(f"{group}.{m.group(1)}")
        self.assertGreater(len(defined), 200)
        used = set()
        for path in FRONTEND_SRC.rglob("*.js*"):
            if path.name == "api.config.js":
                continue
            for m in re.finditer(r"API_ENDPOINTS\.([A-Z_]+)\.([A-Z_0-9]+)", path.read_text(encoding="utf8")):
                used.add(f"{m.group(1)}.{m.group(2)}")
        self.assertEqual(sorted(used - defined), [])
