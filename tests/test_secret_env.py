import subprocess
import unittest
from pathlib import Path

import yaml


CHART = Path(__file__).resolve().parents[1] / "charts" / "dotnet-app"


class SecretEnvironmentTests(unittest.TestCase):
    def test_secret_is_connected_to_container(self):
        cases = {
            "no_secrets": {},
            "secrets_only": {"secrets": {"PLAIN_SECRET": "test-plain"}},
            "mixed_secrets": {
                "secrets": {"PLAIN_SECRET": "test-plain"},
                "b64secrets": {"ENCODED_SECRET": "dGVzdC1lbmNvZGVk"},
            },
            "b64secrets_only": {
                "b64secrets": {
                    "VAULT__VAULTROLEID": "dGVzdC1yb2xl",
                    "VAULT__VAULTSECRET": "dGVzdC1zZWNyZXQ=",
                    "OTEL_EXPORTER_OTLP_HEADERS": "dGVzdC1oZWFkZXJz",
                },
            },
        }
        for name, values in cases.items():
            with self.subTest(case=name):
                result = subprocess.run(
                    ["helm", "template", "secret-test", str(CHART),
                     "--namespace", "staging", "-f", "-"],
                    input=yaml.safe_dump({"environment": "Staging", **values}),
                    text=True, capture_output=True, check=True,
                )
                documents = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
                secrets = [doc for doc in documents if doc["kind"] == "Secret"]
                deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
                container = deployment["spec"]["template"]["spec"]["containers"][0]

                if name == "no_secrets":
                    self.assertEqual(secrets, [])
                    self.assertNotIn("envFrom", container)
                    continue

                self.assertEqual(len(secrets), 1)
                secret = secrets[0]
                self.assertEqual(secret.get("data", {}), values.get("b64secrets", {}))
                self.assertEqual(secret.get("stringData", {}), values.get("secrets", {}))
                self.assertEqual(
                    container.get("envFrom"),
                    [{"secretRef": {"name": secret["metadata"]["name"]}}],
                )
