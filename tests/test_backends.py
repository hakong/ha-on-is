"""Tests for ON backend selection."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "on_is"


def load_package_module(name: str):
    """Load an integration module without importing the HA-facing package."""
    path = PACKAGE_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"custom_components.on_is.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_backend_modules():
    """Load the backend module with enough package context for relative imports."""
    sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=object))
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]

    package = types.ModuleType("custom_components.on_is")
    package.__path__ = [str(PACKAGE_PATH)]
    sys.modules["custom_components.on_is"] = package

    load_package_module("const")
    api = load_package_module("api")
    backends = load_package_module("backends")
    return api, backends


api, backends = load_backend_modules()


class BackendTests(unittest.TestCase):
    def test_default_backend_metadata(self):
        metadata = backends.get_backend_metadata()

        self.assertEqual(metadata["key"], "ocean")
        self.assertEqual(metadata["name"], "Etrel OCEAN")
        self.assertEqual(metadata["base_url"], api.BASE_URL)

    def test_create_default_backend_client(self):
        client = backends.create_backend_client(
            "user@example.com",
            "secret",
            session=object(),
        )

        self.assertIsInstance(client, api.OnIsClient)
        self.assertEqual(client.backend_key, "ocean")

    def test_unsupported_backend_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported ON backend"):
            backends.create_backend_client(
                "user@example.com",
                "secret",
                session=object(),
                backend_key="monta",
            )


if __name__ == "__main__":
    unittest.main()
