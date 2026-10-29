import json
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml


CHART = Path(__file__).resolve().parents[1] / "charts" / "dotnet-app"


def render(values=None, *args):
    return subprocess.run(
        ["helm", "template", "discovery-test", str(CHART),
         "--namespace", "staging", "-f", "-", *args],
        input=yaml.safe_dump(values or {}), text=True, capture_output=True,
    )


def container_environment(result):
    documents = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]["containers"][0]["env"]


@contextmanager
def kubernetes_api(cluster_ip="10.42.0.53", namespace="kube-system", name="kube-dns-upstream"):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            responses = {
                "/version": {"major": "1", "minor": "34", "gitVersion": "v1.34.0"},
                "/api": {"kind": "APIVersions", "versions": ["v1"]},
                "/apis": {"kind": "APIGroupList", "groups": [
                    {"name": group, "versions": [{"groupVersion": f"{group}/v1", "version": "v1"}],
                     "preferredVersion": {"groupVersion": f"{group}/v1", "version": "v1"}}
                    for group in ("apps", "networking.k8s.io")
                ]},
                "/api/v1": {
                    "kind": "APIResourceList", "groupVersion": "v1",
                    "resources": [{"name": "services", "kind": "Service", "namespaced": True,
                                   "verbs": ["get"]}],
                },
            }
            for group, resource, kind in (("apps", "deployments", "Deployment"),
                                           ("networking.k8s.io", "ingresses", "Ingress")):
                responses[f"/apis/{group}/v1"] = {
                    "kind": "APIResourceList", "groupVersion": f"{group}/v1",
                    "resources": [{"name": resource, "kind": kind, "namespaced": True, "verbs": ["get"]}],
                }
            if cluster_ip is not None:
                responses[f"/api/v1/namespaces/{namespace}/services/{name}"] = {
                    "apiVersion": "v1", "kind": "Service",
                    "metadata": {"name": name, "namespace": namespace},
                    "spec": {"clusterIP": cluster_ip, "ports": [{"port": 53}]},
                }
            response = responses.get(urlsplit(self.path).path)
            self.send_response(200 if response is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response or {
                "apiVersion": "v1", "kind": "Status", "status": "Failure",
                "reason": "NotFound", "code": 404,
            }).encode())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "kubeconfig"
                config.write_text(yaml.safe_dump({
                    "apiVersion": "v1", "kind": "Config",
                    "clusters": [{"name": "test", "cluster": {
                        "server": f"http://127.0.0.1:{server.server_port}",
                    }}],
                    "contexts": [{"name": "test", "context": {"cluster": "test", "user": "test"}}],
                    "current-context": "test", "users": [{"name": "test", "user": {}}],
                }))
                yield ["--dry-run=server", "--disable-openapi-validation", "--kubeconfig", str(config)]
        finally:
            server.shutdown()
            thread.join()


class ServiceDiscoveryTests(unittest.TestCase):
    def test_grpc_external_addresses_use_pod_ip_and_services_are_preserved(self):
        result = render({"consulDns": {"enabled": False}})
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = container_environment(result)
        for protocol in ("gRPC", "gRPCInsecure"):
            name = f"APPLICATION__WEB__PORTS__{protocol}__ExternalAddress"
            self.assertEqual(
                [item for item in environment if item["name"] == name],
                [{"name": name, "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}}],
            )
        services = {
            doc["metadata"]["name"]: doc["spec"]["ports"]
            for doc in yaml.safe_load_all(result.stdout) if doc and doc["kind"] == "Service"
        }
        self.assertEqual(services, {
            "discovery-test": [
                {"port": 80, "targetPort": "http", "protocol": "TCP", "name": "http"},
            ],
            "discovery-test-grpc": [
                {"port": 81, "targetPort": 81, "protocol": "TCP", "name": "grpc"},
                {"port": 82, "targetPort": 82, "protocol": "TCP", "name": "grpc-insecure"},
            ],
        })


    def test_enabled_dns_uses_service_cluster_ip_with_port_53(self):
        for settings, cluster_ip in (
            ({}, "10.42.0.53"),
            ({"serviceNamespace": "custom-dns", "serviceName": "resolver"}, "10.43.0.54"),
        ):
            with self.subTest(settings=settings), kubernetes_api(
                cluster_ip=cluster_ip, namespace=settings.get("serviceNamespace", "kube-system"),
                name=settings.get("serviceName", "kube-dns-upstream"),
            ) as args:
                result = render({"consulDns": settings}, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                environment = container_environment(result)
                self.assertEqual(
                    [item for item in environment if item["name"] == "ServiceDiscovery__Consul__DnsServers__0"],
                    [{"name": "ServiceDiscovery__Consul__DnsServers__0", "value": f"{cluster_ip}:53"}],
                )
                self.assertFalse(any(item["name"].lower() == "servicediscovery__enabled" for item in environment))

    def test_disabled_dns_renders_offline_and_preserves_manual_setting(self):
        for values, expected in (
            ({}, []),
            ({"env": {"ServiceDiscovery__Consul__DnsServers__0": "192.0.2.1:53"}},
             [{"name": "ServiceDiscovery__Consul__DnsServers__0", "value": "192.0.2.1:53"}]),
        ):
            with self.subTest(values=values):
                result = render({**values, "consulDns": {"enabled": False}})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    [item for item in container_environment(result)
                     if item["name"] == "ServiceDiscovery__Consul__DnsServers__0"], expected,
                )

    def test_missing_dns_service_stops_rendering_with_clear_error(self):
        with kubernetes_api(cluster_ip=None) as args:
            result = render({"consulDns": {"enabled": True}}, *args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("consulDns: Service kube-system/kube-dns-upstream not found", result.stderr)

    def test_dns_service_requires_cluster_ip(self):
        for cluster_ip in ("None", ""):
            with self.subTest(cluster_ip=cluster_ip), kubernetes_api(cluster_ip=cluster_ip) as args:
                result = render({"consulDns": {"enabled": True}}, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("consulDns: Service kube-system/kube-dns-upstream must have a clusterIP", result.stderr)

    def test_managed_environment_variables_have_no_duplicates(self):
        variables = {
            "ServiceDiscovery__Consul__DnsServers__0": "192.0.2.1:53",
            "APPLICATION__WEB__PORTS__gRPC__ExternalAddress": "shared-service",
            "APPLICATION__WEB__PORTS__gRPCInsecure__ExternalAddress": "shared-service",
        }
        with kubernetes_api() as args:
            result = render({
                "consulDns": {"enabled": True}, "env": variables,
                "environment_env": {"production": {**variables, "KEEP_ME": "kept"}},
            }, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = container_environment(result)
        for name in variables:
            self.assertEqual(sum(item["name"] == name for item in environment), 1, name)
        self.assertIn({"name": "KEEP_ME", "value": "kept"}, environment)
