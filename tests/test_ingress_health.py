import subprocess
import unittest
from pathlib import Path

import yaml


CHART = Path(__file__).resolve().parents[1] / "charts" / "dotnet-app"


class IngressHealthTests(unittest.TestCase):
    def test_ingress_health_rule_works_with_nginx_compatibility_provider(self):
        result = subprocess.run(
            ["helm", "template", "health-test", str(CHART),
             "--set", "ingress.enabled=true", "--set", "ingress.secureHealthLocations=true",
             "--set", "consulDns.enabled=false", "--show-only", "templates/ingress.yaml"],
            text=True, capture_output=True, check=True,
        )
        ingress = yaml.safe_load(result.stdout)
        snippet = ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/configuration-snippet"]
        self.assertEqual(
            snippet.strip(),
            'if ($uri ~ "^/(health|healthz|ready)") { return 404; }',
        )
