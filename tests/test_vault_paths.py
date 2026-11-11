import subprocess
import unittest
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1] / "charts" / "dotnet-app"


def render(values):
    return subprocess.run(
        ["helm", "template", "vault-test", str(CHART), "-f", "-"],
        input=yaml.safe_dump({"consulDns": {"enabled": False}, **values}),
        text=True, capture_output=True,
    )


class VaultPathsTests(unittest.TestCase):
    def test_common_path_precedes_service_paths(self):
        result = render({"vaultSecrets": ["Service/Common", "Service/App"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual([item for item in env if item["name"].startswith("VAULT__SECRETS__")], [
            {"name": "VAULT__SECRETS__0", "value": "YandexCloud/Common"},
            {"name": "VAULT__SECRETS__1", "value": "Service/Common"},
            {"name": "VAULT__SECRETS__2", "value": "Service/App"},
        ])

    def test_common_path_is_not_duplicated(self):
        result = render({"vaultSecrets": ["Service/A", "YandexCloud/Common", "Service/B", "YandexCloud/Common"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual([item["value"] for item in env if item["name"].startswith("VAULT__SECRETS__")],
                         ["YandexCloud/Common", "Service/A", "Service/B"])

    def test_legacy_path_conflicts_fail_for_all_sources_and_case_variants(self):
        for source in ("env", "environment_env", "secrets", "b64secrets"):
            with self.subTest(source=source):
                variable = {"vault__Secrets__12": "U2VydmljZS9B" if source == "b64secrets" else "Service/A"}
                values = {source: {"production": variable} if source == "environment_env" else variable,
                          "vaultSecrets": ["Service/B"]}
                result = render(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("vaultSecrets cannot be combined with legacy VAULT__SECRETS__", result.stderr)

    def test_empty_list_preserves_legacy_paths_and_other_variables(self):
        values = {
            "vaultSecrets": [],
            "env": {"VAULT__SECRETS__0": "App/A", "ENV_KEEP": "env"},
            "environment_env": {"production": {"VAULT__SECRETS__1": "App/B", "ENVIRONMENT_KEEP": "environment"}},
            "secrets": {"VAULT__SECRETS__2": "App/C", "SECRET_KEEP": "secret"},
            "b64secrets": {"VAULT__SECRETS__3": "QXBwL0Q=", "B64_KEEP": "ZW5jb2RlZA=="},
        }
        result = render(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        for source in (values["env"], values["environment_env"]["production"]):
            for name, value in source.items():
                self.assertIn({"name": name, "value": value}, env)
        secret = next(doc for doc in docs if doc["kind"] == "Secret")
        self.assertEqual(secret["stringData"], values["secrets"])
        self.assertEqual(secret["data"], values["b64secrets"])

    def test_new_paths_preserve_other_variables_and_no_paths_generate_nothing(self):
        values = {"env": {"ENV_KEEP": "env"}, "secrets": {"SECRET_KEEP": "secret"},
                  "b64secrets": {"B64_KEEP": "ZW5jb2RlZA=="}}
        for paths in ([], ["App/A"]):
            with self.subTest(paths=paths):
                result = render({**values, "vaultSecrets": paths})
                self.assertEqual(result.returncode, 0, result.stderr)
                docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
                container = next(doc for doc in docs if doc["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]
                self.assertIn({"name": "ENV_KEEP", "value": "env"}, container["env"])
                self.assertEqual(sum(item["name"].startswith("VAULT__SECRETS__") for item in container["env"]), 2 if paths else 0)
                secret = next(doc for doc in docs if doc["kind"] == "Secret")
                self.assertEqual(secret["stringData"], values["secrets"])
                self.assertEqual(secret["data"], values["b64secrets"])
                self.assertEqual(container["envFrom"], [{"secretRef": {"name": secret["metadata"]["name"]}}])
